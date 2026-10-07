# Cost control

All costs are simulated using fictional USD prices per million tokens:

| Adapter | Input | Output |
|---|---:|---:|
| `sim-primary` | $0.50 | $1.50 |
| `sim-fallback` | $0.10 | $0.30 |

Token usage is `ceil(characters / 4)` with a minimum of one token. Input estimation includes the versioned system prompt. It is not a model tokenizer. Cost is `(input_tokens × input_price + output_tokens × output_price) / 1,000,000` for each successful attempt, including successful output that safety subsequently rejects.

Retry/failure attempts may have unknown usage. Their reported known cost is zero and `usage_unknown=true`; the summary counts unknown attempts. The estimated total is therefore a known-cost subtotal, not a billing total. With a real adapter, reconcile provider usage and invoices, including requests that time out after upstream computation. Cache hits incur no new model cost; they do not repeat the original cost.

Implemented controls: an 8,000-character prompt limit, a fixed model allowlist, two retries/provider by default, attempt deadlines, circuit breakers, a cheaper simulated fallback, per-IP quotas, and a bounded 60-second primary-result cache. Fallback responses are deliberately not cached so recovered primary quality can return immediately.

Operational strategy: monitor estimated cost by attempted model together with retry/fallback rates and unknown-usage count. Investigate sudden cache-hit drops or prompt-version changes. A daily budget, output-token cap, provider concurrency limit, and preflight admission budget are future controls; this repository does not claim to enforce a monetary spend cap. Extend `ModelResult` and provider configuration with real token accounting and prices when integrating an actual API.
