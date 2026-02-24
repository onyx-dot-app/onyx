from onyx.db.models import VoiceProvider
from onyx.voice.interface import VoiceProviderInterface


def get_voice_provider(provider: VoiceProvider) -> VoiceProviderInterface:
    """
    Factory function to get the appropriate voice provider implementation.

    Args:
        provider: VoiceProvider database model instance

    Returns:
        VoiceProviderInterface implementation

    Raises:
        ValueError: If provider_type is not supported
    """
    provider_type = provider.provider_type.lower()

    if provider_type == "openai":
        from onyx.voice.providers.openai import OpenAIVoiceProvider

        return OpenAIVoiceProvider(
            api_key=provider.api_key,
            api_base=provider.api_base,
            stt_model=provider.stt_model,
            tts_model=provider.tts_model,
            default_voice=provider.default_voice,
        )

    elif provider_type == "azure":
        from onyx.voice.providers.azure import AzureVoiceProvider

        return AzureVoiceProvider(
            api_key=provider.api_key,
            custom_config=provider.custom_config or {},
            stt_model=provider.stt_model,
            tts_model=provider.tts_model,
            default_voice=provider.default_voice,
        )

    elif provider_type == "elevenlabs":
        from onyx.voice.providers.elevenlabs import ElevenLabsVoiceProvider

        return ElevenLabsVoiceProvider(
            api_key=provider.api_key,
            api_base=provider.api_base,
            stt_model=provider.stt_model,
            tts_model=provider.tts_model,
            default_voice=provider.default_voice,
        )

    else:
        raise ValueError(f"Unsupported voice provider type: {provider_type}")
