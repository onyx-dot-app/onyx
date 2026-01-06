from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from onyx.db.models import ImageGenerationConfig as ImageGenerationConfigModel


def _mask_api_key(api_key: str | None) -> str | None:
    """Mask API key, showing first 4 and last 4 characters."""
    if not api_key:
        return None
    if len(api_key) <= 8:
        return "****"
    return api_key[:4] + "****" + api_key[-4:]


class TestImageGenerationRequest(BaseModel):
    """Request model for testing image generation API key.

    Two modes:
    1. Direct API key: Provide api_key + provider
    2. From existing provider: Provide source_llm_provider_id (backend fetches API key)
    """

    model_name: str  # e.g., "gpt-image-1", "dall-e-3"

    # Option 1: Direct API key
    provider: str | None = None  # e.g., "openai", "azure"
    api_key: str | None = None

    # Option 2: Use API key from existing provider
    source_llm_provider_id: int | None = None

    # Additional fields for Azure
    api_base: str | None = None
    api_version: str | None = None
    deployment_name: str | None = None


class ImageGenerationConfigCreate(BaseModel):
    """Request model for creating an image generation config.

    Two creation modes (backend always creates new LLM provider + model config):

    1. Clone mode: Provide source_llm_provider_id + model_name
       → Backend extracts credentials from existing provider and creates new provider

    2. New credentials mode: Provide api_key + provider + model_name (+ optional fields)
       → Backend creates new provider with provided credentials
    """

    # Required for both modes
    image_provider_id: str  # Static unique key (e.g., "openai_gpt_image_1")
    model_name: str  # e.g., "gpt-image-1", "dall-e-3"

    # Option 1: Clone mode - use credentials from existing provider
    source_llm_provider_id: int | None = None

    # Option 2: New credentials mode
    provider: str | None = None  # e.g., "openai", "azure"
    api_key: str | None = None
    api_base: str | None = None
    api_version: str | None = None
    deployment_name: str | None = None

    is_default: bool = False


class ImageGenerationConfigUpdate(BaseModel):
    """Request model for updating an image generation config.

    Same modes as create - either clone from existing provider or use new credentials.
    Backend will delete old LLM provider and create new one.
    """

    # Required
    model_name: str  # e.g., "gpt-image-1", "dall-e-3"
    # Note: image_provider_id cannot be changed during update

    # Option 1: Clone mode - use credentials from existing provider
    source_llm_provider_id: int | None = None

    # Option 2: New credentials mode
    provider: str | None = None  # e.g., "openai", "azure"
    api_key: str | None = None
    api_base: str | None = None
    api_version: str | None = None
    deployment_name: str | None = None

    # If False and using new credentials mode, preserve existing API key from DB
    api_key_changed: bool = False


class ImageGenerationConfigView(BaseModel):
    """Response model for image generation config with related data."""

    image_provider_id: str  # Primary key - static unique key for UI-DB mapping
    model_configuration_id: int
    model_name: str  # From model_configuration.name
    llm_provider_id: int  # From model_configuration.llm_provider_id
    llm_provider_name: str  # From model_configuration.llm_provider.name
    is_default: bool

    @classmethod
    def from_model(
        cls, config: "ImageGenerationConfigModel"
    ) -> "ImageGenerationConfigView":
        """Convert database model to view model."""
        return cls(
            image_provider_id=config.image_provider_id,
            model_configuration_id=config.model_configuration_id,
            model_name=config.model_configuration.name,
            llm_provider_id=config.model_configuration.llm_provider_id,
            llm_provider_name=config.model_configuration.llm_provider.name,
            is_default=config.is_default,
        )


class ImageGenerationCredentials(BaseModel):
    """Response model for image generation config credentials (edit mode)."""

    api_key: str | None
    api_base: str | None
    api_version: str | None
    deployment_name: str | None

    @classmethod
    def from_model(
        cls, config: "ImageGenerationConfigModel"
    ) -> "ImageGenerationCredentials":
        """Convert database model to credentials model.

        Note: API key is masked for security - only first 4 and last 4 chars shown.
        """
        llm_provider = config.model_configuration.llm_provider
        return cls(
            api_key=_mask_api_key(llm_provider.api_key),
            api_base=llm_provider.api_base,
            api_version=llm_provider.api_version,
            deployment_name=llm_provider.deployment_name,
        )


class DefaultImageGenerationConfig(BaseModel):
    """Contains all info needed for image generation tool."""

    model_configuration_id: int
    model_name: str  # From model_configuration.name
    provider: str  # e.g., "openai", "azure" - from llm_provider.provider
    api_key: str | None
    api_base: str | None
    api_version: str | None
    deployment_name: str | None

    @classmethod
    def from_model(
        cls, config: "ImageGenerationConfigModel"
    ) -> "DefaultImageGenerationConfig":
        """Convert database model to default config model."""
        llm_provider = config.model_configuration.llm_provider
        return cls(
            model_configuration_id=config.model_configuration_id,
            model_name=config.model_configuration.name,
            provider=llm_provider.provider,
            api_key=llm_provider.api_key,
            api_base=llm_provider.api_base,
            api_version=llm_provider.api_version,
            deployment_name=llm_provider.deployment_name,
        )
