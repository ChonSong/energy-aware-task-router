"""FastAPI application for the energy-aware task router."""

from __future__ import annotations

import os
import time
import uuid
from datetime import datetime
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from energy_router import __version__
from energy_router.carbon import CarbonApiClient, GridCarbonLevel
from energy_router.config import load_config
from energy_router.router import Task, TaskRouter

app = FastAPI(title="Energy-Aware Task Router")
_router: TaskRouter | None = None
_startup_time: float | None = None


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


@app.on_event("startup")
async def startup():
    global _router, _startup_time
    cfg = load_config("config.yaml")
    client = CarbonApiClient(
        api_key=cfg.carbon_api_key,
        base_url=cfg.carbon_api_base_url,
        timeout=cfg.carbon_api_timeout,
        cache_ttl=cfg.carbon_cache_ttl,
    )
    _router = TaskRouter(carbon_client=client, default_region=cfg.default_region)
    _startup_time = time.time()


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


@app.get("/health")
async def health():
    """Comprehensive healthcheck endpoint.

    Returns service status, version, uptime, and individual component health.
    """
    global _router, _startup_time

    router_ok = _router is not None
    carbon_key_set = (
        _router is not None
        and _router.carbon is not None
        and _router.carbon.api_key is not None
    )

    # Build component checks
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

    # Try Redis connectivity — check if config has redis_url
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

    # Overall status
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
