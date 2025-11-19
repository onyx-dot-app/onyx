import json
import os
from copy import deepcopy
from typing import List
from typing import Optional

from pydantic import BaseModel
from sqlalchemy.orm import Session

from ee.onyx.db.standard_answer import (
    create_initial_default_standard_answer_category,
)
from ee.onyx.server.enterprise_settings.models import AnalyticsScriptUpload
from ee.onyx.server.enterprise_settings.models import EnterpriseSettings
from ee.onyx.server.enterprise_settings.models import NavigationItem
from ee.onyx.server.enterprise_settings.store import store_analytics_script
from ee.onyx.server.enterprise_settings.store import (
    store_settings as store_ee_settings,
)
from ee.onyx.server.enterprise_settings.store import upload_logo
from onyx.context.search.enums import RecencyBiasSetting
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.llm import update_default_provider
from onyx.db.llm import upsert_llm_provider
from onyx.db.models import Tool
from onyx.db.persona import upsert_persona
from onyx.server.features.persona.models import PersonaUpsertRequest
from onyx.server.manage.llm.models import LLMProviderUpsertRequest
from onyx.server.settings.models import Settings
from onyx.server.settings.store import store_settings as store_base_settings
from onyx.utils.logger import setup_logger


class CustomToolSeed(BaseModel):
    name: str
    description: str
    definition_path: str
    custom_headers: Optional[List[dict]] = None
    display_name: Optional[str] = None
    in_code_tool_id: Optional[str] = None
    user_id: Optional[str] = None


logger = setup_logger()

_SEED_CONFIG_ENV_VAR_NAME = "ENV_SEED_CONFIGURATION"


class NavigationItemSeed(BaseModel):
    link: str
    title: str
    # NOTE: SVG at this path must not have a width / height specified
    svg_path: str


class SeedConfiguration(BaseModel):
    llms: list[LLMProviderUpsertRequest] | None = None
    admin_user_emails: list[str] | None = None
    seeded_logo_path: str | None = None
    personas: list[PersonaUpsertRequest] | None = None
    settings: Settings | None = None
    enterprise_settings: EnterpriseSettings | None = None

    # allows for specifying custom navigation items that have your own custom SVG logos
    nav_item_overrides: list[NavigationItemSeed] | None = None

    # Use existing `CUSTOM_ANALYTICS_SECRET_KEY` for reference
    analytics_script_path: str | None = None
    custom_tools: List[CustomToolSeed] | None = None


def _parse_env() -> SeedConfiguration | None:
    seed_config_str = os.getenv(_SEED_CONFIG_ENV_VAR_NAME)
    if not seed_config_str:
        return None
    seed_config = SeedConfiguration.model_validate_json(seed_config_str)
    return seed_config


def _seed_custom_tools(db_session: Session, tools: List[CustomToolSeed]) -> None:
    if tools:
        logger.notice("Seeding Custom Tools")
        for tool in tools:
            try:
                logger.debug(f"Attempting to seed tool: {tool.name}")
                logger.debug(f"Reading definition from: {tool.definition_path}")
                with open(tool.definition_path, "r") as file:
                    file_content = file.read()
                    if not file_content.strip():
                        raise ValueError("File is empty")
                    openapi_schema = json.loads(file_content)
                db_tool = Tool(
                    name=tool.name,
                    description=tool.description,
                    openapi_schema=openapi_schema,
                    custom_headers=tool.custom_headers,
                    display_name=tool.display_name,
                    in_code_tool_id=tool.in_code_tool_id,
                    user_id=tool.user_id,
                )
                db_session.add(db_tool)
                logger.debug(f"Successfully added tool: {tool.name}")
            except FileNotFoundError:
                logger.error(
                    f"Definition file not found for tool {tool.name}: {tool.definition_path}"
                )
            except json.JSONDecodeError as e:
                logger.error(
                    f"Invalid JSON in definition file for tool {tool.name}: {str(e)}"
                )
            except Exception as e:
                logger.error(f"Failed to seed tool {tool.name}: {str(e)}")
        db_session.commit()
        logger.notice(f"Successfully seeded {len(tools)} Custom Tools")


