from typing import Any
from typing import TYPE_CHECKING

from pydantic import BaseModel
from pydantic import Field
from pydantic import field_validator

from onyx.llm.utils import get_max_input_tokens
from onyx.llm.utils import model_supports_image_input


if TYPE_CHECKING:
    from onyx.db.models import (
        LLMProvider as LLMProviderModel,
        ModelConfiguration as ModelConfigurationModel,
    )


class TestLLMRequest(BaseModel):
    # provider level
    name: str | None = None
    provider: str
    api_key: str | None = None
    api_base: str | None = None
    api_version: str | None = None
    custom_config: dict[str, str] | None = None

    # model level
    default_model_name: str
    fast_default_model_name: str | None = None
    deployment_name: str | None = None

    model_configurations: list["ModelConfigurationUpsertRequest"]

    # if try and use the existing API key
    api_key_changed: bool

    @field_validator("provider", mode="before")
    @classmethod
    def normalize_provider(cls, value: str) -> str:
        """Normalize provider name by stripping whitespace and lowercasing."""
        return value.strip().lower()


class LLMProviderDescriptor(BaseModel):
    """A descriptor for an LLM provider that can be safely viewed by
    non-admin users. Used when giving a list of available LLMs."""

    name: str
    provider: str
    default_model_name: str
    fast_default_model_name: str | None
    is_default_provider: bool | None
    is_default_vision_provider: bool | None
    default_vision_model: str | None
    model_configurations: list["ModelConfigurationView"]

    @classmethod
    def from_model(
        cls,
        llm_provider_model: "LLMProviderModel",
    ) -> "LLMProviderDescriptor":
        return cls(
            name=llm_provider_model.name,
            provider=llm_provider_model.provider,
            default_model_name=llm_provider_model.default_model_name,
            fast_default_model_name=llm_provider_model.fast_default_model_name,
            is_default_provider=llm_provider_model.is_default_provider,
            is_default_vision_provider=llm_provider_model.is_default_vision_provider,
            default_vision_model=llm_provider_model.default_vision_model,
            model_configurations=list(
                ModelConfigurationView.from_model(
                    model_configuration, llm_provider_model.provider
                )
                for model_configuration in llm_provider_model.model_configurations
            ),
        )


class LLMProvider(BaseModel):
    name: str
    provider: str
    api_key: str | None = None
    api_base: str | None = None
    api_version: str | None = None
    custom_config: dict[str, str] | None = None
    default_model_name: str
    fast_default_model_name: str | None = None
    is_public: bool = True
    groups: list[int] = Field(default_factory=list)
    deployment_name: str | None = None
    default_vision_model: str | None = None


class LLMProviderUpsertRequest(LLMProvider):
    # should only be used for a "custom" provider
    # for default providers, the built-in model names are used
    api_key_changed: bool = False
    model_configurations: list["ModelConfigurationUpsertRequest"] = []

    @field_validator("provider", mode="before")
    @classmethod
    def normalize_provider(cls, value: str) -> str:
        """Normalize provider name by stripping whitespace and lowercasing."""
        return value.strip().lower()


class LLMProviderView(LLMProvider):
    """Stripped down representation of LLMProvider for display / limited access info only"""

    id: int
    is_default_provider: bool | None = None
    is_default_vision_provider: bool | None = None
    model_configurations: list["ModelConfigurationView"]

    @classmethod
    def from_model(
        cls,
        llm_provider_model: "LLMProviderModel",
    ) -> "LLMProviderView":
        # Safely get groups - handle detached instance case
        try:
            groups = [group.id for group in llm_provider_model.groups]
        except Exception:
            # If groups relationship can't be loaded (detached instance), use empty list
            groups = []

        return cls(
            id=llm_provider_model.id,
            name=llm_provider_model.name,
            provider=llm_provider_model.provider,
            api_key=llm_provider_model.api_key,
            api_base=llm_provider_model.api_base,
            api_version=llm_provider_model.api_version,
            custom_config=llm_provider_model.custom_config,
            default_model_name=llm_provider_model.default_model_name,
            fast_default_model_name=llm_provider_model.fast_default_model_name,
            is_default_provider=llm_provider_model.is_default_provider,
            is_default_vision_provider=llm_provider_model.is_default_vision_provider,
            default_vision_model=llm_provider_model.default_vision_model,
            is_public=llm_provider_model.is_public,
            groups=groups,
            deployment_name=llm_provider_model.deployment_name,
            model_configurations=list(
                ModelConfigurationView.from_model(
                    model_configuration, llm_provider_model.provider
                )
                for model_configuration in llm_provider_model.model_configurations
            ),
        )


