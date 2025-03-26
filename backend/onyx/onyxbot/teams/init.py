from typing import Any
from typing import cast

from sqlalchemy.orm import Session

from onyx.db.models import TeamsBot, TeamsChannelConfig
from onyx.db.teams_bot import fetch_teams_bot_tokens
from onyx.onyxbot.teams.constants import (
    TEAMS_GRAPH_API_BASE,
    TEAMS_SCOPE,
)
from onyx.onyxbot.teams.utils import (
    create_teams_subscription,
    get_teams_access_token,
    delete_teams_subscription,
    validate_teams_access,
)
from onyx.utils.logger import setup_logger


logger = setup_logger()


def initialize_teams_bot(
    db_session: Session,
    teams_bot: TeamsBot,
) -> bool:
    """Initialize a Teams bot with necessary subscriptions."""
    try:
        # Get access token
        access_token = get_teams_access_token(db_session, teams_bot.id)
        if not access_token:
            logger.error("Failed to get access token")
            return False

        # Create subscription for team messages
        subscription = create_teams_subscription(
            access_token=access_token,
            resource=f"{TEAMS_GRAPH_API_BASE}/teams/{teams_bot.team_id}/channels",
            notification_url=teams_bot.webhook_url,
        )
        if not subscription:
            logger.error("Failed to create Teams subscription")
            return False

        # Store subscription information in database
        teams_bot.subscription_id = subscription.get("id")
        teams_bot.subscription_expiry = subscription.get("expirationDateTime")
        db_session.commit()

        return True

    except Exception as e:
        logger.error(f"Error initializing Teams bot: {str(e)}")
        return False


def cleanup_teams_bot(
    db_session: Session,
    teams_bot: TeamsBot,
) -> bool:
    """Clean up a Teams bot and its subscriptions."""
    try:
        # Delete subscriptions if they exist
        if teams_bot.subscription_id:
            access_token = get_teams_access_token(db_session, teams_bot.id)
            if access_token:
                delete_teams_subscription(access_token, teams_bot.subscription_id)

        # Clean up channel configs
        db_session.query(TeamsChannelConfig).filter(
            TeamsChannelConfig.teams_bot_id == teams_bot.id
        ).delete()

        return True

    except Exception as e:
        logger.error(f"Error cleaning up Teams bot: {str(e)}")
        return False


def validate_teams_bot_config(
    db_session: Session,
    teams_bot: TeamsBot,
) -> bool:
    """Validate a Teams bot configuration."""
    try:
        # Get access token
        access_token = get_teams_access_token(db_session, teams_bot.id)
        if not access_token:
            logger.error("Failed to get access token")
            return False

        # Validate team access
        if not validate_teams_access(access_token, teams_bot.team_id):
            logger.error("Failed to validate team access")
            return False

        return True

    except Exception as e:
        logger.error(f"Error validating Teams bot config: {str(e)}")
        return False


def update_teams_bot_config(
    db_session: Session,
    teams_bot: TeamsBot,
    config: dict[str, Any],
) -> bool:
    """Update a Teams bot configuration."""
    try:
        # Update basic fields
        for field, value in config.items():
            if hasattr(teams_bot, field):
                setattr(teams_bot, field, value)

        # Update channel configs if provided
        if "channel_configs" in config:
            # Delete existing configs
            db_session.query(TeamsChannelConfig).filter(
                TeamsChannelConfig.teams_bot_id == teams_bot.id
            ).delete()

            # Add new configs
            for channel_config in config["channel_configs"]:
                new_config = TeamsChannelConfig(
                    teams_bot_id=teams_bot.id,
                    channel_config=channel_config,
                )
                db_session.add(new_config)

        db_session.commit()
        return True

    except Exception as e:
        logger.error(f"Error updating Teams bot config: {str(e)}")
        return False 