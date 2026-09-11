"""Backpressured model output ingestion; idle streams occupy no Python thread."""

from typing import Annotated, Any
from uuid import UUID

import anyio
from anyio.to_thread import run_sync
from fastapi import APIRouter, Header, Request
from pydantic import BaseModel, Field

from onyx.chat.pi.runtime import ModelStreamProjection, finish
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError

router = APIRouter()
MAX_FRAME_BYTES = 2 * 1024 * 1024


class EventFrame(BaseModel):
    events: list[dict[str, Any]] = Field(max_length=4096)


@router.post("/runs/{run_id}/events-stream")
async def events_stream(
    run_id: UUID,
    request: Request,
    attempt_id: Annotated[UUID, Header(alias="X-Onyx-Attempt-Id")],
    sequence: Annotated[int, Header(alias="X-Onyx-Sequence", ge=1)],
) -> dict[str, bool]:
    projection = await run_sync(
        ModelStreamProjection.claim, run_id, attempt_id, sequence
    )
    buffer = bytearray()
    try:
        async for chunk in request.stream():
            if len(buffer) + len(chunk) > MAX_FRAME_BYTES:
                raise OnyxError(
                    OnyxErrorCode.INVALID_INPUT, "Agent event frame is too large"
                )
            buffer.extend(chunk)
            while (boundary := buffer.find(b"\n")) >= 0:
                line = bytes(buffer[:boundary])
                del buffer[: boundary + 1]
                if line:
                    frame = EventFrame.model_validate_json(line)
                    await run_sync(projection.feed, frame.events)
        if buffer:
            frame = EventFrame.model_validate_json(buffer)
            await run_sync(projection.feed, frame.events)
        await run_sync(projection.checkpoint)
        return {"ok": True}
    except BaseException:
        # The queue must not replay a run whose streamed callback was interrupted.
        with anyio.CancelScope(shield=True):
            await run_sync(
                finish,
                run_id,
                attempt_id,
                "interrupted",
            )
        raise
