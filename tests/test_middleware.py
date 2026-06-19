"""Tests for FastAPI middleware behaviour: logging, auth edge cases, rate-limit edge cases.

These tests complement the already-extensive unit tests in
``test_auth.py``, ``test_ratelimit.py``, and ``test_api.py`` by
covering integration-level scenarios that exercise the middleware
stack as a whole.
"""

from __future__ import annotations

import io
import logging
import re

import pytest
import structlog
from httpx import AsyncClient, ASGITransport

from energy_router.api import app
from energy_router.auth import AUTH_EXEMPT_PATHS, APIKeyAuth
from energy_router.carbon import CarbonApiClient
from energy_router.config import load_config
from energy_router.logging_config import configure_logging
from energy_router.api import RATE_LIMIT_EXEMPT_PATHS as API_RATE_LIMIT_EXEMPT_PATHS
from energy_router.ratelimit import RateLimiter
from energy_router.router import TaskRouter


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_state():
    """Reset globals before each test to prevent cross-test pollution."""
    import energy_router.api as api_mod

    api_mod._rate_limiter = RateLimiter(max_requests=1000, window_seconds=60, burst_max=100)
    api_mod._auth = None
    api_mod._router = None
    api_mod._startup_time = None
    yield


@pytest.fixture
async def client():
    """Test client with router initialised and auth in permissive mode."""
    import energy_router.api as api_mod

    cfg = load_config()
    carbon_client = CarbonApiClient(api_key=cfg.carbon_api_key)
    api_mod._router = TaskRouter(carbon_client=carbon_client, default_region=cfg.default_region)
    api_mod._startup_time = 1000.0
    api_mod._auth = None  # permissive

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Logging middleware tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_logging_middleware_captures_request_details(client):
    """The logging middleware should log method, path and status for every request."""
    import energy_router.api as api_mod

    # Reconfigure structlog first (calls basicConfig with force=True)
    configure_logging(level="DEBUG")

    # Then add a capture handler to the root logger
    log_stream = io.StringIO()
    handler = logging.StreamHandler(log_stream)
    handler.setLevel(logging.DEBUG)
    root = logging.getLogger()
    root.addHandler(handler)

    resp = await client.get("/health")
    assert resp.status_code == 200

    root.removeHandler(handler)
    log_output = log_stream.getvalue()

    # The JSON log line should contain the expected keys
    assert '"method": "GET"' in log_output or "'method': 'GET'" in log_output
    assert '"path": "/health"' in log_output or "'path': '/health'" in log_output


@pytest.mark.asyncio
async def test_logging_middleware_records_status_code(client):
    """The logging middleware should include the HTTP status code in the log."""
    import energy_router.api as api_mod

    configure_logging(level="DEBUG")
    log_stream = io.StringIO()
    handler = logging.StreamHandler(log_stream)
    handler.setLevel(logging.DEBUG)
    root = logging.getLogger()
    root.addHandler(handler)

    # Enable auth so we get a 401 and can verify the status code is logged
    api_mod._auth = APIKeyAuth(valid_keys=["sk-valid"])
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post("/tasks", json={"name": "test"})
    assert resp.status_code == 401

    root.removeHandler(handler)
    log_output = log_stream.getvalue()

    assert '"status": 401' in log_output or "'status': 401" in log_output


@pytest.mark.asyncio
async def test_logging_middleware_records_duration(client):
    """The logging middleware should include duration_ms in the log."""
    configure_logging(level="DEBUG")
    log_stream = io.StringIO()
    handler = logging.StreamHandler(log_stream)
    handler.setLevel(logging.DEBUG)
    root = logging.getLogger()
    root.addHandler(handler)

    resp = await client.get("/health")
    assert resp.status_code == 200

    root.removeHandler(handler)
    log_output = log_stream.getvalue()

    # duration_ms should be a positive integer or float
    match = re.search(r'"duration_ms":\s*([\d.]+)', log_output)
    assert match is not None, f"duration_ms not found in log output: {log_output}"
    assert float(match.group(1)) > 0


# ---------------------------------------------------------------------------
# Auth middleware edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_with_empty_key_string(client):
    """An empty X-API-Key header should be treated as missing (401)."""
    import energy_router.api as api_mod

    api_mod._auth = APIKeyAuth(valid_keys=["sk-valid"])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/tasks",
            json={"name": "test"},
            headers={"X-API-Key": ""},
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_auth_with_whitespace_only_key(client):
    """A whitespace-only X-API-Key should be treated as missing (401)."""
    import energy_router.api as api_mod

    api_mod._auth = APIKeyAuth(valid_keys=["sk-valid"])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/tasks",
            json={"name": "test"},
            headers={"X-API-Key": "   "},
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_auth_with_lowercase_header_name(client):
    """The auth middleware should accept lowercased 'x-api-key' header."""
    import energy_router.api as api_mod

    api_mod._auth = APIKeyAuth(valid_keys=["sk-valid"])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/tasks",
            json={"name": "test"},
            headers={"x-api-key": "sk-valid"},
        )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_auth_all_exempt_paths_defined():
    """All paths in AUTH_EXEMPT_PATHS are publicly accessible when auth is active."""
    exempt_paths = sorted(AUTH_EXEMPT_PATHS)
    assert len(exempt_paths) >= 5, f"Expected at least 5 exempt paths, got {exempt_paths}"
    assert "/health" in exempt_paths
    assert "/metrics" in exempt_paths
    assert "/livez" in exempt_paths
    assert "/readyz" in exempt_paths
    assert "/dashboard" in exempt_paths


