from typing import Any

from onyx.db.models import VoiceProvider
from onyx.voice.interface import VoiceProviderInterface


def _extract_sensitive_string(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "get_value"):
        return value.get_value(apply_mask=False)
    return value


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
    api_key = _extract_sensitive_string(provider.api_key)
    api_secret = _extract_sensitive_string(provider.api_secret)
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
            api_base=api_base,
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

    elif provider_type == "zoom":
        from onyx.voice.providers.zoom import ZoomVoiceProvider

        return ZoomVoiceProvider(
            api_key=api_key,
            api_secret=api_secret,
            custom_config=custom_config or {},
            stt_model=stt_model,
        )

    else:
        raise ValueError(f"Unsupported voice provider type: {provider_type}")
