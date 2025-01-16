import requests
from fastapi import HTTPException

SLACK_API_URL = "https://slack.com/api/auth.test"


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
    if not app_token.startswith("xapp-"):
        raise HTTPException(status_code=400, detail="Invalid app token format.")

    # Placeholder logic here:

    return True


print(validate_app_token("xapp-1"))
