"""Teams bot message handling and response logic."""

from pydantic import BaseModel

from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.models import TeamsChannelConfig
from onyx.db.models import TeamsTeamConfig
from onyx.db.teams_bot import get_channel_config_by_teams_ids
from onyx.db.teams_bot import get_team_config_by_teams_id
from onyx.onyxbot.api_client import OnyxAPIClient
from onyx.onyxbot.exceptions import APIError
from onyx.onyxbot.teams.cards import build_answer_card
from onyx.onyxbot.teams.cards import build_error_card
from onyx.onyxbot.teams.utils import is_bot_mentioned
from onyx.onyxbot.teams.utils import strip_bot_mention
from onyx.utils.logger import setup_logger

logger = setup_logger()


class ShouldRespondContext(BaseModel):
    """Context for whether the bot should respond to a message."""

    should_respond: bool
    persona_id: int | None
    tenant_id: str | None = None
    api_key: str | None = None


def should_respond(
    activity_dict: dict,
    team_id: str | None,
    channel_id: str | None,
    tenant_id: str,
    bot_id: str,
) -> ShouldRespondContext:
    """Determine if bot should respond and which persona to use.

    This is a synchronous function that performs DB lookups.
    """
    no_response = ShouldRespondContext(should_respond=False, persona_id=None)

    if not team_id or not channel_id:
        # DM or group chat — respond if we have a tenant
        return ShouldRespondContext(should_respond=True, persona_id=None)

    with get_session_with_tenant(tenant_id=tenant_id) as db:
        team_config: TeamsTeamConfig | None = get_team_config_by_teams_id(db, team_id)
        if not team_config or not team_config.enabled:
            return no_response

        channel_config: TeamsChannelConfig | None = get_channel_config_by_teams_ids(
            db, team_id, channel_id
        )
        if not channel_config or not channel_config.enabled:
            return no_response

        # Determine persona (channel override or team default)
        persona_id = (
            channel_config.persona_override_id or team_config.default_persona_id
        )

        # Check mention requirement
        if channel_config.require_bot_mention:
            if not is_bot_mentioned(activity_dict, bot_id):
                return no_response

        return ShouldRespondContext(should_respond=True, persona_id=persona_id)


async def process_chat_message(
    text: str,
    api_key: str,
    persona_id: int | None,
    api_client: OnyxAPIClient,
    bot_name: str,
) -> dict:
    """Process a message and return an Adaptive Card response.

    Returns:
        Adaptive Card dict for the response.
    """
    try:
        # Strip bot mention from the message
        clean_text = strip_bot_mention(text, bot_name)
        if not clean_text:
            return build_error_card("Please include a message after the @mention.")

        # Send to Onyx API
        response = await api_client.send_chat_message(
            message=clean_text,
            api_key=api_key,
            persona_id=persona_id,
        )

        answer = response.answer or "I couldn't generate a response."
        return build_answer_card(answer, response)

    except APIError as e:
        logger.error(f"API error processing Teams message: {e}")
        return build_error_card(
            "Sorry, I encountered an error processing your message. "
            "Please try again later."
        )
    except Exception as e:
        logger.exception(f"Error processing Teams chat message: {e}")
        return build_error_card(
            "Sorry, an unexpected error occurred. Please try again later."
        )
