from typing import TYPE_CHECKING

from pydantic import BaseModel
from pydantic import Field


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
    model_configurations: list["ModelConfiguration"]

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
                map(
                    ModelConfiguration.from_model,
                    llm_provider_model.model_configurations,
                )
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
    model_configurations: list["ModelConfiguration"] = []


class LLMProviderView(LLMProvider):
    """Stripped down representation of LLMProvider for display / limited access info only"""

    id: int
    is_default_provider: bool | None = None
    is_default_vision_provider: bool | None = None
    model_configurations: list["ModelConfiguration"]

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
                map(
                    ModelConfiguration.from_model,
                    llm_provider_model.model_configurations,
                )
            ),
        )


class ModelConfiguration(BaseModel):
    name: str
    is_visible: bool | None = False
    max_input_tokens: int | None = None

    @classmethod
    def from_model(
        cls, model_configuration_model: "ModelConfigurationModel"
    ) -> "ModelConfiguration":
        return cls(
            name=model_configuration_model.name,
            is_visible=model_configuration_model.is_visible,
            max_input_tokens=model_configuration_model.max_input_tokens,
        )


class VisionProviderResponse(LLMProviderView):
    """Response model for vision providers endpoint, including vision-specific fields."""

    vision_models: list[str]


class LLMCost(BaseModel):
    provider: str
    model_name: str
    cost: float
