import asyncio
import sqlite3
from uuid import uuid4

import pytest

from app.config import Settings
from app.gateway import DETERMINISTIC
from app.main import create_app
from tests.conftest import fetch_trace


def generate(client, **kwargs):
    return client.post("/v1/generate", json={"prompt": "Explain reliable AI", **kwargs})


def test_success_and_health(client):
    assert client.get("/health").json()["status"] == "alive"
    assert client.get("/ready").json()["status"] == "ready"
    response = generate(client)
    assert response.status_code == 200
    trace = fetch_trace(client, response)
    assert response.json()["trace_id"] == trace["trace_id"]
    assert trace["model"] == "sim-primary"
    assert trace["status"] == "success"
    assert trace["estimated_cost"] > 0
    assert trace["input_tokens"] > 0
    assert trace["safety_outcome"] == "allowed"
    assert "Explain reliable AI" not in str(trace)


def test_cache_and_prompt_version_isolation(client):
    first = generate(client)
    second = generate(client)
    assert not first.json()["cache_hit"]
    assert second.json()["cache_hit"]
    trace = fetch_trace(client, second)
    assert trace["attempts"] == []
    assert trace["estimated_cost"] == 0
    assert not generate(client, prompt_version="v2").json()["cache_hit"]
    assert not generate(client, use_cache=False).json()["cache_hit"]
    assert generate(client, scenario="failure").json()["status"] == "fallback"


def test_slow_success(client):
    response = generate(client, scenario="slow", use_cache=False)
    assert response.json()["status"] == "success"
    assert fetch_trace(client, response)["latency_ms"] >= 40


def test_retry_recovers(client):
    response = generate(client, scenario="flaky", use_cache=False)
    trace = fetch_trace(client, response)
    assert trace["status"] == "success"
    assert trace["retry_count"] == 1
    assert len(trace["attempts"]) == 2
    assert trace["events"][0]["kind"] == "retry"


@pytest.mark.parametrize(
    "scenario,error", [("failure", "ProviderFailure"), ("timeout", "TimeoutError")]
)
def test_provider_failure_and_timeout_use_fallback(client, scenario, error):
    response = generate(client, scenario=scenario, use_cache=False)
    assert response.status_code == 200
    assert response.json()["model"] == "sim-fallback"
    trace = fetch_trace(client, response)
    assert trace["error_type"] == error
    assert trace["retry_count"] == 2
    assert trace["fallback_used"]
    assert len(trace["attempts"]) == 4
    assert trace["usage_unknown"]
    assert "fallback" in [e["kind"] for e in trace["events"]]


def test_both_providers_fail_deterministic_fallback(client):
    response = generate(client, scenario="failure", fallback_scenario="failure", use_cache=False)
    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["response"] == DETERMINISTIC
    trace = fetch_trace(client, response)
    assert trace["retry_count"] == 4
    assert trace["model"] == "deterministic"


def test_circuit_skip_and_recovery(make_client):
    client = make_client(retries=0, circuit_threshold=1)
    generate(client, scenario="failure", use_cache=False)
    response = generate(client, use_cache=False)
    trace = fetch_trace(client, response)
    assert trace["events"][0]["kind"] == "circuit_skipped"
    assert all(a["model"] == "sim-fallback" for a in trace["attempts"])
    breaker = client.app.state.gateway.breakers["sim-primary"]
    breaker.opened_at -= 10
    response = generate(client, use_cache=False)
    assert response.json()["model"] == "sim-primary"
    assert breaker.state == "closed"
    assert fetch_trace(client, response)["events"][0]["kind"] == "circuit_recovered"


def test_rate_limit_applies_to_cache_hits(make_client):
    client = make_client(rate_limit=2)
    assert generate(client).status_code == 200
    assert generate(client).json()["cache_hit"]
    response = generate(client)
    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) >= 1
    trace = fetch_trace(client, response)
    assert trace["status"] == "rate_limited"
    assert trace["attempts"] == []


@pytest.mark.parametrize(
    "payload,outcome",
    [
        ({"prompt": "[blocked-input]"}, "input_blocked"),
        ({"scenario": "unsafe"}, "output_blocked"),
        ({"scenario": "failure", "fallback_scenario": "unsafe"}, "output_blocked"),
    ],
)
def test_safety_blocks_without_retrying_unsafe_output(client, payload, outcome):
    response = generate(client, use_cache=False, **payload)
    assert response.status_code == 400
    trace = fetch_trace(client, response)
    assert trace["safety_outcome"] == outcome
    assert trace["status"] == "blocked"
    if outcome == "input_blocked":
        assert not trace["attempts"]
    else:
        assert trace["attempts"][-1]["status"] == "safety_blocked"


