from typing import Any
from typing import cast

from fastapi import APIRouter
from fastapi import Request
from sqlalchemy.orm import Session

from onyx.db.models import TeamsBot
from onyx.db.teams_bot import fetch_teams_bot_tokens
from onyx.onyxbot.teams.constants import (
    TEAMS_MESSAGE_TYPE,
    TEAMS_SUBSCRIPTION_NOTIFICATION,
)
from onyx.onyxbot.teams.models import TeamsMessageInfo
from onyx.onyxbot.teams.processor import TeamsBotProcessor
from onyx.onyxbot.teams.utils import (
    get_teams_access_token,
    get_teams_channel_name_from_id,
    get_teams_user_email,
    send_teams_message,
    validate_teams_webhook,
)
from onyx.utils.logger import setup_logger


logger = setup_logger()
router = APIRouter()


@router.post("/teams/webhook")
async def handle_teams_webhook(
    request: Request,
    db_session: Session,
) -> dict[str, Any]:
    """Handle incoming Teams webhook notifications."""
    try:
        body = await request.json()
        notification_type = body.get("value", [{}])[0].get("changeType")
        resource_data = body.get("value", [{}])[0].get("resourceData", {})

        if notification_type == TEAMS_SUBSCRIPTION_NOTIFICATION:
            # Handle subscription validation
            validation_token = body.get("validationToken")
            if validation_token:
                return validate_teams_webhook(validation_token)

            # Process message notifications
            message_data = resource_data.get("message", {})
            if not message_data:
                return {"status": "success"}

            # Extract message information
            message_id = message_data.get("id")
            channel_id = message_data.get("channelId")
            team_id = message_data.get("teamId")
            sender_id = message_data.get("from", {}).get("user", {}).get("id")
            content = message_data.get("body", {}).get("content", "")

            if not all([message_id, channel_id, team_id, sender_id]):
                return {"status": "success"}

            # Get Teams bot information
            teams_bot = db_session.query(TeamsBot).filter(
                TeamsBot.team_id == team_id,
            ).first()
            if not teams_bot:
                return {"status": "success"}

            # Get access token
            access_token = get_teams_access_token(db_session, teams_bot.id)
            if not access_token:
                return {"status": "error", "message": "Failed to get access token"}

            # Get additional information
            channel_name = get_teams_channel_name_from_id(
                access_token=access_token,
                channel_id=channel_id,
                team_id=team_id,
            )
            sender_email = get_teams_user_email(
                access_token=access_token,
                user_id=sender_id,
            )

            # Create message info object
            message_info = TeamsMessageInfo(
                thread_messages=[],
                channel_to_respond=channel_id,
                msg_to_respond=message_id,
                thread_to_respond=None,
                sender_id=sender_id,
                email=sender_email,
                bypass_filters=False,
                is_bot_msg=False,
                is_bot_dm=False,
            )

            # Process message using Teams bot processor
            processor = TeamsBotProcessor(db_session, teams_bot)
            processor.process_message(message_info, content)

            return {"status": "success"}

        return {"status": "success"}

    except Exception as e:
        logger.error(f"Error handling Teams webhook: {str(e)}")
        return {"status": "error", "message": str(e)}


@router.post("/teams/actions")
async def handle_teams_actions(
    request: Request,
    db_session: Session,
) -> dict[str, Any]:
    """Handle Teams message actions (e.g., reactions)."""
    try:
        body = await request.json()
        action_type = body.get("type")
        message_id = body.get("messageId")
        channel_id = body.get("channelId")
        team_id = body.get("teamId")
        user_id = body.get("userId")

        if not all([action_type, message_id, channel_id, team_id, user_id]):
            return {"status": "error", "message": "Missing required fields"}

        # Get Teams bot information
        teams_bot = db_session.query(TeamsBot).filter(
            TeamsBot.team_id == team_id,
        ).first()
        if not teams_bot:
            return {"status": "error", "message": "Teams bot not found"}

        # Get access token
        access_token = get_teams_access_token(db_session, teams_bot.id)
        if not access_token:
            return {"status": "error", "message": "Failed to get access token"}

        # Process action using Teams bot processor
        processor = TeamsBotProcessor(db_session, teams_bot)
        processor.process_action(action_type, message_id, channel_id, user_id)

        return {"status": "success"}

    except Exception as e:
        logger.error(f"Error handling Teams actions: {str(e)}")
        return {"status": "error", "message": str(e)} 