from typing import Any
from typing import ClassVar

from onyx.db.enums import ExternalAppType
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.providers.base import OAuth
from onyx.external_apps.providers.base import OrgCredentialField


class LinearOAuth(OAuth):
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

    description = (
        "Read and create issues, projects, and comments in Linear on the user's behalf."
    )
    upstream_url_patterns = ["https://api\\.linear\\.app/.*"]
    auth_template = {"Authorization": "Bearer {access_token}"}
    required_org_credential_fields = [
        OrgCredentialField(
            key="client_id",
            label="Client ID",
            description=(
                "Found in Linear → Settings → API → OAuth applications → your app."
            ),
        ),
        OrgCredentialField(
            key="client_secret",
            label="Client Secret",
            description=("Found alongside the Client ID. Treat this like a password."),
            secret=True,
        ),
    ]
    setup_instructions = (
        "In Linear: Settings → API → OAuth applications → New OAuth "
        "application. Fill in name, developer email, and description. Add "
        "this Onyx instance's callback URL (/craft/v1/apps/oauth/callback) "
        "to Callback URLs. Save. Then paste the Client ID and Client "
        "Secret below. The agent will be granted read+write access to "
        "issues, projects, and comments."
    )

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
