from enum import StrEnum


class VoiceProviderType(StrEnum):
    OPENAI = "openai"
    OPENAI_COMPATIBLE = "openai_compatible"
    AZURE = "azure"
    ELEVENLABS = "elevenlabs"


def voice_provider_requires_api_key(provider_type: str | VoiceProviderType) -> bool:
    return provider_type != VoiceProviderType.OPENAI_COMPATIBLE
