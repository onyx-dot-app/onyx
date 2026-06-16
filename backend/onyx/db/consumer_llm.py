from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.orm import Session

from onyx.configs.app_configs import AUTO_PROVISION_DEFAULT_LLM_PROVIDERS
from onyx.configs.app_configs import CONSUMER_DEFAULT_LLM_API_BASE
from onyx.configs.app_configs import CONSUMER_DEFAULT_LLM_API_KEY
from onyx.configs.app_configs import CONSUMER_DEFAULT_LLM_ENABLED
from onyx.configs.app_configs import CONSUMER_DEFAULT_LLM_MODEL_NAME
from onyx.configs.app_configs import CONSUMER_DEFAULT_LLM_PROVIDER_NAME
from onyx.configs.app_configs import CONSUMER_DEFAULT_LLM_PROVIDER_TYPE
from onyx.server.manage.llm.models import LLMProviderUpsertRequest
from onyx.server.manage.llm.models import ModelConfigurationUpsertRequest
from onyx.utils.logger import setup_logger

logger = setup_logger()


class _ExistingModelConfiguration(Protocol):
    name: str
    is_visible: bool
    max_input_tokens: int | None
    supports_image_input: bool | None
    display_name: str | None
    custom_display_name: str | None


@dataclass(frozen=True)
class ConsumerDefaultLLMConfig:
    enabled: bool
    api_base: str | None
    api_key: str | None
    model_name: str | None
    auto_provision_enabled: bool


@dataclass(frozen=True)
class ConsumerDefaultLLMSeedResult:
    seeded: bool
    reason: str


def get_consumer_default_llm_config() -> ConsumerDefaultLLMConfig:
    return ConsumerDefaultLLMConfig(
        enabled=CONSUMER_DEFAULT_LLM_ENABLED,
        api_base=CONSUMER_DEFAULT_LLM_API_BASE,
        api_key=CONSUMER_DEFAULT_LLM_API_KEY,
        model_name=CONSUMER_DEFAULT_LLM_MODEL_NAME,
        auto_provision_enabled=AUTO_PROVISION_DEFAULT_LLM_PROVIDERS,
    )


def _model_config_from_existing(
    model_configuration: _ExistingModelConfiguration,
) -> ModelConfigurationUpsertRequest:
    return ModelConfigurationUpsertRequest(
        name=model_configuration.name,
        is_visible=model_configuration.is_visible,
        max_input_tokens=model_configuration.max_input_tokens,
        supports_image_input=model_configuration.supports_image_input,
        display_name=model_configuration.display_name,
        custom_display_name=model_configuration.custom_display_name,
    )


def build_consumer_llm_provider_request(
    config: ConsumerDefaultLLMConfig,
) -> LLMProviderUpsertRequest:
    if not config.model_name:
        raise ValueError("model_name is required to build provider request")

    return LLMProviderUpsertRequest(
        name=CONSUMER_DEFAULT_LLM_PROVIDER_NAME,
        provider=CONSUMER_DEFAULT_LLM_PROVIDER_TYPE,
        api_key=config.api_key,
        api_base=config.api_base,
        api_key_changed=True,
        is_public=True,
        is_auto_mode=False,
        model_configurations=[
            ModelConfigurationUpsertRequest(
                name=config.model_name,
                is_visible=True,
                max_input_tokens=None,
            )
        ],
    )


def _should_update_default_model(
    current_default: object | None,
    provider_id: int,
    model_name: str,
) -> bool:
    if current_default is None:
        return True

    return (
        getattr(current_default, "llm_provider_id", None) == provider_id
        and getattr(current_default, "name", None) != model_name
    )


def seed_consumer_default_llm_provider(
    db_session: Session,
    config: ConsumerDefaultLLMConfig | None = None,
) -> ConsumerDefaultLLMSeedResult:
    from onyx.db.glomi_model_catalog import GLOMI_PLATFORM_MODELS
    from onyx.db.glomi_model_catalog import GlomiPlatformModelCatalog
    from onyx.db.glomi_model_catalog import sync_glomi_platform_model_catalog

    config = config or get_consumer_default_llm_config()
    if not config.enabled:
        logger.info("Skipping consumer default LLM provider seed: disabled")
        return ConsumerDefaultLLMSeedResult(seeded=False, reason="disabled")

    if not config.auto_provision_enabled:
        logger.info(
            "Skipping consumer default LLM provider seed: auto provisioning disabled"
        )
        return ConsumerDefaultLLMSeedResult(
            seeded=False, reason="auto_provision_disabled"
        )

    if not config.api_key:
        logger.warning(
            "Skipping consumer default LLM provider seed: "
            "CONSUMER_DEFAULT_LLM_API_KEY is unset"
        )
        return ConsumerDefaultLLMSeedResult(seeded=False, reason="missing_api_key")

    if not config.api_base:
        logger.warning(
            "Skipping consumer default LLM provider seed: "
            "CONSUMER_DEFAULT_LLM_API_BASE is unset"
        )
        return ConsumerDefaultLLMSeedResult(seeded=False, reason="missing_api_base")

    catalog = GlomiPlatformModelCatalog(
        provider_name=CONSUMER_DEFAULT_LLM_PROVIDER_NAME,
        provider_type=CONSUMER_DEFAULT_LLM_PROVIDER_TYPE,
        api_base=config.api_base,
        api_key=config.api_key,
        enabled=True,
        models=GLOMI_PLATFORM_MODELS,
    )
    result = sync_glomi_platform_model_catalog(db_session, catalog)
    return ConsumerDefaultLLMSeedResult(
        seeded=result.synced,
        reason=result.reason,
    )
