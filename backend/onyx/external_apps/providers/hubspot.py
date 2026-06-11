from typing import Any

import requests

from onyx.configs.app_configs import EXT_APP_HUBSPOT_CLIENT_ID
from onyx.configs.app_configs import EXT_APP_HUBSPOT_CLIENT_SECRET
from onyx.db.enums import EndpointPolicy
from onyx.db.enums import ExternalAppType
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.providers.actions import EndpointSpec
from onyx.external_apps.providers.actions import ExternalAppAction
from onyx.external_apps.providers.actions import RestRoute
from onyx.external_apps.providers.base import AdminDescriptorSpec
from onyx.external_apps.providers.base import OAuthExternalAppProvider
from onyx.external_apps.providers.base import OAuthFlowSpec
from onyx.external_apps.providers.base import OAuthProviderSpec
from onyx.external_apps.providers.base import OnyxManagedExtApp
from onyx.external_apps.providers.base import OrgCredentialField
from onyx.external_apps.providers.base import token_response_error


class HubSpotAction(ExternalAppAction):
    """Strongly-typed catalog ids for the HubSpot provider."""

    OBJECTS_READ = "hubspot.objects.read"
    OBJECTS_SEARCH = "hubspot.objects.search"
    PROPERTIES_READ = "hubspot.properties.read"
    OWNERS_READ = "hubspot.owners.read"
    OBJECTS_CREATE = "hubspot.objects.create"
    OBJECTS_UPDATE = "hubspot.objects.update"
    OBJECTS_ARCHIVE = "hubspot.objects.archive"


