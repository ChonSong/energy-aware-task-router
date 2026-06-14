"""Core routing logic for energy-aware task scheduling."""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any

import structlog

from energy_router.carbon import CarbonApiClient, GridCarbonLevel, GridConditions

logger = structlog.get_logger()


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


class TaskRouter:
    def __init__(self, carbon_client: CarbonApiClient, default_region: str = "AU-NSW"):
        self.carbon = carbon_client
        self.default_region = default_region

    async def route(self, task: Task) -> RoutingDecision:
        conditions = await self.carbon.fetch_carbon_intensity(region=self.default_region)
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
