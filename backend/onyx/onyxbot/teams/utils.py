import json
from datetime import datetime, timedelta, UTC
from typing import Any
from typing import cast

import requests
from msal import ConfidentialClientApplication
from sqlalchemy.orm import Session

from onyx.db.models import TeamsBot, TeamsChannelConfig
from onyx.db.teams_bot import fetch_teams_bot_tokens
from onyx.onyxbot.teams.constants import (
    TEAMS_AUTH_ENDPOINT,
    TEAMS_GRAPH_API_BASE,
    TEAMS_GRAPH_API_BETA,
    TEAMS_SCOPE,
    TEAMS_SUBSCRIPTION_EXPIRY_DAYS,
    TEAMS_SUBSCRIPTION_RENEWAL_BUFFER_HOURS,
)
from onyx.utils.logger import setup_logger


logger = setup_logger()


def get_teams_bot_id(teams_bot: TeamsBot) -> str:
    """Get the Teams bot ID from the TeamsBot model."""
    return f"teams_bot_{teams_bot.id}"


def get_teams_channel_name_from_id(
    access_token: str,
    channel_id: str,
    team_id: str,
) -> str | None:
    """Get the channel name from a channel ID using the Graph API."""
    url = f"{TEAMS_GRAPH_API_BASE}/teams/{team_id}/channels/{channel_id}"
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.json().get("displayName")
    return None


def get_teams_user_email(
    access_token: str,
    user_id: str,
) -> str | None:
    """Get the user's email from their user ID using the Graph API."""
    url = f"{TEAMS_GRAPH_API_BASE}/users/{user_id}"
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.json().get("userPrincipalName")
    return None


def get_teams_access_token(
    db_session: Session,
    teams_bot_id: int,
) -> str | None:
    """Get a valid access token for the Teams bot using MSAL."""
    tokens = fetch_teams_bot_tokens(db_session=db_session, teams_bot_id=teams_bot_id)
    if not tokens:
        return None

    app = ConfidentialClientApplication(
        client_id=tokens["client_id"],
        client_credential=tokens["client_secret"],
        authority=TEAMS_AUTH_ENDPOINT.format(tenant_id=tokens["tenant_id"]),
    )

    result = app.acquire_token_silent(
        scopes=[TEAMS_SCOPE],
        account=None,
    )
    if not result:
        result = app.acquire_token_for_client(
            scopes=[TEAMS_SCOPE],
        )

    if "access_token" in result:
        return result["access_token"]
    return None


def format_teams_message(
    text: str,
    sources: list[dict[str, Any]] | None = None,
) -> str:
    """Format a message for Teams with markdown."""
    message = text

    if sources:
        message += "\n\n**Sources:**\n"
        for i, source in enumerate(sources, 1):
            title = source.get("title", f"Source {i}")
            url = source.get("url", "")
            if url:
                message += f"{i}. [{title}]({url})\n"
            else:
                message += f"{i}. {title}\n"

    return message


def format_teams_code_block(text: str) -> str:
    """Format text as a code block for Teams."""
    return f"```\n{text}\n```"


def format_teams_quote(text: str) -> str:
    """Format text as a quote for Teams."""
    return f"> {text}"


def format_teams_link(text: str, url: str) -> str:
    """Format text as a link for Teams."""
    return f"[{text}]({url})"


def format_teams_bold(text: str) -> str:
    """Format text as bold for Teams."""
    return f"**{text}**"


def format_teams_italic(text: str) -> str:
    """Format text as italic for Teams."""
    return f"*{text}*"


def send_teams_message(
    access_token: str,
    team_id: str,
    channel_id: str,
    message: str,
    reply_to_message_id: str | None = None,
) -> bool:
    """Send a message to a Teams channel using the Graph API."""
    if reply_to_message_id:
        url = f"{TEAMS_GRAPH_API_BASE}/teams/{team_id}/channels/{channel_id}/messages/{reply_to_message_id}/replies"
    else:
        url = f"{TEAMS_GRAPH_API_BASE}/teams/{team_id}/channels/{channel_id}/messages"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    data = {
        "body": {
            "contentType": "markdown",
            "content": message,
        }
    }

    response = requests.post(url, headers=headers, json=data)
    return response.status_code == 201


