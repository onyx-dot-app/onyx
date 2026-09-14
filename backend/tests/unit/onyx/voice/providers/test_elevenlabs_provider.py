import json
from collections.abc import AsyncIterator
from typing import Any, cast

import aiohttp
import pytest

from onyx.voice.interface import STREAM_FAILED_ERROR
from onyx.voice.providers.elevenlabs import (
    DEFAULT_ELEVENLABS_API_BASE,
    ElevenLabsStreamingTranscriber,
    ElevenLabsSTTMessageType,
    ElevenLabsVoiceProvider,
    _http_to_ws_url,
)

# --- _http_to_ws_url ---


def test_http_to_ws_url_converts_https_to_wss() -> None:
    assert _http_to_ws_url("https://api.elevenlabs.io") == "wss://api.elevenlabs.io"


def test_http_to_ws_url_converts_http_to_ws() -> None:
    assert _http_to_ws_url("http://localhost:8080") == "ws://localhost:8080"


def test_http_to_ws_url_passes_through_other_schemes() -> None:
    assert _http_to_ws_url("wss://already.ws") == "wss://already.ws"


def test_http_to_ws_url_preserves_path() -> None:
    assert (
        _http_to_ws_url("https://api.elevenlabs.io/v1/tts")
        == "wss://api.elevenlabs.io/v1/tts"
    )


# --- StrEnum comparison ---


def test_stt_message_type_compares_as_string() -> None:
    """StrEnum members should work in string comparisons (e.g. from JSON)."""
    assert str(ElevenLabsSTTMessageType.COMMITTED_TRANSCRIPT) == "committed_transcript"
    assert isinstance(ElevenLabsSTTMessageType.ERROR, str)


# --- Provider Model Defaulting ---


def test_provider_defaults_invalid_stt_model() -> None:
    provider = ElevenLabsVoiceProvider(api_key="test", stt_model="invalid_model")
    assert provider.stt_model == "scribe_v1"


def test_provider_defaults_invalid_tts_model() -> None:
    provider = ElevenLabsVoiceProvider(api_key="test", tts_model="invalid_model")
    assert provider.tts_model == "eleven_multilingual_v2"


def test_provider_accepts_valid_models() -> None:
    provider = ElevenLabsVoiceProvider(
        api_key="test", stt_model="scribe_v2_realtime", tts_model="eleven_turbo_v2_5"
    )
    assert provider.stt_model == "scribe_v2_realtime"
    assert provider.tts_model == "eleven_turbo_v2_5"


def test_provider_defaults_api_base() -> None:
    provider = ElevenLabsVoiceProvider(api_key="test")
    assert provider.api_base == DEFAULT_ELEVENLABS_API_BASE


def test_provider_get_available_voices_returns_copy() -> None:
    provider = ElevenLabsVoiceProvider(api_key="test")
    voices = provider.get_available_voices()
    voices.clear()
    assert len(provider.get_available_voices()) > 0


# --- Streaming error propagation ---


class FakeTextMessage:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.type = aiohttp.WSMsgType.TEXT
        self.data = json.dumps(payload)


class FakeCloseMessage:
    def __init__(self) -> None:
        self.type = aiohttp.WSMsgType.CLOSED


class FakeWebSocket:
    def __init__(self, messages: list[Any]) -> None:
        self._messages = messages
        self.close_code = 1000

    async def __aiter__(self) -> AsyncIterator[Any]:
        for message in self._messages:
            yield message


def _transcriber(messages: list[Any]) -> ElevenLabsStreamingTranscriber:
    transcriber = ElevenLabsStreamingTranscriber(api_key="test")
    transcriber._ws = cast(Any, FakeWebSocket(messages))
    return transcriber


@pytest.mark.asyncio
async def test_streaming_api_error_reports_sanitized_error() -> None:
    transcriber = _transcriber(
        [
            FakeTextMessage(
                {
                    "message_type": ElevenLabsSTTMessageType.ERROR,
                    "error": "raw upstream details",
                }
            )
        ]
    )

    await transcriber._receive_loop()

    result = await transcriber.receive_transcript()
    assert result is not None
    assert result.error == STREAM_FAILED_ERROR
    assert result.text == ""
    assert await transcriber.receive_transcript() is None


@pytest.mark.asyncio
async def test_streaming_unexpected_server_close_reports_error() -> None:
    """A close without session_ended is a failure, not a clean end.

    aiohttp stops the message iterator on close, so no close message arrives.
    """
    transcriber = _transcriber([])

    await transcriber._receive_loop()

    result = await transcriber.receive_transcript()
    assert result is not None
    assert result.error == STREAM_FAILED_ERROR
    assert await transcriber.receive_transcript() is None


@pytest.mark.asyncio
async def test_streaming_session_ended_reports_no_error() -> None:
    transcriber = _transcriber(
        [
            FakeTextMessage({"message_type": ElevenLabsSTTMessageType.SESSION_ENDED}),
            FakeCloseMessage(),
        ]
    )

    await transcriber._receive_loop()

    assert await transcriber.receive_transcript() is None


@pytest.mark.asyncio
async def test_streaming_client_close_reports_no_error() -> None:
    """The client ends the session, so the socket close is expected."""
    transcriber = _transcriber(
        [FakeTextMessage({"message_type": "partial_transcript", "text": "hi"})]
    )
    transcriber._closed = True

    await transcriber._receive_loop()

    result = await transcriber.receive_transcript()
    assert result is not None
    assert result.text == "hi"
    assert await transcriber.receive_transcript() is None
