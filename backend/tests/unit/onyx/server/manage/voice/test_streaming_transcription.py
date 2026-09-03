import asyncio
from typing import Any, cast

import pytest

from onyx.server.manage.voice.websocket_api import (
    WS_SERVER_ERROR_CLOSE_CODE,
    handle_streaming_transcription,
)
from onyx.voice.interface import TranscriptResult


class FakeWebSocket:
    def __init__(self) -> None:
        self.sent_json: list[dict[str, str]] = []
        self.close_code: int | None = None
        self._closed = asyncio.Event()

    async def receive(self) -> dict[str, str]:
        await self._closed.wait()
        return {"type": "websocket.disconnect"}

    async def send_json(self, data: dict[str, str]) -> None:
        self.sent_json.append(data)

    async def close(self, code: int = 1000) -> None:
        self.close_code = code
        self._closed.set()


class ErrorResultTranscriber:
    async def send_audio(self, chunk: bytes) -> None:
        _ = chunk

    async def receive_transcript(self) -> TranscriptResult | None:
        return TranscriptResult(
            text="already transcribed",
            is_vad_end=True,
            error="raw upstream details",
        )

    async def close(self) -> str:
        return ""

    def reset_transcript(self) -> None:
        return None


@pytest.mark.asyncio
async def test_streaming_handler_sends_sanitized_error_and_closes() -> None:
    websocket = FakeWebSocket()

    await handle_streaming_transcription(
        cast(Any, websocket),
        cast(Any, ErrorResultTranscriber()),
    )

    assert websocket.sent_json == [
        {"type": "error", "message": "Streaming transcription failed"}
    ]
    assert websocket.close_code == WS_SERVER_ERROR_CLOSE_CODE
