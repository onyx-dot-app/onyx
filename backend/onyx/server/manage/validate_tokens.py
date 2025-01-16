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
