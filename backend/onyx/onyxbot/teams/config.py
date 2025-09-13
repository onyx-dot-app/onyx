import os

from sqlalchemy.orm import Session

from onyx.db.models import TeamsChannelConfig
from onyx.db.teams_channel_config import (
    fetch_teams_channel_config_for_channel_or_default,
)
from onyx.db.teams_channel_config import fetch_teams_channel_configs

VALID_TEAMS_FILTERS = [
    "answerable_prefilter",
    "well_answered_postfilter",
    "questionmark_prefilter",
]


def get_teams_channel_config_for_bot_and_channel(
    db_session: Session,
    teams_bot_id: int,
    channel_name: str | None,
) -> TeamsChannelConfig:
    teams_bot_config = fetch_teams_channel_config_for_channel_or_default(
        db_session=db_session, teams_bot_id=teams_bot_id, channel_name=channel_name
    )
    if not teams_bot_config:
        raise ValueError(
            "No default configuration has been set for this Teams bot. This should not be possible."
        )

    return teams_bot_config


def validate_channel_name(channel_name: str) -> bool:
    """Validate that the channel name is valid for Teams."""
    # Teams channel names can contain letters, numbers, spaces, and some special characters
    # They must be between 1 and 50 characters
    if not channel_name or len(channel_name) > 50:
        return False
    
    # Teams channel names can't contain these characters: < > * / \ ? : |
    invalid_chars = set("< > * / \\ ? : |")
    return not any(c in invalid_chars for c in channel_name)


# Teams-specific configuration variables
TEAMS_BOT_NUM_DOCS_TO_DISPLAY = int(
    os.environ.get("TEAMS_BOT_NUM_DOCS_TO_DISPLAY", "5")
)
TEAMS_BOT_MAX_QPM = int(os.environ.get("TEAMS_BOT_MAX_QPM") or 0) or None
TEAMS_BOT_MAX_WAIT_TIME = int(os.environ.get("TEAMS_BOT_MAX_WAIT_TIME") or 180)
TEAMS_BOT_FEEDBACK_REMINDER = int(
    os.environ.get("TEAMS_BOT_FEEDBACK_REMINDER") or 0
)
TEAMS_BOT_REPHRASE_MESSAGE = (
    os.environ.get("TEAMS_BOT_REPHRASE_MESSAGE", "").lower() == "true"
)
TEAMS_BOT_RESPONSE_LIMIT_PER_TIME_PERIOD = int(
    os.environ.get("TEAMS_BOT_RESPONSE_LIMIT_PER_TIME_PERIOD", "5000")
)
TEAMS_BOT_RESPONSE_LIMIT_TIME_PERIOD_SECONDS = int(
    os.environ.get("TEAMS_BOT_RESPONSE_LIMIT_TIME_PERIOD_SECONDS", "86400")
)
TEAMS_BOT_RESPOND_EVERY_CHANNEL = (
    os.environ.get("TEAMS_BOT_RESPOND_EVERY_CHANNEL", "").lower() == "true"
)
NOTIFY_TEAMS_BOT_NO_ANSWER = (
    os.environ.get("NOTIFY_TEAMS_BOT_NO_ANSWER", "").lower() == "true"
) 