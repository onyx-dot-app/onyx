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

    CONTACTS_READ = "hubspot.contacts.read"
    COMPANIES_READ = "hubspot.companies.read"
    DEALS_READ = "hubspot.deals.read"
    OWNERS_READ = "hubspot.owners.read"
    SEARCH_READ = "hubspot.search.read"
    CONTACTS_CREATE = "hubspot.contacts.create"
    CONTACTS_UPDATE = "hubspot.contacts.update"
    COMPANIES_CREATE = "hubspot.companies.create"
    DEALS_CREATE = "hubspot.deals.create"
    NOTES_CREATE = "hubspot.notes.create"


# HubSpot's CRM API is a path-addressed JSON API rooted at
# https://api.hubapi.com; the action is the method + path template. A `{name}`
# segment matches one path segment (a record id, etc.).
#
# CRM object search is a `POST .../search` read: it carries a filter body but
# mutates nothing, so it defaults to ALWAYS like the GET reads. Its extra
# trailing `/search` segment keeps it from colliding with the create POSTs
# (`POST /crm/v3/objects/contacts`).
_CONTACTS = "/crm/v3/objects/contacts"
_COMPANIES = "/crm/v3/objects/companies"
_DEALS = "/crm/v3/objects/deals"
_ENDPOINTS: list[EndpointSpec] = [
    EndpointSpec(
        id=HubSpotAction.CONTACTS_READ,
        normalised_name="Read contacts",
        description="List contacts and fetch a single contact.",
        matches=(
            RestRoute(method="GET", path=_CONTACTS),
            RestRoute(method="GET", path=f"{_CONTACTS}/{{contactId}}"),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=HubSpotAction.COMPANIES_READ,
        normalised_name="Read companies",
        description="List companies and fetch a single company.",
        matches=(
            RestRoute(method="GET", path=_COMPANIES),
            RestRoute(method="GET", path=f"{_COMPANIES}/{{companyId}}"),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=HubSpotAction.DEALS_READ,
        normalised_name="Read deals",
        description="List deals and fetch a single deal.",
        matches=(
            RestRoute(method="GET", path=_DEALS),
            RestRoute(method="GET", path=f"{_DEALS}/{{dealId}}"),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=HubSpotAction.OWNERS_READ,
        normalised_name="Read owners",
        description="List CRM owners (users) and fetch a single owner.",
        matches=(
            RestRoute(method="GET", path="/crm/v3/owners"),
            RestRoute(method="GET", path="/crm/v3/owners/{ownerId}"),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=HubSpotAction.SEARCH_READ,
        normalised_name="Search the CRM",
        description="Search contacts, companies, and deals by query or filters.",
        matches=(
            RestRoute(method="POST", path=f"{_CONTACTS}/search"),
            RestRoute(method="POST", path=f"{_COMPANIES}/search"),
            RestRoute(method="POST", path=f"{_DEALS}/search"),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=HubSpotAction.CONTACTS_CREATE,
        normalised_name="Create a contact",
        description="Create a new contact record.",
        matches=(RestRoute(method="POST", path=_CONTACTS),),
    ),
    EndpointSpec(
        id=HubSpotAction.CONTACTS_UPDATE,
        normalised_name="Edit a contact",
        description="Update an existing contact's properties.",
        matches=(RestRoute(method="PATCH", path=f"{_CONTACTS}/{{contactId}}"),),
    ),
    EndpointSpec(
        id=HubSpotAction.COMPANIES_CREATE,
        normalised_name="Create a company",
        description="Create a new company record.",
        matches=(RestRoute(method="POST", path=_COMPANIES),),
    ),
    EndpointSpec(
        id=HubSpotAction.DEALS_CREATE,
        normalised_name="Create a deal",
        description="Create a new deal record.",
        matches=(RestRoute(method="POST", path=_DEALS),),
    ),
    EndpointSpec(
        id=HubSpotAction.NOTES_CREATE,
        normalised_name="Create a note",
        description="Log a note (engagement), optionally associated to a record.",
        matches=(RestRoute(method="POST", path="/crm/v3/objects/notes"),),
    ),
]


class HubSpotProvider(OAuthExternalAppProvider, OnyxManagedExtApp):
    spec = OAuthProviderSpec(
        app_type=ExternalAppType.HUBSPOT,
        app_name="HubSpot",
        oauth=OAuthFlowSpec(
            authorize_url="https://app.hubspot.com/oauth/authorize",
            token_url="https://api.hubapi.com/oauth/v1/token",
            # HubSpot uses granular CRM scopes plus `oauth` (required for the
            # refresh-token grant). Reads and writes are both requested; every
            # mutation is still gated by per-action ASK approval at the egress.
            scope=" ".join(
                [
                    "oauth",
                    "crm.objects.contacts.read",
                    "crm.objects.contacts.write",
                    "crm.objects.companies.read",
                    "crm.objects.companies.write",
                    "crm.objects.deals.read",
                    "crm.objects.deals.write",
                ]
            ),
            scope_param="scope",
        ),
        descriptor=AdminDescriptorSpec(
            description=(
                "Read, search, create, and edit HubSpot CRM contacts, companies, "
                "and deals on the user's behalf."
            ),
            upstream_url_patterns=["https://api\\.hubapi\\.com/.*"],
            auth_template={"Authorization": "Bearer {access_token}"},
            required_org_credential_fields=[
                OrgCredentialField(
                    key="client_id",
                    label="Client ID",
                    description=(
                        "Found on your HubSpot app's Auth tab "
                        "(developer account → Apps → your app → Auth)."
                    ),
                ),
                OrgCredentialField(
                    key="client_secret",
                    label="Client Secret",
                    description=(
                        "Found alongside the Client ID on the app's Auth tab. "
                        "Treat this like a password."
                    ),
                    secret=True,
                ),
            ],
            setup_instructions=(
                "In HubSpot: create a developer account, then Apps → Create app. "
                "On the app's Auth tab, add this Onyx instance's callback URL "
                "(/craft/v1/apps/oauth/callback) to the redirect URLs and select "
                "the CRM contacts/companies/deals read+write scopes (plus oauth). "
                "Save, then paste the Client ID and Client Secret below."
            ),
        ),
        endpoint_catalog=_ENDPOINTS,
    )

    managed_org_credentials = {
        "client_id": EXT_APP_HUBSPOT_CLIENT_ID,
        "client_secret": EXT_APP_HUBSPOT_CLIENT_SECRET,
    }

    # HubSpot signals a dead refresh token with `BAD_REFRESH_TOKEN` in the
    # response `status` field rather than RFC-6749's `invalid_grant`; treat it as
    # terminal so the stored credential is cleared and the user reconnects.
    terminal_refresh_errors = frozenset({"invalid_grant", "BAD_REFRESH_TOKEN"})

    def classify_token_response(
        self, response: requests.Response, body: dict[str, Any]
    ) -> str | None:
        # HubSpot returns a non-2xx with a `{"status": "...", "message": ...}`
        # body on failure (e.g. `BAD_REFRESH_TOKEN`, `BAD_AUTH_CODE`); its
        # machine-readable code lives in `status`, not the RFC-6749 `error`
        # field the generic check looks for. Surface it so terminal-vs-transient
        # classification can match it.
        if (
            response.status_code >= 400
            and isinstance(body, dict)
            and body.get("status")
        ):
            return str(body["status"])
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
        # HubSpot always returns a (non-expiring) refresh token and an
        # access-token TTL on the initial grant; a refresh returns the same shape.
        if response_data.get("refresh_token"):
            creds["refresh_token"] = response_data["refresh_token"]
        if response_data.get("expires_in"):
            creds["expires_in"] = response_data["expires_in"]
        return creds
