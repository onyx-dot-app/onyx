from typing import Any
from typing import cast

from sqlalchemy.orm import Session

from onyx.db.models import TeamsBot
from onyx.db.teams_bot import fetch_teams_bot_tokens
from onyx.onyxbot.teams.constants import (
    TEAMS_LIKE_EMOJI,
    TEAMS_DISLIKE_EMOJI,
)
from onyx.onyxbot.teams.utils import (
    add_teams_reaction,
    get_teams_access_token,
    remove_teams_reaction,
)
from onyx.utils.logger import setup_logger


logger = setup_logger()


class TeamsBotReactionHandler:
    """Handle Teams message reactions."""

    def __init__(
        self,
        db_session: Session,
        teams_bot: TeamsBot,
    ):
        """Initialize the Teams bot reaction handler."""
        self.db_session = db_session
        self.teams_bot = teams_bot
        self.access_token = get_teams_access_token(db_session, teams_bot.id)

    def handle_reaction_added(
        self,
        message_id: str,
        channel_id: str,
        user_id: str,
        emoji: str,
    ) -> None:
        """Handle a reaction added to a message."""
        try:
            if not self.access_token:
                logger.error("Failed to get access token")
                return

            # Add reaction
            success = add_teams_reaction(
                access_token=self.access_token,
                team_id=self.teams_bot.team_id,
                channel_id=channel_id,
                message_id=message_id,
                emoji=emoji,
            )
            if not success:
                logger.error("Failed to add Teams reaction")

        except Exception as e:
            logger.error(f"Error handling Teams reaction added: {str(e)}")

    def handle_reaction_removed(
        self,
        message_id: str,
        channel_id: str,
        user_id: str,
        emoji: str,
    ) -> None:
        """Handle a reaction removed from a message."""
        try:
            if not self.access_token:
                logger.error("Failed to get access token")
                return

            # Remove reaction
            success = remove_teams_reaction(
                access_token=self.access_token,
                team_id=self.teams_bot.team_id,
                channel_id=channel_id,
                message_id=message_id,
                emoji=emoji,
            )
            if not success:
                logger.error("Failed to remove Teams reaction")

        except Exception as e:
            logger.error(f"Error handling Teams reaction removed: {str(e)}")

    def handle_feedback(
        self,
        message_id: str,
        channel_id: str,
        user_id: str,
        is_positive: bool,
    ) -> None:
        """Handle feedback reactions (like/dislike)."""
        try:
            if not self.access_token:
                logger.error("Failed to get access token")
                return

            # Add appropriate reaction
            emoji = TEAMS_LIKE_EMOJI if is_positive else TEAMS_DISLIKE_EMOJI
            success = add_teams_reaction(
                access_token=self.access_token,
                team_id=self.teams_bot.team_id,
                channel_id=channel_id,
                message_id=message_id,
                emoji=emoji,
            )
            if not success:
                logger.error("Failed to add Teams feedback reaction")

        except Exception as e:
            logger.error(f"Error handling Teams feedback: {str(e)}") 