import asyncio
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from fastapi import WebSocket

from onyx.db.models import User
from onyx.server.manage.voice import websocket_api
from onyx.voice.interface import VoiceSessionPolicy
from onyx.voice.providers.zoom import (
    ZOOM_CLOSE_TIMEOUT_SECONDS,
    ZOOM_SESSION_POLICY,
    ZOOM_VOICE_SESSION_MAX_SECONDS,
)

# A tiny cap so hanging handlers end quickly; teardown is zero so the whole
# cap is the handler budget.
TEST_POLICY = ZOOM_SESSION_POLICY.model_copy(
    update={"max_session_seconds": 0.01, "teardown_seconds": 0.0}
)


class _FakeSession:
    def __enter__(self) -> "_FakeSession":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> None:
        return None


class _FakeWebSocket:
    def __init__(self) -> None:
        self.sent_json: list[dict[str, str]] = []
        self.accept = AsyncMock()
        self.close = AsyncMock()

    async def send_json(self, payload: dict[str, str]) -> None:
        self.sent_json.append(payload)


class _FailingZoomProvider:
    def session_policy(self) -> VoiceSessionPolicy | None:
        return TEST_POLICY

    def supports_streaming_stt(self) -> bool:
        return True

    def allows_streaming_stt_fallback(self) -> bool:
        return False

    async def create_streaming_transcriber(self) -> None:
        raise RuntimeError("upstream unavailable")


class _HandshakeTimeoutZoomProvider(_FailingZoomProvider):
    async def create_streaming_transcriber(self) -> None:
        raise TimeoutError


class _FakeStreamingTranscriber:
    def __init__(self) -> None:
        self.close = AsyncMock(return_value="")


class _StreamingZoomProvider:
    def __init__(self) -> None:
        self.transcriber = _FakeStreamingTranscriber()

    def session_policy(self) -> VoiceSessionPolicy | None:
        return TEST_POLICY

    def supports_streaming_stt(self) -> bool:
        return True

    def allows_streaming_stt_fallback(self) -> bool:
        return False

    async def create_streaming_transcriber(self) -> _FakeStreamingTranscriber:
        return self.transcriber


class _SlowSetupZoomProvider(_StreamingZoomProvider):
    async def create_streaming_transcriber(self) -> _FakeStreamingTranscriber:
        await asyncio.sleep(60)
        return self.transcriber


async def _raise_limit(*, policy: VoiceSessionPolicy, user_id: str) -> str:
    _ = user_id
    raise websocket_api.VoiceSessionLimitExceeded(policy.limit_message)


async def _hang(_websocket: object, _transcriber: object, **_kwargs: object) -> None:
    await asyncio.sleep(60)


def _install_transcribe_deps(
    monkeypatch: pytest.MonkeyPatch,
    provider: object,
    *,
    provider_type: str = "zoom",
    acquire: object | None = None,
    release: AsyncMock | None = None,
) -> tuple[AsyncMock, AsyncMock]:
    """Patch the DB and Redis seams of websocket_transcribe for one constrained row."""
    provider_db = SimpleNamespace(id=42, provider_type=provider_type, api_key="api-key")
    acquire_mock = (
        acquire if acquire is not None else AsyncMock(return_value="session-member-1")
    )
    release_mock = release if release is not None else AsyncMock()

    monkeypatch.setattr(websocket_api, "get_sqlalchemy_engine", lambda: object())
    monkeypatch.setattr(websocket_api, "Session", lambda _engine: _FakeSession())
    monkeypatch.setattr(
        websocket_api, "fetch_default_stt_provider", lambda _db_session: provider_db
    )
    monkeypatch.setattr(
        websocket_api, "get_voice_provider", lambda _provider_db: provider
    )
    monkeypatch.setattr(websocket_api, "acquire_voice_session", acquire_mock)
    monkeypatch.setattr(websocket_api, "release_voice_session", release_mock)
    return cast(AsyncMock, acquire_mock), release_mock


async def _run_transcribe(websocket: _FakeWebSocket) -> None:
    await websocket_api.websocket_transcribe(
        cast(WebSocket, websocket),
        _user=cast(User, SimpleNamespace(id="user-7")),
    )


def _error(message: str) -> list[dict[str, str]]:
    return [{"type": "error", "message": message}]


@pytest.mark.asyncio
async def test_zoom_transcribe_releases_session_when_upstream_creation_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    websocket = _FakeWebSocket()
    acquire, release = _install_transcribe_deps(monkeypatch, _FailingZoomProvider())

    await _run_transcribe(websocket)

    acquire.assert_awaited_once_with(policy=TEST_POLICY, user_id="user-7")
    release.assert_awaited_once_with(
        policy=TEST_POLICY, user_id="user-7", session_member_id="session-member-1"
    )
    assert websocket.sent_json == _error(websocket_api.STREAM_FAILED_ERROR)
    websocket.accept.assert_awaited_once()
    websocket.close.assert_any_await(code=websocket_api.WS_SERVER_ERROR_CLOSE_CODE)


