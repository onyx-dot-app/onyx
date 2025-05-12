from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.configs.chat_configs import MAX_CHUNKS_FED_TO_CHAT
from onyx.context.search.enums import RecencyBiasSetting
from onyx.db.constants import DEFAULT_PERSONA_SLACK_SHORTCUT_NAME
from onyx.db.constants import SLACK_BOT_PERSONA_PREFIX
from onyx.db.models import Persona
from onyx.db.models import Persona__DocumentSet
from onyx.db.models import SlackShortcutConfig
from onyx.db.models import User
from onyx.db.persona import mark_persona_as_deleted
from onyx.db.persona import upsert_persona
from onyx.db.prompts import get_default_prompt
from onyx.tools.built_in_tools import get_search_tool
from onyx.utils.errors import EERequiredError
from onyx.utils.variable_functionality import (
    fetch_versioned_implementation_with_fallback,
)


def _build_shortcut_persona_name(shortcut_name: str | None) -> str:
    return f"{SLACK_BOT_PERSONA_PREFIX}{shortcut_name if shortcut_name else DEFAULT_PERSONA_SLACK_SHORTCUT_NAME}"


def create_slack_shortcut_persona(
    db_session: Session,
    shortcut_name: str | None,
    document_set_ids: list[int],
    existing_persona_id: int | None = None,
    num_chunks: float = MAX_CHUNKS_FED_TO_CHAT,
    enable_auto_filters: bool = False,
) -> Persona:
    """Create or update a persona for a Slack shortcut. NOTE: does not commit changes"""

    search_tool = get_search_tool(db_session)
    if search_tool is None:
        raise ValueError("Search tool not found")

    # create/update persona associated with the Slack shortcut
    persona_name = _build_shortcut_persona_name(shortcut_name)
    default_prompt = get_default_prompt(db_session)
    persona = upsert_persona(
        user=None,  # Slack shortcut Personas are not attached to users
        persona_id=existing_persona_id,
        name=persona_name,
        description="",
        num_chunks=num_chunks,
        llm_relevance_filter=True,
        llm_filter_extraction=enable_auto_filters,
        recency_bias=RecencyBiasSetting.AUTO,
        prompt_ids=[default_prompt.id],
        tool_ids=[search_tool.id],
        document_set_ids=document_set_ids,
        llm_model_provider_override=None,
        llm_model_version_override=None,
        starter_messages=None,
        is_public=True,
        is_default_persona=False,
        db_session=db_session,
        commit=False,
    )

    return persona

def _cleanup_relationships(db_session: Session, persona_id: int) -> None:
    """Delete existing persona-document_set relationships. NOTE: does not commit changes"""
    # delete existing persona-document_set relationships
    existing_relationships = db_session.scalars(
        select(Persona__DocumentSet).where(
            Persona__DocumentSet.persona_id == persona_id
        )
    )
    for rel in existing_relationships:
        db_session.delete(rel)


def insert_slack_shortcut_config(
    db_session: Session,
    slack_bot_id: int,
    persona_id: int | None,
    shortcut_config: dict[str, Any],
    standard_answer_category_ids: list[int],
    enable_auto_filters: bool,
    response_type: str = "citations",
    is_default: bool = False,
) -> SlackShortcutConfig:
    """Create a new Slack shortcut configuration"""
    versioned_fetch_standard_answer_categories_by_ids = (
        fetch_versioned_implementation_with_fallback(
            "onyx.db.standard_answer",
            "fetch_standard_answer_categories_by_ids",
            _no_ee_standard_answer_categories,
        )
    )
    existing_standard_answer_categories = (
        versioned_fetch_standard_answer_categories_by_ids(
            standard_answer_category_ids=standard_answer_category_ids,
            db_session=db_session,
        )
    )

    if len(existing_standard_answer_categories) != len(standard_answer_category_ids):
        if len(existing_standard_answer_categories) == 0:
            raise EERequiredError(
                "Standard answers are a paid Enterprise Edition feature - enable EE or remove standard answer categories"
            )
        else:
            raise ValueError(
                f"Some or all categories with ids {standard_answer_category_ids} do not exist"
            )

    if is_default:
        existing_default = db_session.scalar(
            select(SlackShortcutConfig).where(
                SlackShortcutConfig.slack_bot_id == slack_bot_id,
                SlackShortcutConfig.is_default == True,  # noqa: E712
            )
        )
        if existing_default:
            raise ValueError("A default config already exists for this Slack bot.")
    else:
        if "shortcut_name" not in shortcut_config:
            raise ValueError("Shortcut name is required for non-default configs.")

    slack_shortcut_config = SlackShortcutConfig(
        slack_bot_id=slack_bot_id,
        persona_id=persona_id,
        shortcut_config=shortcut_config,
        standard_answer_categories=existing_standard_answer_categories,
        enable_auto_filters=enable_auto_filters,
        is_default=is_default,
        response_type=response_type,
    )
    db_session.add(slack_shortcut_config)
    db_session.commit()

    return slack_shortcut_config

def _no_ee_standard_answer_categories(*args: Any, **kwargs: Any) -> list:
    return []

