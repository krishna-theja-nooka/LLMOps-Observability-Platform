# SLOs and SLIs

These are proposed operating targets and executable simulator gates. They are not claims about a deployed production service.

| SLI | Exact implementation | Proposed target |
|---|---|---|
| Gateway error rate | Persisted generation traces with HTTP >=500 / all persisted generation traces | <1% over 30 days; window API supports up to 7 days |
| Eligible p95 latency | Nearest-rank 95th percentile for status `success`, `fallback`, `degraded`, or `error` | <500 ms for the controlled regression workload |
| Model completion availability | (`success` + `fallback`) / eligible requests | >=99% over 30 days; derive from status counts |
| Degraded response rate | `degraded` / eligible requests | <1% over 30 days |
| Fallback rate | Requests with `fallback_used=true` / eligible requests | Investigate >10% over 15 minutes |
| Cache-hit rate | Cache hits / eligible requests | Track workload trend; no universal target |
| Unknown usage attempts | Provider attempts without observed usage | Reconcile; never assume zero billable cost |

Eligible latency covers middleware processing through response construction, including authentication, validation, rate limiting, provider attempts, and backoffs. It excludes SQLite persistence, response transmission, and network overhead. Blocked, rejected, and rate-limited requests are excluded from the eligible latency distribution and fallback/cache denominators. Client rejections are still included in total requests and status counts. This makes the error-rate SLI distinct from model completion availability.

An HTTP 200 `degraded` response is an availability notice, not a usable model completion. A healthy fallback contributes to model completion availability; deterministic fallback does not. The API exposes `degraded_rate` so HTTP success does not hide a loss of AI functionality. A storage outage can prevent a trace from being persisted and thus disappear from these metrics; an external HTTP probe/log is necessary for end-to-end availability measurement.

## Executable regression gate

`tests/test_reliability_regression.py` submits 30 unique sequential requests with success, timeout, and provider-failure scenarios. Test settings use a 30 ms attempt deadline, one retry, and 1 ms base backoff. It asserts p95 <500 ms, zero 5xx, at least one successful model fallback, and no deterministic degradation. It then reaches a 50-request quota and asserts the next request returns 429. Other tests prove circuit recovery, both-provider degradation, cache behavior, safety, and storage failures.

The small workload is a functional regression test. Run a separate load test with concurrency, persistent storage, real provider budgets, and end-to-end timing before adopting an operational SLO. Latency assertions can fail on a severely overloaded CI host; investigate before changing a target.

## Error budget and alerts

A proposed 99% usable-completion objective allows 1% unavailable eligible requests. With 100,000 eligible requests, that is 1,000 unsuccessful completions. Proposed alerts: fallback >10% for 15 minutes; degraded >1% for 5 minutes; readiness 503 twice consecutively; p95 >500 ms for 15 minutes. This project provides the APIs and runbook for those checks, not a scheduler or notification integration.
