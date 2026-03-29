"""FastAPI server for energy-aware task router."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from router import Task, TaskRouter, CarbonApiClient, GridCarbonLevel


app = FastAPI(title="Energy-Aware Task Router")
_router: TaskRouter | None = None


class TaskSubmitRequest(BaseModel):
    name: str
    deferrable: bool = True
    defer_until: str | None = None
    deadline: datetime | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class TaskSubmitResponse(BaseModel):
    task_id: str
    name: str
    status: str


@app.on_event("startup")
async def startup():
    global _router
    import os
    _router = TaskRouter(CarbonApiClient(api_key=os.getenv("CARBON_API_KEY")))


@app.post("/tasks", response_model=TaskSubmitResponse)
async def submit_task(req: TaskSubmitRequest):
    if _router is None:
        raise HTTPException(status_code=503, detail="Router not initialized")
    defer_until = None
    if req.defer_until:
        try:
            defer_until = GridCarbonLevel(req.defer_until)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid defer_until: {req.defer_until}")
    task = Task(
        id=str(uuid.uuid4()),
        name=req.name,
        deferrable=req.deferrable,
        defer_until=defer_until,
        deadline=req.deadline,
        payload=req.payload,
    )
    decision = await _router.route(task)
    return TaskSubmitResponse(task_id=task.id, name=task.name, status=decision.decision)


@app.get("/health")
async def health():
    return {"status": "ok", "router": _router is not None}
