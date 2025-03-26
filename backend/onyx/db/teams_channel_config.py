from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.models import ChannelConfig
from onyx.db.models import Persona
from onyx.db.models import TeamsChannelConfig
from onyx.db.models import TeamsChannelConfig__StandardAnswerCategory


def insert_teams_channel_config(
    db_session: Session,
    teams_bot_id: int,
    persona_id: int | None,
    channel_config: ChannelConfig,
    standard_answer_category_ids: list[int],
    enable_auto_filters: bool = False,
    is_default: bool = False,
) -> TeamsChannelConfig:
    teams_channel_config = TeamsChannelConfig(
        teams_bot_id=teams_bot_id,
        persona_id=persona_id,
        channel_config=channel_config,
        enable_auto_filters=enable_auto_filters,
        is_default=is_default,
    )
    db_session.add(teams_channel_config)
    db_session.flush()

    for standard_answer_category_id in standard_answer_category_ids:
        teams_channel_config__standard_answer_category = (
            TeamsChannelConfig__StandardAnswerCategory(
                teams_channel_config_id=teams_channel_config.id,
                standard_answer_category_id=standard_answer_category_id,
            )
        )
        db_session.add(teams_channel_config__standard_answer_category)

    db_session.commit()
    return teams_channel_config


def update_teams_channel_config(
    db_session: Session,
    teams_channel_config_id: int,
    persona_id: int | None = None,
    channel_config: ChannelConfig | None = None,
    standard_answer_category_ids: list[int] | None = None,
    enable_auto_filters: bool | None = None,
    is_default: bool | None = None,
) -> TeamsChannelConfig:
    teams_channel_config = fetch_teams_channel_config(
        db_session=db_session, teams_channel_config_id=teams_channel_config_id
    )
    if not teams_channel_config:
        raise ValueError(
            f"Teams channel config with id {teams_channel_config_id} not found"
        )

    if persona_id is not None:
        teams_channel_config.persona_id = persona_id
    if channel_config is not None:
        teams_channel_config.channel_config = channel_config
    if enable_auto_filters is not None:
        teams_channel_config.enable_auto_filters = enable_auto_filters
    if is_default is not None:
        teams_channel_config.is_default = is_default

    if standard_answer_category_ids is not None:
        # Remove existing standard answer categories
        db_session.query(TeamsChannelConfig__StandardAnswerCategory).filter(
            TeamsChannelConfig__StandardAnswerCategory.teams_channel_config_id
            == teams_channel_config_id
        ).delete()

        # Add new standard answer categories
        for standard_answer_category_id in standard_answer_category_ids:
            teams_channel_config__standard_answer_category = (
                TeamsChannelConfig__StandardAnswerCategory(
                    teams_channel_config_id=teams_channel_config_id,
                    standard_answer_category_id=standard_answer_category_id,
                )
            )
            db_session.add(teams_channel_config__standard_answer_category)

    db_session.commit()
    return teams_channel_config


def remove_teams_channel_config(
    db_session: Session,
    teams_channel_config_id: int,
) -> None:
    teams_channel_config = fetch_teams_channel_config(
        db_session=db_session, teams_channel_config_id=teams_channel_config_id
    )
    if not teams_channel_config:
        raise ValueError(
            f"Teams channel config with id {teams_channel_config_id} not found"
        )

    db_session.delete(teams_channel_config)
    db_session.commit()


def fetch_teams_channel_config(
    db_session: Session,
    teams_channel_config_id: int,
) -> TeamsChannelConfig | None:
    return db_session.get(TeamsChannelConfig, teams_channel_config_id)


def fetch_teams_channel_configs(
    db_session: Session,
    teams_bot_id: int,
) -> Sequence[TeamsChannelConfig]:
    return db_session.scalars(
        select(TeamsChannelConfig).where(
            TeamsChannelConfig.teams_bot_id == teams_bot_id
        )
    ).all()


def fetch_teams_channel_config_for_channel_or_default(
    db_session: Session,
    teams_bot_id: int,
    channel_name: str | None = None,
) -> TeamsChannelConfig | None:
    # First try to find a config for the specific channel
    if channel_name:
        teams_channel_configs = db_session.scalars(
            select(TeamsChannelConfig).where(
                TeamsChannelConfig.teams_bot_id == teams_bot_id,
                TeamsChannelConfig.channel_config["channel_name"].astext == channel_name,
            )
        ).all()
        if teams_channel_configs:
            return teams_channel_configs[0]

    # If no specific config found, return the default config
    return db_session.scalar(
        select(TeamsChannelConfig).where(
            TeamsChannelConfig.teams_bot_id == teams_bot_id,
            TeamsChannelConfig.is_default == True,
        )
    ) 