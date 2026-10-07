"""Project 4-style quality gate: controlled reliability workload, not a load test."""


def test_reliability_targets(make_client):
    client = make_client(timeout_s=0.03, backoff_s=0.001, retries=1, rate_limit=50)
    statuses = []
    for index in range(30):
        scenario = "timeout" if index % 6 == 0 else "failure" if index % 5 == 0 else "success"
        response = client.post(
            "/v1/generate",
            json={
                "prompt": f"Reliability workload {index}",
                "scenario": scenario,
                "use_cache": False,
            },
        )
        assert response.status_code == 200
        statuses.append(response.json()["status"])
    metrics = client.get("/v1/metrics/summary").json()
    assert metrics["requests"] == 30
    assert metrics["p95_latency_ms"] < 500  # generous CI threshold, not an internet SLA
    assert metrics["error_rate"] == 0
    assert "fallback" in statuses
    assert "degraded" not in statuses
    for _ in range(20):
        assert client.post("/v1/generate", json={"prompt": "quota"}).status_code == 200
    assert client.post("/v1/generate", json={"prompt": "quota"}).status_code == 429
