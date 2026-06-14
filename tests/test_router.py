"""Tests for the TaskRouter."""

from __future__ import annotations

import datetime
from unittest.mock import AsyncMock

import pytest

from energy_router.carbon import CarbonApiClient, GridCarbonLevel, GridConditions
from energy_router.router import Task, TaskRouter


@pytest.fixture
def mock_carbon_client():
    client = AsyncMock(spec=CarbonApiClient)
    return client


@pytest.mark.asyncio
async def test_route_non_deferrable_task():
    """Non-deferrable tasks should always route now."""
    client = AsyncMock(spec=CarbonApiClient)
    client.fetch_carbon_intensity.return_value = GridConditions(
        timestamp=datetime.datetime.utcnow(),
        carbon_intensity_gco2kwh=500.0,
        level=GridCarbonLevel.HIGH,
        region="AU-NSW",
    )
    router = TaskRouter(carbon_client=client)
    task = Task(id="1", name="urgent", deferrable=False)
    decision = await router.route(task)
    assert decision.decision == "route_now"
    assert "non-deferrable" in decision.reason


@pytest.mark.asyncio
async def test_route_deferrable_when_high_carbon():
    """Deferrable tasks should be deferred when carbon is high."""
    client = AsyncMock(spec=CarbonApiClient)
    client.fetch_carbon_intensity.return_value = GridConditions(
        timestamp=datetime.datetime.utcnow(),
        carbon_intensity_gco2kwh=500.0,
        level=GridCarbonLevel.HIGH,
        region="AU-NSW",
    )
    router = TaskRouter(carbon_client=client)
    task = Task(id="2", name="batch", deferrable=True)
    decision = await router.route(task)
    assert decision.decision == "defer"


@pytest.mark.asyncio
async def test_route_when_low_carbon():
    """Should route now when carbon is already low."""
    client = AsyncMock(spec=CarbonApiClient)
    client.fetch_carbon_intensity.return_value = GridConditions(
        timestamp=datetime.datetime.utcnow(),
        carbon_intensity_gco2kwh=100.0,
        level=GridCarbonLevel.LOW,
        region="AU-NSW",
    )
    router = TaskRouter(carbon_client=client)
    task = Task(id="3", name="batch", deferrable=True)
    decision = await router.route(task)
    assert decision.decision == "route_now"


@pytest.mark.asyncio
async def test_route_unknown_carbon_defaults_to_now():
    """When carbon data is unknown, should route now by default."""
    client = AsyncMock(spec=CarbonApiClient)
    client.fetch_carbon_intensity.return_value = GridConditions(
        timestamp=datetime.datetime.utcnow(),
        carbon_intensity_gco2kwh=None,
        level=GridCarbonLevel.UNKNOWN,
        region="AU-NSW",
    )
    router = TaskRouter(carbon_client=client)
    task = Task(id="4", name="batch", deferrable=True)
    decision = await router.route(task)
    assert decision.decision == "route_now"
    assert "unavailable" in decision.reason.lower()


@pytest.mark.asyncio
async def test_route_task_with_deadline_passed():
    """Tasks past their deadline should route now even if deferrable."""
    client = AsyncMock(spec=CarbonApiClient)
    client.fetch_carbon_intensity.return_value = GridConditions(
        timestamp=datetime.datetime.utcnow(),
        carbon_intensity_gco2kwh=500.0,
        level=GridCarbonLevel.HIGH,
        region="AU-NSW",
    )
    router = TaskRouter(carbon_client=client)
    past = datetime.datetime.utcnow() - datetime.timedelta(hours=1)
    task = Task(id="5", name="late", deferrable=True, deadline=past)
    decision = await router.route(task)
    assert decision.decision == "route_now"
    assert "deadline" in decision.reason


@pytest.mark.asyncio
async def test_routing_decision_includes_grid_conditions():
    """RoutingDecision should contain the grid conditions at decision time."""
    client = AsyncMock(spec=CarbonApiClient)
    client.fetch_carbon_intensity.return_value = GridConditions(
        timestamp=datetime.datetime.utcnow(),
        carbon_intensity_gco2kwh=100.0,
        level=GridCarbonLevel.LOW,
        region="AU-NSW",
    )
    router = TaskRouter(carbon_client=client)
    task = Task(id="6", name="batch", deferrable=True)
    decision = await router.route(task)
    assert decision.grid_conditions.level == GridCarbonLevel.LOW
    assert decision.task_id == "6"