def _seed_llms(
    db_session: Session, llm_upsert_requests: list[LLMProviderUpsertRequest]
) -> None:
    if llm_upsert_requests:
        logger.notice("Seeding LLMs")
        seeded_providers = [
            upsert_llm_provider(llm_upsert_request, db_session)
            for llm_upsert_request in llm_upsert_requests
        ]
        update_default_provider(
            provider_id=seeded_providers[0].id, db_session=db_session
        )


def _seed_personas(db_session: Session, personas: list[PersonaUpsertRequest]) -> None:
    if personas:
        logger.notice("Seeding Personas")
        try:
            for persona in personas:
                upsert_persona(
                    user=None,  # Seeding is done as admin
                    name=persona.name,
                    description=persona.description,
                    num_chunks=(
                        persona.num_chunks if persona.num_chunks is not None else 0.0
                    ),
                    llm_relevance_filter=persona.llm_relevance_filter,
                    llm_filter_extraction=persona.llm_filter_extraction,
                    recency_bias=RecencyBiasSetting.AUTO,
                    document_set_ids=persona.document_set_ids,
                    llm_model_provider_override=persona.llm_model_provider_override,
                    llm_model_version_override=persona.llm_model_version_override,
                    starter_messages=persona.starter_messages,
                    is_public=persona.is_public,
                    db_session=db_session,
                    tool_ids=persona.tool_ids,
                    display_priority=persona.display_priority,
                    system_prompt=persona.system_prompt,
                    task_prompt=persona.task_prompt,
                    datetime_aware=persona.datetime_aware,
                    commit=False,
                )
            db_session.commit()
        except Exception:
            logger.exception("Failed to seed personas.")
            raise


def _seed_settings(settings: Settings) -> None:
    logger.notice("Seeding Settings")
    try:
        store_base_settings(settings)
        logger.notice("Successfully seeded Settings")
    except ValueError as e:
        logger.error(f"Failed to seed Settings: {str(e)}")


def _seed_enterprise_settings(seed_config: SeedConfiguration) -> None:
    if (
        seed_config.enterprise_settings is not None
        or seed_config.nav_item_overrides is not None
    ):
        final_enterprise_settings = (
            deepcopy(seed_config.enterprise_settings)
            if seed_config.enterprise_settings
            else EnterpriseSettings()
        )

        final_nav_items = final_enterprise_settings.custom_nav_items
        if seed_config.nav_item_overrides is not None:
            final_nav_items = []
            for item in seed_config.nav_item_overrides:
                with open(item.svg_path, "r") as file:
                    svg_content = file.read().strip()

                final_nav_items.append(
                    NavigationItem(
                        link=item.link,
                        title=item.title,
                        svg_logo=svg_content,
                    )
                )

        final_enterprise_settings.custom_nav_items = final_nav_items

        logger.notice("Seeding enterprise settings")
        store_ee_settings(final_enterprise_settings)


def _seed_logo(logo_path: str | None) -> None:
    if logo_path:
        logger.notice("Uploading logo")
        upload_logo(file=logo_path)


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

    with get_session_with_current_tenant() as db_session:
        if seed_config.llms is not None:
            _seed_llms(db_session, seed_config.llms)
        if seed_config.personas is not None:
            _seed_personas(db_session, seed_config.personas)
        if seed_config.settings is not None:
            _seed_settings(seed_config.settings)
        if seed_config.custom_tools is not None:
            _seed_custom_tools(db_session, seed_config.custom_tools)

        _seed_logo(seed_config.seeded_logo_path)
        _seed_enterprise_settings(seed_config)
        _seed_analytics_script(seed_config)

        logger.notice("Verifying default standard answer category exists.")
        create_initial_default_standard_answer_category(db_session)
