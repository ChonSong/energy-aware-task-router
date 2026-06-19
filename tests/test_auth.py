"""Tests for the API key authentication middleware."""

from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

from energy_router.api import app, _auth, _router, _startup_time
from energy_router.auth import APIKeyAuth
from energy_router.carbon import CarbonApiClient
from energy_router.config import load_config
from energy_router.ratelimit import RateLimiter
from energy_router.router import TaskRouter


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Reset the per-app rate limiter before each test."""
    import energy_router.api as api_mod
    api_mod._rate_limiter = RateLimiter(max_requests=1000, window_seconds=60, burst_max=100)
    yield


@pytest.fixture
async def client():
    """Set up the app with no auth keys (permissive mode)."""
    import energy_router.api as api_mod
    cfg = load_config()
    carbon_client = CarbonApiClient(api_key=cfg.carbon_api_key)
    api_mod._router = TaskRouter(carbon_client=carbon_client, default_region=cfg.default_region)
    api_mod._startup_time = 1000.0
    api_mod._auth = APIKeyAuth()  # no keys = permissive

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def secured_client():
    """Set up the app with a configured API key."""
    import energy_router.api as api_mod
    cfg = load_config()
    carbon_client = CarbonApiClient(api_key=cfg.carbon_api_key)
    api_mod._router = TaskRouter(carbon_client=carbon_client, default_region=cfg.default_region)
    api_mod._startup_time = 1000.0
    api_mod._auth = APIKeyAuth(valid_keys=["sk-***"])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Permissive mode (no keys configured)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_permissive_mode_allows_all(client):
    """When no API keys are configured, all requests pass."""
    resp = await client.post("/tasks", json={"name": "test-job"})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_permissive_mode_with_api_key(client):
    """Sending a key when auth is disabled doesn't break anything."""
    resp = await client.post(
        "/tasks",
        json={"name": "test-job"},
        headers={"X-API-Key": "sk-som...-key"},
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Secured mode (keys configured)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_key_returns_401(secured_client):
    """Request without an API key should return 401."""
    resp = await secured_client.post("/tasks", json={"name": "test-job"})
    assert resp.status_code == 401
    data = resp.json()
    assert "detail" in data
    assert "Unauthorized" in data["detail"]
    assert data["error_code"] == "unauthorized"
    assert data["status"] == 401
    assert resp.headers.get("www-authenticate") == "APIKey"


@pytest.mark.asyncio
async def test_invalid_key_returns_401(secured_client):
    """Request with an invalid API key should return 401."""
    resp = await secured_client.post(
        "/tasks",
        json={"name": "test-job"},
        headers={"X-API-Key": "sk-wrong-key"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_valid_key_succeeds(secured_client):
    """Request with a valid API key should succeed."""
    resp = await secured_client.post(
        "/tasks",
        json={"name": "test-job"},
        headers={"X-API-Key": "sk-***"},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_multiple_valid_keys(secured_client):
    """Multiple valid keys should all work."""
    import energy_router.api as api_mod
    api_mod._auth = APIKeyAuth(valid_keys=["sk-alpha", "sk-beta", "sk-gamma"])

    for key in ("sk-alpha", "sk-beta", "sk-gamma"):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                "/tasks",
                json={"name": "test"},
                headers={"X-API-Key": key},
            )
        assert resp.status_code == 200, f"Key {key} should be valid"


@pytest.mark.asyncio
async def test_auth_exempts_health_endpoint(secured_client):
    """Health endpoint should bypass auth."""
    resp = await secured_client.get("/health")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_auth_exempts_metrics_endpoint(secured_client):
    """Metrics endpoint should bypass auth."""
    resp = await secured_client.get("/metrics")
    assert resp.status_code == 200
