"""TTS streams must not leave tracing state for another task to reset.

`synthesize_speech` pulls the first chunk in the request task, and Starlette's
`StreamingResponse` reads the rest in another task with a copied context. The
provider's span must not set a context variable that the other task resets.
"""

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator, Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

import onyx.server.manage.voice.user_api as user_api
from onyx.server.manage.voice.user_api import SynthesizeRequest, synthesize_speech
from onyx.tracing.framework.create import get_current_span
from onyx.voice.providers.openai import OpenAIVoiceProvider

_CHUNKS = [b"first-chunk", b"middle-chunk", b"last-chunk"]


class _FakeSpeechStream:
    """Stands in for `client.audio.speech.with_streaming_response.create(...)`."""

    async def __aenter__(self) -> "_FakeSpeechStream":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def iter_bytes(self, chunk_size: int) -> AsyncIterator[bytes]:
        _ = chunk_size
        for chunk in _CHUNKS:
            yield chunk


def _openai_provider() -> OpenAIVoiceProvider:
    provider = OpenAIVoiceProvider(api_key="sk-test")
    client: Any = MagicMock()
    client.audio.speech.with_streaming_response.create = lambda **_kwargs: (
        _FakeSpeechStream()
    )
    provider._client = client
    return provider


@pytest.fixture
def tts_app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    @contextmanager
    def fake_session() -> Iterator[MagicMock]:
        yield MagicMock()

    monkeypatch.setattr(user_api, "get_session_with_current_tenant", fake_session)
    monkeypatch.setattr(
        user_api,
        "fetch_default_tts_provider",
        lambda _db: SimpleNamespace(
            api_key="sk-test", default_voice="alloy", provider_type="openai"
        ),
    )
    provider = _openai_provider()
    monkeypatch.setattr(user_api, "get_voice_provider", lambda _db: provider)

    app = FastAPI()

    # Awaits the real endpoint in the request task, as the router does.
    @app.post("/voice/synthesize")
    async def synthesize() -> StreamingResponse:
        return await synthesize_speech(
            SynthesizeRequest(text="Hello there", speed=1.0), user=MagicMock()
        )

    return app


def test_read_aloud_streams_every_chunk(tts_app: FastAPI) -> None:
    with TestClient(tts_app) as client:
        response = client.post("/voice/synthesize")

    assert response.status_code == 200
    assert response.content == b"".join(_CHUNKS)


@pytest.mark.asyncio
async def test_stream_closed_early_from_another_task() -> None:
    stream = _openai_provider().synthesize_stream("Hello there")
    assert isinstance(stream, AsyncGenerator)

    assert await stream.__anext__() == _CHUNKS[0]
    # The provider's span stays inside the stream, not in the caller's context.
    assert get_current_span() is None

    await asyncio.create_task(stream.aclose())