# HubSpot's CRM is a path-addressed JSON API rooted at https://api.hubapi.com;
# the action is the HTTP method + path template. CRM records (contacts,
# companies, deals, tickets, …) are uniformly addressed under
# `/crm/v3/objects/{objectType}`, so one action governs the whole object family
# per verb. A `{name}` segment matches exactly one path segment (the object type
# or a record id). Note that HubSpot's "search" is a POST that mutates nothing —
# it stays a read (auto-approved) while the create/update/archive writes ask.
_ENDPOINTS: list[EndpointSpec] = [
    EndpointSpec(
        id=HubSpotAction.OBJECTS_READ,
        normalised_name="Read CRM records",
        description=(
            "List a CRM object type's records and fetch a single record "
            "(contacts, companies, deals, tickets, etc.)."
        ),
        matches=(
            RestRoute(method="GET", path="/crm/v3/objects/{object_type}"),
            RestRoute(method="GET", path="/crm/v3/objects/{object_type}/{id}"),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=HubSpotAction.OBJECTS_SEARCH,
        normalised_name="Search CRM records",
        description="Filter and search a CRM object type's records.",
        matches=(
            RestRoute(method="POST", path="/crm/v3/objects/{object_type}/search"),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=HubSpotAction.PROPERTIES_READ,
        normalised_name="Read object properties",
        description=(
            "List the properties (fields) defined for a CRM object type, so the "
            "agent knows which fields it can read and write."
        ),
        matches=(
            RestRoute(method="GET", path="/crm/v3/properties/{object_type}"),
            RestRoute(method="GET", path="/crm/v3/properties/{object_type}/{name}"),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=HubSpotAction.OWNERS_READ,
        normalised_name="Read owners",
        description="List the account's owners (users) and fetch a single owner.",
        matches=(
            RestRoute(method="GET", path="/crm/v3/owners"),
            RestRoute(method="GET", path="/crm/v3/owners/{id}"),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=HubSpotAction.OBJECTS_CREATE,
        normalised_name="Create a CRM record",
        description="Create a new record of a CRM object type.",
        matches=(RestRoute(method="POST", path="/crm/v3/objects/{object_type}"),),
    ),
    EndpointSpec(
        id=HubSpotAction.OBJECTS_UPDATE,
        normalised_name="Update a CRM record",
        description="Update the properties of an existing CRM record.",
        matches=(RestRoute(method="PATCH", path="/crm/v3/objects/{object_type}/{id}"),),
    ),
    EndpointSpec(
        id=HubSpotAction.OBJECTS_ARCHIVE,
        normalised_name="Archive a CRM record",
        description="Archive (soft-delete) a CRM record.",
        matches=(
            RestRoute(method="DELETE", path="/crm/v3/objects/{object_type}/{id}"),
        ),
    ),
]


class HubSpotProvider(OAuthExternalAppProvider, OnyxManagedExtApp):
    spec = OAuthProviderSpec(
        app_type=ExternalAppType.HUBSPOT,
        app_name="HubSpot",
        oauth=OAuthFlowSpec(
            authorize_url="https://app.hubspot.com/oauth/authorize",
            token_url="https://api.hubapi.com/oauth/v1/token",
            # Space-delimited granular CRM scopes. `oauth` is the base scope every
            # HubSpot app needs; the rest grant read+write on the core CRM objects.
            scope=" ".join(
                [
                    "oauth",
                    "crm.objects.contacts.read",
                    "crm.objects.contacts.write",
                    "crm.objects.companies.read",
                    "crm.objects.companies.write",
                    "crm.objects.deals.read",
                    "crm.objects.deals.write",
                    "crm.schemas.contacts.read",
                    "crm.schemas.companies.read",
                    "crm.schemas.deals.read",
                ]
            ),
            scope_param="scope",
        ),
        descriptor=AdminDescriptorSpec(
            description=(
                "Read, search, create, and update CRM records (contacts, "
                "companies, deals, and more) in HubSpot on the user's behalf."
            ),
            upstream_url_patterns=["https://api\\.hubapi\\.com/.*"],
            auth_template={"Authorization": "Bearer {access_token}"},
            required_org_credential_fields=[
                OrgCredentialField(
                    key="client_id",
                    label="Client ID",
                    description=(
                        "Found on your HubSpot app's Auth page "
                        "(developer account → Apps → your app → Auth)."
                    ),
                ),
                OrgCredentialField(
                    key="client_secret",
                    label="Client Secret",
                    description=(
                        "Found alongside the Client ID on the app's Auth page. "
                        "Treat this like a password."
                    ),
                    secret=True,
                ),
            ],
            setup_instructions=(
                "In HubSpot: create (or open) a developer account, then Apps → "
                "Create app. On the app's Auth tab, add this Onyx instance's "
                "callback URL (/craft/v1/apps/oauth/callback) to Redirect URLs "
                "and add the CRM scopes (contacts, companies, deals read/write). "
                "Save, then paste the Client ID and Client Secret below. The "
                "agent is granted read+write access to the core CRM objects."
            ),
        ),
        endpoint_catalog=_ENDPOINTS,
    )

    managed_org_credentials = {
        "client_id": EXT_APP_HUBSPOT_CLIENT_ID,
        "client_secret": EXT_APP_HUBSPOT_CLIENT_SECRET,
    }

    # HubSpot signals a dead refresh token with `BAD_REFRESH_TOKEN` (in the
    # response body's `status`/`category`) rather than RFC-6749's `invalid_grant`;
    # treat it as terminal so the user is prompted to reconnect.
    terminal_refresh_errors = frozenset({"invalid_grant", "BAD_REFRESH_TOKEN"})

    def classify_token_response(
        self, response: requests.Response, body: dict[str, Any]
    ) -> str | None:
        # HubSpot's OAuth errors don't use the RFC-6749 `error` field; a failure
        # is a non-2xx with a body like `{"status": "BAD_REFRESH_TOKEN",
        # "message": "...", "category": "..."}`. Surface that machine-readable
        # status so terminal-vs-transient classification can match it; otherwise
        # fall back to the generic detector.
        if response.status_code >= 400 and isinstance(body, dict):
            status = body.get("status") or body.get("category")
            if status:
                return str(status)
        return token_response_error(response, body)

    def extract_credentials(self, response_data: dict[str, Any]) -> dict[str, Any]:
        access_token = response_data.get("access_token")
        if not access_token:
            raise OnyxError(
                OnyxErrorCode.BAD_GATEWAY,
                "HubSpot OAuth response did not contain an access token.",
            )
        creds: dict[str, Any] = {
            "access_token": access_token,
            "token_type": response_data.get("token_type"),
        }
        # HubSpot access tokens are short-lived (~30 min) and always issue a
        # refresh token on the initial grant; keep both so the token can be
        # refreshed without a reconnect.
        if response_data.get("refresh_token"):
            creds["refresh_token"] = response_data["refresh_token"]
        if response_data.get("expires_in"):
            creds["expires_in"] = response_data["expires_in"]
        return creds