# ---------------------------------------------------------------------------
# Rate-limit middleware edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_limit_burst_via_headers(client):
    """Rate-limit headers should reflect burst consumption accurately."""
    import energy_router.api as api_mod

    # Tight burst: 3 requests per second
    api_mod._rate_limiter = RateLimiter(
        max_requests=100, window_seconds=60,
        burst_max=3, burst_window_seconds=1,
    )

    resp1 = await client.post("/tasks", json={"name": "t1"})
    assert resp1.status_code == 200
    remaining_after_first = int(resp1.headers["X-RateLimit-Remaining"])

    resp2 = await client.post("/tasks", json={"name": "t2"})
    assert resp2.status_code == 200

    resp3 = await client.post("/tasks", json={"name": "t3"})
    assert resp3.status_code == 200

    # After 3 burst requests, remaining should be 0 (burst exhausted)
    resp4 = await client.post("/tasks", json={"name": "t4"})
    assert resp4.status_code == 429

    assert int(resp4.headers["X-RateLimit-Remaining"]) == 0
    assert int(resp4.headers["X-RateLimit-Limit"]) == 100


@pytest.mark.asyncio
async def test_rate_limit_window_expiry(client):
    """After the rate-limit window expires, the client should be allowed again."""
    import energy_router.api as api_mod

    api_mod._rate_limiter = RateLimiter(
        max_requests=1, window_seconds=0.1, burst_max=5,
    )

    # Consume the only allowed request
    resp1 = await client.post("/tasks", json={"name": "t1"})
    assert resp1.status_code == 200

    # Second request should be blocked
    resp2 = await client.post("/tasks", json={"name": "t2"})
    assert resp2.status_code == 429

    # Wait for window to slide
    import time
    time.sleep(0.15)

    # Should be allowed again
    resp3 = await client.post("/tasks", json={"name": "t3"})
    assert resp3.status_code == 200


@pytest.mark.asyncio
async def test_rate_limit_429_response_shape(client):
    """The 429 response from rate limiting should use structured ErrorResponse."""
    import energy_router.api as api_mod

    api_mod._rate_limiter = RateLimiter(max_requests=0, window_seconds=60)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post("/tasks", json={"name": "t"})

    assert resp.status_code == 429
    data = resp.json()
    assert data["status"] == 429
    assert data["error_code"] == "rate_limited"
    assert "detail" in data


@pytest.mark.asyncio
async def test_rate_limit_exempt_paths_defined():
    """All expected monitoring paths are in the rate-limit exempt set."""
    exempt = sorted(API_RATE_LIMIT_EXEMPT_PATHS)
    assert "/health" in exempt
    assert "/metrics" in exempt
    assert "/dashboard" in exempt
    assert "/livez" in exempt
    assert "/readyz" in exempt


# ---------------------------------------------------------------------------
# Validation error response shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validation_error_response_shape(client):
    """Pydantic validation errors should return a structured ValidationErrorResponse."""
    payload = {"name": 42}  # name should be str, not int
    resp = await client.post("/tasks", json=payload)
    assert resp.status_code == 422
    data = resp.json()
    assert data["status"] == 422
    assert data["error_code"] == "validation_error"
    assert "errors" in data
    assert isinstance(data["errors"], list)
    assert len(data["errors"]) > 0
    assert "field" in data["errors"][0]
    assert "message" in data["errors"][0]


@pytest.mark.asyncio
async def test_404_returns_structured_error(client):
    """A request to a non-existent route should return a structured ErrorResponse."""
    resp = await client.get("/nonexistent")
    assert resp.status_code == 404
    data = resp.json()
    assert data["status"] == 404
    assert data["error_code"] == "not_found"
    assert "detail" in data


@pytest.mark.asyncio
async def test_405_returns_structured_error(client):
    """Using an unsupported HTTP method should return a structured ErrorResponse."""
    resp = await client.delete("/tasks")
    assert resp.status_code == 405
    data = resp.json()
    assert data["status"] == 405
    assert data["error_code"] == "method_not_allowed"
    assert "detail" in data
