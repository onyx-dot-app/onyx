import requests

from onyx.configs.constants import SLACK_USER_TOKEN_PREFIX
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError

SLACK_API_URL = "https://slack.com/api/auth.test"
SLACK_CONNECTIONS_OPEN_URL = "https://slack.com/api/apps.connections.open"


def validate_bot_token(bot_token: str) -> bool:
    headers = {"Authorization": f"Bearer {bot_token}"}
    response = requests.post(SLACK_API_URL, headers=headers)

    if response.status_code != 200:
        raise OnyxError(
            OnyxErrorCode.INTERNAL_ERROR, "Error communicating with Slack API."
        )

    data = response.json()
    if not data.get("ok", False):
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR,
            f"Invalid bot token: {data.get('error', 'Unknown error')}",
        )

    return True


def validate_app_token(app_token: str) -> bool:
    headers = {"Authorization": f"Bearer {app_token}"}
    response = requests.post(SLACK_CONNECTIONS_OPEN_URL, headers=headers)

    if response.status_code != 200:
        raise OnyxError(
            OnyxErrorCode.INTERNAL_ERROR, "Error communicating with Slack API."
        )

    data = response.json()
    if not data.get("ok", False):
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR,
            f"Invalid app token: {data.get('error', 'Unknown error')}",
        )

    return True


def validate_user_token(user_token: str | None) -> None:
    """
    Validate that the user_token is a valid user OAuth token (xoxp-...)
    and not a bot token (xoxb-...)
    Args:
        user_token: The user OAuth token to validate.
    Returns:
        None is valid and will return successfully.
    Raises:
        OnyxError: If the token is invalid or missing required fields
    """
    if not user_token:
        # user_token is optional, so None or empty string is valid
        return

    if not user_token.startswith(SLACK_USER_TOKEN_PREFIX):
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR,
            f"Invalid user token format. User OAuth tokens must start with '{SLACK_USER_TOKEN_PREFIX}'",
        )

    # Test the token with Slack API to ensure it's valid
    headers = {"Authorization": f"Bearer {user_token}"}
    response = requests.post(SLACK_API_URL, headers=headers)

    if response.status_code != 200:
        raise OnyxError(
            OnyxErrorCode.INTERNAL_ERROR, "Error communicating with Slack API."
        )

    data = response.json()
    if not data.get("ok", False):
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR,
            f"Invalid user token: {data.get('error', 'Unknown error')}",
        )
