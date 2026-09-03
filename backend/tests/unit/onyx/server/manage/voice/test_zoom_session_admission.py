import inspect
from collections.abc import Awaitable
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from fastapi import WebSocket

from onyx.db.models import User
from onyx.server.manage.voice import websocket_api


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
    def supports_streaming_stt(self) -> bool:
        return True

    def allows_streaming_stt_fallback(self) -> bool:
        return False

    async def create_streaming_transcriber(self) -> None:
        raise RuntimeError("upstream unavailable")


class _FakeStreamingTranscriber:
    def __init__(self) -> None:
        self.close = AsyncMock(return_value="")


class _StreamingZoomProvider:
    def __init__(self) -> None:
        self.transcriber = _FakeStreamingTranscriber()

    def supports_streaming_stt(self) -> bool:
        return True

    def allows_streaming_stt_fallback(self) -> bool:
        return False

    async def create_streaming_transcriber(self) -> _FakeStreamingTranscriber:
        return self.transcriber


@pytest.mark.asyncio
async def test_zoom_transcribe_releases_session_when_upstream_creation_fails(
    monkeypatch,
) -> None:
    websocket = _FakeWebSocket()
    provider_db = SimpleNamespace(
        id=42,
        provider_type="zoom",
        api_key="api-key",
    )
    acquire = AsyncMock(return_value="session-member-1")
    release = AsyncMock()

    monkeypatch.setattr(websocket_api, "get_sqlalchemy_engine", lambda: object())
    monkeypatch.setattr(websocket_api, "Session", lambda _engine: _FakeSession())
    monkeypatch.setattr(
        websocket_api, "fetch_default_stt_provider", lambda _db_session: provider_db
    )
    monkeypatch.setattr(
        websocket_api, "get_voice_provider", lambda _provider_db: _FailingZoomProvider()
    )
    monkeypatch.setattr(websocket_api, "acquire_zoom_voice_session", acquire)
    monkeypatch.setattr(websocket_api, "release_zoom_voice_session", release)

    await websocket_api.websocket_transcribe(
        cast(WebSocket, websocket),
        _user=cast(User, SimpleNamespace(id="user-7")),
    )

    acquire.assert_awaited_once_with(provider_id=42, user_id="user-7")
    release.assert_awaited_once_with(
        provider_id=42,
        user_id="user-7",
        session_member_id="session-member-1",
    )
    assert websocket.sent_json == [{"type": "error", "message": "Streaming STT failed"}]
    websocket.accept.assert_awaited_once()
    websocket.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_zoom_transcribe_timeout_uses_hard_cap_and_releases_session(
    monkeypatch,
) -> None:
    websocket = _FakeWebSocket()
    provider_db = SimpleNamespace(
        id=42,
        provider_type="zoom",
        api_key="api-key",
    )
    provider = _StreamingZoomProvider()
    acquire = AsyncMock(return_value="session-member-1")
    release = AsyncMock()
    observed_timeouts: list[float | None] = []

    async def fake_wait_for(awaitable: Awaitable[None], timeout: float | None) -> None:
        observed_timeouts.append(timeout)
        if inspect.iscoroutine(awaitable):
            awaitable.close()
        raise TimeoutError

    monkeypatch.setattr(websocket_api, "get_sqlalchemy_engine", lambda: object())
    monkeypatch.setattr(websocket_api, "Session", lambda _engine: _FakeSession())
    monkeypatch.setattr(
        websocket_api, "fetch_default_stt_provider", lambda _db_session: provider_db
    )
    monkeypatch.setattr(
        websocket_api, "get_voice_provider", lambda _provider_db: provider
    )
    monkeypatch.setattr(websocket_api, "acquire_zoom_voice_session", acquire)
    monkeypatch.setattr(websocket_api, "release_zoom_voice_session", release)
    monkeypatch.setattr(websocket_api.asyncio, "wait_for", fake_wait_for)

    await websocket_api.websocket_transcribe(
        cast(WebSocket, websocket),
        _user=cast(User, SimpleNamespace(id="user-7")),
    )

    assert observed_timeouts == [websocket_api.ZOOM_VOICE_SESSION_MAX_SECONDS]
    assert websocket.sent_json == [
        {
            "type": "error",
            "message": websocket_api.ZOOM_STREAMING_SESSION_TIMEOUT_MESSAGE,
        }
    ]
    acquire.assert_awaited_once_with(provider_id=42, user_id="user-7")
    release.assert_awaited_once_with(
        provider_id=42,
        user_id="user-7",
        session_member_id="session-member-1",
    )
    provider.transcriber.close.assert_awaited_once()
    websocket.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_zoom_transcribe_limit_returns_sanitized_message(monkeypatch) -> None:
    websocket = _FakeWebSocket()
    provider_db = SimpleNamespace(
        id=42,
        provider_type="zoom",
        api_key="api-key",
    )
    release = AsyncMock()

    async def raise_limit(*, provider_id: int, user_id: str) -> str:
        _ = provider_id, user_id
        raise websocket_api.ZoomVoiceSessionLimitExceeded(
            websocket_api.ZOOM_VOICE_SESSION_LIMIT_MESSAGE
        )

    monkeypatch.setattr(websocket_api, "get_sqlalchemy_engine", lambda: object())
    monkeypatch.setattr(websocket_api, "Session", lambda _engine: _FakeSession())
    monkeypatch.setattr(
        websocket_api, "fetch_default_stt_provider", lambda _db_session: provider_db
    )
    monkeypatch.setattr(
        websocket_api, "get_voice_provider", lambda _provider_db: _FailingZoomProvider()
    )
    monkeypatch.setattr(websocket_api, "acquire_zoom_voice_session", raise_limit)
    monkeypatch.setattr(websocket_api, "release_zoom_voice_session", release)

    await websocket_api.websocket_transcribe(
        cast(WebSocket, websocket),
        _user=cast(User, SimpleNamespace(id="user-7")),
    )

    release.assert_not_awaited()
    assert websocket.sent_json == [
        {
            "type": "error",
            "message": websocket_api.ZOOM_VOICE_SESSION_LIMIT_MESSAGE,
        }
    ]
    websocket.close.assert_awaited_once()
