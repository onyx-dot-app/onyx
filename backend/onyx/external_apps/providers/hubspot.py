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
    CONTACTS_CREATE = "hubspot.contacts.create"
    CONTACTS_UPDATE = "hubspot.contacts.update"
    COMPANIES_READ = "hubspot.companies.read"
    COMPANIES_CREATE = "hubspot.companies.create"
    COMPANIES_UPDATE = "hubspot.companies.update"
    DEALS_READ = "hubspot.deals.read"
    DEALS_CREATE = "hubspot.deals.create"
    DEALS_UPDATE = "hubspot.deals.update"


# HubSpot's CRM API is a path-addressed JSON API rooted at
# https://api.hubapi.com; the action is the HTTP method + path template. A
# `{name}` segment matches one path segment (an object id). Each CRM object
# type (contacts / companies / deals) lives under `/crm/v3/objects/<type>`:
# list + read are GETs (auto-approved), create is a POST and update a PATCH
# (both default to ASK so the egress approval gate prompts the user first).
_OBJECTS = "/crm/v3/objects"
_CONTACTS = f"{_OBJECTS}/contacts"
_COMPANIES = f"{_OBJECTS}/companies"
_DEALS = f"{_OBJECTS}/deals"
_ENDPOINTS: list[EndpointSpec] = [
    EndpointSpec(
        id=HubSpotAction.CONTACTS_READ,
        normalised_name="Read contacts",
        description="List contacts and fetch a single contact by id.",
        matches=(
            RestRoute(method="GET", path=_CONTACTS),
            RestRoute(method="GET", path=f"{_CONTACTS}/{{contactId}}"),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=HubSpotAction.COMPANIES_READ,
        normalised_name="Read companies",
        description="List companies and fetch a single company by id.",
        matches=(
            RestRoute(method="GET", path=_COMPANIES),
            RestRoute(method="GET", path=f"{_COMPANIES}/{{companyId}}"),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=HubSpotAction.DEALS_READ,
        normalised_name="Read deals",
        description="List deals and fetch a single deal by id.",
        matches=(
            RestRoute(method="GET", path=_DEALS),
            RestRoute(method="GET", path=f"{_DEALS}/{{dealId}}"),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=HubSpotAction.CONTACTS_CREATE,
        normalised_name="Create a contact",
        description="Create a new contact.",
        matches=(RestRoute(method="POST", path=_CONTACTS),),
    ),
    EndpointSpec(
        id=HubSpotAction.CONTACTS_UPDATE,
        normalised_name="Update a contact",
        description="Update an existing contact's properties.",
        matches=(RestRoute(method="PATCH", path=f"{_CONTACTS}/{{contactId}}"),),
    ),
    EndpointSpec(
        id=HubSpotAction.COMPANIES_CREATE,
        normalised_name="Create a company",
        description="Create a new company.",
        matches=(RestRoute(method="POST", path=_COMPANIES),),
    ),
    EndpointSpec(
        id=HubSpotAction.COMPANIES_UPDATE,
        normalised_name="Update a company",
        description="Update an existing company's properties.",
        matches=(RestRoute(method="PATCH", path=f"{_COMPANIES}/{{companyId}}"),),
    ),
    EndpointSpec(
        id=HubSpotAction.DEALS_CREATE,
        normalised_name="Create a deal",
        description="Create a new deal.",
        matches=(RestRoute(method="POST", path=_DEALS),),
    ),
    EndpointSpec(
        id=HubSpotAction.DEALS_UPDATE,
        normalised_name="Update a deal",
        description="Update an existing deal's properties.",
        matches=(RestRoute(method="PATCH", path=f"{_DEALS}/{{dealId}}"),),
    ),
]


class HubSpotProvider(OAuthExternalAppProvider, OnyxManagedExtApp):
    spec = OAuthProviderSpec(
        app_type=ExternalAppType.HUBSPOT,
        app_name="HubSpot",
        oauth=OAuthFlowSpec(
            authorize_url="https://app.hubspot.com/oauth/authorize",
            token_url="https://api.hubapi.com/oauth/v1/token",
            scope=" ".join(
                [
                    "crm.objects.contacts.read",
                    "crm.objects.contacts.write",
                    "crm.objects.companies.read",
                    "crm.objects.companies.write",
                    "crm.objects.deals.read",
                    "crm.objects.deals.write",
                    "oauth",
                ]
            ),
            scope_param="scope",
        ),
        descriptor=AdminDescriptorSpec(
            description=(
                "Read, create, and update contacts, companies, and deals in "
                "HubSpot on the user's behalf."
            ),
            upstream_url_patterns=["https://api\\.hubapi\\.com/.*"],
            auth_template={"Authorization": "Bearer {access_token}"},
            required_org_credential_fields=[
                OrgCredentialField(
                    key="client_id",
                    label="Client ID",
                    description=(
                        "Found on your HubSpot app's Auth settings page "
                        "(Developer account → Apps → your app → Auth)."
                    ),
                ),
                OrgCredentialField(
                    key="client_secret",
                    label="Client Secret",
                    description=(
                        "Generated on the same app Auth settings page. "
                        "Treat this like a password."
                    ),
                    secret=True,
                ),
            ],
            setup_instructions=(
                "In HubSpot: Developer account → Apps → Create app (or pick an "
                "existing one) → Auth. Add this Onyx instance's callback URL "
                "(/craft/v1/apps/oauth/callback) as a redirect URL and select the "
                "contacts, companies, and deals CRM scopes. Copy the Client ID "
                "and Client Secret and paste them below. The agent is granted "
                "read/write on contacts, companies, and deals."
            ),
        ),
        endpoint_catalog=_ENDPOINTS,
    )

    managed_org_credentials = {
        "client_id": EXT_APP_HUBSPOT_CLIENT_ID,
        "client_secret": EXT_APP_HUBSPOT_CLIENT_SECRET,
    }

    # HubSpot signals a dead refresh token with `BAD_REFRESH_TOKEN` rather than
    # RFC-6749's `invalid_grant`; treat it as terminal so the user reconnects.
    terminal_refresh_errors = frozenset({"invalid_grant", "BAD_REFRESH_TOKEN"})

    def classify_token_response(
        self, response: requests.Response, body: dict[str, Any]
    ) -> str | None:
        # HubSpot's token endpoint reports failures as a non-2xx with a body
        # shaped `{"status": "BAD_AUTH_CODE", "message": "..."}` — it carries no
        # RFC-6749 `error` key, so surface the machine-readable `status` for
        # terminal-vs-transient classification before falling back to the generic
        # handler.
        if response.status_code >= 400 and isinstance(body, dict) and body.get("status"):
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
        # HubSpot access tokens are short-lived (~30 min) and always issue a
        # refresh token, so persist both for the lazy-refresh path.
        if response_data.get("refresh_token"):
            creds["refresh_token"] = response_data["refresh_token"]
        if response_data.get("expires_in"):
            creds["expires_in"] = response_data["expires_in"]
        return creds
