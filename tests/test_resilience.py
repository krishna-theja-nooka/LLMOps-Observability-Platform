import pytest

from app.config import Settings
from app.resilience import CircuitBreaker, CircuitOpen, RateLimiter, TTLCache


def test_circuit_half_open_allows_one_probe_and_reopens():
    now = [100.0]
    breaker = CircuitBreaker(2, 5, clock=lambda: now[0])
    assert not breaker.acquire()
    assert not breaker.failure()
    assert breaker.failure()
    with pytest.raises(CircuitOpen):
        breaker.acquire()
    now[0] += 6
    assert breaker.acquire()
    assert breaker.state == "half_open"
    with pytest.raises(CircuitOpen):
        breaker.acquire()
    assert breaker.failure()
    assert breaker.state == "open"
    now[0] += 6
    breaker.acquire()
    breaker.success()
    assert breaker.state == "closed"


def test_cache_ttl_and_lru():
    now = [0]
    cache = TTLCache(5, 2, lambda: now[0])
    cache.put("a", "A")
    cache.put("b", "B")
    assert cache.get("a") == "A"
    cache.put("c", "C")
    assert cache.get("b") is None
    now[0] = 6
    assert cache.get("a") is None


def test_stale_inflight_results_do_not_close_or_extend_an_open_circuit():
    breaker = CircuitBreaker(1, 5)
    epoch = breaker.epoch
    breaker.failure(epoch)
    opened_at = breaker.opened_at
    breaker.success(epoch)
    assert breaker.state == "open"
    assert not breaker.failure(epoch)
    assert breaker.opened_at == opened_at


def test_limiter_window_capacity_and_client_isolation():
    now = [0]
    limiter = RateLimiter(2, 5, 2, lambda: now[0])
    assert limiter.allow("a")[0]
    assert limiter.allow("a")[0]
    assert not limiter.allow("a")[0]
    assert limiter.allow("b")[0]
    assert not limiter.allow("c")[0]
    now[0] = 6
    assert limiter.allow("c")[0]
    assert limiter.allow("a")[0]


@pytest.mark.parametrize("options", [{"timeout_s": 0}, {"retries": -1}, {"backoff_s": -1}])
def test_invalid_configuration(options):
    with pytest.raises(ValueError):
        Settings(**options)


def test_environment_settings(monkeypatch):
    monkeypatch.setenv("GATEWAY_DB_PATH", "example.db")
    monkeypatch.setenv("GATEWAY_API_KEY", "example-key")
    monkeypatch.setenv("GATEWAY_ALLOW_SIMULATION", "false")
    settings = Settings.from_env()
    assert settings.db_path == "example.db"
    assert settings.api_key == "example-key"
    assert not settings.allow_simulation
