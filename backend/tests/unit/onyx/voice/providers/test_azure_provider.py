import pytest

from onyx.voice.providers.azure import AzureVoiceProvider


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
