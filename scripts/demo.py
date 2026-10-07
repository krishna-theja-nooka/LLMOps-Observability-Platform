"""Run a no-cost incident exercise against the app or a running gateway."""

import argparse
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def walkthrough(client):
    outcomes, traces = [], []
    cases = [
        ("primary success", {"prompt": "Explain monitoring"}),
        ("cache hit", {"prompt": "Explain monitoring"}),
        ("retry recovery", {"prompt": "Retry demo", "scenario": "flaky"}),
        ("timeout fallback", {"prompt": "Timeout demo", "scenario": "timeout"}),
        ("provider fallback 1", {"prompt": "Outage 1", "scenario": "failure"}),
        ("provider fallback 2", {"prompt": "Outage 2", "scenario": "failure"}),
        ("circuit bypass", {"prompt": "Skip open primary", "use_cache": False}),
        (
            "both paths unavailable",
            {
                "prompt": "Total outage",
                "scenario": "failure",
                "fallback_scenario": "failure",
            },
        ),
        ("input safety", {"prompt": "[blocked-input]"}),
    ]
    for label, payload in cases:
        response = client.post("/v1/generate", json=payload)
        trace_id = response.headers["X-Trace-ID"]
        outcomes.append(
            {
                "case": label,
                "http_status": response.status_code,
                "body": response.json(),
                "trace_id": trace_id,
            }
        )
        traces.append(client.get(f"/v1/traces/{trace_id}").json())
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "provider": "simulator",
        "outcomes": outcomes,
        "traces": traces,
        "metrics": client.get("/v1/metrics/summary").json(),
        "incidents": client.get("/v1/incidents").json(),
    }
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in-process", action="store_true")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.in_process:
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(db_path=str(Path(directory) / "demo.db"), rate_limit=9)
            with TestClient(create_app(settings)) as client:
                report = walkthrough(client)
                limited = client.post("/v1/generate", json={"prompt": "Excess request"})
                assert limited.status_code == 429
                report["quota_check"] = {
                    "http_status": limited.status_code,
                    "trace": client.get(f"/v1/traces/{limited.headers['X-Trace-ID']}").json(),
                }
                # Include quota rejection in the final dashboard/event snapshot.
                report["metrics"] = client.get("/v1/metrics/summary").json()
                report["incidents"] = client.get("/v1/incidents").json()
        statuses = [item["body"].get("status") for item in report["outcomes"]]
        assert "fallback" in statuses and "degraded" in statuses
        assert report["outcomes"][1]["body"]["cache_hit"]
    else:
        headers = {"X-API-Key": os.getenv("GATEWAY_API_KEY", "")}
        # The demo targets a local gateway; do not route it through ambient proxy variables.
        with httpx.Client(
            base_url=args.base_url, headers=headers, timeout=10, trust_env=False
        ) as client:
            report = walkthrough(client)
        # Live-server mode observes existing state and does not assert a fresh database or quota.
    content = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content)
        print(f"Wrote {args.output}")
    else:
        print(content)


if __name__ == "__main__":
    main()
