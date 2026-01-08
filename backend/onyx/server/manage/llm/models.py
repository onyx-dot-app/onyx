from typing import Any
from typing import TYPE_CHECKING

from pydantic import BaseModel
from pydantic import Field
from pydantic import field_validator

from onyx.llm.utils import get_max_input_tokens
from onyx.llm.utils import litellm_thinks_model_supports_image_input
from onyx.llm.utils import model_is_reasoning_model
from onyx.server.manage.llm.utils import DYNAMIC_LLM_PROVIDERS
from onyx.server.manage.llm.utils import extract_vendor_from_model_name
from onyx.server.manage.llm.utils import filter_model_configurations
from onyx.server.manage.llm.utils import is_reasoning_model


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
    provider_display_name: str  # Human-friendly name like "Claude (Anthropic)"
    default_model_name: str
    is_default_provider: bool | None
    is_default_vision_provider: bool | None
    default_vision_model: str | None
    model_configurations: list["ModelConfigurationView"]

    @classmethod
    def from_model(
        cls,
        llm_provider_model: "LLMProviderModel",
    ) -> "LLMProviderDescriptor":
        from onyx.llm.well_known_providers.llm_provider_options import (
            get_provider_display_name,
        )

        provider = llm_provider_model.provider

        return cls(
            name=llm_provider_model.name,
            provider=provider,
            provider_display_name=get_provider_display_name(provider),
            default_model_name=llm_provider_model.default_model_name,
            is_default_provider=llm_provider_model.is_default_provider,
            is_default_vision_provider=llm_provider_model.is_default_vision_provider,
            default_vision_model=llm_provider_model.default_vision_model,
            model_configurations=filter_model_configurations(
                llm_provider_model.model_configurations, provider
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
    is_public: bool = True
    is_auto_mode: bool = False
    groups: list[int] = Field(default_factory=list)
    personas: list[int] = Field(default_factory=list)
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
        # Safely get personas - similar handling as groups
        try:
            personas = [persona.id for persona in llm_provider_model.personas]
        except Exception:
            personas = []

        provider = llm_provider_model.provider

        return cls(
            id=llm_provider_model.id,
            name=llm_provider_model.name,
            provider=provider,
            api_key=llm_provider_model.api_key,
            api_base=llm_provider_model.api_base,
            api_version=llm_provider_model.api_version,
            custom_config=llm_provider_model.custom_config,
            default_model_name=llm_provider_model.default_model_name,
            is_default_provider=llm_provider_model.is_default_provider,
            is_default_vision_provider=llm_provider_model.is_default_vision_provider,
            default_vision_model=llm_provider_model.default_vision_model,
            is_public=llm_provider_model.is_public,
            is_auto_mode=llm_provider_model.is_auto_mode,
            groups=groups,
            personas=personas,
            deployment_name=llm_provider_model.deployment_name,
            model_configurations=filter_model_configurations(
                llm_provider_model.model_configurations, provider
            ),
        )


class ModelConfigurationUpsertRequest(BaseModel):
    name: str
    is_visible: bool
    max_input_tokens: int | None = None
    supports_image_input: bool | None = None
    display_name: str | None = None  # For dynamic providers, from source API

    @classmethod
    def from_model(
        cls, model_configuration_model: "ModelConfigurationModel"
    ) -> "ModelConfigurationUpsertRequest":
        return cls(
            name=model_configuration_model.name,
            is_visible=model_configuration_model.is_visible,
            max_input_tokens=model_configuration_model.max_input_tokens,
            supports_image_input=model_configuration_model.supports_image_input,
            display_name=model_configuration_model.display_name,
        )


class ModelConfigurationView(BaseModel):
    name: str
    is_visible: bool
    max_input_tokens: int | None = None
    supports_image_input: bool
    supports_reasoning: bool = False
    display_name: str | None = None
    provider_display_name: str | None = None
    vendor: str | None = None
    version: str | None = None
    region: str | None = None

    @classmethod
    def from_model(
        cls,
        model_configuration_model: "ModelConfigurationModel",
        provider_name: str,
    ) -> "ModelConfigurationView":
        # For dynamic providers (OpenRouter, Bedrock, Ollama), use the display_name
        # stored in DB from the source API. Skip LiteLLM parsing entirely.
        if (
            provider_name in DYNAMIC_LLM_PROVIDERS
            and model_configuration_model.display_name
        ):
            # Extract vendor from model name for grouping (e.g., "Anthropic", "OpenAI")
            vendor = extract_vendor_from_model_name(
                model_configuration_model.name, provider_name
            )

            return cls(
                name=model_configuration_model.name,
                is_visible=model_configuration_model.is_visible,
                max_input_tokens=model_configuration_model.max_input_tokens,
                supports_image_input=(
                    model_configuration_model.supports_image_input or False
                ),
                # Infer reasoning support from model name/display name
                supports_reasoning=is_reasoning_model(
                    model_configuration_model.name,
                    model_configuration_model.display_name or "",
                ),
                display_name=model_configuration_model.display_name,
                provider_display_name=None,  # Not needed for dynamic providers
                vendor=vendor,
                version=None,
                region=None,
            )

        # For static providers (OpenAI, Anthropic, etc.), use LiteLLM enrichments
        from onyx.llm.model_name_parser import parse_litellm_model_name

        # Parse the model name to get display information
        # Include provider prefix if not already present (enrichments use full keys like "vertex_ai/...")
        model_name = model_configuration_model.name
        if provider_name and not model_name.startswith(f"{provider_name}/"):
            model_name = f"{provider_name}/{model_name}"
        parsed = parse_litellm_model_name(model_name)

        # Include region in display name for Bedrock cross-region models
        display_name = (
            f"{parsed.display_name} ({parsed.region})"
            if parsed.region
            else parsed.display_name
        )

        return cls(
            name=model_configuration_model.name,
            is_visible=model_configuration_model.is_visible,
            max_input_tokens=(
                model_configuration_model.max_input_tokens
                or get_max_input_tokens(
                    model_name=model_configuration_model.name,
                    model_provider=provider_name,
                )
            ),
            supports_image_input=(
                val
                if (val := model_configuration_model.supports_image_input) is not None
                else litellm_thinks_model_supports_image_input(
                    model_configuration_model.name, provider_name
                )
            ),
            supports_reasoning=model_is_reasoning_model(
                model_configuration_model.name, provider_name
            ),
            # Populate display fields from parsed model name
            display_name=display_name,
            provider_display_name=parsed.provider_display_name,
            vendor=parsed.vendor,
            version=parsed.version,
            region=parsed.region,
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


class BedrockFinalModelResponse(BaseModel):
    name: str  # Model ID (e.g., "anthropic.claude-3-5-sonnet-20241022-v2:0")
    display_name: str  # Human-readable name from AWS (e.g., "Claude 3.5 Sonnet v2")
    max_input_tokens: int  # From LiteLLM, our mapping, or default 32000
    supports_image_input: bool


class OllamaModelsRequest(BaseModel):
    api_base: str
    provider_name: str | None = None  # Optional: to save models to existing provider


class OllamaFinalModelResponse(BaseModel):
    name: str
    display_name: str  # Generated from model name (e.g., "llama3:7b" → "Llama 3 7B")
    max_input_tokens: int | None  # From Ollama API or None if unavailable
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
    provider_name: str | None = None  # Optional: to save models to existing provider


class OpenRouterModelDetails(BaseModel):
    """Response model for OpenRouter /api/v1/models endpoint"""

    # This is used to ignore any extra fields that are returned from the API
    model_config = {"extra": "ignore"}

    id: str
    # OpenRouter API returns "name" but we use "display_name" for consistency
    display_name: str = Field(alias="name")
    # context_length may be missing or 0 for some models
    context_length: int | None = None
    architecture: dict[str, Any] = {}  # Contains 'input_modalities' key

    @property
    def supports_image_input(self) -> bool:
        input_modalities = self.architecture.get("input_modalities", [])
        return isinstance(input_modalities, list) and "image" in input_modalities

    @property
    def is_embedding_model(self) -> bool:
        output_modalities = self.architecture.get("output_modalities", [])
        return isinstance(output_modalities, list) and "embeddings" in output_modalities


class OpenRouterFinalModelResponse(BaseModel):
    name: str  # Model ID (e.g., "openai/gpt-5-pro")
    display_name: str  # Human-readable name from OpenRouter API
    max_input_tokens: (
        int | None
    )  # From OpenRouter API context_length (may be missing for some models)
    supports_image_input: bool
