import asyncio
import hashlib
import json
import random
import time

from fastapi import HTTPException

from app.adapters import FakeLLMAdapter, OutputBlocked, ProviderFailure
from app.config import Settings
from app.models import GenerateRequest, GenerateResponse
from app.resilience import CircuitBreaker, CircuitOpen, RateLimiter, TTLCache

# Fictional prices per million tokens; never presented as real provider prices.
PRICES = {"sim-primary": (0.5, 1.5), "sim-fallback": (0.1, 0.3)}
PROMPTS = {"v1": "Be concise.", "v2": "Be concise and explain your reasoning briefly."}
DETERMINISTIC = "The AI service is temporarily unavailable. Please try again shortly."


def safe(text: str):
    # Minimal demo policy, intentionally not a production moderation classifier.
    return not any(marker in text.lower() for marker in ("[blocked-input]", "[blocked-output]"))


class Gateway:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.adapters = {model: FakeLLMAdapter(model) for model in PRICES}
        self.breakers = {
            model: CircuitBreaker(settings.circuit_threshold, settings.circuit_reset_s)
            for model in PRICES
        }
        self.cache = TTLCache(settings.cache_ttl_s, settings.cache_capacity)
        self.limiter = RateLimiter(
            settings.rate_limit, settings.rate_window_s, settings.client_capacity
        )

    async def call(self, model, prompt, scenario, trace):
        breaker = self.breakers[model]
        try:
            probe = breaker.acquire()
        except CircuitOpen:
            trace["error_type"] = "CircuitOpen"
            trace["events"].append({"kind": "circuit_skipped", "model": model})
            raise
        epoch = breaker.epoch
        try:
            for index in range(self.settings.retries + 1):
                attempt = {
                    "model": model,
                    "attempt": index + 1,
                    "status": "pending",
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "estimated_cost": 0.0,
                    "usage_unknown": False,
                }
                trace["attempts"].append(attempt)
                started = time.perf_counter()
                try:
                    result = await asyncio.wait_for(
                        self.adapters[model].generate(prompt, scenario, index),
                        timeout=self.settings.timeout_s,
                    )
                    in_price, out_price = PRICES[model]
                    attempt.update(
                        input_tokens=result.input_tokens,
                        output_tokens=result.output_tokens,
                        estimated_cost=(
                            result.input_tokens * in_price + result.output_tokens * out_price
                        )
                        / 1_000_000,
                        status="success",
                    )
                    if not safe(result.text):
                        attempt["status"] = "safety_blocked"
                        # Provider is healthy; a safety denial should not open its circuit.
                        breaker.success(epoch)
                        raise OutputBlocked()
                    breaker.success(epoch)
                    if probe:
                        trace["events"].append({"kind": "circuit_recovered", "model": model})
                    return result
                except (TimeoutError, ProviderFailure) as error:
                    attempt.update(
                        status="error", error_type=type(error).__name__, usage_unknown=True
                    )
                    trace["error_type"] = type(error).__name__
                    if index == self.settings.retries:
                        if breaker.failure(epoch):
                            trace["events"].append({"kind": "circuit_opened", "model": model})
                        raise
                    trace["retry_count"] += 1
                    delay = self.settings.backoff_s * (2**index) * random.uniform(0.8, 1.2)
                    trace["events"].append(
                        {"kind": "retry", "model": model, "delay_ms": round(delay * 1000, 2)}
                    )
                except OutputBlocked:
                    raise
                except Exception as error:
                    attempt.update(
                        status="error", error_type=type(error).__name__, usage_unknown=True
                    )
                    breaker.failure(epoch)
                    raise
                finally:
                    attempt["latency_ms"] = round((time.perf_counter() - started) * 1000, 3)
                await asyncio.sleep(delay)
        finally:
            # Releases a half-open reservation on disconnect/cancellation or unexpected errors.
            if probe and breaker.probing:
                breaker.cancel_probe()

    async def generate(self, body: GenerateRequest, trace: dict, client: str):
        trace.update(
            model=body.model, requested_model=body.model, prompt_version=body.prompt_version
        )
        allowed, retry_after = self.limiter.allow(client)
        if not allowed:
            trace.update(status="rate_limited", error_type="RateLimited")
            trace["events"].append({"kind": "rate_limited"})
            raise HTTPException(
                429, "Request quota exceeded", headers={"Retry-After": str(retry_after)}
            )
        if not self.settings.allow_simulation and (
            body.scenario != "success" or body.fallback_scenario != "success"
        ):
            trace.update(status="rejected", error_type="SimulationDisabled")
            raise HTTPException(400, "Failure simulation is disabled")
        if not safe(body.prompt):
            trace.update(
                status="blocked", safety_outcome="input_blocked", error_type="InputBlocked"
            )
            trace["events"].append({"kind": "safety_blocked", "stage": "input"})
            raise HTTPException(400, "Prompt rejected by demonstration safety policy")
        prompt = PROMPTS[body.prompt_version] + "\n" + body.prompt
        # Include tenant/IP, version, model and simulation mode to avoid cross-context reuse.
        key = hashlib.sha256(
            json.dumps(
                [
                    client,
                    prompt,
                    body.model,
                    body.prompt_version,
                    body.scenario,
                    body.fallback_scenario,
                ]
            ).encode()
        ).hexdigest()
        cached = self.cache.get(key) if body.use_cache else None
        model, text, status = body.model, None, "success"
        if cached:
            text = cached
            trace["cache_hit"] = True
        else:
            try:
                result = await self.call(model, prompt, body.scenario, trace)
                text = result.text
                if body.use_cache:
                    self.cache.put(key, text)
            except (TimeoutError, ProviderFailure, CircuitOpen):
                model, status = "sim-fallback", "fallback"
                trace["model"] = model
                trace["fallback_used"] = True
                trace["events"].append({"kind": "fallback", "model": model})
                try:
                    text = (await self.call(model, prompt, body.fallback_scenario, trace)).text
                except (TimeoutError, ProviderFailure, CircuitOpen):
                    model, status, text = "deterministic", "degraded", DETERMINISTIC
                    trace["events"].append({"kind": "deterministic_fallback"})
                except OutputBlocked:
                    return self.block_output(trace)
            except OutputBlocked:
                return self.block_output(trace)
        trace.update(model=model, status=status, safety_outcome="allowed")
        return GenerateResponse(
            trace_id=trace["trace_id"],
            response=text,
            model=model,
            prompt_version=body.prompt_version,
            status=status,
            cache_hit=trace["cache_hit"],
        )

    @staticmethod
    def block_output(trace):
        trace.update(status="blocked", safety_outcome="output_blocked", error_type="OutputBlocked")
        trace["events"].append({"kind": "safety_blocked", "stage": "output"})
        raise HTTPException(400, "Response rejected by demonstration safety policy")
