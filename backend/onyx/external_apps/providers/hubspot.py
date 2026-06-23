from typing import Any

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


class HubSpotAction(ExternalAppAction):
    """Strongly-typed catalog ids for the HubSpot provider."""

    CONTACTS_READ = "hubspot.contacts.read"
    CONTACTS_SEARCH = "hubspot.contacts.search"
    CONTACTS_CREATE = "hubspot.contacts.create"
    CONTACTS_UPDATE = "hubspot.contacts.update"
    COMPANIES_READ = "hubspot.companies.read"
    COMPANIES_SEARCH = "hubspot.companies.search"
    COMPANIES_CREATE = "hubspot.companies.create"
    COMPANIES_UPDATE = "hubspot.companies.update"
    DEALS_READ = "hubspot.deals.read"
    DEALS_SEARCH = "hubspot.deals.search"
    DEALS_CREATE = "hubspot.deals.create"
    DEALS_UPDATE = "hubspot.deals.update"


# HubSpot's CRM is a path-addressed JSON API rooted at https://api.hubapi.com;
# the action is the HTTP method + path template. A `{id}` segment matches one
# path segment (the CRM object id). Searches are POSTs but read-only, so they
# auto-approve; creates (POST) and updates (PATCH) require approval by default.
_ENDPOINTS: list[EndpointSpec] = [
    EndpointSpec(
        id=HubSpotAction.CONTACTS_READ,
        normalised_name="Read contacts",
        description="List contacts and fetch a single contact by id.",
        matches=(
            RestRoute(method="GET", path="/crm/v3/objects/contacts"),
            RestRoute(method="GET", path="/crm/v3/objects/contacts/{id}"),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=HubSpotAction.CONTACTS_SEARCH,
        normalised_name="Search contacts",
        description="Search contacts with filters (a read).",
        matches=(RestRoute(method="POST", path="/crm/v3/objects/contacts/search"),),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=HubSpotAction.CONTACTS_CREATE,
        normalised_name="Create a contact",
        description="Create a new contact.",
        matches=(RestRoute(method="POST", path="/crm/v3/objects/contacts"),),
    ),
    EndpointSpec(
        id=HubSpotAction.CONTACTS_UPDATE,
        normalised_name="Update a contact",
        description="Update an existing contact by id.",
        matches=(RestRoute(method="PATCH", path="/crm/v3/objects/contacts/{id}"),),
    ),
    EndpointSpec(
        id=HubSpotAction.COMPANIES_READ,
        normalised_name="Read companies",
        description="List companies and fetch a single company by id.",
        matches=(
            RestRoute(method="GET", path="/crm/v3/objects/companies"),
            RestRoute(method="GET", path="/crm/v3/objects/companies/{id}"),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=HubSpotAction.COMPANIES_SEARCH,
        normalised_name="Search companies",
        description="Search companies with filters (a read).",
        matches=(RestRoute(method="POST", path="/crm/v3/objects/companies/search"),),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=HubSpotAction.COMPANIES_CREATE,
        normalised_name="Create a company",
        description="Create a new company.",
        matches=(RestRoute(method="POST", path="/crm/v3/objects/companies"),),
    ),
    EndpointSpec(
        id=HubSpotAction.COMPANIES_UPDATE,
        normalised_name="Update a company",
        description="Update an existing company by id.",
        matches=(RestRoute(method="PATCH", path="/crm/v3/objects/companies/{id}"),),
    ),
    EndpointSpec(
        id=HubSpotAction.DEALS_READ,
        normalised_name="Read deals",
        description="List deals and fetch a single deal by id.",
        matches=(
            RestRoute(method="GET", path="/crm/v3/objects/deals"),
            RestRoute(method="GET", path="/crm/v3/objects/deals/{id}"),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=HubSpotAction.DEALS_SEARCH,
        normalised_name="Search deals",
        description="Search deals with filters (a read).",
        matches=(RestRoute(method="POST", path="/crm/v3/objects/deals/search"),),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=HubSpotAction.DEALS_CREATE,
        normalised_name="Create a deal",
        description="Create a new deal.",
        matches=(RestRoute(method="POST", path="/crm/v3/objects/deals"),),
    ),
    EndpointSpec(
        id=HubSpotAction.DEALS_UPDATE,
        normalised_name="Update a deal",
        description="Update an existing deal by id.",
        matches=(RestRoute(method="PATCH", path="/crm/v3/objects/deals/{id}"),),
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
            extra_authorize_params={"response_type": "code"},
        ),
        descriptor=AdminDescriptorSpec(
            description=(
                "Read, search, create, and update contacts, companies, and "
                "deals in HubSpot CRM on the user's behalf."
            ),
            upstream_url_patterns=["https://api\\.hubapi\\.com/.*"],
            auth_template={"Authorization": "Bearer {access_token}"},
            required_org_credential_fields=[
                OrgCredentialField(
                    key="client_id",
                    label="Client ID",
                    description=(
                        "Found on your HubSpot app's Auth settings page "
                        "(developer account → Apps → your app → Auth)."
                    ),
                ),
                OrgCredentialField(
                    key="client_secret",
                    label="Client Secret",
                    description=(
                        "Found alongside the Client ID on the app's Auth "
                        "settings page. Treat this like a password."
                    ),
                    secret=True,
                ),
            ],
            setup_instructions=(
                "In HubSpot: create a developer account, then Apps → Create app. "
                "On the app's Auth tab, add this Onyx instance's callback URL "
                "(/craft/v1/apps/oauth/callback) to the Redirect URLs and select "
                "the CRM scopes for contacts, companies, and deals (read+write). "
                "Save, then paste the Client ID and Client Secret below. The "
                "agent is granted read+write access to CRM contacts, companies, "
                "and deals."
            ),
        ),
        endpoint_catalog=_ENDPOINTS,
    )

    managed_org_credentials = {
        "client_id": EXT_APP_HUBSPOT_CLIENT_ID,
        "client_secret": EXT_APP_HUBSPOT_CLIENT_SECRET,
    }

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
        # HubSpot tokens expire; the flow always returns a refresh token and an
        # expiry so the runtime can refresh without user reconnection.
        if response_data.get("refresh_token"):
            creds["refresh_token"] = response_data["refresh_token"]
        if response_data.get("expires_in"):
            creds["expires_in"] = response_data["expires_in"]
        return creds
