"""Redis-backed deferral queue for postponed tasks."""

from __future__ import annotations

import json
import time
from typing import Any

import structlog

logger = structlog.get_logger()


class TaskQueue:
    """Stores deferred tasks in a Redis sorted set.

    Score = unix timestamp when the task should be promoted.
    """

    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        self.redis_url = redis_url
        self._redis = None

    @property
    def redis(self):
        if self._redis is None:
            import redis as r

            self._redis = r.from_url(self.redis_url)
        return self._redis

    async def enqueue(self, task_id: str, payload: dict[str, Any], promote_at: float) -> None:
        """Store a deferred task in the sorted set keyed by promote_at timestamp."""
        key = "deferred:tasks"
        data = json.dumps({"task_id": task_id, "payload": payload, "promote_at": promote_at})
        self.redis.zadd(key, {data: promote_at})
        logger.info("queue.enqueue", task_id=task_id, promote_at=promote_at)

    async def promote_due_tasks(self) -> list[dict[str, Any]]:
        """Fetch all tasks whose promote_at timestamp has passed.

        Returns list of task payloads that are due for routing.
        """
        key = "deferred:tasks"
        now = time.time()
        due = self.redis.zrangebyscore(key, 0, now)
        if due:
            self.redis.zremrangebyscore(key, 0, now)
        results = []
        for item in due:
            data = json.loads(item)
            results.append(data)
            logger.info("queue.promote", task_id=data.get("task_id"))
        return results

    async def task_count(self) -> int:
        """Return the number of tasks currently in the deferral queue."""
        key = "deferred:tasks"
        return self.redis.zcard(key)
