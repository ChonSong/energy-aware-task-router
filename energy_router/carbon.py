"""Carbon intensity data fetching from electricitymap.org API."""

from __future__ import annotations

import datetime
from dataclasses import dataclass
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


class CarbonApiClient:
    """Fetches real-time carbon intensity from electricitymap.org API.

    Falls back to UNKNOWN level if the API is unreachable or the key is missing.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://api.electricitymap.org/v3",
        timeout: int = 10,
        cache_ttl: int = 300,
        http_client: Any | None = None,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.cache_ttl = cache_ttl
        self._cache: dict[str, tuple[datetime.datetime, GridConditions]] = {}
        # Shared HTTPX client — set externally for lifecycle management.
        # When None, a temporary client is created per-request (legacy behaviour).
        self._http_client = http_client

    # -- lifecycle -----------------------------------------------------------

    async def close(self) -> None:
        """Close the shared HTTP client if one was provided (no-op otherwise).

        This is called automatically by the lifecycle manager when the
        server shuts down.
        """
        if self._http_client is not None:
            try:
                await self._http_client.aclose()
            except Exception:
                pass

    # -- public API ----------------------------------------------------------

    async def fetch_carbon_intensity(self, region: str = "AU-NSW") -> GridConditions:
        """Fetch current carbon intensity for the given region.

        Returns cached data if it's still fresh (within cache_ttl).
        Falls back to UNKNOWN on any error.
        """
        now = datetime.datetime.utcnow()

        # Check cache
        if region in self._cache:
            cached_at, cached_conditions = self._cache[region]
            if (now - cached_at).total_seconds() < self.cache_ttl:
                return cached_conditions

        # No API key — return simulated/unknown data
        if not self.api_key:
            logger.warning("carbon_api.no_key", region=region)
            conditions = GridConditions(
                timestamp=now,
                carbon_intensity_gco2kwh=None,
                level=GridCarbonLevel.UNKNOWN,
                region=region,
                source="no_api_key",
            )
            self._cache[region] = (now, conditions)
            return conditions

        try:
            import httpx

            url = f"{self.base_url}/carbon-intensity/latest"
            params = {"zone": region}
            headers = {"auth-token": self.api_key}

            if self._http_client is not None:
                # Use the shared client (managed by LifecycleManager)
                resp = await self._http_client.get(url, params=params, headers=headers)
            else:
                # Legacy: create a temporary client per request
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            data = resp.json()

            intensity = data.get("carbonIntensity")
            if intensity is not None:
                intensity = float(intensity)

            level = self._intensity_to_level(intensity)

            conditions = GridConditions(
                timestamp=now,
                carbon_intensity_gco2kwh=intensity,
                level=level,
                region=region,
                source="electricitymap.org",
            )
            self._cache[region] = (now, conditions)
            logger.info("carbon_api.success", region=region, intensity=intensity, level=level.value)
            return conditions

        except Exception as exc:
            logger.error("carbon_api.failure", region=region, error=str(exc))
            conditions = GridConditions(
                timestamp=now,
                carbon_intensity_gco2kwh=None,
                level=GridCarbonLevel.UNKNOWN,
                region=region,
                source="error_fallback",
            )
            self._cache[region] = (now, conditions)
            return conditions

    @staticmethod
    def _intensity_to_level(intensity: float | None) -> GridCarbonLevel:
        """Convert carbon intensity gCO2/kWh to a qualitative level."""
        if intensity is None:
            return GridCarbonLevel.UNKNOWN
        if intensity < 200:
            return GridCarbonLevel.LOW
        if intensity < 450:
            return GridCarbonLevel.MEDIUM
        return GridCarbonLevel.HIGH
