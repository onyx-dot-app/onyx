from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from onyx.configs.app_configs import AUTO_PROVISION_DEFAULT_LLM_PROVIDERS
from onyx.configs.app_configs import CONSUMER_DEFAULT_LLM_API_BASE
from onyx.configs.app_configs import CONSUMER_DEFAULT_LLM_API_KEY
from onyx.configs.app_configs import CONSUMER_DEFAULT_LLM_DEFAULT_PROFILE
from onyx.configs.app_configs import CONSUMER_DEFAULT_LLM_ENABLED
from onyx.configs.app_configs import CONSUMER_DEFAULT_LLM_PROVIDER_NAME
from onyx.configs.app_configs import CONSUMER_DEFAULT_LLM_PROVIDER_TYPE
from onyx.db.llm import fetch_default_llm_model
from onyx.db.llm import fetch_default_vision_model
from onyx.db.llm import fetch_existing_llm_provider_by_name_and_type
from onyx.db.llm import update_default_provider
from onyx.db.llm import update_default_vision_provider
from onyx.db.llm import upsert_llm_provider
from onyx.llm.consumer_model_catalog import CONSUMER_MODEL_PROFILES
from onyx.llm.consumer_model_catalog import get_consumer_model_profile
from onyx.server.manage.llm.models import LLMProviderUpsertRequest
from onyx.server.manage.llm.models import ModelConfigurationUpsertRequest
from onyx.utils.logger import setup_logger

logger = setup_logger()


@dataclass(frozen=True)
class ConsumerDefaultLLMConfig:
    enabled: bool
    provider_name: str
    provider_type: str
    api_base: str
    api_key: str | None
    default_profile_id: str
    auto_provision_enabled: bool


@dataclass(frozen=True)
class ConsumerDefaultLLMSeedResult:
    seeded: bool
    reason: str


def get_consumer_default_llm_config() -> ConsumerDefaultLLMConfig:
    return ConsumerDefaultLLMConfig(
        enabled=CONSUMER_DEFAULT_LLM_ENABLED,
        provider_name=CONSUMER_DEFAULT_LLM_PROVIDER_NAME,
        provider_type=CONSUMER_DEFAULT_LLM_PROVIDER_TYPE,
        api_base=CONSUMER_DEFAULT_LLM_API_BASE,
        api_key=CONSUMER_DEFAULT_LLM_API_KEY,
        default_profile_id=CONSUMER_DEFAULT_LLM_DEFAULT_PROFILE,
        auto_provision_enabled=AUTO_PROVISION_DEFAULT_LLM_PROVIDERS,
    )


def build_consumer_llm_provider_request(
    config: ConsumerDefaultLLMConfig,
) -> LLMProviderUpsertRequest:
    return LLMProviderUpsertRequest(
        name=config.provider_name,
        provider=config.provider_type,
        api_key=config.api_key,
        api_base=config.api_base,
        api_key_changed=True,
        is_public=True,
        is_auto_mode=False,
        model_configurations=[
            ModelConfigurationUpsertRequest(
                name=profile.model_name,
                is_visible=True,
                max_input_tokens=None,
                supports_image_input=profile.supports_image,
                display_name=profile.display_name,
            )
            for profile in CONSUMER_MODEL_PROFILES
        ],
    )


def seed_consumer_default_llm_provider(
    db_session: Session,
    config: ConsumerDefaultLLMConfig | None = None,
) -> ConsumerDefaultLLMSeedResult:
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

    request = build_consumer_llm_provider_request(config)
    catalog_model_names = {
        model_config.name for model_config in request.model_configurations
    }

    existing_provider = fetch_existing_llm_provider_by_name_and_type(
        name=config.provider_name,
        provider_type=config.provider_type,
        db_session=db_session,
    )
    if existing_provider:
        request.id = existing_provider.id
        for existing_model_config in existing_provider.model_configurations:
            if existing_model_config.name in catalog_model_names:
                continue
            request.model_configurations.append(
                ModelConfigurationUpsertRequest(
                    name=existing_model_config.name,
                    is_visible=False,
                    max_input_tokens=existing_model_config.max_input_tokens,
                    supports_image_input=existing_model_config.supports_image_input,
                    display_name=existing_model_config.display_name,
                    custom_display_name=existing_model_config.custom_display_name,
                )
            )

    provider = upsert_llm_provider(request, db_session)

    default_profile = get_consumer_model_profile(config.default_profile_id)
    if fetch_default_llm_model(db_session) is None:
        update_default_provider(provider.id, default_profile.model_name, db_session)

    vision_profile = next(
        (profile for profile in CONSUMER_MODEL_PROFILES if profile.supports_image),
        None,
    )
    if vision_profile and fetch_default_vision_model(db_session) is None:
        update_default_vision_provider(provider.id, vision_profile.model_name, db_session)

    return ConsumerDefaultLLMSeedResult(seeded=True, reason="seeded")
