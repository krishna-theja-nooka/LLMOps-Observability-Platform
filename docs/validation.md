# Release validation

Validated in a clean virtual environment on Python 3.12.14 using `requirements-dev.lock`:

- Locked dependency installation and editable package installation succeeded.
- `pip check`: no broken requirements.
- `python -m pytest`: **34 passed**, **100% statement coverage** across `app`.
- `python -m ruff check .`: passed.
- `python -m ruff format --check .`: passed.
- In-process scenario demo: passed; actual output in `examples/demo-report.json`.
- CI and release YAML: parsed successfully.
- Real HTTP Uvicorn smoke: readiness, provider fallback, trace retrieval, and metrics passed.
- Live-server demo command: passed.

The walkthrough recorded 10 requests: 3 primary successes, 4 model fallbacks, 1 deterministic degraded response, 1 safety rejection, and 1 quota rejection. Its eligible p95 was approximately 335 ms on this run. That measurement belongs to the demo workload; the separate regression workload asserts p95 below 500 ms with shorter test deadlines.

The pinned Starlette/FastAPI test client emits one deprecation warning about its HTTPX compatibility path. Tests pass; a future dependency upgrade should revisit the test-client transport. Coverage measures exercised statements, not complete security, concurrency, or production-readiness proof.

Python 3.11 is configured in CI but was not available for local validation. Docker image build and GitHub-hosted workflow execution were not run in this environment. No real-provider performance or billing is claimed.
