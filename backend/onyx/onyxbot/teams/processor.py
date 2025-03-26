from typing import Any
from typing import cast

from sqlalchemy.orm import Session

from onyx.db.models import TeamsBot
from onyx.db.teams_bot import fetch_teams_bot_tokens
from onyx.onyxbot.teams.config import get_channel_config
from onyx.onyxbot.teams.constants import (
    TEAMS_LIKE_EMOJI,
    TEAMS_DISLIKE_EMOJI,
)
from onyx.onyxbot.teams.models import TeamsMessageInfo
from onyx.onyxbot.teams.reactions import TeamsBotReactionHandler
from onyx.onyxbot.teams.response import TeamsBotResponseGenerator
from onyx.onyxbot.teams.utils import (
    add_teams_reaction,
    format_teams_message,
    get_teams_access_token,
    remove_teams_reaction,
    send_teams_message,
)
from onyx.utils.logger import setup_logger


logger = setup_logger()


class TeamsBotProcessor:
    """Process Teams messages and generate responses."""

    def __init__(
        self,
        db_session: Session,
        teams_bot: TeamsBot,
    ):
        """Initialize the Teams bot processor."""
        self.db_session = db_session
        self.teams_bot = teams_bot
        self.access_token = get_teams_access_token(db_session, teams_bot.id)
        self.response_generator = TeamsBotResponseGenerator(db_session, teams_bot)
        self.reaction_handler = TeamsBotReactionHandler(db_session, teams_bot)

    def process_message(
        self,
        message_info: TeamsMessageInfo,
        content: str,
    ) -> None:
        """Process a Teams message and generate a response."""
        try:
            if not self.access_token:
                logger.error("Failed to get access token")
                return

            # Get channel configuration
            channel_config = get_channel_config(
                db_session=self.db_session,
                teams_bot_id=self.teams_bot.id,
                channel_id=message_info.channel_to_respond,
            )
            if not channel_config:
                logger.warning(f"No configuration found for channel {message_info.channel_to_respond}")
                return

            # Check if message should be processed
            if not self._should_process_message(message_info, channel_config):
                return

            # Generate response
            response = self.response_generator.generate_response(
                content=content,
                message_info=message_info,
                channel_config=channel_config,
            )
            if not response:
                return

            # Send response
            self._send_response(message_info, response)

        except Exception as e:
            logger.error(f"Error processing Teams message: {str(e)}")

    def process_action(
        self,
        action_type: str,
        message_id: str,
        channel_id: str,
        user_id: str,
        emoji: str | None = None,
    ) -> None:
        """Process a Teams message action."""
        try:
            if not self.access_token:
                logger.error("Failed to get access token")
                return

            if action_type == "reaction_added":
                if emoji:
                    self.reaction_handler.handle_reaction_added(
                        message_id=message_id,
                        channel_id=channel_id,
                        user_id=user_id,
                        emoji=emoji,
                    )
            elif action_type == "reaction_removed":
                if emoji:
                    self.reaction_handler.handle_reaction_removed(
                        message_id=message_id,
                        channel_id=channel_id,
                        user_id=user_id,
                        emoji=emoji,
                    )
            elif action_type == "feedback":
                if emoji in [TEAMS_LIKE_EMOJI, TEAMS_DISLIKE_EMOJI]:
                    self.reaction_handler.handle_feedback(
                        message_id=message_id,
                        channel_id=channel_id,
                        user_id=user_id,
                        is_positive=emoji == TEAMS_LIKE_EMOJI,
                    )

        except Exception as e:
            logger.error(f"Error processing Teams action: {str(e)}")

    def _should_process_message(
        self,
        message_info: TeamsMessageInfo,
        channel_config: dict[str, Any],
    ) -> bool:
        """Check if a message should be processed based on configuration."""
        # Skip if message is from a bot
        if message_info.is_bot_msg:
            return False

        # Skip if message is a DM and not configured for DMs
        if message_info.is_bot_dm and not channel_config.get("allow_dm", False):
            return False

        # Skip if message is in a thread and not configured for threads
        if message_info.thread_to_respond and not channel_config.get("allow_threads", False):
            return False

        return True

    def _send_response(
        self,
        message_info: TeamsMessageInfo,
        response: str,
    ) -> None:
        """Send a response to a Teams message."""
        try:
            success = send_teams_message(
                access_token=self.access_token,
                team_id=self.teams_bot.team_id,
                channel_id=message_info.channel_to_respond,
                message=response,
                reply_to_message_id=message_info.msg_to_respond,
            )
            if not success:
                logger.error("Failed to send Teams message")

        except Exception as e:
            logger.error(f"Error sending Teams message: {str(e)}") 