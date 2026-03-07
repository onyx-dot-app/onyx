"""Utility functions for Teams bot."""

from onyx.configs.app_configs import TEAMS_BOT_APP_ID
from onyx.configs.app_configs import TEAMS_BOT_APP_SECRET
from onyx.configs.app_configs import TEAMS_BOT_AZURE_TENANT_ID
from onyx.utils.logger import setup_logger

logger = setup_logger()


def get_bot_credentials_from_env() -> tuple[str, str, str | None] | None:
    """Get bot credentials from environment variables.

    Returns:
        (app_id, app_secret, azure_tenant_id) or None if not configured.
    """
    if not TEAMS_BOT_APP_ID or not TEAMS_BOT_APP_SECRET:
        return None
    return TEAMS_BOT_APP_ID, TEAMS_BOT_APP_SECRET, TEAMS_BOT_AZURE_TENANT_ID


def extract_team_id(activity: dict) -> str | None:
    """Extract the Teams team ID from an Activity's channelData.

    Teams Activities include channelData.team.id for messages in team channels.
    For 1:1 or group chats, this will be None.
    """
    channel_data = activity.get("channelData", {})
    team = channel_data.get("team")
    if team:
        return team.get("id")
    return None


def extract_channel_id(activity: dict) -> str | None:
    """Extract the Teams channel ID from an Activity's channelData."""
    channel_data = activity.get("channelData", {})
    channel = channel_data.get("channel")
    if channel:
        return channel.get("id")
    return None


def extract_team_name(activity: dict) -> str | None:
    """Extract the Teams team name from an Activity's channelData."""
    channel_data = activity.get("channelData", {})
    team = channel_data.get("team")
    if team:
        return team.get("name")
    return None


def strip_bot_mention(text: str, bot_name: str) -> str:
    """Remove the bot @mention from the message text.

    Teams includes the @mention in the message text as <at>BotName</at>.
    """
    import re

    # Remove <at>BotName</at> tags
    cleaned = re.sub(
        rf"<at>{re.escape(bot_name)}</at>",
        "",
        text,
        flags=re.IGNORECASE,
    )
    # Also try without the specific name (some clients send generic)
    cleaned = re.sub(r"<at>[^<]*</at>", "", cleaned)
    return cleaned.strip()


def is_bot_mentioned(activity: dict, bot_id: str) -> bool:
    """Check if the bot is mentioned in the activity.

    Teams includes mentions in the activity entities array.
    """
    entities = activity.get("entities", [])
    for entity in entities:
        if entity.get("type") == "mention":
            mentioned = entity.get("mentioned", {})
            if mentioned.get("id") == bot_id:
                return True
    return False
