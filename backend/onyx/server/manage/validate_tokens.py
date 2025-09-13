import requests
from fastapi import HTTPException

SLACK_API_URL = "https://slack.com/api/auth.test"
SLACK_CONNECTIONS_OPEN_URL = "https://slack.com/api/apps.connections.open"


def validate_bot_token(bot_token: str) -> bool:
    headers = {"Authorization": f"Bearer {bot_token}"}
    response = requests.post(SLACK_API_URL, headers=headers)

    if response.status_code != 200:
        raise HTTPException(
            status_code=500, detail="Error communicating with Slack API."
        )

    data = response.json()
    if not data.get("ok", False):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid bot token: {data.get('error', 'Unknown error')}",
        )

    return True


def validate_app_token(app_token: str) -> bool:
    headers = {"Authorization": f"Bearer {app_token}"}
    response = requests.post(SLACK_CONNECTIONS_OPEN_URL, headers=headers)

    if response.status_code != 200:
        raise HTTPException(
            status_code=500, detail="Error communicating with Slack API."
        )

    data = response.json()
    if not data.get("ok", False):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid app token: {data.get('error', 'Unknown error')}",
        )

    return True


def validate_user_token(user_token: str | None) -> bool:
    """
    Validate that the user_token is a valid user OAuth token (xoxp-...)
    and not a bot token (xoxb-...)
    """
    if user_token is None:
        # user_token is optional, so None is valid
        return True

    # Check token format - user tokens should start with xoxp-
    if not user_token.startswith("xoxp-"):
        raise HTTPException(
            status_code=400,
            detail="Invalid user token format. User OAuth tokens must start with 'xoxp-'",
        )

    # Test the token with Slack API to ensure it's valid
    headers = {"Authorization": f"Bearer {user_token}"}
    response = requests.post(SLACK_API_URL, headers=headers)

    if response.status_code != 200:
        raise HTTPException(
            status_code=500, detail="Error communicating with Slack API."
        )

    data = response.json()
    if not data.get("ok", False):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid user token: {data.get('error', 'Unknown error')}",
        )

    return True
