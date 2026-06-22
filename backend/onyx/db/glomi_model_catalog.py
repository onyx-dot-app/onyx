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
from onyx.configs.app_configs import GLOMI_MINIMAX_LLM_API_BASE
from onyx.configs.app_configs import GLOMI_MINIMAX_LLM_API_KEY
from onyx.configs.app_configs import GLOMI_MINIMAX_LLM_ENABLED
from onyx.configs.app_configs import GLOMI_MINIMAX_LLM_MODEL_NAMES
from onyx.configs.app_configs import GLOMI_MINIMAX_LLM_PROVIDER_NAME
from onyx.configs.app_configs import GLOMI_MINIMAX_LLM_PROVIDER_TYPE
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
class GlomiSupplierMetadata:
    supplier_id: str
    supplier_display_name: str


@dataclass(frozen=True)
class GlomiPlatformProviderCatalog:
    provider_name: str
    provider_type: str
    supplier_id: str
    supplier_display_name: str
    api_base: str | None
    api_key: str | None
    enabled: bool
    models: tuple[GlomiPlatformModel, ...]


@dataclass(frozen=True)
class GlomiPlatformModelCatalog:
    enabled: bool
    providers: tuple[GlomiPlatformProviderCatalog, ...]


@dataclass(frozen=True)
class GlomiModelCatalogSyncResult:
    synced: bool
    reason: str
    model_count: int = 0


GLOMI_GPT_SUPPLIER_ID = "gpt"
GLOMI_MINIMAX_SUPPLIER_ID = "minimax"

GLOMI_GPT_PLATFORM_MODELS: tuple[GlomiPlatformModel, ...] = (
    GlomiPlatformModel(
        model_name="gpt-5.5",
        display_name="GPT-5.5",
        supports_image_input=True,
        supports_reasoning=True,
        roles=("balanced", "reasoning", "research", "vision", "coding"),
        is_default=True,
    ),
)

GLOMI_MINIMAX_PLATFORM_MODELS: tuple[GlomiPlatformModel, ...] = (
    GlomiPlatformModel(
        model_name="MiniMax-M3",
        display_name="MiniMax-M3",
        supports_image_input=True,
        supports_reasoning=True,
        roles=("balanced", "reasoning", "research", "vision", "coding"),
    ),
)

# Backward-compatible aggregate used by model-role lookup paths.
GLOMI_PLATFORM_MODELS: tuple[GlomiPlatformModel, ...] = (
    *GLOMI_GPT_PLATFORM_MODELS,
    *GLOMI_MINIMAX_PLATFORM_MODELS,
)

_SUPPLIER_METADATA_BY_PROVIDER: dict[tuple[str, str], GlomiSupplierMetadata] = {
    (
        CONSUMER_DEFAULT_LLM_PROVIDER_NAME,
        CONSUMER_DEFAULT_LLM_PROVIDER_TYPE,
    ): GlomiSupplierMetadata(
        supplier_id=GLOMI_GPT_SUPPLIER_ID,
        supplier_display_name="GPT",
    ),
    (
        GLOMI_MINIMAX_LLM_PROVIDER_NAME,
        GLOMI_MINIMAX_LLM_PROVIDER_TYPE,
    ): GlomiSupplierMetadata(
        supplier_id=GLOMI_MINIMAX_SUPPLIER_ID,
        supplier_display_name="MiniMax",
    ),
}


def get_glomi_supplier_metadata_for_provider(
    provider_name: str | None,
    provider_type: str,
) -> GlomiSupplierMetadata | None:
    if provider_name is None:
        return None
    return _SUPPLIER_METADATA_BY_PROVIDER.get((provider_name, provider_type))


def _minimax_models_from_env() -> tuple[GlomiPlatformModel, ...]:
    known_models = {
        model.model_name: model for model in GLOMI_MINIMAX_PLATFORM_MODELS
    }
    return tuple(
        known_models.get(
            model_name,
            GlomiPlatformModel(
                model_name=model_name,
                display_name=model_name,
                supports_image_input=True,
                supports_reasoning=True,
                roles=("balanced", "reasoning", "research", "vision", "coding"),
            ),
        )
        for model_name in GLOMI_MINIMAX_LLM_MODEL_NAMES
    )


