import re
from typing import Any
from typing import TYPE_CHECKING

from pydantic import BaseModel
from pydantic import Field
from pydantic import field_validator

from onyx.llm.utils import get_max_input_tokens
from onyx.llm.utils import litellm_thinks_model_supports_image_input
from onyx.llm.utils import model_is_reasoning_model
from onyx.server.manage.llm.utils import is_reasoning_model


def _is_obsolete_model(model_name: str, provider: str) -> bool:
    """Check if a model is obsolete and should be filtered out.

    Filters models that are 2+ major versions behind or deprecated.
    """
    model_lower = model_name.lower()

    # OpenAI obsolete models
    if provider == "openai":
        # GPT-3 (not 3.5) is obsolete
        if "gpt-3" in model_lower and "gpt-3.5" not in model_lower:
            return True
        # Legacy models
        if any(
            m in model_lower
            for m in [
                "text-davinci",
                "text-curie",
                "text-babbage",
                "text-ada",
                "davinci",
                "curie",
                "babbage",
                "ada",
            ]
        ):
            return True

    # Anthropic obsolete models
    if provider == "anthropic":
        if "claude-2" in model_lower or "claude-instant" in model_lower:
            return True

    # Vertex AI obsolete models
    if provider == "vertex_ai":
        if "gemini-1.0" in model_lower:
            return True
        if "palm" in model_lower or "bison" in model_lower:
            return True

    return False


def _extract_base_model_name(model: str) -> str | None:
    """Extract base model name by removing date suffixes.

    Returns None if no date suffix was found.
    """
    patterns = [
        r"-\d{8}$",  # -20250929
        r"-\d{4}-\d{2}-\d{2}$",  # -2024-08-06
        r"@\d{8}$",  # @20250219
    ]
    for pattern in patterns:
        if re.search(pattern, model):
            return re.sub(pattern, "", model)
    return None


def _should_filter_as_dated_duplicate(
    model_name: str, all_model_names: set[str]
) -> bool:
    """Check if this model is a dated variant and a non-dated version exists."""
    base = _extract_base_model_name(model_name)
    if base and base in all_model_names:
        return True
    return False


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
    provider_display_name: str  # Human-friendly name like "Claude (Anthropic)"
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
        from onyx.llm.llm_provider_options import get_provider_display_name

        provider = llm_provider_model.provider

        # Get all model names for deduplication check
        all_model_names = {mc.name for mc in llm_provider_model.model_configurations}

        # Filter out obsolete and duplicate models
        filtered_configs = []
        for model_configuration in llm_provider_model.model_configurations:
            # Skip obsolete models
            if _is_obsolete_model(model_configuration.name, provider):
                continue
            # Skip dated duplicates when non-dated version exists
            if _should_filter_as_dated_duplicate(
                model_configuration.name, all_model_names
            ):
                continue
            filtered_configs.append(
                ModelConfigurationView.from_model(model_configuration, provider)
            )

        return cls(
            name=llm_provider_model.name,
            provider=provider,
            provider_display_name=get_provider_display_name(provider),
            default_model_name=llm_provider_model.default_model_name,
            fast_default_model_name=llm_provider_model.fast_default_model_name,
            is_default_provider=llm_provider_model.is_default_provider,
            is_default_vision_provider=llm_provider_model.is_default_vision_provider,
            default_vision_model=llm_provider_model.default_vision_model,
            model_configurations=filtered_configs,
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

        # Get all model names for deduplication check
        all_model_names = {mc.name for mc in llm_provider_model.model_configurations}

        # Filter out obsolete and duplicate models
        filtered_configs = []
        for model_configuration in llm_provider_model.model_configurations:
            # Skip obsolete models
            if _is_obsolete_model(model_configuration.name, provider):
                continue
            # Skip dated duplicates when non-dated version exists
            if _should_filter_as_dated_duplicate(
                model_configuration.name, all_model_names
            ):
                continue
            filtered_configs.append(
                ModelConfigurationView.from_model(model_configuration, provider)
            )

        return cls(
            id=llm_provider_model.id,
            name=llm_provider_model.name,
            provider=provider,
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
            personas=personas,
            deployment_name=llm_provider_model.deployment_name,
            model_configurations=filtered_configs,
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


# Dynamic providers fetch models directly from source APIs (not LiteLLM)
DYNAMIC_LLM_PROVIDERS = {"openrouter", "bedrock", "ollama_chat"}


def _extract_vendor_from_model_name(model_name: str, provider: str) -> str | None:
    """Extract vendor from model name for aggregator providers.

    Examples:
        - OpenRouter: "anthropic/claude-3-5-sonnet" → "Anthropic"
        - Bedrock: "anthropic.claude-3-5-sonnet-..." → "Anthropic"
        - Bedrock: "us.anthropic.claude-..." → "Anthropic"
        - Ollama: "llama3:70b" → "Meta"
        - Ollama: "qwen2.5:7b" → "Alibaba"
    """
    from onyx.llm.constants import OLLAMA_MODEL_TO_VENDOR
    from onyx.llm.constants import PROVIDER_DISPLAY_NAMES

    if provider == "openrouter":
        # Format: "vendor/model-name" e.g., "anthropic/claude-3-5-sonnet"
        if "/" in model_name:
            vendor_key = model_name.split("/")[0].lower()
            return PROVIDER_DISPLAY_NAMES.get(vendor_key, vendor_key.title())

    elif provider == "bedrock":
        # Format: "vendor.model-name" or "region.vendor.model-name"
        parts = model_name.split(".")
        if len(parts) >= 2:
            # Check if first part is a region (us, eu, global, etc.)
            if parts[0] in ("us", "eu", "global", "ap", "apac"):
                vendor_key = parts[1].lower() if len(parts) > 2 else parts[0].lower()
            else:
                vendor_key = parts[0].lower()
            return PROVIDER_DISPLAY_NAMES.get(vendor_key, vendor_key.title())

    elif provider == "ollama_chat":
        # Format: "model-name:tag" e.g., "llama3:70b", "qwen2.5:7b"
        # Extract base name (before colon)
        base_name = model_name.split(":")[0].lower()
        # Match against known model prefixes
        for prefix, vendor in OLLAMA_MODEL_TO_VENDOR.items():
            if base_name.startswith(prefix):
                return vendor
        # Fallback: capitalize the base name as vendor
        return base_name.split("-")[0].title()

    return None


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
            vendor = _extract_vendor_from_model_name(
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
    max_input_tokens: int  # From LiteLLM, our mapping, or default 4096
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
