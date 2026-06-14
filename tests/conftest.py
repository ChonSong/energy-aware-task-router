"""Pytest configuration and fixtures for energy-router tests."""

from __future__ import annotations

from typing import AsyncGenerator

import httpx
import pytest
import pytest_asyncio

from energy_router.carbon import CarbonApiClient


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Reset the global rate limiter before each test to avoid cross-test pollution."""
    from energy_router.ratelimit import get_default_limiter
    get_default_limiter().reset()
    yield


@pytest.fixture
def api_key() -> str | None:
    return None


@pytest_asyncio.fixture
async def carbon_client(api_key: str | None) -> AsyncGenerator[CarbonApiClient, None]:
    client = CarbonApiClient(api_key=api_key)
    yield client


@pytest_asyncio.fixture
async def carbon_client_mocked(api_key: str | None) -> AsyncGenerator[CarbonApiClient, None]:
    """CarbonApiClient with mocking set up for httpx."""
    client = CarbonApiClient(api_key=api_key or "test-key")
    yield client
