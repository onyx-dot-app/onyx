import asyncio
import json
from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any, cast

import aiohttp
import jwt
import pytest

from onyx.db.models import VoiceProvider
from onyx.server.manage.voice.websocket_api import (
    WS_SERVER_ERROR_CLOSE_CODE,
    handle_streaming_transcription,
)
from onyx.voice.factory import get_voice_provider
from onyx.voice.interface import TranscriptResult
from onyx.voice.providers import zoom
from onyx.voice.providers.zoom import (
    ZOOM_API_BASE,
    ZOOM_FRAME_BYTES,
    ZOOM_JWT_IAT_SKEW_SECONDS,
    ZOOM_JWT_TTL_SECONDS,
    ZOOM_SCRIBE_LIVE_PATH,
    ZOOM_STT_MODEL,
    ZOOM_SUPPORTED_LANGUAGES,
    ZOOM_TARGET_SAMPLE_RATE,
    ZOOM_TRANSCRIBE_SEND_CHUNK_BYTES,
    ZOOM_WS_SUBPROTOCOL,
    ZoomStreamingTranscriber,
    ZoomVoiceProvider,
    build_zoom_scribe_jwt,
)


class FakeWebSocket:
    def __init__(self, messages: list[Any] | None = None):
        self.messages = list(messages or [])
        self.sent_str: list[str] = []
        self.sent_bytes: list[bytes] = []
        self.closed = False
        self.close_code: int | None = None

    def __aiter__(self) -> "FakeWebSocket":
        return self

    async def __anext__(self) -> Any:
        if not self.messages:
            raise StopAsyncIteration
        await asyncio.sleep(0)
        return self.messages.pop(0)

    async def send_str(self, data: str) -> None:
        self.sent_str.append(data)

    async def send_bytes(self, data: bytes) -> None:
        self.sent_bytes.append(data)

    async def close(self) -> None:
        self.closed = True


class FailingSendBytesWebSocket(FakeWebSocket):
    async def send_bytes(self, data: bytes) -> None:
        _ = data
        raise RuntimeError("send failed")


class FailingCloseWebSocket(FakeWebSocket):
    async def close(self) -> None:
        self.closed = True
        raise RuntimeError("close failed")


class HangingWebSocket(FakeWebSocket):
    async def __anext__(self) -> Any:
        await asyncio.sleep(60)
        raise StopAsyncIteration


class FakeSession:
    def __init__(self, ws: FakeWebSocket):
        self.ws = ws
        self.closed = False
        self.ws_connect_calls: list[dict[str, Any]] = []

    async def ws_connect(self, url: str, **kwargs: Any) -> FakeWebSocket:
        self.ws_connect_calls.append({"url": url, **kwargs})
        return self.ws

    async def close(self) -> None:
        self.closed = True


class CancelledConnectSession(FakeSession):
    async def ws_connect(self, url: str, **kwargs: Any) -> FakeWebSocket:
        self.ws_connect_calls.append({"url": url, **kwargs})
        raise asyncio.CancelledError


class FakeClientWebSocket:
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


