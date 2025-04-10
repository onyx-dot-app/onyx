from typing import TYPE_CHECKING

from pydantic import BaseModel
from pydantic import Field

from onyx.llm.llm_provider_options import fetch_models_for_provider
from onyx.llm.utils import get_max_input_tokens


if TYPE_CHECKING:
    from onyx.db.models import LLMProvider as LLMProviderModel


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
    model_names: list[str]
    default_model_name: str
    fast_default_model_name: str | None
    is_default_provider: bool | None
    is_default_vision_provider: bool | None
    default_vision_model: str | None
    display_model_names: list[str] | None
    model_token_limits: dict[str, int] | None = None

    @classmethod
    def from_model(
        cls, llm_provider_model: "LLMProviderModel"
    ) -> "LLMProviderDescriptor":
        import time

        start_time = time.time()

        model_names = (
            llm_provider_model.model_names
            or fetch_models_for_provider(llm_provider_model.provider)
            or [llm_provider_model.default_model_name]
        )

        model_token_rate = (
            {
                model_name: get_max_input_tokens(
                    model_name, llm_provider_model.provider
                )
                for model_name in model_names
            }
            if model_names is not None
            else None
        )

        result = cls(
            name=llm_provider_model.name,
            provider=llm_provider_model.provider,
            default_model_name=llm_provider_model.default_model_name,
            fast_default_model_name=llm_provider_model.fast_default_model_name,
            is_default_provider=llm_provider_model.is_default_provider,
            model_names=model_names,
            model_token_limits=model_token_rate,
            is_default_vision_provider=llm_provider_model.is_default_vision_provider,
            default_vision_model=llm_provider_model.default_vision_model,
            display_model_names=llm_provider_model.display_model_names,
        )

        time.time() - start_time

        return result


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
    display_model_names: list[str] | None = None
    deployment_name: str | None = None
    default_vision_model: str | None = None


class LLMProviderUpsertRequest(LLMProvider):
    # should only be used for a "custom" provider
    # for default providers, the built-in model names are used
    model_names: list[str] | None = None
    api_key_changed: bool = False


class LLMProviderView(LLMProvider):
    """Stripped down representation of LLMProvider for display / limited access info only"""

    id: int
    is_default_provider: bool | None = None
    is_default_vision_provider: bool | None = None
    model_names: list[str]
    model_token_limits: dict[str, int] | None = None

    @classmethod
    def from_model(cls, llm_provider_model: "LLMProviderModel") -> "LLMProviderView":
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
            display_model_names=llm_provider_model.display_model_names,
            model_names=(
                llm_provider_model.model_names
                or fetch_models_for_provider(llm_provider_model.provider)
                or [llm_provider_model.default_model_name]
            ),
            model_token_limits=(
                {
                    model_name: get_max_input_tokens(
                        model_name, llm_provider_model.provider
                    )
                    for model_name in llm_provider_model.model_names
                }
                if llm_provider_model.model_names is not None
                else None
            ),
            is_public=llm_provider_model.is_public,
            groups=[group.id for group in llm_provider_model.groups],
            deployment_name=llm_provider_model.deployment_name,
        )


class VisionProviderResponse(LLMProviderView):
    """Response model for vision providers endpoint, including vision-specific fields."""

    vision_models: list[str]


class LLMCost(BaseModel):
    provider: str
    model_name: str
    cost: float
