import asyncio
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from fastapi import UploadFile

from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.redis.redis_pool import (
    ZOOM_VOICE_SESSION_LIMIT_MESSAGE,
    ZoomVoiceSessionLimitExceeded,
)
from onyx.server.manage.voice import user_api


class _FakeUpload:
    def __init__(self, filename: str, data: bytes) -> None:
        self.filename = filename
        self._data = data
        self._sent = False

    async def read(self, _size: int) -> bytes:
        if self._sent:
            return b""
        self._sent = True
        return self._data


class _ZoomProvider:
    def __init__(self, transcript: str = "hello") -> None:
        self.transcript = transcript
        self.calls: list[str] = []

    async def transcribe(self, audio_data: bytes, audio_format: str) -> str:
        _ = audio_data
        self.calls.append(audio_format)
        if audio_format != "pcm16":
            raise ValueError("Zoom Scribe only supports pcm16 audio in Onyx.")
        return self.transcript


def _install_zoom_provider(
    monkeypatch: pytest.MonkeyPatch, provider: _ZoomProvider
) -> None:
    monkeypatch.setattr(
        user_api,
        "fetch_default_stt_provider",
        lambda _db_session: SimpleNamespace(provider_type="Zoom", api_key="api-key"),
    )
    monkeypatch.setattr(user_api, "get_voice_provider", lambda _provider_db: provider)


async def _transcribe(filename: str) -> dict[str, str]:
    return await user_api.transcribe_audio(
        audio=cast(UploadFile, _FakeUpload(filename, b"\x01\x00" * 100)),
        user=cast(User, SimpleNamespace(id="user-7")),
        db_session=cast(Any, object()),
    )


@pytest.mark.asyncio
async def test_rest_transcribe_admits_and_releases_zoom_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _ZoomProvider()
    _install_zoom_provider(monkeypatch, provider)
    acquire = AsyncMock(return_value="session-member-1")
    release = AsyncMock()
    monkeypatch.setattr(user_api, "acquire_zoom_voice_session", acquire)
    monkeypatch.setattr(user_api, "release_zoom_voice_session", release)

    assert await _transcribe("audio.pcm16") == {"text": "hello"}

    acquire.assert_awaited_once_with(user_id="user-7")
    release.assert_awaited_once_with(
        user_id="user-7", session_member_id="session-member-1"
    )


@pytest.mark.asyncio
async def test_rest_transcribe_releases_zoom_session_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _ZoomProvider()
    _install_zoom_provider(monkeypatch, provider)
    release = AsyncMock()
    monkeypatch.setattr(
        user_api,
        "acquire_zoom_voice_session",
        AsyncMock(return_value="session-member-1"),
    )
    monkeypatch.setattr(user_api, "release_zoom_voice_session", release)

    with pytest.raises(OnyxError) as exc_info:
        await _transcribe("audio.webm")

    assert exc_info.value.error_code == OnyxErrorCode.VALIDATION_ERROR
    release.assert_awaited_once()


@pytest.mark.asyncio
async def test_rest_transcribe_reports_zoom_session_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_zoom_provider(monkeypatch, _ZoomProvider())

    async def raise_limit(*, user_id: str) -> str:
        _ = user_id
        raise ZoomVoiceSessionLimitExceeded(ZOOM_VOICE_SESSION_LIMIT_MESSAGE)

    release = AsyncMock()
    monkeypatch.setattr(user_api, "acquire_zoom_voice_session", raise_limit)
    monkeypatch.setattr(user_api, "release_zoom_voice_session", release)

    with pytest.raises(OnyxError) as exc_info:
        await _transcribe("audio.pcm16")

    assert exc_info.value.error_code == OnyxErrorCode.RATE_LIMITED
    assert exc_info.value.detail == ZOOM_VOICE_SESSION_LIMIT_MESSAGE
    release.assert_not_awaited()


@pytest.mark.asyncio
async def test_rest_transcribe_skips_zoom_guards_for_other_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _ZoomProvider()
    monkeypatch.setattr(
        user_api,
        "fetch_default_stt_provider",
        lambda _db_session: SimpleNamespace(provider_type="openai", api_key="api-key"),
    )
    monkeypatch.setattr(user_api, "get_voice_provider", lambda _provider_db: provider)
    acquire = AsyncMock()
    monkeypatch.setattr(user_api, "acquire_zoom_voice_session", acquire)

    assert await _transcribe("audio.pcm16") == {"text": "hello"}

    acquire.assert_not_awaited()


class _HangingZoomProvider(_ZoomProvider):
    async def transcribe(self, audio_data: bytes, audio_format: str) -> str:
        _ = (audio_data, audio_format)
        await asyncio.sleep(60)
        return self.transcript


@pytest.mark.asyncio
async def test_rest_transcribe_timeout_releases_zoom_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_zoom_provider(monkeypatch, _HangingZoomProvider())
    release = AsyncMock()
    monkeypatch.setattr(
        user_api,
        "acquire_zoom_voice_session",
        AsyncMock(return_value="session-member-1"),
    )
    monkeypatch.setattr(user_api, "release_zoom_voice_session", release)
    monkeypatch.setattr(user_api, "ZOOM_REST_TRANSCRIBE_SECONDS", 0.01)

    with pytest.raises(OnyxError) as exc_info:
        await _transcribe("audio.pcm16")

    assert exc_info.value.error_code == OnyxErrorCode.INTERNAL_ERROR
    release.assert_awaited_once_with(
        user_id="user-7", session_member_id="session-member-1"
    )


def test_rest_transcribe_budget_reserves_provider_teardown() -> None:
    # A cancelled transcribe still closes its Zoom session, so transcribe plus
    # teardown must stay inside the admission window.
    assert (
        user_api.ZOOM_REST_TRANSCRIBE_SECONDS + user_api.ZOOM_CLOSE_TIMEOUT_SECONDS
        == user_api.ZOOM_VOICE_SESSION_MAX_SECONDS
    )
