"""Authenticated worker control plane. Tools share the API's bounded thread capacity."""

import asyncio
from contextlib import suppress
from typing import Any, Literal
from uuid import UUID

from anyio import to_thread
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from onyx.chat.pi import runtime
from onyx.chat.pi.auth import worker_identity
from onyx.chat.pi.stream_api import router as stream_router
from onyx.db.agent_runs import heartbeat_finalizer, heartbeat_run, heartbeat_runs
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError

router = APIRouter(
    prefix="/internal/agent",
    dependencies=[Depends(worker_identity)],
    include_in_schema=False,
)


class Attempt(BaseModel):
    attemptId: UUID


class Operation(Attempt):
    sequence: int = Field(ge=1)


class Callback(Operation):
    type: Literal["prepare", "model_start", "tools", "turn_end"]
    payload: dict[str, Any] = Field(default_factory=dict)


class Events(Operation):
    events: list[dict[str, Any]] = Field(max_length=4096)


class Finish(Attempt):
    status: Literal["completed", "failed", "interrupted", "cancelled"]
    error: dict[str, Any] | None = None


class RunHeartbeat(Attempt):
    runId: UUID


class Heartbeats(BaseModel):
    runs: list[RunHeartbeat] = Field(max_length=512)


@router.post("/runs/{run_id}/claim")
async def claim(run_id: UUID, body: Attempt) -> dict[str, Any]:
    return await to_thread.run_sync(runtime.claim, run_id, body.attemptId)


@router.post("/runs/{run_id}/heartbeat")
async def heartbeat(run_id: UUID, body: Attempt) -> dict[str, bool]:
    owned = await to_thread.run_sync(heartbeat_run, run_id, body.attemptId)
    return {"cancelled": not owned}


@router.post("/runs/{run_id}/callback")
async def callback(run_id: UUID, body: Callback, request: Request) -> dict[str, Any]:
    limiter = request.app.state.agent_tool_limiter if body.type == "tools" else None
    value = await to_thread.run_sync(
        runtime.apply_operation,
        run_id,
        body.attemptId,
        body.sequence,
        body.type,
        body.payload,
        limiter=limiter,
    )
    return {"value": value}


@router.post("/runs/{run_id}/events")
async def events(run_id: UUID, body: Events) -> dict[str, bool]:
    if len(body.model_dump_json()) > 2 * 1024 * 1024:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "Agent event batch is too large")
    await to_thread.run_sync(
        runtime.apply_operation,
        run_id,
        body.attemptId,
        body.sequence,
        "events",
        {"events": body.events},
    )
    return {"ok": True}


@router.post("/runs/{run_id}/finish")
async def finish(run_id: UUID, body: Finish) -> dict[str, bool]:
    async def keep_finalizer_alive() -> None:
        while True:
            await asyncio.sleep(30)
            await to_thread.run_sync(heartbeat_finalizer, run_id, body.attemptId)

    heartbeat_task = asyncio.create_task(keep_finalizer_alive())
    try:
        await to_thread.run_sync(
            runtime.finish, run_id, body.attemptId, body.status, body.error
        )
    finally:
        heartbeat_task.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat_task

    return {"ok": True}


@router.post("/heartbeats")
async def heartbeats(body: Heartbeats) -> dict[str, list[str]]:
    cancelled = await to_thread.run_sync(
        heartbeat_runs, [(run.runId, run.attemptId) for run in body.runs]
    )
    return {"cancelled": [str(run_id) for run_id in cancelled]}


router.include_router(stream_router)
