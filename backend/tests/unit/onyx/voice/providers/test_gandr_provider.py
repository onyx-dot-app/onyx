import asyncio

import pytest

from onyx.voice.providers.gandr import (
    DEFAULT_GANDR_API_BASE,
    GANDR_MAX_INPUT_CHARACTERS,
    GandrVoiceProvider,
    _validate_input_length,
)

# --- Input length validation ---


def test_validate_input_length_allows_input_at_cap() -> None:
    _validate_input_length("a" * GANDR_MAX_INPUT_CHARACTERS)


def test_validate_input_length_rejects_input_over_cap() -> None:
    with pytest.raises(ValueError, match="2000"):
        _validate_input_length("a" * (GANDR_MAX_INPUT_CHARACTERS + 1))


def test_synthesize_stream_rejects_input_over_cap() -> None:
    """Over-cap input fails client side before any request is made."""
    provider = GandrVoiceProvider(api_key="test")

    async def _consume() -> None:
        text = "a" * (GANDR_MAX_INPUT_CHARACTERS + 1)
        async for _ in provider.synthesize_stream(text):
            pass

    with pytest.raises(ValueError, match="2000"):
        asyncio.run(_consume())


# --- Provider Model Defaulting ---


def test_provider_defaults_invalid_tts_model() -> None:
    provider = GandrVoiceProvider(api_key="test", tts_model="invalid_model")
    assert provider.tts_model == "tts-1"


def test_provider_accepts_valid_model() -> None:
    provider = GandrVoiceProvider(api_key="test", tts_model="tts-1")
    assert provider.tts_model == "tts-1"


def test_provider_defaults_api_base() -> None:
    provider = GandrVoiceProvider(api_key="test")
    assert provider.api_base == DEFAULT_GANDR_API_BASE


def test_provider_defaults_voice() -> None:
    provider = GandrVoiceProvider(api_key="test")
    assert provider.default_voice == "gandr-mia"


def test_provider_get_available_voices_returns_copy() -> None:
    provider = GandrVoiceProvider(api_key="test")
    voices = provider.get_available_voices()
    voices.clear()
    assert len(provider.get_available_voices()) > 0


# --- STT surface ---


def test_provider_has_no_stt_models() -> None:
    provider = GandrVoiceProvider(api_key="test")
    assert provider.get_available_stt_models() == []


def test_transcribe_raises_not_implemented() -> None:
    provider = GandrVoiceProvider(api_key="test")
    with pytest.raises(NotImplementedError):
        asyncio.run(provider.transcribe(b"", "wav"))


# --- Streaming support flags ---


def test_supports_streaming_tts_but_not_stt() -> None:
    provider = GandrVoiceProvider(api_key="test")
    assert provider.supports_streaming_tts() is True
    assert provider.supports_streaming_stt() is False
