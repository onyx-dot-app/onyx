"""Model stream ingestion handles fragmented frames and interrupted requests."""

import asyncio
from collections.abc import AsyncIterator
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import Request
from starlette.requests import ClientDisconnect

from onyx.chat.pi.stream_api import events_stream


def test_fragmented_frames_are_processed_before_completion_ack() -> None:
    async def chunks() -> AsyncIterator[bytes]:
        yield b'{"events":[{"type":"chunk","chunk":'
        yield b'{}}]}\n{"events":[{"type":"model_end"}]}\n'

    request = MagicMock(spec=Request)
    request.stream = chunks
    projection = MagicMock()
    with (
        patch(
            "onyx.chat.pi.stream_api.ModelStreamProjection.claim",
            return_value=projection,
        ),
        patch("onyx.chat.pi.stream_api.finish") as finish,
    ):
        result = asyncio.run(events_stream(uuid4(), request, uuid4(), 2))
    assert result == {"ok": True}
    assert [call.args for call in projection.feed.call_args_list] == [
        ([{"type": "chunk", "chunk": {}}],),
        ([{"type": "model_end"}],),
    ]
    projection.checkpoint.assert_called_once_with()
    finish.assert_not_called()


def test_disconnected_model_stream_interrupts_run_without_replay() -> None:
    async def chunks() -> AsyncIterator[bytes]:
        yield b'{"events":[{"type":"chunk","chunk":{}}]}\n'
        raise ClientDisconnect()

    request = MagicMock(spec=Request)
    request.stream = chunks
    projection = MagicMock()
    run_id, attempt_id = uuid4(), uuid4()
    with (
        patch(
            "onyx.chat.pi.stream_api.ModelStreamProjection.claim",
            return_value=projection,
        ),
        patch("onyx.chat.pi.stream_api.finish") as finish,
    ):
        with pytest.raises(ClientDisconnect):
            asyncio.run(events_stream(run_id, request, attempt_id, 2))
    finish.assert_called_once_with(run_id, attempt_id, "interrupted")
    projection.checkpoint.assert_not_called()
