from onyx.db.models import VoiceProvider
from onyx.voice.interface import VoiceProviderInterface
from onyx.voice.types import VoiceProviderType


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
        api_key = provider.api_key
    api_base = provider.api_base
    custom_config = provider.custom_config
    stt_model = provider.stt_model
    tts_model = provider.tts_model
    default_voice = provider.default_voice

    if provider_type == VoiceProviderType.OPENAI:
        from onyx.voice.providers.openai import OpenAIVoiceProvider

        return OpenAIVoiceProvider(
            api_key=api_key,
            api_base=api_base,
            stt_model=stt_model,
            tts_model=tts_model,
            default_voice=default_voice,
        )

    elif provider_type == VoiceProviderType.OPENAI_COMPATIBLE:
        from onyx.voice.providers.openai_compatible import (
            OpenAICompatibleVoiceProvider,
        )

        if not api_base or not stt_model:
            raise ValueError(
                "OpenAI-compatible providers require an API base and STT model."
            )
        return OpenAICompatibleVoiceProvider(
            api_key=api_key,
            api_base=api_base,
            stt_model=stt_model,
        )

    elif provider_type == VoiceProviderType.AZURE:
        from onyx.voice.providers.azure import AzureVoiceProvider

        return AzureVoiceProvider(
            api_key=api_key,
            api_base=api_base,
            custom_config=custom_config or {},
            stt_model=stt_model,
            tts_model=tts_model,
            default_voice=default_voice,
        )

    elif provider_type == VoiceProviderType.ELEVENLABS:
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
