"""Tests for the FastAPI endpoint."""

from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

from energy_router.api import app, _startup_time, _router, _rate_limiter
from energy_router.auth import APIKeyAuth
from energy_router.carbon import CarbonApiClient
from energy_router.config import load_config
from energy_router.router import TaskRouter
from energy_router.ratelimit import RateLimiter


@pytest.fixture(autouse=True)
def reset_state():
    """Reset the per-app rate limiter and auth before each test."""
    import energy_router.api as api_mod
    api_mod._rate_limiter = RateLimiter(max_requests=1000, window_seconds=60, burst_max=100)
    api_mod._auth = None
    yield


@pytest.fixture
async def client():
    """Set up the router and create a test client."""
    import energy_router.api as api_mod
    cfg = load_config()
    carbon_client = CarbonApiClient(api_key=cfg.carbon_api_key)
    api_mod._router = TaskRouter(carbon_client=carbon_client, default_region=cfg.default_region)
    api_mod._startup_time = 1000.0  # fixed fake startup time
    api_mod._auth = None  # permissive mode (no keys configured)

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
    data = resp.json()
    assert "Router not initialized" in data["detail"]
    assert data["error_code"] == "service_unavailable"
    assert data["status"] == 503


# ---------------------------------------------------------------------------
# K8s probe endpoint tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_livez_returns_alive(client):
    """Liveness probe should always return 200."""
    resp = await client.get("/livez")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "alive"


@pytest.mark.asyncio
async def test_readyz_ready_when_router_initialised(client):
    """Readiness probe should return 200 when router is set."""
    resp = await client.get("/readyz")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ready"


@pytest.mark.asyncio
async def test_readyz_not_ready_when_router_missing(client):
    """Readiness probe should return 503 when router is None."""
    import energy_router.api as api_mod

    saved = api_mod._router
    api_mod._router = None

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/readyz")

    api_mod._router = saved

    assert resp.status_code == 503
    data = resp.json()
    assert data["status"] == "not_ready"


@pytest.mark.asyncio
async def test_livez_is_rate_limit_exempt(client):
    """Liveness probe should not be rate limited."""
    import energy_router.api as api_mod
    api_mod._rate_limiter = RateLimiter(max_requests=0, window_seconds=60)

    resp = await client.get("/livez")
    assert resp.status_code == 200  # exempt despite zero capacity


@pytest.mark.asyncio
async def test_readyz_is_rate_limit_exempt(client):
    """Readiness probe should not be rate limited."""
    import energy_router.api as api_mod
    api_mod._rate_limiter = RateLimiter(max_requests=0, window_seconds=60)

    resp = await client.get("/readyz")
    assert resp.status_code == 200  # exempt despite zero capacity


@pytest.mark.asyncio
async def test_livez_is_auth_exempt(client):
    """Liveness probe should not require authentication."""
    import energy_router.api as api_mod
    api_mod._auth = APIKeyAuth(["test-key"])

    resp = await client.get("/livez")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_readyz_is_auth_exempt(client):
    """Readiness probe should not require authentication."""
    import energy_router.api as api_mod
    api_mod._auth = APIKeyAuth(["test-key"])

    resp = await client.get("/readyz")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Rate limiting tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_limit_headers_on_success(client):
    """Successful requests should include rate-limit headers."""
    resp = await client.post("/tasks", json={"name": "test"})
    assert resp.status_code == 200
    assert "X-RateLimit-Limit" in resp.headers
    assert "X-RateLimit-Remaining" in resp.headers
    assert resp.headers["X-RateLimit-Remaining"].isdigit()


@pytest.mark.asyncio
async def test_rate_limit_exempts_monitoring_endpoints(client):
    """Health, metrics, and dashboard should not be rate limited."""
    import energy_router.api as api_mod
    api_mod._rate_limiter = RateLimiter(max_requests=1, window_seconds=60)

    resp = await client.get("/health")
    assert resp.status_code == 200  # first request

    resp = await client.get("/health")
    assert resp.status_code == 200  # second request still works (exempt)


@pytest.mark.asyncio
async def test_rate_limit_blocks_over_limit(client):
    """Client exceeding the rate limit should receive 429."""
    import energy_router.api as api_mod
    api_mod._rate_limiter = RateLimiter(max_requests=2, window_seconds=60)

    resp1 = await client.post("/tasks", json={"name": "t1"})
    assert resp1.status_code == 200

    resp2 = await client.post("/tasks", json={"name": "t2"})
    assert resp2.status_code == 200

    resp3 = await client.post("/tasks", json={"name": "t3"})
    assert resp3.status_code == 429
    data = resp3.json()
    assert "rate limit" in data["detail"].lower()
    assert data["error_code"] == "rate_limited"
    assert data["status"] == 429
