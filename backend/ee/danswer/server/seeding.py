import os

from pydantic import BaseModel
from sqlalchemy.orm import Session

from danswer.db.engine import get_session_context_manager
from danswer.db.llm import update_default_provider
from danswer.db.llm import upsert_llm_provider
from danswer.db.persona import upsert_persona
from danswer.search.enums import RecencyBiasSetting
from danswer.server.features.persona.models import CreatePersonaRequest
from danswer.server.manage.llm.models import LLMProviderUpsertRequest
from danswer.server.settings.models import Settings
from danswer.server.settings.store import store_settings as store_base_settings
from danswer.utils.logger import setup_logger
from ee.danswer.server.enterprise_settings.models import AnalyticsScriptUpload
from ee.danswer.server.enterprise_settings.models import EnterpriseSettings
from ee.danswer.server.enterprise_settings.store import store_analytics_script
from ee.danswer.server.enterprise_settings.store import (
    store_settings as store_ee_settings,
)
from ee.danswer.server.enterprise_settings.store import upload_logo

logger = setup_logger()

_SEED_CONFIG_ENV_VAR_NAME = "ENV_SEED_CONFIGURATION"


class SeedConfiguration(BaseModel):
    llms: list[LLMProviderUpsertRequest] | None = None
    admin_user_emails: list[str] | None = None
    seeded_logo_path: str | None = None
    personas: list[CreatePersonaRequest] | None = None
    settings: Settings | None = None
    enterprise_settings: EnterpriseSettings | None = None
    # Use existing `CUSTOM_ANALYTICS_SECRET_KEY` for reference
    analytics_script_path: str | None = None


def _parse_env() -> SeedConfiguration | None:
    seed_config_str = os.getenv(_SEED_CONFIG_ENV_VAR_NAME)
    if not seed_config_str:
        return None
    seed_config = SeedConfiguration.parse_raw(seed_config_str)
    return seed_config


def _seed_llms(
    db_session: Session, llm_upsert_requests: list[LLMProviderUpsertRequest]
) -> None:
    if llm_upsert_requests:
        logger.notice("Seeding LLMs")
        seeded_providers = [
            upsert_llm_provider(db_session, llm_upsert_request)
            for llm_upsert_request in llm_upsert_requests
        ]
        update_default_provider(db_session, seeded_providers[0].id)


def _seed_personas(db_session: Session, personas: list[CreatePersonaRequest]) -> None:
    if personas:
        logger.notice("Seeding Personas")
        for persona in personas:
            upsert_persona(
                user=None,  # Seeding is done as admin
                name=persona.name,
                description=persona.description,
                num_chunks=persona.num_chunks
                if persona.num_chunks is not None
                else 0.0,
                llm_relevance_filter=persona.llm_relevance_filter,
                llm_filter_extraction=persona.llm_filter_extraction,
                recency_bias=RecencyBiasSetting.AUTO,
                prompt_ids=persona.prompt_ids,
                document_set_ids=persona.document_set_ids,
                llm_model_provider_override=persona.llm_model_provider_override,
                llm_model_version_override=persona.llm_model_version_override,
                starter_messages=persona.starter_messages,
                is_public=persona.is_public,
                db_session=db_session,
                tool_ids=persona.tool_ids,
            )


def _seed_settings(settings: Settings) -> None:
    logger.notice("Seeding Settings")
    try:
        settings.check_validity()
        store_base_settings(settings)
        logger.notice("Successfully seeded Settings")
    except ValueError as e:
        logger.error(f"Failed to seed Settings: {str(e)}")


def _seed_enterprise_settings(seed_config: SeedConfiguration) -> None:
    if seed_config.enterprise_settings is not None:
        logger.notice("Seeding enterprise settings")
        store_ee_settings(seed_config.enterprise_settings)


def _seed_logo(db_session: Session, logo_path: str | None) -> None:
    if logo_path:
        logger.notice("Uploading logo")
        upload_logo(db_session=db_session, file=logo_path)


def _seed_analytics_script(seed_config: SeedConfiguration) -> None:
    custom_analytics_secret_key = os.environ.get("CUSTOM_ANALYTICS_SECRET_KEY")
    if seed_config.analytics_script_path and custom_analytics_secret_key:
        logger.notice("Seeding analytics script")
        try:
            with open(seed_config.analytics_script_path, "r") as file:
                script_content = file.read()
            analytics_script = AnalyticsScriptUpload(
                script=script_content, secret_key=custom_analytics_secret_key
            )
            store_analytics_script(analytics_script)
        except FileNotFoundError:
            logger.error(
                f"Analytics script file not found: {seed_config.analytics_script_path}"
            )
        except ValueError as e:
            logger.error(f"Failed to seed analytics script: {str(e)}")


def get_seed_config() -> SeedConfiguration | None:
    return _parse_env()


def seed_db() -> None:
    seed_config = _parse_env()
    if seed_config is None:
        logger.debug("No seeding configuration file passed")
        return

    with get_session_context_manager() as db_session:
        if seed_config.llms is not None:
            _seed_llms(db_session, seed_config.llms)
        if seed_config.personas is not None:
            _seed_personas(db_session, seed_config.personas)
        if seed_config.settings is not None:
            _seed_settings(seed_config.settings)

        _seed_logo(db_session, seed_config.seeded_logo_path)
        _seed_enterprise_settings(seed_config)
        _seed_analytics_script(seed_config)
