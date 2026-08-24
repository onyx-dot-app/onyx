import asyncio
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from onyx.voice.providers.azure import AzureStreamingTranscriber, AzureVoiceProvider


def test_azure_provider_extracts_region_from_target_uri() -> None:
    provider = AzureVoiceProvider(
        api_key="key",
        api_base="https://westus.api.cognitive.microsoft.com/",
        custom_config={},
    )
    assert provider.speech_region == "westus"


def test_azure_provider_normalizes_uppercase_region() -> None:
    provider = AzureVoiceProvider(
        api_key="key",
        api_base=None,
        custom_config={"speech_region": "WestUS2"},
    )
    assert provider.speech_region == "westus2"


def test_azure_provider_rejects_invalid_speech_region() -> None:
    with pytest.raises(ValueError, match="Invalid Azure speech_region"):
        AzureVoiceProvider(
            api_key="key",
            api_base=None,
            custom_config={"speech_region": "westus/../../etc"},
        )


def test_azure_provider_stt_languages_from_custom_config() -> None:
    provider = AzureVoiceProvider(
        api_key="key",
        api_base=None,
        custom_config={"speech_region": "eastus", "stt_languages": ["en-US", "fr-FR"]},
    )
    assert provider.stt_languages == ["en-US", "fr-FR"]


def test_azure_provider_stt_languages_default_to_english() -> None:
    provider = AzureVoiceProvider(
        api_key="key",
        api_base=None,
        custom_config={"speech_region": "eastus"},
    )
    assert provider.stt_languages == ["en-US"]


def test_azure_provider_rejects_duplicate_base_language() -> None:
    with pytest.raises(ValueError, match="one locale per language"):
        AzureVoiceProvider(
            api_key="key",
            api_base=None,
            custom_config={
                "speech_region": "eastus",
                "stt_languages": ["en-US", "en-GB"],
            },
        )


def test_azure_provider_self_hosted_caps_at_start_languages() -> None:
    five_languages = ["en-US", "fr-FR", "de-DE", "es-ES", "it-IT"]
    with pytest.raises(ValueError, match="at most 4"):
        AzureVoiceProvider(
            api_key="key",
            api_base="http://localhost:5000",
            custom_config={"stt_languages": five_languages},
        )
    # The same list is fine in cloud mode (continuous LID allows 10).
    provider = AzureVoiceProvider(
        api_key="key",
        api_base=None,
        custom_config={"speech_region": "eastus", "stt_languages": five_languages},
    )
    assert provider.stt_languages == five_languages


# --- Streaming SDK configuration ---


def _connect_transcriber(
    languages: list[str], **transcriber_kwargs: Any
) -> dict[str, MagicMock]:
    with (
        patch("azure.cognitiveservices.speech.SpeechConfig") as speech_config,
        patch("azure.cognitiveservices.speech.SpeechRecognizer") as recognizer,
        patch(
            "azure.cognitiveservices.speech.languageconfig.AutoDetectSourceLanguageConfig"
        ) as auto_detect,
        patch("azure.cognitiveservices.speech.audio.AudioStreamFormat"),
        patch("azure.cognitiveservices.speech.audio.PushAudioInputStream"),
        patch("azure.cognitiveservices.speech.audio.AudioConfig"),
    ):
        transcriber = AzureStreamingTranscriber(
            api_key="key", languages=languages, **transcriber_kwargs
        )
        asyncio.run(transcriber.connect())
    return {
        "speech_config": speech_config,
        "recognizer": recognizer,
        "auto_detect": auto_detect,
    }


def test_streaming_multilingual_cloud_uses_v2_endpoint_and_continuous_lid() -> None:
    import azure.cognitiveservices.speech as speechsdk

    mocks = _connect_transcriber(["en-US", "fr-FR"], region="swedencentral")

    mocks["speech_config"].assert_called_once_with(
        subscription="key",
        endpoint="wss://swedencentral.stt.speech.microsoft.com/speech/universal/v2",
    )
    mocks["speech_config"].return_value.set_property.assert_called_once_with(
        speechsdk.PropertyId.SpeechServiceConnection_LanguageIdMode,
        "Continuous",
    )
    mocks["auto_detect"].assert_called_once_with(languages=["en-US", "fr-FR"])
    recognizer_kwargs = mocks["recognizer"].call_args.kwargs
    assert (
        recognizer_kwargs["auto_detect_source_language_config"]
        is mocks["auto_detect"].return_value
    )


def test_streaming_single_language_cloud_pins_recognition_language() -> None:
    mocks = _connect_transcriber(["fr-FR"], region="swedencentral")

    mocks["speech_config"].assert_called_once_with(
        subscription="key", region="swedencentral"
    )
    assert mocks["speech_config"].return_value.speech_recognition_language == "fr-FR"
    mocks["auto_detect"].assert_not_called()
    assert (
        mocks["recognizer"].call_args.kwargs["auto_detect_source_language_config"]
        is None
    )


def test_streaming_multilingual_self_hosted_keeps_at_start_detection() -> None:
    mocks = _connect_transcriber(["en-US", "fr-FR"], endpoint="http://localhost:5000")

    mocks["speech_config"].assert_called_once_with(
        subscription="key", endpoint="http://localhost:5000"
    )
    mocks["speech_config"].return_value.set_property.assert_not_called()
    mocks["auto_detect"].assert_called_once_with(languages=["en-US", "fr-FR"])
