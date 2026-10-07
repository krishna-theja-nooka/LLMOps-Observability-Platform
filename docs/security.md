# Security guidance

The default configuration is a local demonstration. Bind to loopback. For any remote deployment, set a strong `GATEWAY_API_KEY`, terminate TLS at a trusted ingress, restrict `/docs` and observability access, enforce a request-body size limit, and configure network access controls. All `/v1/*` endpoints share the optional key; `/health` and `/ready` are unauthenticated and readiness reveals simulator circuit states.

The shared key is not a tenant authentication system. Rate limits/cache isolation use the peer IP; multiple users behind NAT share a quota and cache context. Traces and incident APIs are global for key holders. A production multi-tenant service needs verified tenant identities, tenant-scoped traces and cache keys, scoped authorization, and separate administrative access. Never accept a client-supplied tenant ID as trusted identity.

Run with `--no-proxy-headers` for the local demo. Behind a proxy, explicitly configure trusted forwarding IPs and authenticated identity; do not blindly trust `X-Forwarded-For`. Publicly exposed identity churn can exhaust the bounded rate-limiter map. Add ingress quotas, concurrency limits, and overload protection.

SQLite stores request metadata, attempts, and events, not prompts or completions. Cache entries hold response text in memory until expiration/eviction/restart. Prompt text still passes through process memory and any future provider. Trace logs include ID, status, and latency only. Protect the database volume, log access, backup retention, and encryption at the platform level. Establish retention before handling sensitive data.

Safety is deliberately a deterministic marker policy. It is not a moderation model, PII detector, or prompt-injection defense. Input and output policy checks run before caching/returning model output; failed output is not rerouted through a less restrictive safety policy. Add validated content moderation, PII controls, red-team cases, and a task-specific policy before processing real users.

Failure scenarios are test controls. Set `GATEWAY_ALLOW_SIMULATION=false` to reject injected failure modes for a remote demonstration. The underlying provider remains a simulator; this setting does not switch to a real model. Secrets belong in environment variables or a secret manager, not `.env` commits, request bodies, or GitHub Actions logs. SQL queries use bound parameters.

The non-root Docker image and dependency lock aid repeatability. Audit dependencies and image provenance before deployment. Readiness checks writability and lock acquisition, but cannot guarantee the next commit will succeed or prove provider availability. A failed telemetry commit causes 503 after model work may already have occurred; callers need idempotency support before adding side-effecting tools or automatic client retries.
