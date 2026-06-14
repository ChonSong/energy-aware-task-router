"""In-memory sliding-window rate limiter for FastAPI.

No external dependencies — uses time.monotonic and a dict of deques.
"""

from __future__ import annotations

import time
import uuid
from collections import defaultdict, deque
from typing import Any

import structlog

logger = structlog.get_logger()

# Default limits: 100 requests per minute per client, 10 burst
DEFAULT_MAX_REQUESTS = 100
DEFAULT_WINDOW_SECONDS = 60
DEFAULT_BURST_MAX = 10
DEFAULT_BURST_WINDOW_SECONDS = 1


class RateLimiter:
    """Sliding-window rate limiter keyed by client identifier.

    Uses time.monotonic for wall-clock independent timestamps.
    Thread-safe for asyncio single-threaded access; if used with
    multiple workers, consider a Redis-backed implementation instead.
    """

    def __init__(
        self,
        max_requests: int = DEFAULT_MAX_REQUESTS,
        window_seconds: float = DEFAULT_WINDOW_SECONDS,
        burst_max: int = DEFAULT_BURST_MAX,
        burst_window_seconds: float = DEFAULT_BURST_WINDOW_SECONDS,
    ):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.burst_max = burst_max
        self.burst_window_seconds = burst_window_seconds
        self._windows: dict[str, deque] = defaultdict(deque)
        self._bursts: dict[str, deque] = defaultdict(deque)

    def _prune(self, dq: deque, window: float) -> None:
        """Remove timestamps older than *window* seconds ago from *dq*."""
        cutoff = time.monotonic() - window
        while dq and dq[0] < cutoff:
            dq.popleft()

    def check(self, key: str, cost: int = 1) -> bool:
        """Return True if request is allowed, False if rate-limited."""
        self._prune(self._windows[key], self.window_seconds)
        self._prune(self._bursts[key], self.burst_window_seconds)

        if len(self._windows[key]) >= self.max_requests:
            return False
        if len(self._bursts[key]) >= self.burst_max:
            return False

        now = time.monotonic()
        self._windows[key].append(now)
        self._bursts[key].append(now)
        return True

    def reset(self, key: str | None = None) -> None:
        """Clear rate-limit state for *key*, or all keys if None."""
        if key is None:
            self._windows.clear()
            self._bursts.clear()
        else:
            self._windows.pop(key, None)
            self._bursts.pop(key, None)

    def remaining(self, key: str) -> int:
        """Return how many requests the client can still make in this window."""
        self._prune(self._windows[key], self.window_seconds)
        self._prune(self._bursts[key], self.burst_window_seconds)
        remaining = self.max_requests - len(self._windows[key])
        burst_remaining = self.burst_max - len(self._bursts[key])
        return min(remaining, burst_remaining)


# Shared default instance — used by the middleware.
_default_limiter: RateLimiter | None = None


def get_default_limiter() -> RateLimiter:
    global _default_limiter
    if _default_limiter is None:
        _default_limiter = RateLimiter()
    return _default_limiter


def extract_client_key(request: Any) -> str:
    """Extract a stable client identifier from a request.

    Priority: X-Forwarded-For > remote addr > uuid fallback.
    """
    headers = getattr(request, "headers", {}) or {}
    forwarded = headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    client = getattr(request, "client", None)
    if client is not None:
        return client.host or str(uuid.uuid4())
    return str(uuid.uuid4())
