from typing import Any
from typing import ClassVar

from onyx.db.enums import ExternalAppType
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.providers.base import OAuth
from onyx.external_apps.providers.base import OrgCredentialField


class GoogleCalendarOAuth(OAuth):
    app_type = ExternalAppType.GOOGLE_CALENDAR
    app_name = "Google Calendar"
    authorize_url = "https://accounts.google.com/o/oauth2/v2/auth"
    token_url = "https://oauth2.googleapis.com/token"
    scope = "https://www.googleapis.com/auth/calendar"
    scope_param = "scope"
    # access_type=offline issues a refresh_token; prompt=consent
    # forces fresh consent so Google reissues it on re-auth.
    extra_authorize_params: ClassVar[dict[str, str]] = {
        "response_type": "code",
        "access_type": "offline",
        "prompt": "consent",
    }

    description = (
        "Read and create events on your Google Calendar from inside Onyx Craft."
    )
    upstream_url_patterns = ["https://www\\.googleapis\\.com/calendar/.*"]
    auth_template = {"Authorization": "Bearer {access_token}"}
    required_org_credential_fields = [
        OrgCredentialField(
            key="client_id",
            label="Client ID",
            description=(
                "Found in Google Cloud Console → APIs & Services → "
                "Credentials → OAuth 2.0 Client IDs."
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
        "In Google Cloud Console: create a project (or pick one), enable the "
        "Google Calendar API under APIs & Services → Library, configure the "
        "OAuth consent screen (External for personal Google accounts, "
        "Internal for Workspace), then under APIs & Services → Credentials "
        "create an OAuth 2.0 Client ID of type Web application. Add this "
        "Onyx instance's callback URL (/craft/v1/apps/oauth/callback) to "
        "Authorized redirect URIs. Then paste the Client ID and Client "
        "Secret below."
    )

    def extract_credentials(self, response_data: dict[str, Any]) -> dict[str, Any]:
        access_token = response_data.get("access_token")
        if not access_token:
            raise OnyxError(
                OnyxErrorCode.BAD_GATEWAY,
                "Google OAuth response did not contain an access token.",
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
        if response_data.get("id_token"):
            creds["id_token"] = response_data["id_token"]
        return creds