@pytest.mark.parametrize(
    "payload",
    [{}, {"prompt": ""}, {"prompt": "x", "model": "unknown"}, {"prompt": "x", "unexpected": True}],
)
def test_validation_errors_are_traced(client, payload):
    response = client.post("/v1/generate", json=payload)
    assert response.status_code == 422
    assert fetch_trace(client, response)["error_type"] == "HTTP422"


def test_authentication(make_client):
    client = make_client(api_key="test-only-key")
    response = generate(client)
    assert response.status_code == 401
    assert client.get("/v1/metrics/summary").status_code == 401
    assert client.get("/health").status_code == 200
    good = client.post(
        "/v1/generate", json={"prompt": "hello"}, headers={"X-API-Key": "test-only-key"}
    )
    assert good.status_code == 200
    trace = client.get(
        f"/v1/traces/{response.headers['X-Trace-ID']}", headers={"X-API-Key": "test-only-key"}
    ).json()
    assert trace["http_status"] == 401


def test_simulation_can_be_disabled(make_client):
    client = make_client(allow_simulation=False)
    assert generate(client, scenario="failure").status_code == 400
    assert generate(client).status_code == 200


def test_missing_trace_and_bad_uuid(client):
    assert client.get(f"/v1/traces/{uuid4()}").status_code == 404
    assert client.get("/v1/traces/not-a-uuid").status_code == 422


def test_metrics_costs_and_incident_pagination(client):
    assert client.get("/v1/metrics/summary").json()["requests"] == 0
    generate(client)
    generate(client)
    failed = generate(client, scenario="failure", use_cache=False)
    trace = fetch_trace(client, failed)
    metrics = client.get("/v1/metrics/summary").json()
    assert metrics["requests_by_status"] == {"success": 2, "fallback": 1}
    assert metrics["cache_hit_rate"] == pytest.approx(1 / 3)
    assert metrics["fallback_rate"] == pytest.approx(1 / 3)
    assert metrics["error_rate"] == 0
    assert metrics["unknown_usage_attempts"] == 3
    assert metrics["estimated_cost_by_model"]["sim-fallback"] == trace["estimated_cost"]
    assert metrics["p95_latency_ms"] >= metrics["p50_latency_ms"]
    incidents = client.get("/v1/incidents?limit=1").json()
    assert incidents["incidents"][0]["trace_id"] == trace["trace_id"]
    assert (
        client.get(f"/v1/incidents?before_id={incidents['next_before_id']}").json()["incidents"]
        == []
    )


def test_unknown_adapter_exception_is_contained_and_traced(client):
    class BrokenAdapter:
        async def generate(self, *args):
            raise RuntimeError("secret must never appear in trace")

    client.app.state.gateway.adapters["sim-primary"] = BrokenAdapter()
    response = generate(client, use_cache=False)
    assert response.status_code == 500
    trace = fetch_trace(client, response)
    assert trace["status"] == "error"
    assert trace["error_type"] == "RuntimeError"
    assert "secret" not in str(trace)
    assert client.get("/v1/metrics/summary").json()["error_rate"] == 1


def test_database_outage_readiness_and_generation(client, monkeypatch):
    def unavailable(*args):
        raise sqlite3.OperationalError("database unavailable")

    monkeypatch.setattr(client.app.state.store, "ready", unavailable)
    assert client.get("/ready").status_code == 503
    monkeypatch.setattr(client.app.state.store, "save", unavailable)
    assert generate(client).status_code == 503
    assert client.get("/health").status_code == 200


def test_trace_survives_process_restart(tmp_path):
    from fastapi.testclient import TestClient

    settings = Settings(db_path=str(tmp_path / "persist.db"))
    with TestClient(create_app(settings)) as client:
        response = generate(client)
    with TestClient(create_app(settings)) as client:
        assert fetch_trace(client, response)["status"] == "success"


def test_model_call_cancellation_releases_half_open_probe(client):
    gateway = client.app.state.gateway
    breaker = gateway.breakers["sim-primary"]
    breaker.opened_at = breaker.clock() - 10

    class CancelledAdapter:
        async def generate(self, *args):
            raise asyncio.CancelledError()

    gateway.adapters["sim-primary"] = CancelledAdapter()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            gateway.call(
                "sim-primary",
                "hello",
                "success",
                {
                    "attempts": [],
                    "events": [],
                    "retry_count": 0,
                },
            )
        )
    assert not breaker.probing
    assert breaker.state == "open"


def test_observability_storage_failure_is_contained(client, monkeypatch):
    def unavailable(*args):
        raise sqlite3.OperationalError("unavailable")

    monkeypatch.setattr(client.app.state.store, "summary", unavailable)
    assert client.get("/v1/metrics/summary").status_code == 503
