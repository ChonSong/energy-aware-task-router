"""Tests for graceful shutdown and lifecycle management."""

from __future__ import annotations

import pytest
import structlog

from energy_router.lifecycle import LifecycleManager


# ---------------------------------------------------------------------------
# LifecycleManager unit tests
# ---------------------------------------------------------------------------


def test_lifecycle_initial_state():
    """LifecycleManager should start with no registered resources."""
    lm = LifecycleManager()
    assert lm._http_client is None
    assert lm._redis_url is None


def test_lifecycle_set_http_client():
    """Registered HTTP client should be stored for shutdown."""
    lm = LifecycleManager()
    client = "fake_client"
    lm.set_http_client(client)
    assert lm._http_client == "fake_client"


def test_lifecycle_set_redis_url():
    """Registered Redis URL should be stored for shutdown."""
    lm = LifecycleManager()
    lm.set_redis_url("redis://localhost:***@***.***")
    assert lm._redis_url == "redis://localhost:***@***.***"


@pytest.mark.asyncio
async def test_lifecycle_shutdown_with_no_resources():
    """Shutdown with no registered resources should be a no-op."""
    lm = LifecycleManager()
    # Should not raise
    await lm.shutdown()


@pytest.mark.asyncio
async def test_lifecycle_shutdown_with_mock_client():
    """Shutdown should close a registered async client."""
    lm = LifecycleManager()

    class MockClient:
        closed = False

        async def aclose(self):
            self.closed = True

    client = MockClient()
    lm.set_http_client(client)
    await lm.shutdown()
    assert client.closed, "HTTP client should have been closed"


@pytest.mark.asyncio
async def test_lifecycle_shutdown_client_error_does_not_bubble():
    """If client.close() raises, shutdown should still complete."""
    lm = LifecycleManager()

    class FailingClient:
        async def aclose(self):
            raise RuntimeError("connection reset")

    lm.set_http_client(FailingClient())
    # Should not raise
    await lm.shutdown()


# ---------------------------------------------------------------------------
# Integration: startup / shutdown event handlers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_startup_initializes_globals():
    """Calling startup() should set _router, _rate_limiter, _auth, _lifecycle."""
    import energy_router.api as api_mod

    # Reset globals
    api_mod._router = None
    api_mod._startup_time = None
    api_mod._rate_limiter = None
    api_mod._auth = None
    api_mod._lifecycle = None

    await api_mod.startup()

    # Check via module reference (not local import) to avoid rebinding issues
    assert api_mod._router is not None
    assert api_mod._startup_time is not None
    assert api_mod._rate_limiter is not None
    assert api_mod._auth is not None
    assert api_mod._lifecycle is not None


@pytest.mark.asyncio
async def test_shutdown_cleans_http_client():
    """Shutdown event should close the HTTP client via LifecycleManager."""
    from energy_router.api import startup, shutdown, _lifecycle

    import energy_router.api as api_mod
    api_mod._router = None
    api_mod._startup_time = None
    api_mod._rate_limiter = None
    api_mod._auth = None
    api_mod._lifecycle = None

    await startup()

    # Confirm the lifecycle manager has an HTTP client registered
    assert _lifecycle is not None
    http_client = _lifecycle._http_client
    assert http_client is not None, "LifecycleManager should have an HTTP client after startup"

    # Shutdown should close it
    await shutdown()

    # After shutdown, trying to use the client should raise (connection closed)
    import httpx
    with pytest.raises(Exception):
        await http_client.get("http://localhost:***/")


@pytest.mark.asyncio
async def test_double_shutdown_safe():
    """Calling shutdown twice should not raise."""
    from energy_router.api import startup, shutdown

    import energy_router.api as api_mod
    api_mod._router = None
    api_mod._startup_time = None
    api_mod._rate_limiter = None
    api_mod._auth = None
    api_mod._lifecycle = None

    await startup()
    await shutdown()
    # Second call is safe
    await shutdown()


@pytest.mark.asyncio
async def test_health_works_after_startup():
    """After startup, the health endpoint should report correctly."""
    from energy_router.api import startup

    import energy_router.api as api_mod
    api_mod._router = None
    api_mod._startup_time = None
    api_mod._rate_limiter = None
    api_mod._auth = None
    api_mod._lifecycle = None

    await startup()

    from energy_router.api import health as health_handler
    result = await health_handler()
    # health() now returns a HealthResponse model (not a dict)
    assert result.status in ("healthy", "degraded")
    assert result.version == "0.1.0"
    assert result.uptime_seconds >= 0
    assert not hasattr(result, "lifecycle")  # just to confirm no leak
