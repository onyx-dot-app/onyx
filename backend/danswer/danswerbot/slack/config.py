import os

from sqlalchemy.orm import Session

from danswer.db.models import SlackBotConfig
from danswer.db.slack_bot_config import fetch_slack_bot_configs


VALID_SLACK_FILTERS = [
    "answerable_prefilter",
    "well_answered_postfilter",
    "questionmark_prefilter",
]


def get_slack_bot_config_for_channel(
    channel_name: str | None, db_session: Session
) -> SlackBotConfig | None:
    if not channel_name:
        return None

    slack_bot_configs = fetch_slack_bot_configs(db_session=db_session)
    for config in slack_bot_configs:
        if channel_name in config.channel_config["channel_names"]:
            return config

    return None


def validate_channel_names(
    channel_names: list[str],
    current_slack_bot_config_id: int | None,
    db_session: Session,
) -> list[str]:
    """Make sure that these channel_names don't exist in other slack bot configs.
    Returns a list of cleaned up channel names (e.g. '#' removed if present)"""
    slack_bot_configs = fetch_slack_bot_configs(db_session=db_session)
    cleaned_channel_names = [
        channel_name.lstrip("#").lower() for channel_name in channel_names
    ]
    for slack_bot_config in slack_bot_configs:
        if slack_bot_config.id == current_slack_bot_config_id:
            continue

        for channel_name in cleaned_channel_names:
            if channel_name in slack_bot_config.channel_config["channel_names"]:
                raise ValueError(
                    f"Channel name '{channel_name}' already exists in "
                    "another slack bot config"
                )

    return cleaned_channel_names


# Scaling configurations for multi-tenant Slack bot handling
TENANT_LOCK_EXPIRATION = 1800  # How long a pod can hold exclusive access to a tenant before other pods can acquire it
TENANT_HEARTBEAT_INTERVAL = (
    60  # How often pods send heartbeats to indicate they are still processing a tenant
)
TENANT_HEARTBEAT_EXPIRATION = 180  # How long before a tenant's heartbeat expires, allowing other pods to take over
TENANT_ACQUISITION_INTERVAL = (
    60  # How often pods attempt to acquire unprocessed tenants
)

MAX_TENANTS_PER_POD = int(os.getenv("MAX_TENANTS_PER_POD", 50))