def _text_message(data: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(type=aiohttp.WSMsgType.TEXT, data=json.dumps(data))


def _binary_message(data: bytes = b"data") -> SimpleNamespace:
    return SimpleNamespace(type=aiohttp.WSMsgType.BINARY, data=data)


@pytest.mark.asyncio
async def test_streaming_handler_sends_sanitized_error_and_closes() -> None:
    websocket = FakeClientWebSocket()

    await handle_streaming_transcription(
        cast(Any, websocket),
        cast(Any, ErrorResultTranscriber()),
    )

    assert websocket.sent_json == [
        {"type": "error", "message": "Streaming transcription failed"}
    ]
    assert websocket.close_code == WS_SERVER_ERROR_CLOSE_CODE


def test_build_zoom_scribe_jwt_uses_expected_claims_and_hs256() -> None:
    secret = "x" * 32
    token = build_zoom_scribe_jwt("api-key", secret, now=1_700_000_000)

    header = jwt.get_unverified_header(token)
    claims = jwt.decode(
        token,
        secret,
        algorithms=["HS256"],
        options={"verify_exp": False, "verify_iat": False},
    )

    assert header["alg"] == "HS256"
    assert claims["iss"] == "api-key"
    assert claims["iat"] == 1_700_000_000 - ZOOM_JWT_IAT_SKEW_SECONDS
    assert claims["exp"] == 1_700_000_000 + ZOOM_JWT_TTL_SECONDS


def test_provider_accepts_missing_credentials_for_static_metadata() -> None:
    provider = ZoomVoiceProvider(api_key=None, api_secret=None)

    assert provider.get_available_voices() == []
    assert provider.get_available_tts_models() == []
    assert provider.get_available_stt_models() == [
        {"id": ZOOM_STT_MODEL, "name": "Zoom Scribe Live"}
    ]


@pytest.mark.asyncio
async def test_provider_requires_both_credentials_for_validation_and_streaming() -> (
    None
):
    provider = ZoomVoiceProvider(api_key="key", api_secret=None)

    with pytest.raises(ValueError, match="API key and API secret"):
        await provider.validate_credentials()
    with pytest.raises(ValueError, match="API key and API secret"):
        await provider.create_streaming_transcriber()
    with pytest.raises(ValueError, match="API key and API secret"):
        await provider.transcribe(b"\x00\x00", "pcm16")


def test_provider_validates_supported_languages() -> None:
    for language in ZOOM_SUPPORTED_LANGUAGES:
        assert (
            ZoomVoiceProvider(
                api_key=None,
                api_secret=None,
                custom_config={"language": language},
            ).language
            == language
        )

    with pytest.raises(ValueError, match="Unsupported Zoom language"):
        ZoomVoiceProvider(
            api_key=None,
            api_secret=None,
            custom_config={"language": "en-GB"},
        )


def test_provider_rejects_non_zoom_stt_model() -> None:
    with pytest.raises(ValueError, match="scribe-live"):
        ZoomVoiceProvider(
            api_key="key",
            api_secret="secret",
            stt_model="other-model",
        )


@pytest.mark.asyncio
async def test_connect_sends_session_update_auth_header_and_subprotocol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ws = FakeWebSocket([_text_message({"type": "session.updated"})])
    session = FakeSession(ws)
    monkeypatch.setattr(zoom.aiohttp, "ClientSession", lambda: session)
    monkeypatch.setattr(
        zoom,
        "build_zoom_scribe_jwt",
        lambda api_key, api_secret: f"token-for-{api_key}-{api_secret}",
    )
    transcriber = ZoomStreamingTranscriber(
        api_key="key",
        api_secret="secret",
        language="fr-FR",
        api_base="https://example.test",
    )

    await transcriber.connect()

    assert session.ws_connect_calls == [
        {
            "url": f"wss://example.test{ZOOM_SCRIBE_LIVE_PATH}",
            "headers": {"Authorization": "Bearer token-for-key-secret"},
            "protocols": [ZOOM_WS_SUBPROTOCOL],
        }
    ]
    assert json.loads(ws.sent_str[0]) == {
        "type": "session.update",
        "language": "fr-FR",
        "audio": {"format": "pcm16"},
    }


@pytest.mark.asyncio
async def test_connect_cleans_up_on_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = CancelledConnectSession(FakeWebSocket())
    monkeypatch.setattr(zoom.aiohttp, "ClientSession", lambda: session)

    transcriber = ZoomStreamingTranscriber(api_key="key", api_secret="x" * 32)

    with pytest.raises(asyncio.CancelledError):
        await transcriber.connect()

    assert session.closed is True


@pytest.mark.asyncio
async def test_send_audio_resamples_and_sends_100ms_16khz_frames() -> None:
    ws = FakeWebSocket()
    transcriber = ZoomStreamingTranscriber(api_key="key", api_secret="x" * 32)
    transcriber._ws = cast(Any, ws)

    await transcriber.send_audio(b"\x01\x00" * 2400)

    assert len(ws.sent_bytes) == 1
    assert len(ws.sent_bytes[0]) == ZOOM_FRAME_BYTES
    assert len(transcriber._buffer) == 0
    assert ZOOM_TARGET_SAMPLE_RATE == 16000


@pytest.mark.asyncio
async def test_close_flushes_remainder_and_is_idempotent() -> None:
    ws = FakeWebSocket()
    session = FakeSession(ws)
    transcriber = ZoomStreamingTranscriber(api_key="key", api_secret="x" * 32)
    transcriber._ws = cast(Any, ws)
    transcriber._session = cast(Any, session)
    transcriber._buffer.extend(b"\x02\x00" * 100)

    assert await transcriber.close() == ""
    assert await transcriber.close() == ""

    assert ws.sent_bytes == [b"\x02\x00" * 100]
    assert json.loads(ws.sent_str[0]) == {"type": "session.close"}
    assert ws.closed is True
    assert session.closed is True


@pytest.mark.asyncio
async def test_close_cleans_up_when_remainder_send_fails() -> None:
    ws = FailingSendBytesWebSocket()
    session = FakeSession(ws)
    transcriber = ZoomStreamingTranscriber(api_key="key", api_secret="x" * 32)
    transcriber._ws = cast(Any, ws)
    transcriber._session = cast(Any, session)
    transcriber._buffer.extend(b"\x02\x00" * 100)
    transcriber._accumulated_transcript = "kept"

    assert await transcriber.close() == "kept"

    assert ws.closed is True
    assert session.closed is True


@pytest.mark.asyncio
async def test_cleanup_closes_session_when_websocket_close_fails() -> None:
    ws = FailingCloseWebSocket()
    session = FakeSession(ws)
    transcriber = ZoomStreamingTranscriber(api_key="key", api_secret="x" * 32)
    transcriber._ws = cast(Any, ws)
    transcriber._session = cast(Any, session)

    await transcriber._cleanup()

    assert ws.closed is True
    assert session.closed is True


@pytest.mark.asyncio
async def test_receive_loop_accumulates_transcription_turns() -> None:
    ws = FakeWebSocket(
        [
            _text_message({"type": "session.updated"}),
            _text_message({"type": "transcription.completed", "transcript": "hello"}),
            _text_message({"type": "transcription.completed", "transcript": "world"}),
            _text_message({"type": "session.closed"}),
        ]
    )
    transcriber = ZoomStreamingTranscriber(api_key="key", api_secret="x" * 32)
    transcriber._ws = cast(Any, ws)

    await transcriber._receive_loop()

    assert await transcriber.receive_transcript() == zoom.TranscriptResult(
        text="hello", is_vad_end=True
    )
    assert await transcriber.receive_transcript() == zoom.TranscriptResult(
        text="hello world", is_vad_end=True
    )
    assert await transcriber.receive_transcript() is None


@pytest.mark.asyncio
async def test_receive_loop_ignores_non_object_json_and_binary() -> None:
    ws = FakeWebSocket(
        [
            SimpleNamespace(type=aiohttp.WSMsgType.TEXT, data='"not-object"'),
            _binary_message(),
            _text_message({"type": "session.closed"}),
        ]
    )
    transcriber = ZoomStreamingTranscriber(api_key="key", api_secret="x" * 32)
    transcriber._ws = cast(Any, ws)

    await transcriber._receive_loop()

    assert await transcriber.receive_transcript() is None


@pytest.mark.asyncio
async def test_receive_loop_logs_nonfatal_errors_and_continues() -> None:
    ws = FakeWebSocket(
        [
            _text_message({"type": "session.updated"}),
            _text_message(
                {
                    "type": "error",
                    "error": {
                        "code": "rate_warning",
                        "message": "raw nonfatal details",
                        "fatal": False,
                    },
                }
            ),
            _text_message({"type": "transcription.completed", "transcript": "after"}),
            _text_message({"type": "session.closed"}),
        ]
    )
    transcriber = ZoomStreamingTranscriber(api_key="key", api_secret="x" * 32)
    transcriber._ws = cast(Any, ws)

    await transcriber._receive_loop()

    assert await transcriber.receive_transcript() == zoom.TranscriptResult(
        text="after", is_vad_end=True
    )
    assert await transcriber.receive_transcript() is None


@pytest.mark.asyncio
async def test_receive_loop_surfaces_fatal_error_safely() -> None:
    ws = FakeWebSocket(
        [
            _text_message({"type": "transcription.completed", "transcript": "kept"}),
            _text_message(
                {
                    "type": "error",
                    "error": {
                        "code": "bad_auth",
                        "message": "raw upstream payload that should not reach client",
                        "fatal": True,
                    },
                }
            ),
            SimpleNamespace(type=aiohttp.WSMsgType.CLOSED, data=None),
        ]
    )
    transcriber = ZoomStreamingTranscriber(api_key="key", api_secret="x" * 32)
    transcriber._ws = cast(Any, ws)

    await transcriber._receive_loop()

    assert await transcriber.receive_transcript() == zoom.TranscriptResult(
        text="kept", is_vad_end=True
    )
    error = await transcriber.receive_transcript()
    assert error == zoom.TranscriptResult(
        text="kept",
        is_vad_end=True,
        error="Zoom Scribe stream failed.",
    )
    assert "upstream payload" not in (error.error or "")
    assert await transcriber.receive_transcript() is None
    assert (
        len([msg for msg in ws.messages if msg.type == aiohttp.WSMsgType.CLOSED]) == 1
    )


@pytest.mark.asyncio
async def test_transcribe_is_pcm_only_and_traced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ZoomVoiceProvider(api_key="key", api_secret="secret")

    with pytest.raises(ValueError, match="pcm16"):
        await provider.transcribe(b"data", "wav")

    calls: list[tuple[str, str]] = []

    @contextmanager
    def fake_trace(**kwargs: Any) -> Iterator[None]:
        calls.append((kwargs["model"], kwargs["provider"]))
        yield

    class FakeTranscriber:
        def __init__(self, **kwargs: Any):
            self.kwargs = kwargs

        async def connect(self) -> None:
            return None

        async def send_audio(self, audio_data: bytes) -> None:
            assert audio_data == b"pcm"

        async def close(self) -> str:
            return "done"

    monkeypatch.setattr(zoom, "traced_llm_call", fake_trace)
    monkeypatch.setattr(zoom, "ZoomStreamingTranscriber", FakeTranscriber)

    assert await provider.transcribe(b"pcm", "pcm16") == "done"
    assert calls == [(ZOOM_STT_MODEL, "zoom")]


@pytest.mark.asyncio
async def test_transcribe_sends_source_pcm_in_bounded_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent_chunks: list[bytes] = []
    close_count = 0

    @contextmanager
    def fake_trace(**kwargs: Any) -> Iterator[None]:
        _ = kwargs
        yield

    class FakeTranscriber:
        def __init__(self, **kwargs: Any):
            self.kwargs = kwargs

        async def connect(self) -> None:
            return None

        async def send_audio(self, audio_data: bytes) -> None:
            sent_chunks.append(audio_data)

        async def close(self) -> str:
            nonlocal close_count
            close_count += 1
            return "done"

    monkeypatch.setattr(zoom, "traced_llm_call", fake_trace)
    monkeypatch.setattr(zoom, "ZoomStreamingTranscriber", FakeTranscriber)

    audio = b"a" * (ZOOM_TRANSCRIBE_SEND_CHUNK_BYTES * 2 + 123)
    provider = ZoomVoiceProvider(api_key="key", api_secret="secret")

    assert await provider.transcribe(audio, "pcm16") == "done"
    assert [len(chunk) for chunk in sent_chunks] == [
        ZOOM_TRANSCRIBE_SEND_CHUNK_BYTES,
        ZOOM_TRANSCRIBE_SEND_CHUNK_BYTES,
        123,
    ]
    assert b"".join(sent_chunks) == audio
    assert close_count == 1


@pytest.mark.asyncio
async def test_transcribe_closes_after_successful_connect_on_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    close_count = 0

    @contextmanager
    def fake_trace(**kwargs: Any) -> Iterator[None]:
        _ = kwargs
        yield

    class FakeTranscriber:
        def __init__(self, **kwargs: Any):
            self.kwargs = kwargs

        async def connect(self) -> None:
            return None

        async def send_audio(self, audio_data: bytes) -> None:
            _ = audio_data
            raise asyncio.CancelledError

        async def close(self) -> str:
            nonlocal close_count
            close_count += 1
            return ""

    monkeypatch.setattr(zoom, "traced_llm_call", fake_trace)
    monkeypatch.setattr(zoom, "ZoomStreamingTranscriber", FakeTranscriber)

    provider = ZoomVoiceProvider(api_key="key", api_secret="secret")

    with pytest.raises(asyncio.CancelledError):
        await provider.transcribe(b"pcm", "pcm16")
    assert close_count == 1


@pytest.mark.asyncio
async def test_validate_credentials_closes_after_successful_connect_on_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    close_count = 0

    class FakeTranscriber:
        def __init__(self, **kwargs: Any):
            self.kwargs = kwargs

        async def connect(self) -> None:
            return None

        async def close(self) -> str:
            nonlocal close_count
            close_count += 1
            raise asyncio.CancelledError

    monkeypatch.setattr(zoom, "ZoomStreamingTranscriber", FakeTranscriber)

    provider = ZoomVoiceProvider(api_key="key", api_secret="secret")

    with pytest.raises(asyncio.CancelledError):
        await provider.validate_credentials()
    assert close_count == 1


def test_provider_capabilities_are_stt_only() -> None:
    provider = ZoomVoiceProvider(api_key="key", api_secret="secret")

    assert provider.supports_streaming_stt() is True
    assert provider.supports_streaming_tts() is False
    assert provider.allows_streaming_stt_fallback() is False


def test_factory_extracts_key_and_secret_and_uses_fixed_api_base() -> None:
    class FakeSensitive:
        def __init__(self, value: str):
            self.value = value

        def get_value(self, apply_mask: bool) -> str:
            assert apply_mask is False
            return self.value

    provider_model = SimpleNamespace(
        name="Zoom",
        provider_type="zoom",
        api_base="https://should-not-be-used.example",
        custom_config={"language": "es-ES"},
        stt_model=ZOOM_STT_MODEL,
        tts_model=None,
        default_voice=None,
    )
    provider_model.api_key = FakeSensitive("key")
    provider_model.api_secret = FakeSensitive("secret")

    provider = get_voice_provider(cast(VoiceProvider, provider_model))

    assert isinstance(provider, ZoomVoiceProvider)
    assert provider.api_key == "key"
    assert provider.api_secret == "secret"
    assert provider.language == "es-ES"
    assert provider.stt_model == ZOOM_STT_MODEL
    assert ZOOM_API_BASE == "https://api.zoom.us"


@pytest.mark.asyncio
async def test_streaming_transcriber_connect_cleans_up_on_handshake_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ws = HangingWebSocket([])
    session = FakeSession(ws)
    monkeypatch.setattr(zoom.aiohttp, "ClientSession", lambda: session)
    monkeypatch.setattr(zoom, "ZOOM_HANDSHAKE_TIMEOUT_SECONDS", 0.01)

    transcriber = ZoomStreamingTranscriber(api_key="key", api_secret="x" * 32)

    with pytest.raises(asyncio.TimeoutError):
        await transcriber.connect()

    assert ws.closed is True
    assert session.closed is True
