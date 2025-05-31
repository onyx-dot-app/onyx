from typing import Any
from typing import cast

from sqlalchemy.orm import Session

from onyx.db.models import TeamsBot, StandardAnswer
from onyx.db.teams_bot import fetch_teams_bot_tokens
from onyx.onyxbot.teams.config import get_channel_config
from onyx.onyxbot.teams.constants import (
    TEAMS_CODE_BLOCK_FORMAT,
    TEAMS_MESSAGE_FORMAT,
)
from onyx.onyxbot.teams.models import TeamsMessageInfo
from onyx.onyxbot.teams.utils import (
    format_teams_bold,
    format_teams_code_block,
    format_teams_link,
    format_teams_message,
)
from onyx.utils.logger import setup_logger
from onyx.chat.process_message import prepare_chat_message_request
from onyx.chat.process_message import stream_chat_message_objects
from onyx.context.search.models import RetrievalDetails
from onyx.context.search.models import BaseFilters
from onyx.context.search.models import OptionalSearchSetting


logger = setup_logger()


class TeamsBotResponseGenerator:
    """Generate responses for Teams messages."""

    def __init__(
        self,
        db_session: Session,
        teams_bot: TeamsBot,
    ):
        """Initialize the Teams bot response generator."""
        self.db_session = db_session
        self.teams_bot = teams_bot

    def generate_response(
        self,
        content: str,
        message_info: TeamsMessageInfo,
        channel_config: dict[str, Any],
    ) -> str | None:
        """Generate a response to a Teams message."""
        try:
            # Get response from standard answers
            response = self._get_standard_answer(content, channel_config)
            if response:
                return self._format_response(response)

            # Get response from custom answers
            response = self._get_custom_answer(content, channel_config)
            if response:
                return self._format_response(response)

            # Get response from AI
            response = self._get_ai_response(content, channel_config)
            if response:
                return self._format_response(response)

            return None

        except Exception as e:
            logger.error(f"Error generating Teams response: {str(e)}")
            return None

    def _get_standard_answer(
        self,
        content: str,
        channel_config: dict[str, Any],
    ) -> str | None:
        """Get a response from standard answers."""
        try:
            # Get configured standard answer categories
            categories = channel_config.get("standard_answer_categories", [])
            if not categories:
                return None

            # Get standard answers from categories
            standard_answers = []
            for category in categories:
                standard_answers.extend(category.standard_answers)

            # Find matching standard answers
            matching_answers = []
            for answer in standard_answers:
                if answer.matches_query(content):
                    matching_answers.append(answer)

            if not matching_answers:
                return None

            # Format matching answers
            formatted_answers = []
            for answer in matching_answers:
                formatted_answer = f"Since your question contains relevant keywords, here's a helpful answer:\n\n{answer.answer}"
                formatted_answers.append(formatted_answer)

            return "\n\n".join(formatted_answers)

        except Exception as e:
            logger.error(f"Error getting standard answer: {str(e)}")
            return None

    def _get_custom_answer(
        self,
        content: str,
        channel_config: dict[str, Any],
    ) -> str | None:
        """Get a response from custom answers."""
        try:
            # Get custom answers from channel config
            custom_answers = channel_config.get("custom_answers", [])
            if not custom_answers:
                return None

            # Find matching custom answers
            matching_answers = []
            for answer in custom_answers:
                if answer.get("keywords") and any(keyword in content.lower() for keyword in answer["keywords"]):
                    matching_answers.append(answer)

            if not matching_answers:
                return None

            # Format matching answers
            formatted_answers = []
            for answer in matching_answers:
                formatted_answer = f"Based on your question, here's a relevant answer:\n\n{answer['response']}"
                formatted_answers.append(formatted_answer)

            return "\n\n".join(formatted_answers)

        except Exception as e:
            logger.error(f"Error getting custom answer: {str(e)}")
            return None

    def _get_ai_response(
        self,
        content: str,
        channel_config: dict[str, Any],
    ) -> str | None:
        """Get a response from AI."""
        try:
            # Get persona from channel config
            persona = channel_config.get("persona")
            if not persona:
                return None

            # Prepare chat message request
            filters = BaseFilters(
                source_type=None,
                document_set=channel_config.get("document_sets", []),
                time_cutoff=None,
            )

            retrieval_details = RetrievalDetails(
                run_search=OptionalSearchSetting.ALWAYS,
                real_time=False,
                filters=filters,
                enable_auto_detect_filters=channel_config.get("enable_auto_filters", True),
            )

            answer_request = prepare_chat_message_request(
                message_text=content,
                user=None,  # Teams bot doesn't have a user
                persona_id=persona.id,
                persona_override_config=None,
                prompt=None,
                message_ts_to_respond_to=None,
                retrieval_details=retrieval_details,
                rerank_settings=None,
                db_session=self.db_session,
            )

            # Get AI response
            answer = stream_chat_message_objects(answer_request)
            if not answer or not answer.answer:
                return None

            # Format response with citations if available
            response = answer.answer
            if answer.citations:
                response += "\n\n**Sources:**\n"
                for i, citation in enumerate(answer.citations, 1):
                    response += f"{i}. {citation}\n"

            return response

        except Exception as e:
            logger.error(f"Error getting AI response: {str(e)}")
            return None

    def _format_response(
        self,
        response: str,
    ) -> str:
        """Format a response for Teams."""
        try:
            # Format code blocks
            response = response.replace("```", TEAMS_CODE_BLOCK_FORMAT)

            # Format links
            response = response.replace("[", "[").replace("]", "](")

            # Format bold text
            response = response.replace("**", format_teams_bold(""))

            # Format message
            return format_teams_message(response)

        except Exception as e:
            logger.error(f"Error formatting Teams response: {str(e)}")
            return response 