from typing import Any

from onyx.db.enums import ExternalAppType
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.providers.actions import EndpointSpec
from onyx.external_apps.providers.actions import RestRoute
from onyx.external_apps.providers.base import AdminDescriptorSpec
from onyx.external_apps.providers.base import OAuthExternalAppProvider
from onyx.external_apps.providers.base import OAuthFlowSpec
from onyx.external_apps.providers.base import OAuthProviderSpec
from onyx.external_apps.providers.base import OrgCredentialField

# Google Calendar REST v3 (https://www.googleapis.com/calendar/v3/...); the
# action is HTTP method + path. Method disambiguates list/create on the shared
# `/events` collection and read/update/delete on `/events/{id}`.
_EVENTS_COLLECTION = r"^/calendar/v3/calendars/[^/]+/events/?$"
_EVENT_ITEM = r"^/calendar/v3/calendars/[^/]+/events/[^/]+$"
_ENDPOINTS: list[EndpointSpec] = [
    EndpointSpec(
        id="gcal.calendars.read",
        normalised_name="List calendars",
        description="List the calendars on the user's calendar list.",
        matches=[
            RestRoute(
                method="GET", path_regex=r"^/calendar/v3/users/[^/]+/calendarList"
            )
        ],
    ),
    EndpointSpec(
        id="gcal.events.read",
        normalised_name="Read events",
        description="List events in a calendar or fetch a single event.",
        matches=[
            RestRoute(method="GET", path_regex=_EVENTS_COLLECTION),
            RestRoute(method="GET", path_regex=_EVENT_ITEM),
        ],
    ),
    EndpointSpec(
        id="gcal.freebusy.read",
        normalised_name="Query free/busy",
        description="Query busy intervals across calendars.",
        matches=[RestRoute(method="POST", path_regex=r"^/calendar/v3/freeBusy$")],
    ),
    EndpointSpec(
        id="gcal.events.create",
        normalised_name="Create an event",
        description="Create a new event on a calendar.",
        matches=[RestRoute(method="POST", path_regex=_EVENTS_COLLECTION)],
    ),
    EndpointSpec(
        id="gcal.events.update",
        normalised_name="Update an event",
        description="Modify an existing event.",
        matches=[
            RestRoute(method="PUT", path_regex=_EVENT_ITEM),
            RestRoute(method="PATCH", path_regex=_EVENT_ITEM),
        ],
    ),
    EndpointSpec(
        id="gcal.events.delete",
        normalised_name="Delete an event",
        description="Permanently delete an event.",
        matches=[RestRoute(method="DELETE", path_regex=_EVENT_ITEM)],
    ),
]


class GoogleCalendarProvider(OAuthExternalAppProvider):
    spec = OAuthProviderSpec(
        app_type=ExternalAppType.GOOGLE_CALENDAR,
        app_name="Google Calendar",
        oauth=OAuthFlowSpec(
            authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
            token_url="https://oauth2.googleapis.com/token",
            scope="https://www.googleapis.com/auth/calendar",
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
            description=(
                "Read and create events on your Google Calendar from inside Onyx Craft."
            ),
            upstream_url_patterns=["https://www\\.googleapis\\.com/calendar/.*"],
            auth_template={"Authorization": "Bearer {access_token}"},
            required_org_credential_fields=[
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
                    description=(
                        "Found alongside the Client ID. Treat this like a password."
                    ),
                    secret=True,
                ),
            ],
            setup_instructions=(
                "In Google Cloud Console: create a project (or pick one), "
                "enable the Google Calendar API under APIs & Services → "
                "Library, configure the OAuth consent screen (External for "
                "personal Google accounts, Internal for Workspace), then under "
                "APIs & Services → Credentials create an OAuth 2.0 Client ID of "
                "type Web application. Add this Onyx instance's callback URL "
                "(/craft/v1/apps/oauth/callback) to Authorized redirect URIs. "
                "Then paste the Client ID and Client Secret below."
            ),
        ),
        endpoint_catalog=_ENDPOINTS,
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
