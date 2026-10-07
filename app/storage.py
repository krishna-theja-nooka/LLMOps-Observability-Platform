import json
import math
import sqlite3
from collections import Counter, defaultdict
from contextlib import contextmanager
from pathlib import Path


class TraceStore:
    def __init__(self, path: str):
        self.path = path

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=1)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        finally:
            connection.close()

    def initialize(self):
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS traces (
                    trace_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    model TEXT NOT NULL,
                    prompt_version TEXT,
                    latency_ms REAL NOT NULL,
                    status TEXT NOT NULL,
                    http_status INTEGER NOT NULL,
                    retry_count INTEGER NOT NULL,
                    cache_hit INTEGER NOT NULL,
                    estimated_cost REAL NOT NULL,
                    error_type TEXT,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS traces_created_at ON traces(created_at);
                CREATE TABLE IF NOT EXISTS incidents (
                    id INTEGER PRIMARY KEY,
                    trace_id TEXT NOT NULL REFERENCES traces(trace_id),
                    created_at TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS incidents_created_at ON incidents(created_at);
            """)

    def ready(self):
        # Checks the write lock and writability; cannot predict a later full-disk failure.
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE traces SET status = status WHERE 0")
            db.rollback()

    def save(self, trace: dict):
        fields = (
            "trace_id",
            "created_at",
            "model",
            "prompt_version",
            "latency_ms",
            "status",
            "http_status",
            "retry_count",
            "cache_hit",
            "estimated_cost",
            "error_type",
        )
        with self.connect() as db:
            db.execute("PRAGMA foreign_keys=ON")
            with db:
                db.execute(
                    "INSERT INTO traces VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    [trace[field] for field in fields] + [json.dumps(trace)],
                )
                for event in trace["events"]:
                    if event["kind"] in {
                        "fallback",
                        "circuit_opened",
                        "circuit_skipped",
                        "deterministic_fallback",
                        "safety_blocked",
                        "internal_error",
                        "rate_limited",
                    }:
                        db.execute(
                            "INSERT INTO incidents(trace_id,created_at,kind,payload) "
                            "VALUES(?,?,?,?)",
                            (
                                trace["trace_id"],
                                trace["created_at"],
                                event["kind"],
                                json.dumps(event),
                            ),
                        )

    def trace(self, trace_id: str):
        with self.connect() as db:
            row = db.execute("SELECT payload FROM traces WHERE trace_id=?", (trace_id,)).fetchone()
            return json.loads(row[0]) if row else None

    def incidents(self, limit: int, before_id: int | None):
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM incidents WHERE (? IS NULL OR id < ?) ORDER BY id DESC LIMIT ?",
                (before_id, before_id, limit),
            ).fetchall()
        return [dict(row) | {"payload": json.loads(row["payload"])} for row in rows]

    def summary(self, since: str):
        with self.connect() as db:
            rows = db.execute(
                "SELECT payload FROM traces WHERE created_at >= ?", (since,)
            ).fetchall()
        traces = [json.loads(row[0]) for row in rows]
        total = len(traces)
        eligible = [
            t for t in traces if t["status"] in {"success", "fallback", "degraded", "error"}
        ]
        latencies = sorted(t["latency_ms"] for t in eligible)
        costs = defaultdict(float)
        for trace in traces:
            for attempt in trace["attempts"]:
                costs[attempt["model"]] += attempt["estimated_cost"]

        def percentile(p):
            return latencies[max(0, math.ceil(p * len(latencies)) - 1)] if latencies else 0

        return {
            "window_start": since,
            "requests": total,
            "eligible_requests": len(eligible),
            "requests_by_status": dict(Counter(t["status"] for t in traces)),
            "p50_latency_ms": percentile(0.50),
            "p95_latency_ms": percentile(0.95),
            "error_rate": sum(t["http_status"] >= 500 for t in traces) / total if total else 0,
            "fallback_rate": sum(t["fallback_used"] for t in eligible) / len(eligible)
            if eligible
            else 0,
            "cache_hit_rate": sum(t["cache_hit"] for t in eligible) / len(eligible)
            if eligible
            else 0,
            "degraded_rate": sum(t["status"] == "degraded" for t in eligible) / len(eligible)
            if eligible
            else 0,
            "estimated_cost_by_model": dict(costs),
            "estimated_cost_total": sum(costs.values()),
            "unknown_usage_attempts": sum(
                a["usage_unknown"] for t in traces for a in t["attempts"]
            ),
            "cost_currency": "USD",
            "cost_is_simulated": True,
        }