def update_slack_shortcut_config(
    db_session: Session,
    slack_shortcut_config_id: int,
    persona_id: int | None,
    shortcut_config: dict[str, Any],
    standard_answer_category_ids: list[int],
    enable_auto_filters: bool,
    response_type: str = "citations",
    disabled: bool = False
) -> SlackShortcutConfig:
    """Update an existing Slack shortcut configuration"""
    slack_shortcut_config = db_session.scalar(
        select(SlackShortcutConfig).where(
            SlackShortcutConfig.id == slack_shortcut_config_id
        )
    )
    if slack_shortcut_config is None:
        raise ValueError(
            f"Unable to find Slack shortcut config with ID {slack_shortcut_config_id}"
        )

    versioned_fetch_standard_answer_categories_by_ids = (
        fetch_versioned_implementation_with_fallback(
            "onyx.db.standard_answer",
            "fetch_standard_answer_categories_by_ids",
            _no_ee_standard_answer_categories,
        )
    )
    existing_standard_answer_categories = (
        versioned_fetch_standard_answer_categories_by_ids(
            standard_answer_category_ids=standard_answer_category_ids,
            db_session=db_session,
        )
    )
    if len(existing_standard_answer_categories) != len(standard_answer_category_ids):
        raise ValueError(
            f"Some or all categories with ids {standard_answer_category_ids} do not exist"
        )

    # update the config
    slack_shortcut_config.persona_id = persona_id
    slack_shortcut_config.shortcut_config = shortcut_config
    slack_shortcut_config.standard_answer_categories = list(
        existing_standard_answer_categories
    )
    slack_shortcut_config.enable_auto_filters = enable_auto_filters
    slack_shortcut_config.response_type = response_type

    db_session.commit()

    return slack_shortcut_config


def remove_slack_shortcut_config(
    db_session: Session,
    slack_shortcut_config_id: int,
    user: User | None,
) -> None:
    """Remove a Slack shortcut configuration and clean up associated resources"""
    slack_shortcut_config = db_session.scalar(
        select(SlackShortcutConfig).where(
            SlackShortcutConfig.id == slack_shortcut_config_id
        )
    )
    if slack_shortcut_config is None:
        raise ValueError(
            f"Unable to find Slack shortcut config with ID {slack_shortcut_config_id}"
        )

    existing_persona_id = slack_shortcut_config.persona_id
    if existing_persona_id:
        existing_persona = db_session.scalar(
            select(Persona).where(Persona.id == existing_persona_id)
        )
        # if the existing persona was one created just for use with this Slack shortcut,
        # then clean it up
        if existing_persona and existing_persona.name.startswith(
            SLACK_BOT_PERSONA_PREFIX
        ):
            _cleanup_relationships(
                db_session=db_session, persona_id=existing_persona_id
            )
            mark_persona_as_deleted(
                persona_id=existing_persona_id, user=user, db_session=db_session
            )

    db_session.delete(slack_shortcut_config)
    db_session.commit()


def fetch_slack_shortcut_configs(
    db_session: Session, slack_bot_id: int | None = None
) -> Sequence[SlackShortcutConfig]:
    """Fetch all shortcut configurations or configurations for a specific bot"""
    if not slack_bot_id:
        return db_session.scalars(select(SlackShortcutConfig)).all()

    return db_session.scalars(
        select(SlackShortcutConfig).where(
            SlackShortcutConfig.slack_bot_id == slack_bot_id
        )
    ).all()


def fetch_slack_shortcut_config(
    db_session: Session, slack_shortcut_config_id: int
) -> SlackShortcutConfig | None:
    """Fetch a specific shortcut configuration by ID"""
    return db_session.scalar(
        select(SlackShortcutConfig).where(
            SlackShortcutConfig.id == slack_shortcut_config_id
        )
    )


def fetch_slack_shortcut_config_for_callback_or_default(
    db_session: Session, slack_bot_id: int, callback_id: str
) -> SlackShortcutConfig | None:
    """
    Fetch a shortcut configuration for a specific callback_id or the default configuration.
    
    Args:
        db_session: The database session
        slack_bot_id: The ID of the Slack bot
        callback_id: The callback ID of the shortcut (corresponds to shortcut_name)
        
    Returns:
        The shortcut configuration or None if not found
    """
    # First try to find configuration for the specific callback_id
    shortcut_config = db_session.scalar(
        select(SlackShortcutConfig).where(
            SlackShortcutConfig.slack_bot_id == slack_bot_id,
            SlackShortcutConfig.shortcut_config["shortcut_name"].astext == callback_id,
        )
    )
    
    # If not found, try to get the default configuration
    if shortcut_config is None:
        shortcut_config = db_session.scalar(
            select(SlackShortcutConfig).where(
                SlackShortcutConfig.slack_bot_id == slack_bot_id,
                SlackShortcutConfig.is_default == True,  # noqa: E712
            )
        )
    
    return shortcut_config


def get_slack_shortcut_config_for_bot_and_callback(
    db_session: Session,
    slack_bot_id: int,
    callback_id: str,
) -> SlackShortcutConfig:
    """
    Get the shortcut configuration for a bot and callback_id.
    
    Args:
        db_session: The database session
        slack_bot_id: The ID of the Slack bot
        callback_id: The callback ID of the shortcut (corresponds to shortcut_name)
        
    Returns:
        The shortcut configuration
        
    Raises:
        ValueError: If no configuration exists for this shortcut or no default configuration exists
    """
    slack_shortcut_config = fetch_slack_shortcut_config_for_callback_or_default(
        db_session=db_session, slack_bot_id=slack_bot_id, callback_id=callback_id
    )
    if not slack_shortcut_config:
        raise ValueError(
            f"No configuration found for shortcut '{callback_id}' and no default configuration exists."
        )

    return slack_shortcut_config