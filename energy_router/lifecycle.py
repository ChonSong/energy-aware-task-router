"""Lifecycle manager — shared resource pool and graceful shutdown.

Tracks long-lived connections (HTTP client, Redis, etc.) and provides
a single ``shutdown()`` entry-point that the FastAPI shutdown event
handler calls.
"""

from __future__ import annotations

import time
from typing import Any

import structlog

logger = structlog.get_logger()


class LifecycleManager:
    """Container for shared resources that need explicit setup and teardown.

    Usage::

        lm = LifecycleManager()
        # … app startup …
        lm.set_http_client(client)
        lm.set_redis_url("redis://…")
        # … on shutdown …
        await lm.shutdown()
    """

    def __init__(self) -> None:
        self._http_client: Any = None
        self._redis_url: str | None = None
        self._shutdown_start: float | None = None
        self._shutdown_timeout: float = 10.0  # seconds

    # -- resource registration -----------------------------------------------

    def set_http_client(self, client: Any) -> None:
        """Register an ``httpx.AsyncClient`` (or compatible) to close on shutdown."""
        self._http_client = client

    def set_redis_url(self, url: str | None) -> None:
        """Remember Redis URL so we can cleanly disconnect on shutdown."""
        self._redis_url = url

    # -- shutdown ------------------------------------------------------------

    async def shutdown(self) -> None:
        """Gracefully close all registered resources.

        This is intended to be called from the FastAPI shutdown event
        handler.  It logs each step and swallows individual errors so
        that one failing resource does not prevent others from being
        cleaned up.
        """
        self._shutdown_start = time.monotonic()
        logger.info("lifecycle.shutdown_started", timeout_seconds=self._shutdown_timeout)

        errors: list[tuple[str, str]] = []

        # 1. Close HTTP client (Carbon API, etc.)
        if self._http_client is not None:
            try:
                await self._http_client.aclose()
                logger.info("lifecycle.http_client_closed")
            except Exception as exc:
                errors.append(("http_client", str(exc)))
                logger.error("lifecycle.http_client_close_failed", error=str(exc))

        # 2. Close Redis connection
        if self._redis_url:
            try:
                import redis as rmod

                conn = rmod.from_url(self._redis_url)
                try:
                    conn.ping()
                    conn.close()
                    logger.info("lifecycle.redis_connection_closed")
                except Exception:
                    logger.info("lifecycle.redis_not_reachable_skip_close")
            except Exception as exc:
                errors.append(("redis", str(exc)))
                logger.error("lifecycle.redis_close_failed", error=str(exc))

        elapsed = time.monotonic() - self._shutdown_start
        logger.info(
            "lifecycle.shutdown_complete",
            elapsed_seconds=round(elapsed, 3),
            error_count=len(errors),
        )

        if errors:
            for resource, msg in errors:
                logger.warning("lifecycle.shutdown_error", resource=resource, error=msg)
