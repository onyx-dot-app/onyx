import os

from sqlalchemy.orm import Session

from onyx.db.models import SlackChannelConfig
from onyx.db.slack_channel_config import (
    fetch_slack_channel_config_for_channel_or_default,
)
from onyx.db.slack_channel_config import fetch_slack_channel_configs

VALID_SLACK_FILTERS = [
    "answerable_prefilter",
    "well_answered_postfilter",
    "questionmark_prefilter",
]


def get_slack_channel_config_for_bot_and_channel(
    db_session: Session,
    slack_bot_id: int,
    channel_name: str | None,
) -> SlackChannelConfig:
    slack_bot_config = fetch_slack_channel_config_for_channel_or_default(
        db_session=db_session, slack_bot_id=slack_bot_id, channel_name=channel_name
    )
    if not slack_bot_config:
        raise ValueError(
            "No default configuration has been set for this Slack bot. This should not be possible."
        )

    return slack_bot_config


def validate_channel_name(
    db_session: Session,
    current_slack_bot_id: int,
    channel_name: str,
    current_slack_channel_config_id: int | None,
) -> str:
    """Make sure that this channel_name does not exist in other Slack channel configs.
    Returns a cleaned up channel name (e.g. '#' removed if present)"""
    slack_bot_configs = fetch_slack_channel_configs(
        db_session=db_session,
        slack_bot_id=current_slack_bot_id,
    )
    cleaned_channel_name = channel_name.lstrip("#").lower()
    for slack_channel_config in slack_bot_configs:
        if slack_channel_config.id == current_slack_channel_config_id:
            continue

        if cleaned_channel_name == slack_channel_config.channel_config["channel_name"]:
            raise ValueError(
                f"Channel name '{channel_name}' already exists in "
                "another Slack channel config with in Slack Bot with name: "
                f"{slack_channel_config.slack_bot.name}"
            )

    return cleaned_channel_name


# Scaling configurations for multi-tenant Slack channel handling
TENANT_LOCK_EXPIRATION = 1800  # How long a pod can hold exclusive access to a tenant before other pods can acquire it
TENANT_HEARTBEAT_INTERVAL = (
    15  # How often pods send heartbeats to indicate they are still processing a tenant
)
TENANT_HEARTBEAT_EXPIRATION = (
    60  # How long before a tenant's heartbeat expires, allowing other pods to take over
)
TENANT_ACQUISITION_INTERVAL = 60  # How often pods attempt to acquire unprocessed tenants and checks for new tokens

MAX_TENANTS_PER_POD = int(os.getenv("MAX_TENANTS_PER_POD", 50))
