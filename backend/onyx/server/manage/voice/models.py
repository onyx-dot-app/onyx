from typing import Any

from pydantic import BaseModel
from pydantic import Field


class VoiceProviderView(BaseModel):
    """Response model for voice provider listing."""

    id: int
    name: str
    provider_type: str  # "openai", "azure", "elevenlabs"
    is_default_stt: bool
    is_default_tts: bool
    stt_model: str | None
    tts_model: str | None
    default_voice: str | None
    has_api_key: bool = Field(
        default=False,
        description="Indicates whether an API key is stored for this provider.",
    )


class VoiceProviderUpsertRequest(BaseModel):
    """Request model for creating or updating a voice provider."""

    id: int | None = Field(default=None, description="Existing provider ID to update.")
    name: str
    provider_type: str  # "openai", "azure", "elevenlabs"
    api_key: str | None = Field(
        default=None,
        description="API key for the provider.",
    )
    api_key_changed: bool = Field(
        default=False,
        description="Set to true when providing a new API key for an existing provider.",
    )
    api_base: str | None = None
    custom_config: dict[str, Any] | None = None
    stt_model: str | None = None
    tts_model: str | None = None
    default_voice: str | None = None
    activate_stt: bool = Field(
        default=False,
        description="If true, sets this provider as the default STT provider after upsert.",
    )
    activate_tts: bool = Field(
        default=False,
        description="If true, sets this provider as the default TTS provider after upsert.",
    )


class VoiceProviderTestRequest(BaseModel):
    """Request model for testing a voice provider connection."""

    provider_type: str
    api_key: str | None = Field(
        default=None,
        description="API key for testing. If not provided, use_stored_key must be true.",
    )
    use_stored_key: bool = Field(
        default=False,
        description="If true, use the stored API key for this provider type.",
    )
    api_base: str | None = None
    custom_config: dict[str, Any] | None = None


class SynthesizeRequest(BaseModel):
    """Request model for text-to-speech synthesis."""

    text: str = Field(..., min_length=1, max_length=4096)
    voice: str | None = None
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
