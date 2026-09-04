import asyncio
from typing import Any, cast

import pytest

from onyx.server.manage.voice.websocket_api import (
    StreamingTranscriptionFailed,
    handle_chunked_transcription,
    handle_streaming_transcription,
)
from onyx.voice.interface import STREAM_FAILED_ERROR, TranscriptResult


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


class NeverReceivingWebSocket(FakeWebSocket):
    """Client that never sends a message and never disconnects."""

    async def receive(self) -> dict[str, str]:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


class ErrorResultTranscriber:
    def __init__(self) -> None:
        self.closed = False

    async def send_audio(self, chunk: bytes) -> None:
        _ = chunk

    async def receive_transcript(self) -> TranscriptResult | None:
        return TranscriptResult(
            text="already transcribed",
            is_vad_end=True,
            error="raw upstream details",
        )

    async def close(self) -> str:
        self.closed = True
        return ""

    def reset_transcript(self) -> None:
        return None


class AudioThenSilentWebSocket(FakeWebSocket):
    """Client that sends one audio chunk and then stays quiet."""

    def __init__(self, chunk: bytes) -> None:
        super().__init__()
        self.chunk = chunk
        self.sent_chunk = False

    async def receive(self) -> Any:
        if not self.sent_chunk:
            self.sent_chunk = True
            return {"bytes": self.chunk}
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


class FailAfterAudioTranscriber(ErrorResultTranscriber):
    """Provider that fails only once it has consumed audio."""

    def __init__(self) -> None:
        super().__init__()
        self.got_audio = asyncio.Event()

    async def send_audio(self, chunk: bytes) -> None:
        _ = chunk
        self.got_audio.set()

    async def receive_transcript(self) -> TranscriptResult | None:
        await self.got_audio.wait()
        return TranscriptResult(error="raw upstream details")


class RecordingChunkedTranscriber:
    def __init__(self) -> None:
        self.chunks: list[bytes] = []

    async def add_chunk(self, chunk: bytes) -> str | None:
        self.chunks.append(chunk)
        return None

    async def flush(self) -> str:
        return "full recording"


@pytest.mark.asyncio
async def test_streaming_failure_keeps_audio_for_fallback() -> None:
    """The fallback needs the audio the failed stream already consumed."""
    websocket = AudioThenSilentWebSocket(b"\x01\x02\x03\x04")

    async with asyncio.timeout(5):
        with pytest.raises(StreamingTranscriptionFailed) as failure:
            await handle_streaming_transcription(
                cast(Any, websocket),
                cast(Any, FailAfterAudioTranscriber()),
            )

    assert failure.value.buffered_audio == b"\x01\x02\x03\x04"
    assert failure.value.client_ended is False


@pytest.mark.asyncio
async def test_chunked_handler_replays_initial_audio() -> None:
    """Recovered audio is transcribed, and an ended recording needs no more input."""
    websocket = NeverReceivingWebSocket()
    transcriber = RecordingChunkedTranscriber()

    async with asyncio.timeout(5):
        await handle_chunked_transcription(
            cast(Any, websocket),
            cast(Any, transcriber),
            initial_audio=b"\x01\x02",
            client_ended=True,
        )

    assert transcriber.chunks == [b"\x01\x02"]
    assert websocket.sent_json == [
        {"type": "transcript", "text": "full recording", "is_final": True}
    ]


@pytest.mark.asyncio
async def test_streaming_handler_raises_on_provider_failure() -> None:
    """The caller decides between fallback and an error, so the socket stays open."""
    websocket = FakeWebSocket()

    with pytest.raises(StreamingTranscriptionFailed) as failure:
        await handle_streaming_transcription(
            cast(Any, websocket),
            cast(Any, ErrorResultTranscriber()),
        )

    assert str(failure.value) == STREAM_FAILED_ERROR
    assert websocket.sent_json == []
    assert websocket.close_code is None


@pytest.mark.asyncio
async def test_streaming_handler_stops_when_client_stays_silent() -> None:
    """A provider failure must end the handler even without client input."""
    websocket = NeverReceivingWebSocket()
    transcriber = ErrorResultTranscriber()

    async with asyncio.timeout(5):
        with pytest.raises(StreamingTranscriptionFailed) as failure:
            await handle_streaming_transcription(
                cast(Any, websocket),
                cast(Any, transcriber),
            )

    assert str(failure.value) == STREAM_FAILED_ERROR
    assert transcriber.closed
