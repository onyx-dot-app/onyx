from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.configs.chat_configs import MAX_CHUNKS_FED_TO_CHAT
from onyx.context.search.enums import RecencyBiasSetting
from onyx.db.constants import SLACK_BOT_PERSONA_PREFIX
from onyx.db.models import ChannelConfig
from onyx.db.models import Persona
from onyx.db.models import Persona__DocumentSet
from onyx.db.models import SlackChannelConfig
from onyx.db.models import User
from onyx.db.persona import get_default_prompt
from onyx.db.persona import mark_persona_as_deleted
from onyx.db.persona import upsert_persona
from onyx.utils.errors import EERequiredError
from onyx.utils.variable_functionality import (
    fetch_versioned_implementation_with_fallback,
)


def _build_persona_name(channel_name: str) -> str:
    return f"{SLACK_BOT_PERSONA_PREFIX}{channel_name}"


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


def create_slack_channel_persona(
    db_session: Session,
    channel_name: str,
    document_set_ids: list[int],
    existing_persona_id: int | None = None,
    num_chunks: float = MAX_CHUNKS_FED_TO_CHAT,
    enable_auto_filters: bool = False,
) -> Persona:
    """NOTE: does not commit changes"""

    # create/update persona associated with the Slack channel
    persona_name = _build_persona_name(channel_name)
    default_prompt = get_default_prompt(db_session)
    persona = upsert_persona(
        user=None,  # Slack channel Personas are not attached to users
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


def insert_slack_channel_config(
    db_session: Session,
    slack_bot_id: int,
    persona_id: int | None,
    channel_config: ChannelConfig,
    standard_answer_category_ids: list[int],
    enable_auto_filters: bool,
) -> SlackChannelConfig:
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

    slack_channel_config = SlackChannelConfig(
        slack_bot_id=slack_bot_id,
        persona_id=persona_id,
        channel_config=channel_config,
        standard_answer_categories=existing_standard_answer_categories,
        enable_auto_filters=enable_auto_filters,
    )
    db_session.add(slack_channel_config)
    db_session.commit()

    return slack_channel_config


def update_slack_channel_config(
    db_session: Session,
    slack_channel_config_id: int,
    persona_id: int | None,
    channel_config: ChannelConfig,
    standard_answer_category_ids: list[int],
    enable_auto_filters: bool,
) -> SlackChannelConfig:
    slack_channel_config = db_session.scalar(
        select(SlackChannelConfig).where(
            SlackChannelConfig.id == slack_channel_config_id
        )
    )
    if slack_channel_config is None:
        raise ValueError(
            f"Unable to find Slack channel config with ID {slack_channel_config_id}"
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

    # get the existing persona id before updating the object
    existing_persona_id = slack_channel_config.persona_id

    # update the config
    # NOTE: need to do this before cleaning up the old persona or else we
    # will encounter `violates foreign key constraint` errors
    slack_channel_config.persona_id = persona_id
    slack_channel_config.channel_config = channel_config
    slack_channel_config.standard_answer_categories = list(
        existing_standard_answer_categories
    )
    slack_channel_config.enable_auto_filters = enable_auto_filters

    # if the persona has changed, then clean up the old persona
    if persona_id != existing_persona_id and existing_persona_id:
        existing_persona = db_session.scalar(
            select(Persona).where(Persona.id == existing_persona_id)
        )
        # if the existing persona was one created just for use with this Slack channel,
        # then clean it up
        if existing_persona and existing_persona.name.startswith(
            SLACK_BOT_PERSONA_PREFIX
        ):
            _cleanup_relationships(
                db_session=db_session, persona_id=existing_persona_id
            )

    db_session.commit()

    return slack_channel_config


def remove_slack_channel_config(
    db_session: Session,
    slack_channel_config_id: int,
    user: User | None,
) -> None:
    slack_channel_config = db_session.scalar(
        select(SlackChannelConfig).where(
            SlackChannelConfig.id == slack_channel_config_id
        )
    )
    if slack_channel_config is None:
        raise ValueError(
            f"Unable to find Slack channel config with ID {slack_channel_config_id}"
        )

    existing_persona_id = slack_channel_config.persona_id
    if existing_persona_id:
        existing_persona = db_session.scalar(
            select(Persona).where(Persona.id == existing_persona_id)
        )
        # if the existing persona was one created just for use with this Slack channel,
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

    db_session.delete(slack_channel_config)
    db_session.commit()


def fetch_slack_channel_configs(
    db_session: Session, slack_bot_id: int | None = None
) -> Sequence[SlackChannelConfig]:
    if not slack_bot_id:
        return db_session.scalars(select(SlackChannelConfig)).all()

    return db_session.scalars(
        select(SlackChannelConfig).where(
            SlackChannelConfig.slack_bot_id == slack_bot_id
        )
    ).all()


def fetch_slack_channel_config(
    db_session: Session, slack_channel_config_id: int
) -> SlackChannelConfig | None:
    return db_session.scalar(
        select(SlackChannelConfig).where(
            SlackChannelConfig.id == slack_channel_config_id
        )
    )
