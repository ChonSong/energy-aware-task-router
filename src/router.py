"""Core routing logic for energy-aware task scheduling."""

from __future__ import annotations

import asyncio
import datetime
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog

logger = structlog.get_logger()


class GridCarbonLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"


@dataclass
class GridConditions:
    timestamp: datetime.datetime
    carbon_intensity_gco2kwh: float | None
    level: GridCarbonLevel
    region: str
    source: str | None = None

    def __post_init__(self):
        if self.carbon_intensity_gco2kwh is None:
            self.level = GridCarbonLevel.UNKNOWN


@dataclass
class Task:
    id: str
    name: str
    deferrable: bool = True
    defer_until: GridCarbonLevel | None = None
    deadline: datetime.datetime | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    @property
    def can_defer(self) -> bool:
        if not self.deferrable:
            return False
        if self.deadline and datetime.datetime.utcnow() >= self.deadline:
            return False
        return True


@dataclass
class RoutingDecision:
    task_id: str
    decision: str
    grid_conditions: GridConditions
    reason: str
    timestamp: datetime.datetime = field(default_factory=datetime.datetime.utcnow)


class CarbonApiClient:
    """Fetches real-time carbon intensity. Stub — replace with real API when key is set."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key

    async def fetch_carbon_intensity(self, region: str = "AU-NSW") -> GridConditions:
        now = datetime.datetime.utcnow()
        if self.api_key:
            pass  # TODO: implement electricitymap.org API call
        level = GridCarbonLevel.LOW if now.hour % 3 == 0 else GridCarbonLevel.MEDIUM
        return GridConditions(
            timestamp=now,
            carbon_intensity_gco2kwh=250.0,
            level=level,
            region=region,
            source="simulation",
        )


class TaskRouter:
    def __init__(self, carbon_client: CarbonApiClient):
        self.carbon = carbon_client

    async def route(self, task: Task) -> RoutingDecision:
        conditions = await self.carbon.fetch_carbon_intensity()
        target_level = task.defer_until or GridCarbonLevel.LOW

        if not task.can_defer:
            decision = "route_now"
            reason = "task deadline reached or non-deferrable"
        elif conditions.level == target_level or conditions.level == GridCarbonLevel.LOW:
            decision = "route_now"
            reason = f"carbon level {conditions.level.value} meets target {target_level.value}"
        elif conditions.level == GridCarbonLevel.UNKNOWN:
            decision = "route_now"
            reason = "carbon data unavailable — defaulting to route now"
        else:
            decision = "defer"
            reason = f"carbon level {conditions.level.value} does not meet target {target_level.value}"

        routing_decision = RoutingDecision(
            task_id=task.id,
            decision=decision,
            grid_conditions=conditions,
            reason=reason,
        )
        logger.info(
            "routing_decision",
            task_id=task.id,
            decision=decision,
            carbon_level=conditions.level.value,
            reason=reason,
        )
        return routing_decision
