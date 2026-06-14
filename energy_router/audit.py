"""SQLite audit trail for routing decisions."""

from __future__ import annotations

import datetime
import sqlite3
from pathlib import Path
from typing import Any

import structlog

from energy_router.carbon import GridCarbonLevel

logger = structlog.get_logger()


class AuditTrail:
    """Records every routing decision to a SQLite database."""

    def __init__(self, db_path: str = "routing_audit.db"):
        self.db_path = db_path
        self._ensure_table()

    def _ensure_table(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS routing_decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    carbon_level TEXT NOT NULL,
                    intensity REAL,
                    region TEXT NOT NULL,
                    reason TEXT,
                    timestamp TEXT NOT NULL
                )
            """)
            conn.commit()

    def record(
        self,
        task_id: str,
        decision: str,
        carbon_level: GridCarbonLevel,
        intensity: float | None,
        region: str,
        reason: str,
    ) -> None:
        """Insert a routing decision into the audit trail."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO routing_decisions
                    (task_id, decision, carbon_level, intensity, region, reason, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    decision,
                    carbon_level.value,
                    intensity,
                    region,
                    reason,
                    datetime.datetime.utcnow().isoformat(),
                ),
            )
            conn.commit()
        logger.info("audit.record", task_id=task_id, decision=decision)

    def query(
        self,
        limit: int = 50,
        offset: int = 0,
        decision: str | None = None,
        task_id: str | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> list[dict[str, Any]]:
        """Query the audit trail with optional filters."""
        conditions = []
        params: list[Any] = []

        if decision:
            conditions.append("decision = ?")
            params.append(decision)
        if task_id:
            conditions.append("task_id = ?")
            params.append(task_id)
        if since:
            conditions.append("timestamp >= ?")
            params.append(since)
        if until:
            conditions.append("timestamp <= ?")
            params.append(until)

        where = ""
        if conditions:
            where = " WHERE " + " AND ".join(conditions)

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                f"SELECT * FROM routing_decisions{where} ORDER BY id DESC LIMIT ? OFFSET ?",
                params + [limit, offset],
            )
            rows = cursor.fetchall()

        return [dict(row) for row in rows]

    def count(self) -> int:
        """Return total number of records in the audit trail."""
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute("SELECT COUNT(*) FROM routing_decisions").fetchone()[0]
