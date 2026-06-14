"""CLI tool for the energy-aware task router."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from datetime import datetime

import typer

from energy_router.api import app as fastapi_app
from energy_router.carbon import CarbonApiClient, GridCarbonLevel
from energy_router.config import load_config
from energy_router.router import Task, TaskRouter

cli = typer.Typer(name="energy-router")


@cli.command()
def submit(
    name: str,
    deadline: str | None = None,
    defer_until: str | None = None,
    region: str = "AU-NSW",
):
    """Submit a task to the energy-aware router."""
    cfg = load_config("config.yaml")
    client = CarbonApiClient(
        api_key=cfg.carbon_api_key,
        base_url=cfg.carbon_api_base_url,
        timeout=cfg.carbon_api_timeout,
    )
    router = TaskRouter(carbon_client=client, default_region=region)

    task = Task(
        id=str(uuid.uuid4()),
        name=name,
        deferrable=True,
        defer_until=GridCarbonLevel(defer_until) if defer_until else None,
        deadline=datetime.fromisoformat(deadline) if deadline else None,
    )

    decision = asyncio.run(router.route(task))
    result = {
        "task_id": task.id,
        "name": task.name,
        "decision": decision.decision,
        "carbon_level": decision.grid_conditions.level.value,
        "intensity": decision.grid_conditions.carbon_intensity_gco2kwh,
        "region": decision.grid_conditions.region,
        "reason": decision.reason,
    }
    print(json.dumps(result, indent=2, default=str))


@cli.command()
def status(task_id: str):
    """Check the status of a task (placeholder)."""
    print(json.dumps({"task_id": task_id, "status": "unknown", "note": "status tracking not yet implemented"}))


@cli.command()
def audit(limit: int = 20):
    """View recent routing decisions from the audit trail."""
    from energy_router.audit import AuditTrail

    trail = AuditTrail()
    records = trail.query(limit=limit)
    print(json.dumps(records, indent=2, default=str))


@cli.command()
def health():
    """Check system health."""
    try:
        cfg = load_config("config.yaml")
        print(json.dumps({
            "status": "ok",
            "region": cfg.default_region,
            "api_key_set": cfg.carbon_api_key is not None,
            "audit": {"db": "routing_audit.db"},
        }, indent=2))
    except Exception as e:
        print(json.dumps({"status": "error", "error": str(e)}, indent=2))
        sys.exit(1)


@cli.command()
def serve():
    """Start the FastAPI server."""
    import uvicorn
    uvicorn.run(fastapi_app, host="0.0.0.0", port=8009)


if __name__ == "__main__":
    cli()
