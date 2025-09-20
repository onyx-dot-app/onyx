from typing import Any
from typing import cast

from fastapi import APIRouter
from sqlalchemy.orm import Session

from onyx.db.models import TeamsBot
from onyx.onyxbot.teams.config import get_channel_config
from onyx.onyxbot.teams.constants import (
    TEAMS_MESSAGE_TYPE,
    TEAMS_SUBSCRIPTION_NOTIFICATION,
)
from onyx.onyxbot.teams.events import router as events_router
from onyx.onyxbot.teams.init import (
    cleanup_teams_bot,
    initialize_teams_bot,
    update_teams_bot_config,
    validate_teams_bot_config,
)
from onyx.onyxbot.teams.models import TeamsMessageInfo
from onyx.onyxbot.teams.processor import TeamsBotProcessor
from onyx.onyxbot.teams.response import TeamsBotResponseGenerator
from onyx.onyxbot.teams.reactions import TeamsBotReactionHandler
from onyx.onyxbot.teams.utils import (
    get_teams_access_token,
    get_teams_channel_name_from_id,
    get_teams_user_email,
    send_teams_message,
)
from onyx.utils.logger import setup_logger


logger = setup_logger()
router = APIRouter()


# Include events router
router.include_router(events_router)


def create_teams_bot(
    db_session: Session,
    teams_bot: TeamsBot,
) -> bool:
    """Create a new Teams bot."""
    try:
        # Validate configuration
        if not validate_teams_bot_config(db_session, teams_bot):
            return False

        # Initialize bot
        if not initialize_teams_bot(db_session, teams_bot):
            return False

        return True

    except Exception as e:
        logger.error(f"Error creating Teams bot: {str(e)}")
        return False


def delete_teams_bot(
    db_session: Session,
    teams_bot: TeamsBot,
) -> bool:
    """Delete a Teams bot."""
    try:
        # Clean up bot
        if not cleanup_teams_bot(db_session, teams_bot):
            return False

        return True

    except Exception as e:
        logger.error(f"Error deleting Teams bot: {str(e)}")
        return False


def update_teams_bot(
    db_session: Session,
    teams_bot: TeamsBot,
    config: dict[str, Any],
) -> bool:
    """Update a Teams bot."""
    try:
        # Update configuration
        if not update_teams_bot_config(db_session, teams_bot, config):
            return False

        return True

    except Exception as e:
        logger.error(f"Error updating Teams bot: {str(e)}")
        return False


def process_teams_message(
    db_session: Session,
    teams_bot: TeamsBot,
    message_info: TeamsMessageInfo,
    content: str,
) -> None:
    """Process a Teams message."""
    try:
        # Create processor
        processor = TeamsBotProcessor(db_session, teams_bot)

        # Process message
        processor.process_message(message_info, content)

    except Exception as e:
        logger.error(f"Error processing Teams message: {str(e)}")


def process_teams_action(
    db_session: Session,
    teams_bot: TeamsBot,
    action_type: str,
    message_id: str,
    channel_id: str,
    user_id: str,
    emoji: str | None = None,
) -> None:
    """Process a Teams action."""
    try:
        # Create processor
        processor = TeamsBotProcessor(db_session, teams_bot)

        # Process action
        processor.process_action(
            action_type=action_type,
            message_id=message_id,
            channel_id=channel_id,
            user_id=user_id,
            emoji=emoji,
        )

    except Exception as e:
        logger.error(f"Error processing Teams action: {str(e)}") 