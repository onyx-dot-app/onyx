import io
import wave
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from openai import APIConnectionError, AuthenticationError

from onyx.db.models import VoiceProvider
from onyx.voice.factory import get_voice_provider
from onyx.voice.providers.openai_compatible import (
    OpenAICompatibleVoiceProvider,
    normalize_openai_compatible_api_base,
)
from onyx.voice.types import VoiceProviderType


@pytest.mark.parametrize(
    ("api_base", "expected"),
    [
        ("http://stt.example", "http://stt.example/v1"),
        ("http://stt.example/", "http://stt.example/v1"),
        ("http://stt.example/v1", "http://stt.example/v1"),
        ("http://stt.example/v1/", "http://stt.example/v1"),
    ],
)
def test_openai_compatible_api_base_normalization(api_base: str, expected: str) -> None:
    assert normalize_openai_compatible_api_base(api_base) == expected


@pytest.mark.parametrize(("api_key", "expected"), [(None, ""), ("secret", "secret")])
def test_openai_compatible_client_optional_api_key(
    api_key: str | None, expected: str
) -> None:
    provider = OpenAICompatibleVoiceProvider(
        api_base="http://stt.example", stt_model="whisper", api_key=api_key
    )
    with (
        patch("openai.AsyncOpenAI") as client_cls,
        patch("openai.DefaultAsyncHttpxClient") as http_client_cls,
    ):
        provider._get_client()

    assert client_cls.call_args.kwargs["api_key"] == expected
    assert client_cls.call_args.kwargs["_enforce_credentials"] is False
    http_client_cls.assert_called_once()


@pytest.mark.asyncio
async def test_openai_compatible_transcription_wraps_pcm_and_sends_model() -> None:
    create = AsyncMock(return_value=SimpleNamespace(text="hello"))
    provider = OpenAICompatibleVoiceProvider(
        api_base="http://stt.example", stt_model="whisper"
    )
    provider._client = cast(
        Any,
        SimpleNamespace(
            audio=SimpleNamespace(transcriptions=SimpleNamespace(create=create))
        ),
    )

    assert await provider.transcribe(b"\x00\x00" * 100, "pcm16") == "hello"

    assert create.await_args is not None
    call = create.await_args.kwargs
    assert call["model"] == "whisper"
    audio_file = call["file"]
    assert audio_file.name == "audio.wav"
    with wave.open(io.BytesIO(audio_file.getvalue()), "rb") as wav_file:
        assert wav_file.getframerate() == 24000
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2


@pytest.mark.asyncio
async def test_openai_compatible_validate_credentials_accepts_selected_model() -> None:
    provider = OpenAICompatibleVoiceProvider(
        api_base="http://stt.example", stt_model="whisper"
    )
    provider._client = _client_with_models(["other", "whisper"])

    await provider.validate_credentials()


@pytest.mark.asyncio
async def test_openai_compatible_validate_credentials_rejects_missing_model() -> None:
    provider = OpenAICompatibleVoiceProvider(
        api_base="http://stt.example", stt_model="missing"
    )
    provider._client = _client_with_models(["whisper"])

    with pytest.raises(ValueError, match="'missing' is not available"):
        await provider.validate_credentials()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "message"),
    [
        (
            APIConnectionError(request=httpx.Request("GET", "http://stt.example")),
            "Could not reach",
        ),
        (
            AuthenticationError(
                "unauthorized",
                response=httpx.Response(
                    401,
                    request=httpx.Request("GET", "http://stt.example"),
                ),
                body=None,
            ),
            "rejected the API key",
        ),
    ],
)
async def test_openai_compatible_validate_credentials_reports_upstream_errors(
    error: Exception, message: str
) -> None:
    provider = OpenAICompatibleVoiceProvider(
        api_base="http://stt.example", stt_model="whisper"
    )
    models_list = AsyncMock(side_effect=error)
    provider._client = cast(
        Any, SimpleNamespace(models=SimpleNamespace(list=models_list))
    )

    with pytest.raises(ValueError, match=message):
        await provider.validate_credentials()


def test_openai_compatible_capabilities_are_stt_only() -> None:
    provider = OpenAICompatibleVoiceProvider(
        api_base="http://stt.example", stt_model="whisper"
    )

    assert provider.supports_streaming_stt() is False
    with pytest.raises(NotImplementedError, match="STT-only"):
        provider.synthesize_stream("hello")


def test_openai_compatible_factory_selection() -> None:
    provider_model = VoiceProvider(
        name="compatible",
        provider_type=VoiceProviderType.OPENAI_COMPATIBLE.value,
        api_base="http://stt.example",
        stt_model="whisper",
    )

    provider = get_voice_provider(provider_model)

    assert isinstance(provider, OpenAICompatibleVoiceProvider)
    assert provider.api_key is None


def _client_with_models(model_ids: list[str]) -> Any:
    models_list = AsyncMock(
        return_value=SimpleNamespace(
            data=[SimpleNamespace(id=model_id) for model_id in model_ids]
        )
    )
    return SimpleNamespace(models=SimpleNamespace(list=models_list))
