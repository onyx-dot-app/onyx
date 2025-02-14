import os

from sqlalchemy.orm import Session

from onyx.db.discord_channel_config import fetch_discord_channel_configs
from onyx.db.models import DiscordChannelConfig


VALID_DISCORD_FILTERS = [
    "answerable_prefilter",
    "well_answered_postfilter",
    "questionmark_prefilter",
]


def clean_channel_name(channel_name: str) -> str:
    return channel_name.lstrip("#").lower()


def get_discord_channel_config_for_bot_and_channel(
    db_session: Session,
    discord_bot_id: int,
    channel_name: str | None,
) -> DiscordChannelConfig | None:
    if not channel_name:
        return None

    cleaned_channel_name = clean_channel_name(channel_name)

    discord_bot_configs = fetch_discord_channel_configs(
        db_session=db_session, discord_bot_id=discord_bot_id
    )
    for config in discord_bot_configs:
        stored_name = config.channel_config["channel_name"].lower()
        if cleaned_channel_name == stored_name:
            return config

    return None


def validate_channel_name(
    db_session: Session,
    current_discord_bot_id: int,
    channel_name: str,
    current_discord_channel_config_id: int | None,
) -> str:
    """Make sure that this channel_name does not exist in other Discord channel configs.
    Returns a cleaned up channel name (e.g. '#' removed if present)"""
    discord_bot_configs = fetch_discord_channel_configs(
        db_session=db_session,
        discord_bot_id=current_discord_bot_id,
    )
    cleaned_channel_name = clean_channel_name(channel_name)
    for discord_channel_config in discord_bot_configs:
        if discord_channel_config.id == current_discord_channel_config_id:
            continue

        stored_name = discord_channel_config.channel_config["channel_name"].lower()
        if cleaned_channel_name == stored_name:
            raise ValueError(
                f"Channel name '{channel_name}' already exists in "
                "another Discord channel config within Discord Bot with name: "
                f"{discord_channel_config.discord_bot.name}"
            )

    return cleaned_channel_name


# Scaling configurations for multi-tenant Discord channel handling
TENANT_LOCK_EXPIRATION = 1800  # How long a pod can hold exclusive access to a tenant before other pods can acquire it
TENANT_HEARTBEAT_INTERVAL = (
    15  # How often pods send heartbeats to indicate they are still processing a tenant
)
TENANT_HEARTBEAT_EXPIRATION = (
    30  # How long before a tenant's heartbeat expires, allowing other pods to take over
)
TENANT_ACQUISITION_INTERVAL = 60  # How often pods attempt to acquire unprocessed tenants and checks for new tokens

MAX_TENANTS_PER_POD = int(os.getenv("MAX_TENANTS_PER_POD", 50))
