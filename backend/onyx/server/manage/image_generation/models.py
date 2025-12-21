from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from onyx.db.models import ImageGenerationConfig as ImageGenerationConfigModel


class ImageGenerationConfigCreate(BaseModel):
    """Request model for creating an image generation config."""

    model_configuration_id: int
    is_default: bool = False


class ImageGenerationConfigView(BaseModel):
    """Response model for image generation config with related data."""

    id: int
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
            id=config.id,
            model_configuration_id=config.model_configuration_id,
            model_name=config.model_configuration.name,
            llm_provider_id=config.model_configuration.llm_provider_id,
            llm_provider_name=config.model_configuration.llm_provider.name,
            is_default=config.is_default,
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
