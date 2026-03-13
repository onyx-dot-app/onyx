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
