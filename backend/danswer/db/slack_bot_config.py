from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from danswer.configs.chat_configs import MAX_CHUNKS_FED_TO_CHAT
from danswer.db.constants import SLACK_BOT_PERSONA_PREFIX
from danswer.db.models import ChannelConfig
from danswer.db.models import Persona
from danswer.db.models import Persona__DocumentSet
from danswer.db.models import SlackBotConfig
from danswer.db.models import SlackBotResponseType
from danswer.db.models import User
from danswer.db.persona import get_default_prompt
from danswer.db.persona import mark_persona_as_deleted
from danswer.db.persona import upsert_persona
from danswer.search.enums import RecencyBiasSetting
from danswer.utils.errors import EERequiredError
from danswer.utils.variable_functionality import (
    fetch_versioned_implementation_with_fallback,
)


def _build_persona_name(channel_names: list[str]) -> str:
    return f"{SLACK_BOT_PERSONA_PREFIX}{'-'.join(channel_names)}"


def _cleanup_relationships(db_session: Session, persona_id: int) -> None:
    """NOTE: does not commit changes"""
    # delete existing persona-document_set relationships
    existing_relationships = db_session.scalars(
        select(Persona__DocumentSet).where(
            Persona__DocumentSet.persona_id == persona_id
        )
    )
    for rel in existing_relationships:
        db_session.delete(rel)


def create_slack_bot_persona(
    db_session: Session,
    channel_names: list[str],
    document_set_ids: list[int],
    existing_persona_id: int | None = None,
    num_chunks: float = MAX_CHUNKS_FED_TO_CHAT,
    enable_auto_filters: bool = False,
) -> Persona:
    """NOTE: does not commit changes"""

    # create/update persona associated with the slack bot
    persona_name = _build_persona_name(channel_names)
    default_prompt = get_default_prompt(db_session)
    persona = upsert_persona(
        user=None,  # Slack Bot Personas are not attached to users
        persona_id=existing_persona_id,
        name=persona_name,
        description="",
        num_chunks=num_chunks,
        llm_relevance_filter=True,
        llm_filter_extraction=enable_auto_filters,
        recency_bias=RecencyBiasSetting.AUTO,
        prompt_ids=[default_prompt.id],
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


def _no_ee_standard_answer_categories(*args: Any, **kwargs: Any) -> list:
    return []


def insert_slack_bot_config(
    persona_id: int | None,
    channel_config: ChannelConfig,
    response_type: SlackBotResponseType,
    standard_answer_category_ids: list[int],
    enable_auto_filters: bool,
    db_session: Session,
) -> SlackBotConfig:
    versioned_fetch_standard_answer_categories_by_ids = (
        fetch_versioned_implementation_with_fallback(
            "danswer.db.standard_answer",
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

    slack_bot_config = SlackBotConfig(
        persona_id=persona_id,
        channel_config=channel_config,
        response_type=response_type,
        standard_answer_categories=existing_standard_answer_categories,
        enable_auto_filters=enable_auto_filters,
    )
    db_session.add(slack_bot_config)
    db_session.commit()

    return slack_bot_config


def update_slack_bot_config(
    slack_bot_config_id: int,
    persona_id: int | None,
    channel_config: ChannelConfig,
    response_type: SlackBotResponseType,
    standard_answer_category_ids: list[int],
    enable_auto_filters: bool,
    db_session: Session,
) -> SlackBotConfig:
    slack_bot_config = db_session.scalar(
        select(SlackBotConfig).where(SlackBotConfig.id == slack_bot_config_id)
    )
    if slack_bot_config is None:
        raise ValueError(
            f"Unable to find slack bot config with ID {slack_bot_config_id}"
        )

    versioned_fetch_standard_answer_categories_by_ids = (
        fetch_versioned_implementation_with_fallback(
            "danswer.db.standard_answer",
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

    # get the existing persona id before updating the object
    existing_persona_id = slack_bot_config.persona_id

    # update the config
    # NOTE: need to do this before cleaning up the old persona or else we
    # will encounter `violates foreign key constraint` errors
    slack_bot_config.persona_id = persona_id
    slack_bot_config.channel_config = channel_config
    slack_bot_config.response_type = response_type
    slack_bot_config.standard_answer_categories = list(
        existing_standard_answer_categories
    )
    slack_bot_config.enable_auto_filters = enable_auto_filters

    # if the persona has changed, then clean up the old persona
    if persona_id != existing_persona_id and existing_persona_id:
        existing_persona = db_session.scalar(
            select(Persona).where(Persona.id == existing_persona_id)
        )
        # if the existing persona was one created just for use with this Slack Bot,
        # then clean it up
        if existing_persona and existing_persona.name.startswith(
            SLACK_BOT_PERSONA_PREFIX
        ):
            _cleanup_relationships(
                db_session=db_session, persona_id=existing_persona_id
            )

    db_session.commit()

    return slack_bot_config


def remove_slack_bot_config(
    slack_bot_config_id: int,
    user: User | None,
    db_session: Session,
) -> None:
    slack_bot_config = db_session.scalar(
        select(SlackBotConfig).where(SlackBotConfig.id == slack_bot_config_id)
    )
    if slack_bot_config is None:
        raise ValueError(
            f"Unable to find slack bot config with ID {slack_bot_config_id}"
        )

    existing_persona_id = slack_bot_config.persona_id
    if existing_persona_id:
        existing_persona = db_session.scalar(
            select(Persona).where(Persona.id == existing_persona_id)
        )
        # if the existing persona was one created just for use with this Slack Bot,
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

    db_session.delete(slack_bot_config)
    db_session.commit()


def fetch_slack_bot_config(
    db_session: Session, slack_bot_config_id: int
) -> SlackBotConfig | None:
    return db_session.scalar(
        select(SlackBotConfig).where(SlackBotConfig.id == slack_bot_config_id)
    )


def fetch_slack_bot_configs(db_session: Session) -> Sequence[SlackBotConfig]:
    return db_session.scalars(select(SlackBotConfig)).all()
