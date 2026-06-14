"""Tests for the FastAPI endpoint."""

from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

from energy_router.api import app
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

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_health_endpoint(client):
    """Health endpoint should return 200."""
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"


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
