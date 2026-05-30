from typing import Any

from onyx.db.enums import ExternalAppType
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.providers.actions import EndpointSpec
from onyx.external_apps.providers.base import AdminDescriptorSpec
from onyx.external_apps.providers.base import OAuthExternalAppProvider
from onyx.external_apps.providers.base import OAuthFlowSpec
from onyx.external_apps.providers.base import OAuthProviderSpec
from onyx.external_apps.providers.base import OrgCredentialField

# Google's OAuth 2.0 endpoints are shared across all Google APIs.
_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"

# Every Google provider authenticates with the same Cloud Console OAuth client.
_CLIENT_CREDENTIAL_FIELDS = [
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
        description="Found alongside the Client ID. Treat this like a password.",
        secret=True,
    ),
]


def _setup_instructions(google_api_name: str) -> str:
    """The Cloud Console setup steps, identical across Google providers except
    for which API the admin must enable."""
    return (
        "In Google Cloud Console: create a project (or pick one), enable the "
        f"{google_api_name} under APIs & Services → Library, configure the "
        "OAuth consent screen (External for personal Google accounts, Internal "
        "for Workspace), then under APIs & Services → Credentials create an "
        "OAuth 2.0 Client ID of type Web application. Add this Onyx instance's "
        "callback URL (/craft/v1/apps/oauth/callback) to Authorized redirect "
        "URIs. Then paste the Client ID and Client Secret below."
    )


class GoogleOAuthProvider(OAuthExternalAppProvider, abstract=True):
    """Shared base for Google built-in providers (Calendar, Gmail, ...).

    Google APIs share OAuth endpoints, the offline/consent authorize params,
    the Cloud Console client-credential fields, the bearer ``auth_template``,
    and an identical token-exchange response shape. Concrete subclasses only
    vary scope, upstream URL patterns, user-facing copy, and their action
    catalog — assembled via :meth:`build_spec`.
    """

    @classmethod
    def build_spec(
        cls,
        *,
        app_type: ExternalAppType,
        app_name: str,
        scope: str,
        upstream_url_patterns: list[str],
        description: str,
        google_api_name: str,
        endpoint_catalog: list[EndpointSpec],
    ) -> OAuthProviderSpec:
        return OAuthProviderSpec(
            app_type=app_type,
            app_name=app_name,
            oauth=OAuthFlowSpec(
                authorize_url=_AUTHORIZE_URL,
                token_url=_TOKEN_URL,
                scope=scope,
                scope_param="scope",
                # access_type=offline issues a refresh_token; prompt=consent
                # forces fresh consent so Google reissues it on re-auth.
                extra_authorize_params={
                    "response_type": "code",
                    "access_type": "offline",
                    "prompt": "consent",
                },
            ),
            descriptor=AdminDescriptorSpec(
                description=description,
                upstream_url_patterns=upstream_url_patterns,
                auth_template={"Authorization": "Bearer {access_token}"},
                required_org_credential_fields=list(_CLIENT_CREDENTIAL_FIELDS),
                setup_instructions=_setup_instructions(google_api_name),
            ),
            endpoint_catalog=endpoint_catalog,
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
