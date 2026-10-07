import asyncio
import hmac
import logging
import sqlite3
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from app.config import Settings
from app.gateway import Gateway
from app.models import GenerateRequest, GenerateResponse
from app.storage import TraceStore

logger = logging.getLogger("gateway")


def create_app(settings: Settings | None = None):
    settings = settings or Settings.from_env()
    store = TraceStore(settings.db_path)

    @asynccontextmanager
    async def lifespan(app):
        await asyncio.to_thread(store.initialize)
        app.state.gateway = Gateway(settings)
        app.state.store = store
        yield

    app = FastAPI(title="LLMOps Observability Platform", version="1.0.0", lifespan=lifespan)

    @app.exception_handler(sqlite3.Error)
    async def storage_error(request, error):
        return JSONResponse(
            status_code=503, content={"detail": "Observability storage unavailable"}
        )

    def authorize(request: Request):
        if settings.api_key and not hmac.compare_digest(
            request.headers.get("X-API-Key", "").encode(), settings.api_key.encode()
        ):
            raise HTTPException(401, "Invalid API key")

    @app.middleware("http")
    async def observe(request: Request, call_next):
        if request.method != "POST" or request.url.path != "/v1/generate":
            return await call_next(request)
        started = time.perf_counter()
        trace = {
            "trace_id": str(uuid4()),
            "created_at": datetime.now(UTC).isoformat(),
            "model": "none",
            "requested_model": None,
            "prompt_version": None,
            "status": "rejected",
            "http_status": 0,
            "latency_ms": 0,
            "retry_count": 0,
            "cache_hit": False,
            "fallback_used": False,
            "safety_outcome": "not_evaluated",
            "estimated_cost": 0.0,
            "input_tokens": 0,
            "output_tokens": 0,
            "usage_unknown": False,
            "error_type": None,
            "attempts": [],
            "events": [],
        }
        request.state.trace = trace
        try:
            response = await call_next(request)
        except Exception as error:
            # Never log exception messages, request bodies, or authorization headers.
            trace.update(status="error", error_type=type(error).__name__)
            trace["events"].append({"kind": "internal_error"})
            response = JSONResponse(status_code=500, content={"detail": "Internal gateway error"})
        trace["http_status"] = response.status_code
        if response.status_code >= 400 and trace["error_type"] is None:
            trace["error_type"] = f"HTTP{response.status_code}"
        trace["latency_ms"] = round((time.perf_counter() - started) * 1000, 3)
        for field in ("estimated_cost", "input_tokens", "output_tokens"):
            trace[field] = sum(attempt[field] for attempt in trace["attempts"])
        trace["usage_unknown"] = any(a["usage_unknown"] for a in trace["attempts"])
        try:
            await asyncio.to_thread(store.save, trace)
        except sqlite3.Error:
            logger.error("trace_persistence_failed trace_id=%s", trace["trace_id"])
            response = JSONResponse(
                status_code=503,
                content={
                    "detail": "Observability storage unavailable",
                    "trace_id": trace["trace_id"],
                },
            )
        response.headers["X-Trace-ID"] = trace["trace_id"]
        logger.info(
            "request_complete trace_id=%s status=%s http_status=%s latency_ms=%s",
            trace["trace_id"],
            trace["status"],
            response.status_code,
            trace["latency_ms"],
        )
        return response

    @app.get("/health")
    def health():
        return {"status": "alive", "version": "1.0.0"}

    @app.get("/ready")
    async def ready(request: Request):
        try:
            await asyncio.to_thread(store.ready)
        except sqlite3.Error:
            raise HTTPException(503, "Storage unavailable") from None
        return {
            "status": "ready",
            "adapter": "simulator",
            "circuits": {
                name: breaker.state for name, breaker in request.app.state.gateway.breakers.items()
            },
        }

    @app.post("/v1/generate", response_model=GenerateResponse, dependencies=[Depends(authorize)])
    async def generate(body: GenerateRequest, request: Request):
        client = request.client.host if request.client else "unknown"
        return await request.app.state.gateway.generate(body, request.state.trace, client)

    @app.get("/v1/traces/{trace_id}", dependencies=[Depends(authorize)])
    async def trace(trace_id: UUID):
        result = await asyncio.to_thread(store.trace, str(trace_id))
        if result is None:
            raise HTTPException(404, "Trace not found")
        return result

    @app.get("/v1/metrics/summary", dependencies=[Depends(authorize)])
    async def metrics(window_minutes: int = Query(1440, ge=1, le=10080)):
        since = (datetime.now(UTC) - timedelta(minutes=window_minutes)).isoformat()
        return await asyncio.to_thread(store.summary, since)

    @app.get("/v1/incidents", dependencies=[Depends(authorize)])
    async def incidents(
        limit: int = Query(50, ge=1, le=200), before_id: int | None = Query(None, ge=1)
    ):
        rows = await asyncio.to_thread(store.incidents, limit, before_id)
        return {"incidents": rows, "next_before_id": rows[-1]["id"] if rows else None}

    return app


app = create_app()
