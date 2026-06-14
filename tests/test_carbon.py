"""Tests for the CarbonApiClient."""

from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, patch

import pytest

from energy_router.carbon import CarbonApiClient, GridCarbonLevel


@pytest.mark.asyncio
async def test_fetch_without_api_key_returns_unknown():
    """Without an API key, should return UNKNOWN level."""
    client = CarbonApiClient(api_key=None)
    conditions = await client.fetch_carbon_intensity(region="AU-NSW")
    assert conditions.level == GridCarbonLevel.UNKNOWN
    assert conditions.carbon_intensity_gco2kwh is None
    assert conditions.source == "no_api_key"


@pytest.mark.asyncio
async def test_fetch_cached_response():
    """Should return cached response within cache_ttl."""
    client = CarbonApiClient(api_key="test-key")
    conditions = await client.fetch_carbon_intensity(region="AU-NSW")
    # Second call should be cached (even without mock, it'll return the same UNKNOWN)
    conditions2 = await client.fetch_carbon_intensity(region="AU-NSW")
    assert conditions2.timestamp == conditions.timestamp


@pytest.mark.asyncio
async def test_api_success():
    """Mock a successful API response with LOW intensity."""
    client = CarbonApiClient(api_key="real-key")
    client._cache.clear()

    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"carbonIntensity": 150.0, "zone": "AU-NSW"}

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
        conditions = await client.fetch_carbon_intensity(region="AU-NSW")

    assert conditions.level == GridCarbonLevel.LOW
    assert conditions.carbon_intensity_gco2kwh == 150.0
    assert conditions.source == "electricitymap.org"


@pytest.mark.asyncio
async def test_api_failure_returns_unknown():
    """When API call fails, should return UNKNOWN level."""
    client = CarbonApiClient(api_key="real-key")
    client._cache.clear()

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, side_effect=Exception("API timeout")):
        conditions = await client.fetch_carbon_intensity(region="AU-NSW")

    assert conditions.level == GridCarbonLevel.UNKNOWN
    assert conditions.carbon_intensity_gco2kwh is None
    assert conditions.source == "error_fallback"


@pytest.mark.asyncio
async def test_intensity_to_level():
    """Test the intensity-to-level mapping."""
    assert CarbonApiClient._intensity_to_level(50) == GridCarbonLevel.LOW
    assert CarbonApiClient._intensity_to_level(199) == GridCarbonLevel.LOW
    assert CarbonApiClient._intensity_to_level(200) == GridCarbonLevel.MEDIUM
    assert CarbonApiClient._intensity_to_level(449) == GridCarbonLevel.MEDIUM
    assert CarbonApiClient._intensity_to_level(450) == GridCarbonLevel.HIGH
    assert CarbonApiClient._intensity_to_level(999) == GridCarbonLevel.HIGH
    assert CarbonApiClient._intensity_to_level(None) == GridCarbonLevel.UNKNOWN