class ModelConfigurationUpsertRequest(BaseModel):
    name: str
    is_visible: bool
    max_input_tokens: int | None = None
    supports_image_input: bool | None = None

    @classmethod
    def from_model(
        cls, model_configuration_model: "ModelConfigurationModel"
    ) -> "ModelConfigurationUpsertRequest":
        return cls(
            name=model_configuration_model.name,
            is_visible=model_configuration_model.is_visible,
            max_input_tokens=model_configuration_model.max_input_tokens,
            supports_image_input=model_configuration_model.supports_image_input,
        )


class ModelConfigurationView(BaseModel):
    name: str
    is_visible: bool
    max_input_tokens: int | None = None
    supports_image_input: bool

    @classmethod
    def from_model(
        cls,
        model_configuration_model: "ModelConfigurationModel",
        provider_name: str,
    ) -> "ModelConfigurationView":
        return cls(
            name=model_configuration_model.name,
            is_visible=model_configuration_model.is_visible,
            max_input_tokens=model_configuration_model.max_input_tokens
            or get_max_input_tokens(
                model_name=model_configuration_model.name, model_provider=provider_name
            ),
            supports_image_input=model_supports_image_input(
                model_name=model_configuration_model.name,
                model_provider=provider_name,
            ),
        )


class VisionProviderResponse(LLMProviderView):
    """Response model for vision providers endpoint, including vision-specific fields."""

    vision_models: list[str]


class LLMCost(BaseModel):
    provider: str
    model_name: str
    cost: float


class BedrockModelsRequest(BaseModel):
    aws_region_name: str
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_bearer_token_bedrock: str | None = None
    provider_name: str | None = None  # Optional: to save models to existing provider


class OllamaModelsRequest(BaseModel):
    api_base: str


class OllamaFinalModelResponse(BaseModel):
    name: str
    max_input_tokens: int
    supports_image_input: bool


class OllamaModelDetails(BaseModel):
    """Response model for Ollama /api/show endpoint"""

    model_info: dict[str, Any]
    capabilities: list[str] = []

    def supports_completion(self) -> bool:
        """Check if this model supports completion/chat"""
        return "completion" in self.capabilities

    def supports_image_input(self) -> bool:
        """Check if this model supports image input"""
        return "vision" in self.capabilities


# OpenRouter dynamic models fetch
class OpenRouterModelsRequest(BaseModel):
    api_base: str
    api_key: str


class OpenRouterModelDetails(BaseModel):
    """Response model for OpenRouter /api/v1/models endpoint"""

    # This is used to ignore any extra fields that are returned from the API
    model_config = {"extra": "ignore"}

    id: str
    context_length: int
    architecture: dict[str, Any]  # Contains 'input_modalities' key

    @property
    def supports_image_input(self) -> bool:
        input_modalities = self.architecture.get("input_modalities", [])
        return isinstance(input_modalities, list) and "image" in input_modalities

    @property
    def is_embedding_model(self) -> bool:
        output_modalities = self.architecture.get("output_modalities", [])
        return isinstance(output_modalities, list) and "embeddings" in output_modalities


class OpenRouterFinalModelResponse(BaseModel):
    name: str
    max_input_tokens: int
    supports_image_input: bool
