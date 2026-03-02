from onyx.db.models import VoiceProvider
from onyx.voice.interface import VoiceProviderInterface


def get_voice_provider(provider: VoiceProvider) -> VoiceProviderInterface:
    """
    Factory function to get the appropriate voice provider implementation.

    Args:
        provider: VoiceProvider model instance (can be from DB or constructed temporarily)

    Returns:
        VoiceProviderInterface implementation

    Raises:
        ValueError: If provider_type is not supported
    """
    provider_type = provider.provider_type.lower()

    # Handle both SensitiveValue (from DB) and plain string (from temp model)
    if provider.api_key is None:
        api_key = None
    elif hasattr(provider.api_key, "get_value"):
        # SensitiveValue from database
        api_key = provider.api_key.get_value(apply_mask=False)
    else:
        # Plain string from temporary model
        api_key = provider.api_key  # type: ignore[assignment]
    api_base = provider.api_base
    custom_config = provider.custom_config
    stt_model = provider.stt_model
    tts_model = provider.tts_model
    default_voice = provider.default_voice

    if provider_type == "openai":
        from onyx.voice.providers.openai import OpenAIVoiceProvider

        return OpenAIVoiceProvider(
            api_key=api_key,
            api_base=api_base,
            stt_model=stt_model,
            tts_model=tts_model,
            default_voice=default_voice,
        )

    elif provider_type == "azure":
        from onyx.voice.providers.azure import AzureVoiceProvider

        return AzureVoiceProvider(
            api_key=api_key,
            custom_config=custom_config or {},
            stt_model=stt_model,
            tts_model=tts_model,
            default_voice=default_voice,
        )

    elif provider_type == "elevenlabs":
        from onyx.voice.providers.elevenlabs import ElevenLabsVoiceProvider

        return ElevenLabsVoiceProvider(
            api_key=api_key,
            api_base=api_base,
            stt_model=stt_model,
            tts_model=tts_model,
            default_voice=default_voice,
        )

    else:
        raise ValueError(f"Unsupported voice provider type: {provider_type}")
