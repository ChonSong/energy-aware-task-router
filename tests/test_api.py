"""Tests for the FastAPI endpoint."""

from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

from energy_router.api import app, _startup_time, _router
from energy_router.carbon import CarbonApiClient
from energy_router.config import load_config
from energy_router.router import TaskRouter


@pytest.fixture
async def client():
    """Set up the router and create a test client."""
    import energy_router.api as api_mod
    cfg = load_config()
    carbon_client = CarbonApiClient(api_key=cfg.carbon_api_key)
    api_mod._router = TaskRouter(carbon_client=carbon_client, default_region=cfg.default_region)
    api_mod._startup_time = 1000.0  # fixed fake startup time

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_health_endpoint(client):
    """Health endpoint should return 200 with component checks."""
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("healthy", "degraded", "unhealthy")
    assert data["version"] == "0.1.0"
    assert data["uptime_seconds"] >= 0
    assert "components" in data
    assert "router" in data["components"]
    assert "carbon_api" in data["components"]
    assert "redis" in data["components"]
    assert data["components"]["router"]["status"] == "ok"
    assert data["components"]["router"]["detail"] == "initialized"


@pytest.mark.asyncio
async def test_health_without_router(client):
    """Health endpoint should report router error when not initialized."""
    import energy_router.api as api_mod
    
    # Save and clear router
    saved_router = api_mod._router
    api_mod._router = None
    api_mod._startup_time = None
    
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/health")
    
    # Restore
    api_mod._router = saved_router
    api_mod._startup_time = 1000.0
    
    assert resp.status_code == 200
    data = resp.json()
    assert data["components"]["router"]["status"] == "error"
    assert data["components"]["router"]["detail"] == "not_initialized"


@pytest.mark.asyncio
async def test_submit_task_endpoint(client):
    """POST /tasks should return a task ID and status."""
    payload = {
        "name": "test-batch-job",
        "deferrable": True,
    }
    resp = await client.post("/tasks", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert "task_id" in data
    assert data["name"] == "test-batch-job"
    assert data["status"] in ("route_now", "defer")


@pytest.mark.asyncio
async def test_submit_with_invalid_defer_until(client):
    """Invalid defer_until value should return 400."""
    payload = {
        "name": "bad-task",
        "deferrable": True,
        "defer_until": "super_high",
    }
    resp = await client.post("/tasks", json=payload)
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_submit_with_deadline(client):
    """Task with a deadline should still be routable."""
    payload = {
        "name": "deadlined-task",
        "deferrable": True,
        "deadline": "2026-12-31T23:59:59",
    }
    resp = await client.post("/tasks", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert "task_id" in data


@pytest.mark.asyncio
async def test_submit_when_router_not_initialized(client):
    """POST /tasks should return 503 when router is not initialized."""
    import energy_router.api as api_mod
    
    saved = api_mod._router
    api_mod._router = None
    
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        payload = {"name": "fail-task"}
        resp = await ac.post("/tasks", json=payload)
    
    api_mod._router = saved
    
    assert resp.status_code == 503
    assert "Router not initialized" in resp.json()["detail"]
