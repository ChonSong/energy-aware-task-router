"""FastAPI application for the energy-aware task router."""

from __future__ import annotations

import os
import time
import uuid
from datetime import datetime
from typing import Any

import httpx
import structlog

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from energy_router import __version__
from energy_router.auth import AUTH_EXEMPT_PATHS, APIKeyAuth
from energy_router.carbon import CarbonApiClient, GridCarbonLevel
from energy_router.config import load_config
from energy_router.lifecycle import LifecycleManager
from energy_router.logging_config import configure_logging
from energy_router.monitoring import collect_metrics_text, dashboard_html, record_metric
from energy_router.ratelimit import (
    RateLimiter,
    extract_client_key,
    get_default_limiter,
)
from energy_router.router import Task, TaskRouter

app = FastAPI(title="Energy-Aware Task Router")
_router: TaskRouter | None = None
_startup_time: float | None = None
_rate_limiter: RateLimiter | None = None
_auth: APIKeyAuth | None = None
_lifecycle: LifecycleManager | None = None
_logger = structlog.get_logger()


class TaskSubmitRequest(BaseModel):
    name: str
    deferrable: bool = True
    defer_until: str | None = None
    deadline: datetime | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class TaskSubmitResponse(BaseModel):
    task_id: str
    name: str
    status: str


# ---------------------------------------------------------------------------
# Lifespan (startup / shutdown)
# ---------------------------------------------------------------------------
# Using on_event for backward compatibility — if the FastAPI version used
# supports lifespan context managers these will be migrated when Python 3.12
# is the minimum target.


@app.on_event("startup")
async def startup():
    """Initialise all shared resources on application start.

    - Load configuration
    - Configure structured logging
    - Create shared HTTPX client (managed by LifecycleManager)
    - Create Carbon API client, task router, rate limiter, and auth
    """
    global _router, _startup_time, _rate_limiter, _auth, _lifecycle

    cfg = load_config("config.yaml")

    # Configure structured logging early
    configure_logging(level=cfg.log_level, log_format=cfg.log_format)
    _logger.info("app.startup", log_level=cfg.log_level, log_format=cfg.log_format)

    # Shared HTTPX client (long-lived, closed on shutdown)
    http_client = httpx.AsyncClient(timeout=cfg.carbon_api_timeout)

    _lifecycle = LifecycleManager()
    _lifecycle.set_http_client(http_client)

    if cfg.redis_url:
        _lifecycle.set_redis_url(cfg.redis_url)

    carbon_client = CarbonApiClient(
        api_key=cfg.carbon_api_key,
        base_url=cfg.carbon_api_base_url,
        timeout=cfg.carbon_api_timeout,
        cache_ttl=cfg.carbon_cache_ttl,
        http_client=http_client,
    )
    _router = TaskRouter(carbon_client=carbon_client, default_region=cfg.default_region)
    _startup_time = time.time()
    _rate_limiter = RateLimiter()
    _auth = APIKeyAuth.from_config(config_keys=cfg.api_keys)


@app.on_event("shutdown")
async def shutdown():
    """Gracefully release all shared resources on application stop.

    Order:
        1. Notify that shutdown is beginning
        2. Close the HTTP client (drains in-flight Carbon API requests)
        3. Close the Redis connection (if reachable)
    """
    global _lifecycle

    _logger.info("app.shutdown")
    if _lifecycle is not None:
        await _lifecycle.shutdown()


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

RATE_LIMIT_EXEMPT_PATHS = {"/health", "/metrics", "/dashboard", "/livez", "/readyz"}


@app.middleware("http")
async def auth_middleware(request: Request, call_next: Any):
    """API key authentication middleware.

    Checks ``X-API-Key`` header against configured keys.
    Exempts the same monitoring paths as rate limiting.
    When no keys are configured (development mode) all requests pass.
    """
    if request.url.path in AUTH_EXEMPT_PATHS:
        return await call_next(request)

    authenticator = _auth or APIKeyAuth()
    api_key: str | None = request.headers.get("X-API-Key")

    if not authenticator.authenticate(api_key):
        return JSONResponse(
            status_code=401,
            content={"detail": "Unauthorized. Provide a valid API key via the X-API-Key header."},
            headers={"WWW-Authenticate": "APIKey"},
        )

    return await call_next(request)


