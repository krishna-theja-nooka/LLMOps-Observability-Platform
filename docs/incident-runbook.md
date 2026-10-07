# Incident runbook

## Triage

1. Check `/health` and `/ready`. A live process with readiness 503 points to storage. Provider circuits being open do not alone make the process unready.
2. Inspect `/v1/metrics/summary?window_minutes=15`: status counts, p95, fallback/degraded rates, and unknown usage.
3. Fetch `/v1/incidents?limit=50` and follow `trace_id` to `/v1/traces/{trace_id}`. Use `before_id` for older events.
4. Inspect attempt model, error type, retry count, latency, and event sequence. Never copy confidential prompts or credentials into incident notes.
5. Record impact, start time, affected model, recent release/configuration changes, and recovery evidence.

| Signal | Likely cause | Action |
|---|---|---|
| `TimeoutError`, increasing p95 | Provider slow/unreachable or overly short deadline | Check provider/network externally; retain bounded retries; consider fallback capacity |
| `ProviderFailure`, fallback spikes | Upstream outage | Confirm fallback works; let circuit cooldown and probe recover automatically |
| `circuit_skipped` | Previous calls exhausted retries | Inspect preceding traces; wait cooldown; do not continually restart the process |
| `degraded` | Both model paths failed or are open | State user impact explicitly; investigate both providers; preserve deterministic notice |
| 429 | Client quota or active-identity capacity | Honor `Retry-After`; check caller retries and proxy identity configuration |
| 503 readiness or `trace_persistence_failed` log | SQLite lock, permissions, full disk, or unavailable volume | Restore writable storage; inspect lock contention and disk; recheck readiness |
| `output_blocked` | Demonstration output policy denied content | Do not bypass policy; inspect adapter/policy version changes |
| 500 internal error | Unexpected code/adapter defect | Inspect error type and deployment changes; rollback; do not retry blindly |

## Recovery verification

After restoring a provider, allow the cooldown to elapse and submit a unique uncached success request. Confirm `circuit_recovered`, a closed circuit, primary model output, and declining fallback rate. After storage recovery, check readiness and verify a new trace can be retrieved. A 200 alone is insufficient: inspect `status` and `model` for deterministic degradation.

Before rollback, back up SQLite with its backup API or stop writes before copying; copying a live WAL database file alone is unsafe. Follow [release.md](release.md). Process restart clears cache, circuits, and quotas and therefore changes traffic behavior.

## Incident report template

```text
Title / severity:
UTC start / detection / resolution:
Affected version / prompt version / model:
User impact and unsuccessful-completion count:
Trace IDs and incident-event IDs:
Timeline (evidence, mitigation, recovery):
Root cause:
What controlled the impact (retry/circuit/fallback):
What did not work:
Recovery verification:
Follow-up owner / due date / regression test:
```

## Reproducible exercise

Run `python -m scripts.demo --in-process`. The walkthrough includes successful retry, model fallback, circuit skip, both-model degradation, safety rejection, and quota rejection. Inspect the generated report or `examples/demo-report.json`. These incidents are injected test conditions, not real production outages.