def get_glomi_platform_model_catalog() -> GlomiPlatformModelCatalog:
    return GlomiPlatformModelCatalog(
        enabled=CONSUMER_DEFAULT_LLM_ENABLED or GLOMI_MINIMAX_LLM_ENABLED,
        providers=(
            GlomiPlatformProviderCatalog(
                provider_name=CONSUMER_DEFAULT_LLM_PROVIDER_NAME,
                provider_type=CONSUMER_DEFAULT_LLM_PROVIDER_TYPE,
                supplier_id=GLOMI_GPT_SUPPLIER_ID,
                supplier_display_name="GPT",
                api_base=CONSUMER_DEFAULT_LLM_API_BASE,
                api_key=CONSUMER_DEFAULT_LLM_API_KEY,
                enabled=CONSUMER_DEFAULT_LLM_ENABLED,
                models=GLOMI_GPT_PLATFORM_MODELS,
            ),
            GlomiPlatformProviderCatalog(
                provider_name=GLOMI_MINIMAX_LLM_PROVIDER_NAME,
                provider_type=GLOMI_MINIMAX_LLM_PROVIDER_TYPE,
                supplier_id=GLOMI_MINIMAX_SUPPLIER_ID,
                supplier_display_name="MiniMax",
                api_base=GLOMI_MINIMAX_LLM_API_BASE,
                api_key=GLOMI_MINIMAX_LLM_API_KEY,
                enabled=GLOMI_MINIMAX_LLM_ENABLED,
                models=_minimax_models_from_env(),
            ),
        ),
    )


def _default_model_name(models: tuple[GlomiPlatformModel, ...]) -> str:
    for model in models:
        if model.is_default:
            return model.model_name
    return models[0].model_name


def _build_provider_request(
    provider_catalog: GlomiPlatformProviderCatalog,
) -> LLMProviderUpsertRequest:
    return LLMProviderUpsertRequest(
        name=provider_catalog.provider_name,
        provider=provider_catalog.provider_type,
        api_key=provider_catalog.api_key,
        api_base=provider_catalog.api_base,
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
            for model in provider_catalog.models
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


def _provider_skip_reason(
    provider_catalog: GlomiPlatformProviderCatalog,
) -> str | None:
    if not provider_catalog.enabled:
        return "disabled"
    if not provider_catalog.api_key:
        return "missing_api_key"
    if not provider_catalog.api_base:
        return "missing_api_base"
    if not provider_catalog.models:
        return "missing_models"
    return None


def sync_glomi_platform_model_catalog(
    db_session: Session,
    catalog: GlomiPlatformModelCatalog | None = None,
) -> GlomiModelCatalogSyncResult:
    catalog = catalog or get_glomi_platform_model_catalog()
    if not catalog.enabled:
        return GlomiModelCatalogSyncResult(synced=False, reason="disabled")

    synced_model_count = 0
    first_skip_reason: str | None = None
    current_default = fetch_default_llm_model(db_session)
    default_set = current_default is not None

    for provider_catalog in catalog.providers:
        skip_reason = _provider_skip_reason(provider_catalog)
        if skip_reason is not None:
            first_skip_reason = first_skip_reason or skip_reason
            continue

        request = _build_provider_request(provider_catalog)
        existing_provider = fetch_existing_llm_provider_by_name_and_type(
            name=provider_catalog.provider_name,
            provider_type=provider_catalog.provider_type,
            db_session=db_session,
        )
        if existing_provider:
            _preserve_existing_provider_settings(request, existing_provider)

        provider = upsert_llm_provider(request, db_session)
        synced_model_count += len(provider_catalog.models)
        if not default_set:
            update_default_provider(
                provider.id,
                _default_model_name(provider_catalog.models),
                db_session,
            )
            default_set = True

    if synced_model_count == 0:
        return GlomiModelCatalogSyncResult(
            synced=False,
            reason=first_skip_reason or "missing_providers",
        )

    logger.info(
        "Synced Glomi platform model catalog with %d models",
        synced_model_count,
    )
    return GlomiModelCatalogSyncResult(
        synced=True,
        reason="synced",
        model_count=synced_model_count,
    )
