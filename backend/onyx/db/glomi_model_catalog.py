from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from typing import Literal

from sqlalchemy.orm import Session

from onyx.configs.app_configs import CONSUMER_DEFAULT_LLM_API_BASE
from onyx.configs.app_configs import CONSUMER_DEFAULT_LLM_API_KEY
from onyx.configs.app_configs import CONSUMER_DEFAULT_LLM_ENABLED
from onyx.configs.app_configs import CONSUMER_DEFAULT_LLM_PROVIDER_NAME
from onyx.configs.app_configs import CONSUMER_DEFAULT_LLM_PROVIDER_TYPE
from onyx.db.llm import fetch_default_llm_model
from onyx.db.llm import fetch_existing_llm_provider_by_name_and_type
from onyx.db.llm import update_default_provider
from onyx.db.llm import upsert_llm_provider
from onyx.server.manage.llm.models import LLMProviderUpsertRequest
from onyx.server.manage.llm.models import ModelConfigurationUpsertRequest
from onyx.utils.logger import setup_logger

logger = setup_logger()

GlomiModelRole = Literal[
    "fast",
    "balanced",
    "reasoning",
    "research",
    "vision",
    "coding",
]


@dataclass(frozen=True)
class GlomiPlatformModel:
    model_name: str
    display_name: str
    supports_image_input: bool
    supports_reasoning: bool
    roles: tuple[GlomiModelRole, ...]
    is_default: bool = False


@dataclass(frozen=True)
class GlomiPlatformModelCatalog:
    provider_name: str
    provider_type: str
    api_base: str | None
    api_key: str | None
    enabled: bool
    models: tuple[GlomiPlatformModel, ...]


@dataclass(frozen=True)
class GlomiModelCatalogSyncResult:
    synced: bool
    reason: str
    model_count: int = 0


GLOMI_PLATFORM_MODELS: tuple[GlomiPlatformModel, ...] = (
    GlomiPlatformModel(
        model_name="gpt-5.5",
        display_name="GPT-5.5",
        supports_image_input=True,
        supports_reasoning=True,
        roles=("balanced", "reasoning", "research", "vision", "coding"),
        is_default=True,
    ),
    GlomiPlatformModel(
        model_name="qwen3.7-plus",
        display_name="Qwen3.7 Plus",
        supports_image_input=True,
        supports_reasoning=True,
        roles=("balanced", "reasoning", "research", "vision"),
    ),
    GlomiPlatformModel(
        model_name="deepseek-v4-pro",
        display_name="DeepSeek V4 Pro",
        supports_image_input=False,
        supports_reasoning=True,
        roles=("reasoning", "research"),
    ),
    GlomiPlatformModel(
        model_name="glm-5.2",
        display_name="GLM-5.2",
        supports_image_input=False,
        supports_reasoning=True,
        roles=("reasoning", "research", "coding"),
    ),
)


def get_glomi_platform_model_catalog() -> GlomiPlatformModelCatalog:
    return GlomiPlatformModelCatalog(
        provider_name=CONSUMER_DEFAULT_LLM_PROVIDER_NAME,
        provider_type=CONSUMER_DEFAULT_LLM_PROVIDER_TYPE,
        api_base=CONSUMER_DEFAULT_LLM_API_BASE,
        api_key=CONSUMER_DEFAULT_LLM_API_KEY,
        enabled=CONSUMER_DEFAULT_LLM_ENABLED,
        models=GLOMI_PLATFORM_MODELS,
    )


def _default_model_name(models: tuple[GlomiPlatformModel, ...]) -> str:
    for model in models:
        if model.is_default:
            return model.model_name
    return models[0].model_name


def _build_provider_request(
    catalog: GlomiPlatformModelCatalog,
) -> LLMProviderUpsertRequest:
    return LLMProviderUpsertRequest(
        name=catalog.provider_name,
        provider=catalog.provider_type,
        api_key=catalog.api_key,
        api_base=catalog.api_base,
        api_key_changed=True,
        is_public=True,
        is_auto_mode=False,
        model_configurations=[
            ModelConfigurationUpsertRequest(
                name=model.model_name,
                is_visible=True,
                max_input_tokens=None,
                supports_image_input=model.supports_image_input,
                supports_reasoning=model.supports_reasoning,
                display_name=model.display_name,
                custom_display_name=None,
            )
            for model in catalog.models
        ],
    )


def _existing_provider_api_key(existing_provider: Any) -> str | None:
    api_key = getattr(existing_provider, "api_key", None)
    if api_key is None:
        return None
    if hasattr(api_key, "get_value"):
        return api_key.get_value(apply_mask=False)
    return str(api_key)


def _preserve_existing_provider_settings(
    request: LLMProviderUpsertRequest,
    existing_provider: Any,
) -> None:
    request.id = existing_provider.id
    request.api_key = _existing_provider_api_key(existing_provider)
    request.api_base = existing_provider.api_base
    request.api_version = existing_provider.api_version
    request.custom_config = existing_provider.custom_config
    request.deployment_name = existing_provider.deployment_name
    request.api_key_changed = False

    catalog_model_names = {model.name for model in request.model_configurations}
    for existing_model_config in existing_provider.model_configurations:
        if existing_model_config.name in catalog_model_names:
            continue
        request.model_configurations.append(
            ModelConfigurationUpsertRequest.from_model(existing_model_config)
        )


def sync_glomi_platform_model_catalog(
    db_session: Session,
    catalog: GlomiPlatformModelCatalog | None = None,
) -> GlomiModelCatalogSyncResult:
    catalog = catalog or get_glomi_platform_model_catalog()
    if not catalog.enabled:
        return GlomiModelCatalogSyncResult(synced=False, reason="disabled")
    if not catalog.api_key:
        return GlomiModelCatalogSyncResult(synced=False, reason="missing_api_key")
    if not catalog.api_base:
        return GlomiModelCatalogSyncResult(synced=False, reason="missing_api_base")
    if not catalog.models:
        return GlomiModelCatalogSyncResult(synced=False, reason="missing_models")

    request = _build_provider_request(catalog)
    existing_provider = fetch_existing_llm_provider_by_name_and_type(
        name=catalog.provider_name,
        provider_type=catalog.provider_type,
        db_session=db_session,
    )
    if existing_provider:
        _preserve_existing_provider_settings(request, existing_provider)

    provider = upsert_llm_provider(request, db_session)
    current_default = fetch_default_llm_model(db_session)
    if current_default is None:
        update_default_provider(provider.id, _default_model_name(catalog.models), db_session)

    logger.info(
        "Synced Glomi platform model catalog with %d models",
        len(catalog.models),
    )
    return GlomiModelCatalogSyncResult(
        synced=True,
        reason="synced",
        model_count=len(catalog.models),
    )
