from __future__ import annotations

from pydantic import BaseModel
from pydantic import ConfigDict

from onyx.configs.app_configs import CONSUMER_DEFAULT_LLM_DEFAULT_PROFILE
from onyx.configs.app_configs import CONSUMER_DEFAULT_LLM_PROVIDER_NAME
from onyx.configs.app_configs import CONSUMER_DEFAULT_LLM_PROVIDER_TYPE
from onyx.llm.override_models import LLMOverride

DEFAULT_CONSUMER_MODEL_PROFILE_ID = "balanced"
DEEP_RESEARCH_CONSUMER_MODEL_PROFILE_ID = "deep"
CRAFT_CONSUMER_MODEL_PROFILE_ID = "coding"
TITLE_CONSUMER_MODEL_PROFILE_ID = "fast"


class ConsumerModelProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    label: str
    description: str
    display_name: str
    provider_name: str
    provider_type: str
    model_name: str
    supports_image: bool = False
    temperature: float
    max_tokens: int


class PublicConsumerModelProfile(BaseModel):
    id: str
    label: str
    description: str
    supports_image: bool = False


class ConsumerModelCatalogResponse(BaseModel):
    default_profile_id: str
    profiles: list[PublicConsumerModelProfile]


CONSUMER_MODEL_PROFILES: tuple[ConsumerModelProfile, ...] = (
    ConsumerModelProfile(
        id="fast",
        label="快速",
        description="适合日常问答，响应更快",
        display_name="Qwen Turbo",
        provider_name=CONSUMER_DEFAULT_LLM_PROVIDER_NAME,
        provider_type=CONSUMER_DEFAULT_LLM_PROVIDER_TYPE,
        model_name="qwen-turbo",
        temperature=0.7,
        max_tokens=2048,
    ),
    ConsumerModelProfile(
        id="balanced",
        label="均衡",
        description="默认推荐，质量和速度平衡",
        display_name="Qwen Plus",
        provider_name=CONSUMER_DEFAULT_LLM_PROVIDER_NAME,
        provider_type=CONSUMER_DEFAULT_LLM_PROVIDER_TYPE,
        model_name="qwen-plus",
        temperature=0.5,
        max_tokens=4096,
    ),
    ConsumerModelProfile(
        id="deep",
        label="深度",
        description="适合复杂推理和长内容分析",
        display_name="Qwen Max",
        provider_name=CONSUMER_DEFAULT_LLM_PROVIDER_NAME,
        provider_type=CONSUMER_DEFAULT_LLM_PROVIDER_TYPE,
        model_name="qwen-max",
        temperature=0.3,
        max_tokens=8192,
    ),
    ConsumerModelProfile(
        id="coding",
        label="编程",
        description="适合代码生成、调试和 Craft 任务",
        display_name="Qwen Coder",
        provider_name=CONSUMER_DEFAULT_LLM_PROVIDER_NAME,
        provider_type=CONSUMER_DEFAULT_LLM_PROVIDER_TYPE,
        model_name="qwen3-coder-plus",
        temperature=0.2,
        max_tokens=8192,
    ),
    ConsumerModelProfile(
        id="vision",
        label="多模态",
        description="适合图片理解和图文问答",
        display_name="Qwen Vision",
        provider_name=CONSUMER_DEFAULT_LLM_PROVIDER_NAME,
        provider_type=CONSUMER_DEFAULT_LLM_PROVIDER_TYPE,
        model_name="qwen-vl-plus",
        supports_image=True,
        temperature=0.4,
        max_tokens=4096,
    ),
)

_PROFILES_BY_ID = {profile.id: profile for profile in CONSUMER_MODEL_PROFILES}


def resolve_consumer_model_profile_id(profile_id: str | None) -> str:
    if profile_id in _PROFILES_BY_ID:
        return profile_id

    if CONSUMER_DEFAULT_LLM_DEFAULT_PROFILE in _PROFILES_BY_ID:
        return CONSUMER_DEFAULT_LLM_DEFAULT_PROFILE

    return DEFAULT_CONSUMER_MODEL_PROFILE_ID


def get_consumer_model_profile(profile_id: str | None) -> ConsumerModelProfile:
    resolved_profile_id = resolve_consumer_model_profile_id(profile_id)
    return _PROFILES_BY_ID[resolved_profile_id]


def get_default_consumer_model_profile() -> ConsumerModelProfile:
    return get_consumer_model_profile(None)


def get_consumer_model_catalog_response() -> ConsumerModelCatalogResponse:
    return ConsumerModelCatalogResponse(
        default_profile_id=resolve_consumer_model_profile_id(None),
        profiles=[
            PublicConsumerModelProfile(
                id=profile.id,
                label=profile.label,
                description=profile.description,
                supports_image=profile.supports_image,
            )
            for profile in CONSUMER_MODEL_PROFILES
        ],
    )


def profile_to_user_default_model(profile: ConsumerModelProfile) -> str:
    return f"{profile.display_name}__{profile.provider_type}__{profile.model_name}"


def profile_to_llm_override(profile: ConsumerModelProfile) -> LLMOverride:
    return LLMOverride(
        model_provider=profile.provider_name,
        model_version=profile.model_name,
        temperature=profile.temperature,
        display_name=profile.display_name,
    )


def resolve_single_model_profile_id(
    user_default_model: str | None,
    is_deep_research: bool,
) -> str:
    if is_deep_research:
        return resolve_consumer_model_profile_id(DEEP_RESEARCH_CONSUMER_MODEL_PROFILE_ID)

    return resolve_profile_id_from_user_default_model(user_default_model)


def resolve_profile_id_from_user_default_model(default_model: str | None) -> str:
    if not default_model:
        return resolve_consumer_model_profile_id(None)

    parts = default_model.split("__")
    if len(parts) != 3:
        return resolve_consumer_model_profile_id(None)

    _display_name, provider_type, model_name = parts
    for profile in CONSUMER_MODEL_PROFILES:
        if profile.provider_type == provider_type and profile.model_name == model_name:
            return profile.id

    return resolve_consumer_model_profile_id(None)