@pytest.mark.asyncio
async def test_zoom_transcribe_timeout_uses_hard_cap_and_releases_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    websocket = _FakeWebSocket()
    provider = _StreamingZoomProvider()
    acquire, release = _install_transcribe_deps(monkeypatch, provider)
    monkeypatch.setattr(websocket_api, "handle_streaming_transcription", _hang)

    await _run_transcribe(websocket)

    assert websocket.sent_json == _error(TEST_POLICY.timeout_message)
    acquire.assert_awaited_once_with(policy=TEST_POLICY, user_id="user-7")
    release.assert_awaited_once_with(
        policy=TEST_POLICY, user_id="user-7", session_member_id="session-member-1"
    )
    provider.transcriber.close.assert_awaited_once()
    websocket.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_zoom_transcribe_limit_returns_sanitized_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    websocket = _FakeWebSocket()
    _, release = _install_transcribe_deps(
        monkeypatch, _FailingZoomProvider(), acquire=_raise_limit
    )

    await _run_transcribe(websocket)

    release.assert_not_awaited()
    assert websocket.sent_json == _error(TEST_POLICY.limit_message)
    websocket.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_zoom_chunked_path_uses_hard_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    websocket = _FakeWebSocket()
    acquire, release = _install_transcribe_deps(monkeypatch, _StreamingZoomProvider())
    monkeypatch.setattr(websocket_api, "VOICE_DISABLE_STREAMING_STT", True)
    monkeypatch.setattr(websocket_api, "handle_chunked_transcription", _hang)

    await _run_transcribe(websocket)

    assert websocket.sent_json == _error(TEST_POLICY.timeout_message)
    acquire.assert_awaited_once_with(policy=TEST_POLICY, user_id="user-7")
    release.assert_awaited_once()
    websocket.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_zoom_guards_apply_to_mixed_case_provider_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    websocket = _FakeWebSocket()
    _install_transcribe_deps(
        monkeypatch,
        _FailingZoomProvider(),
        provider_type=" Zoom ",
        acquire=_raise_limit,
    )

    await _run_transcribe(websocket)

    assert websocket.sent_json == _error(TEST_POLICY.limit_message)


@pytest.mark.asyncio
async def test_zoom_handshake_timeout_reports_streaming_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    websocket = _FakeWebSocket()
    _, release = _install_transcribe_deps(monkeypatch, _HandshakeTimeoutZoomProvider())

    await _run_transcribe(websocket)

    assert websocket.sent_json == _error(websocket_api.STREAM_FAILED_ERROR)
    release.assert_awaited_once()


@pytest.mark.asyncio
async def test_zoom_hard_cap_includes_transcriber_setup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    websocket = _FakeWebSocket()
    _, release = _install_transcribe_deps(monkeypatch, _SlowSetupZoomProvider())

    await _run_transcribe(websocket)

    assert websocket.sent_json == _error(TEST_POLICY.timeout_message)
    release.assert_awaited_once()


def test_zoom_policy_reserves_provider_teardown() -> None:
    # Teardown runs after the cap ends the handler, so the policy must carry
    # the real Zoom constants and its teardown budget must cover the
    # WebSocket layer's own close bound.
    assert ZOOM_SESSION_POLICY.max_session_seconds == ZOOM_VOICE_SESSION_MAX_SECONDS
    assert ZOOM_SESSION_POLICY.teardown_seconds == ZOOM_CLOSE_TIMEOUT_SECONDS
    assert ZOOM_CLOSE_TIMEOUT_SECONDS >= websocket_api.TRANSCRIBER_CLOSE_TIMEOUT_SECONDS


class _UnconstrainedProvider(_StreamingZoomProvider):
    def session_policy(self) -> None:
        return None


@pytest.mark.asyncio
async def test_unconstrained_provider_skips_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    websocket = _FakeWebSocket()
    provider = _UnconstrainedProvider()
    acquire, release = _install_transcribe_deps(
        monkeypatch, provider, provider_type="openai"
    )

    async def finish(
        _websocket: object, _transcriber: object, **_kwargs: object
    ) -> None:
        return None

    monkeypatch.setattr(websocket_api, "handle_streaming_transcription", finish)

    await _run_transcribe(websocket)

    acquire.assert_not_awaited()
    release.assert_not_awaited()
    assert websocket.sent_json == []
