from typing import Any
from typing import ClassVar

from onyx.db.enums import ExternalAppType
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.providers.base import OAuth
from onyx.external_apps.providers.base import OrgCredentialField


class SlackOAuth(OAuth):
    app_type = ExternalAppType.SLACK
    app_name = "Slack"
    authorize_url = "https://slack.com/oauth/v2/authorize"
    token_url = "https://slack.com/api/oauth.v2.access"
    scope = ",".join(
        [
            "chat:write",
            "channels:history",
            "channels:read",
            "groups:history",
            "groups:read",
            "im:history",
            "im:read",
            "users:read",
        ]
    )
    scope_param = "user_scope"
    extra_authorize_params: ClassVar[dict[str, str]] = {}

    description = "Read your Slack messages and channels as context inside Onyx Craft."
    upstream_url_patterns = ["https://slack\\.com/api/.*"]
    auth_template = {"Authorization": "Bearer {access_token}"}
    required_org_credential_fields = [
        OrgCredentialField(
            key="client_id",
            label="Client ID",
            description=(
                "Found under your Slack app's Basic Information → App Credentials."
            ),
        ),
        OrgCredentialField(
            key="client_secret",
            label="Client Secret",
            description=(
                "Found under your Slack app's Basic Information → "
                "App Credentials. Treat this like a password."
            ),
            secret=True,
        ),
    ]
    setup_instructions = (
        "Create a Slack app at api.slack.com/apps. Under OAuth & Permissions, "
        "add this Onyx instance's callback URL (/craft/v1/apps/oauth/callback) "
        "to Redirect URLs, and add the User Token Scopes you want the agent "
        "to use (e.g. chat:write, channels:history, channels:read, im:history, "
        "users:read). No bot user is required. Then paste the app's Client ID "
        "and Client Secret below."
    )

    def extract_credentials(self, response_data: dict[str, Any]) -> dict[str, Any]:
        # Slack v2 with `user_scope` returns the user token nested
        # under `authed_user`; the top-level `access_token` would be
        # the bot token, which we don't request.
        authed_user = response_data.get("authed_user") or {}
        access_token = authed_user.get("access_token")
        if not access_token:
            raise OnyxError(
                OnyxErrorCode.BAD_GATEWAY,
                "Slack OAuth response did not contain a user access "
                "token. Make sure the Slack app has user token scopes "
                "configured.",
            )
        creds: dict[str, Any] = {
            "access_token": access_token,
            "team_id": (response_data.get("team") or {}).get("id"),
            "team_name": (response_data.get("team") or {}).get("name"),
            "authed_user_id": authed_user.get("id"),
            "scope": authed_user.get("scope"),
        }
        if authed_user.get("refresh_token"):
            creds["refresh_token"] = authed_user["refresh_token"]
        if authed_user.get("expires_in"):
            creds["expires_in"] = authed_user["expires_in"]
        return creds