def send_teams_chat_message(
    access_token: str,
    chat_id: str,
    message: str,
) -> bool:
    """Send a message to a Teams chat using the Graph API."""
    url = f"{TEAMS_GRAPH_API_BASE}/chats/{chat_id}/messages"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    data = {
        "body": {
            "contentType": "markdown",
            "content": message,
        }
    }

    response = requests.post(url, headers=headers, json=data)
    return response.status_code == 201


def add_teams_reaction(
    access_token: str,
    team_id: str,
    channel_id: str,
    message_id: str,
    emoji: str,
) -> bool:
    """Add a reaction to a Teams message using the Graph API."""
    url = f"{TEAMS_GRAPH_API_BETA}/teams/{team_id}/channels/{channel_id}/messages/{message_id}/reactions"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    data = {
        "reactionType": emoji,
    }

    response = requests.post(url, headers=headers, json=data)
    return response.status_code == 201


def remove_teams_reaction(
    access_token: str,
    team_id: str,
    channel_id: str,
    message_id: str,
    emoji: str,
) -> bool:
    """Remove a reaction from a Teams message using the Graph API."""
    url = f"{TEAMS_GRAPH_API_BETA}/teams/{team_id}/channels/{channel_id}/messages/{message_id}/reactions/{emoji}"
    headers = {"Authorization": f"Bearer {access_token}"}

    response = requests.delete(url, headers=headers)
    return response.status_code == 204


def create_teams_subscription(
    access_token: str,
    resource: str,
    notification_url: str,
) -> dict[str, Any] | None:
    """Create a subscription for Teams notifications using the Graph API."""
    url = f"{TEAMS_GRAPH_API_BASE}/subscriptions"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    
    # Calculate expiration date
    expiration_date = datetime.now(UTC) + timedelta(days=TEAMS_SUBSCRIPTION_EXPIRY_DAYS)
    expiration_date_str = expiration_date.strftime("%Y-%m-%dT%H:%M:%SZ")
    
    data = {
        "changeType": "created,updated,deleted",
        "notificationUrl": notification_url,
        "resource": resource,
        "expirationDateTime": expiration_date_str,
    }

    response = requests.post(url, headers=headers, json=data)
    if response.status_code == 201:
        return response.json()
    return None


def renew_teams_subscription(
    access_token: str,
    subscription_id: str,
    notification_url: str,
) -> dict[str, Any] | None:
    """Renew a Teams subscription using the Graph API."""
    url = f"{TEAMS_GRAPH_API_BASE}/subscriptions/{subscription_id}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    
    # Calculate expiration date with renewal buffer
    expiration_date = datetime.now(UTC) + timedelta(
        days=TEAMS_SUBSCRIPTION_EXPIRY_DAYS,
        hours=TEAMS_SUBSCRIPTION_RENEWAL_BUFFER_HOURS
    )
    expiration_date_str = expiration_date.strftime("%Y-%m-%dT%H:%M:%SZ")
    
    data = {
        "expirationDateTime": expiration_date_str,
    }

    response = requests.patch(url, headers=headers, json=data)
    if response.status_code == 200:
        return response.json()
    return None


def delete_teams_subscription(
    access_token: str,
    subscription_id: str,
) -> bool:
    """Delete a Teams subscription using the Graph API."""
    url = f"{TEAMS_GRAPH_API_BASE}/subscriptions/{subscription_id}"
    headers = {"Authorization": f"Bearer {access_token}"}

    response = requests.delete(url, headers=headers)
    return response.status_code == 204


def validate_teams_access(
    access_token: str,
    team_id: str,
) -> bool:
    """Validate access to a Teams team using the Graph API."""
    url = f"{TEAMS_GRAPH_API_BASE}/teams/{team_id}"
    headers = {"Authorization": f"Bearer {access_token}"}

    response = requests.get(url, headers=headers)
    return response.status_code == 200


def validate_teams_webhook(
    validation_token: str,
) -> dict[str, str]:
    """Validate a Teams webhook request."""
    return {
        "validationResponse": validation_token,
    } 