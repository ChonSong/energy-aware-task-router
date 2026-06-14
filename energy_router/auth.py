"""API key authentication middleware.

Supports multiple static keys configured via YAML config or environment
variable ``ROUTER_API_KEYS`` (comma-separated).  If no keys are configured
the middleware is a no-op (permissive mode) for local development.
"""

from __future__ import annotations

import os
from typing import Any, Sequence

import structlog

logger = structlog.get_logger()

AUTH_HEADER = "X-API-Key"
AUTH_EXEMPT_PATHS = {"/health", "/metrics", "/dashboard"}


class APIKeyAuth:
    """Simple static API key authenticator.

    Usage::

        auth = APIKeyAuth(["sk-...", "sk-..."])
        # In middleware:
        if not auth.authenticate(request):
            return JSONResponse(status_code=401, ...)
    """

    def __init__(self, valid_keys: Sequence[str] | None = None) -> None:
        self._valid_keys: set[str] = set(valid_keys or [])
        if self._valid_keys:
            logger.info("api_key_auth_enabled", key_count=len(self._valid_keys))
        else:
            logger.warning(
                "api_key_auth_disabled",
                detail="No API keys configured — all requests will be allowed",
            )

    @property
    def enabled(self) -> bool:
        """True when at least one key has been configured."""
        return bool(self._valid_keys)

    def authenticate(self, api_key: str | None) -> bool:
        """Return True if *api_key* is recognised.

        When auth is disabled (no keys configured) every key is accepted.
        """
        if not self.enabled:
            return True
        if not api_key:
            return False
        return api_key in self._valid_keys

    @classmethod
    def from_config(
        cls,
        config_keys: list[str] | None = None,
        env_var: str = "ROUTER_API_KEYS",
    ) -> APIKeyAuth:
        """Build an authenticator from config and/or an environment variable.

        Priority:  config_keys (YAML) > env var > no auth.
        """
        keys: list[str] = []

        # 1. Try YAML config
        if config_keys:
            keys.extend(config_keys)

        # 2. Try environment variable (comma or whitespace separated)
        env_val = os.environ.get(env_var, "")
        if env_val:
            keys.extend(k.strip() for k in env_val.replace(",", " ").split() if k.strip())

        # 3. Deduplicate while preserving order
        seen: set[str] = set()
        unique_keys: list[str] = []
        for k in keys:
            if k not in seen:
                seen.add(k)
                unique_keys.append(k)

        return cls(valid_keys=unique_keys)
