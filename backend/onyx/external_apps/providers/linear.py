from typing import Any
from typing import ClassVar

from onyx.db.enums import ExternalAppType
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.providers.base import OAuth
from onyx.external_apps.providers.base import StandardFlatRefresh


class LinearOAuth(OAuth, StandardFlatRefresh):
    app_type = ExternalAppType.LINEAR
    app_name = "Linear"
    authorize_url = "https://linear.app/oauth/authorize"
    token_url = "https://api.linear.app/oauth/token"
    scope = "read,write"
    scope_param = "scope"
    # actor=user is Linear's default but explicit — actor=application
    # would mint an app-acting token instead of user-acting.
    extra_authorize_params: ClassVar[dict[str, str]] = {
        "response_type": "code",
        "actor": "user",
    }

    def extract_credentials(self, response_data: dict[str, Any]) -> dict[str, Any]:
        access_token = response_data.get("access_token")
        if not access_token:
            raise OnyxError(
                OnyxErrorCode.BAD_GATEWAY,
                "Linear OAuth response did not contain an access token.",
            )
        creds: dict[str, Any] = {
            "access_token": access_token,
            "scope": response_data.get("scope"),
            "token_type": response_data.get("token_type"),
        }
        if response_data.get("refresh_token"):
            creds["refresh_token"] = response_data["refresh_token"]
        if response_data.get("expires_in"):
            creds["expires_in"] = response_data["expires_in"]
        return creds
