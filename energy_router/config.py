"""Configuration loading for the energy-aware task router."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class RouterConfig:
    """Top-level configuration for the energy-aware task router."""

    # Region to query carbon intensity for
    default_region: str = "AU-NSW"

    # Carbon API settings
    carbon_api_key: str | None = None
    carbon_api_base_url: str = "https://api.electricitymap.org/v3"
    carbon_api_timeout: int = 10
    carbon_cache_ttl: int = 300

    # Fallback when carbon API is unavailable
    fallback_behavior: str = "route_now"

    # Audit settings
    audit_format: str = "json"
    audit_level: str = "info"
    audit_file: str = "logs/routing_audit.jsonl"

    # Task defaults
    default_max_deferral_hours: int = 24
    eligible_types: list[str] = field(
        default_factory=lambda: ["batch_compute", "model_training", "report_generation"]
    )

    # API key authentication
    api_keys: list[str] = field(default_factory=list)

    # Logging
    log_level: str = "INFO"
    log_format: str = "json"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RouterConfig:
        """Build config from a nested dict (as parsed from YAML)."""
        cfg = cls()
        router = data.get("router", {})
        carbon = data.get("carbon_api", {})
        audit = data.get("audit", {})
        tasks = data.get("tasks", {})
        auth = data.get("auth", {})
        logging_cfg = data.get("logging", {})

        if "default_region" in router:
            cfg.default_region = router["default_region"]
        if "carbon_api_timeout" in router:
            cfg.carbon_api_timeout = int(router["carbon_api_timeout"])
        if "fallback_behavior" in router:
            cfg.fallback_behavior = router["fallback_behavior"]

        if "api_key" in carbon:
            cfg.carbon_api_key = carbon["api_key"]
        if "base_url" in carbon:
            cfg.carbon_api_base_url = carbon["base_url"]
        if "cache_ttl" in carbon:
            cfg.carbon_cache_ttl = int(carbon["cache_ttl"])

        if "format" in audit:
            cfg.audit_format = audit["format"]
        if "level" in audit:
            cfg.audit_level = audit["level"]
        if "file" in audit:
            cfg.audit_file = audit["file"]

        if "default_max_deferral" in tasks:
            # Parse ISO 8601 duration like PT24H
            dur = tasks["default_max_deferral"]
            if dur.startswith("PT") and dur.endswith("H"):
                cfg.default_max_deferral_hours = int(dur[2:-1])
        if "eligible_types" in tasks:
            cfg.eligible_types = tasks["eligible_types"]

        if "api_keys" in auth:
            cfg.api_keys = auth["api_keys"]

        if "level" in logging_cfg:
            cfg.log_level = logging_cfg["level"]
        if "format" in logging_cfg:
            cfg.log_format = logging_cfg["format"]

        return cfg


def load_config(path: str | Path | None = None) -> RouterConfig:
    """Load configuration from a YAML file, with env var overrides.

    Env vars:
        CARBON_API_KEY        overrides carbon_api.api_key
        ROUTER_DEFAULT_REGION overrides router.default_region
        ROUTER_API_KEYS       overrides auth.api_keys (comma-separated)
    """
    import os

    cfg = RouterConfig()

    # Try loading from file
    if path is not None:
        path = Path(path)
        if path.exists():
            with open(path) as f:
                data = yaml.safe_load(f)
            if data:
                cfg = RouterConfig.from_dict(data)

    # Environment variable overrides
    if api_key := os.environ.get("CARBON_API_KEY"):
        cfg.carbon_api_key = api_key
    if region := os.environ.get("ROUTER_DEFAULT_REGION"):
        cfg.default_region = region
    if env_keys := os.environ.get("ROUTER_API_KEYS"):
        cfg.api_keys = [k.strip() for k in env_keys.replace(",", " ").split() if k.strip()]

    if log_level := os.environ.get("LOG_LEVEL"):
        cfg.log_level = log_level.upper()
    if log_format := os.environ.get("LOG_FORMAT"):
        cfg.log_format = log_format.lower()

    return cfg