@app.middleware("http")
async def log_requests(request: Request, call_next: Any):
    """Log every request and its response status."""
    start = time.monotonic()
    method = request.method
    path = request.url.path
    client_ip = request.client.host if request.client else "unknown"

    response = await call_next(request)

    elapsed = time.monotonic() - start
    _logger.info(
        "http.request",
        method=method,
        path=path,
        status=response.status_code,
        duration_ms=round(elapsed * 1000, 1),
        client_ip=client_ip,
    )
    return response


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next: Any):
    if request.url.path in RATE_LIMIT_EXEMPT_PATHS:
        return await call_next(request)

    limiter = _rate_limiter or get_default_limiter()
    client_key = extract_client_key(request)

    if not limiter.check(client_key):
        return JSONResponse(
            status_code=429,
            content={
                "detail": "Rate limit exceeded. Try again later.",
                "retry_after_seconds": int(limiter.window_seconds),
            },
            headers={
                "X-RateLimit-Limit": str(limiter.max_requests),
                "X-RateLimit-Remaining": "0",
                "Retry-After": str(int(limiter.window_seconds)),
            },
        )

    response = await call_next(request)
    remaining = limiter.remaining(client_key)
    response.headers["X-RateLimit-Limit"] = str(limiter.max_requests)
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    return response


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.post("/tasks", response_model=TaskSubmitResponse)
async def submit_task(req: TaskSubmitRequest):
    if _router is None:
        raise HTTPException(status_code=503, detail="Router not initialized")
    defer_until = None
    if req.defer_until:
        try:
            defer_until = GridCarbonLevel(req.defer_until)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid defer_until: {req.defer_until}")
    task = Task(
        id=str(uuid.uuid4()),
        name=req.name,
        deferrable=req.deferrable,
        defer_until=defer_until,
        deadline=req.deadline,
        payload=req.payload,
    )
    decision = await _router.route(task)
    return TaskSubmitResponse(task_id=task.id, name=task.name, status=decision.decision)


@app.get("/livez")
async def livez():
    """Kubernetes liveness probe.

    Returns 200 with ``{"status": "alive"}`` if the process is running
    and the ASGI loop is responsive.  No dependency checks — a dead
    process won't reach this handler, so a 200 response is sufficient
    proof of life.
    """
    return {"status": "alive"}


@app.get("/readyz")
async def readyz():
    """Kubernetes readiness probe.

    Returns 200 if the router is initialised and the app is ready to
    serve traffic.  Returns 503 if the router has not yet been
    initialised (or has been cleared during a graceful shutdown).
    """
    global _router
    if _router is None:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "detail": "router not initialised"},
        )
    return {"status": "ready"}


@app.get("/metrics")
async def metrics():
    """Prometheus-format metrics endpoint."""
    return Response(content=collect_metrics_text(), media_type="text/plain; version=0.0.4")


@app.get("/dashboard")
async def dashboard():
    """Minimal HTML monitoring dashboard."""
    return HTMLResponse(content=dashboard_html())


@app.get("/health")
async def health():
    """Comprehensive healthcheck endpoint."""
    global _router, _startup_time

    router_ok = _router is not None
    carbon_key_set = (
        _router is not None
        and _router.carbon is not None
        and _router.carbon.api_key is not None
    )

    components = {
        "router": {
            "status": "ok" if router_ok else "error",
            "detail": "initialized" if router_ok else "not_initialized",
        },
        "carbon_api": {
            "status": "ok" if carbon_key_set else "degraded",
            "detail": "key_configured" if carbon_key_set else "no_api_key",
        },
    }

    redis_status = "unknown"
    redis_detail = "not_checked"
    if _router is not None:
        try:
            cfg = load_config("config.yaml")
            if cfg.redis_url:
                import redis as rmod

                redis_conn = rmod.from_url(cfg.redis_url)
                redis_conn.ping()
                redis_status = "ok"
                redis_detail = "connected"
            else:
                redis_detail = "no_redis_url_configured"
        except Exception as exc:
            redis_status = "degraded" if "connection refused" in str(exc).lower() else "error"
            redis_detail = str(exc)
    components["redis"] = {"status": redis_status, "detail": redis_detail}

    all_ok = all(c["status"] == "ok" for c in components.values())
    any_error = any(c["status"] == "error" for c in components.values())
    if all_ok:
        overall_status = "healthy"
    elif any_error:
        overall_status = "unhealthy"
    else:
        overall_status = "degraded"

    uptime = None
    if _startup_time is not None:
        uptime = round(time.time() - _startup_time, 2)

    return {
        "status": overall_status,
        "version": __version__,
        "uptime_seconds": uptime,
        "components": components,
    }
