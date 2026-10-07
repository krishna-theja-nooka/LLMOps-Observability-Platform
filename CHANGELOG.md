# Changelog

## 1.0.0

- Introduce a FastAPI simulator-backed LLM gateway with versioned prompts.
- Add bounded caching, rate limits, retries, deadlines, and per-model circuit recovery.
- Add fallback model and explicit deterministic degraded responses.
- Persist metadata-only traces and incident events in SQLite.
- Expose health, readiness, traces, rolling metrics, and paginated incidents.
- Add reliability regression tests, CI, release automation, and operator documentation.
