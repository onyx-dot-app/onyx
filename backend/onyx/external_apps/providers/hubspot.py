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


# HubSpot's CRM API is a path-addressed JSON API rooted at
# https://api.hubapi.com; an action is the method + path template. CRM objects
# live under `/crm/v3/objects/<object>`; a `{id}` segment matches one path
# segment (a record id). Reads — list/get (GET) and the POST-based `search`
# endpoint — default to ALWAYS; every mutation (create/update) defaults to ASK
# so the egress approval gate prompts the user before it runs.
_CONTACTS = "/crm/v3/objects/contacts"
_COMPANIES = "/crm/v3/objects/companies"
_DEALS = "/crm/v3/objects/deals"
_ENDPOINTS: list[EndpointSpec] = [
    # --- Contacts ---
    EndpointSpec(
        id=HubSpotAction.CONTACTS_READ,
        normalised_name="Read contacts",
        description="List contacts and fetch a single contact by id.",
        matches=(
            RestRoute(method="GET", path=_CONTACTS),
            RestRoute(method="GET", path=f"{_CONTACTS}/{{id}}"),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=HubSpotAction.CONTACTS_SEARCH,
        normalised_name="Search contacts",
        description="Search contacts by property filters via the search endpoint.",
        matches=(RestRoute(method="POST", path=f"{_CONTACTS}/search"),),
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
        matches=(RestRoute(method="PATCH", path=f"{_CONTACTS}/{{id}}"),),
    ),
    # --- Companies ---
    EndpointSpec(
        id=HubSpotAction.COMPANIES_READ,
        normalised_name="Read companies",
        description="List companies and fetch a single company by id.",
        matches=(
            RestRoute(method="GET", path=_COMPANIES),
            RestRoute(method="GET", path=f"{_COMPANIES}/{{id}}"),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=HubSpotAction.COMPANIES_SEARCH,
        normalised_name="Search companies",
        description="Search companies by property filters via the search endpoint.",
        matches=(RestRoute(method="POST", path=f"{_COMPANIES}/search"),),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=HubSpotAction.COMPANIES_CREATE,
        normalised_name="Create a company",
        description="Create a new company record.",
        matches=(RestRoute(method="POST", path=_COMPANIES),),
    ),
    EndpointSpec(
        id=HubSpotAction.COMPANIES_UPDATE,
        normalised_name="Edit a company",
        description="Update an existing company's properties.",
        matches=(RestRoute(method="PATCH", path=f"{_COMPANIES}/{{id}}"),),
    ),
    # --- Deals ---
    EndpointSpec(
        id=HubSpotAction.DEALS_READ,
        normalised_name="Read deals",
        description="List deals and fetch a single deal by id.",
        matches=(
            RestRoute(method="GET", path=_DEALS),
            RestRoute(method="GET", path=f"{_DEALS}/{{id}}"),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=HubSpotAction.DEALS_SEARCH,
        normalised_name="Search deals",
        description="Search deals by property filters via the search endpoint.",
        matches=(RestRoute(method="POST", path=f"{_DEALS}/search"),),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=HubSpotAction.DEALS_CREATE,
        normalised_name="Create a deal",
        description="Create a new deal record.",
        matches=(RestRoute(method="POST", path=_DEALS),),
    ),
    EndpointSpec(
        id=HubSpotAction.DEALS_UPDATE,
        normalised_name="Edit a deal",
        description="Update an existing deal's properties.",
        matches=(RestRoute(method="PATCH", path=f"{_DEALS}/{{id}}"),),
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
                ]
            ),
            scope_param="scope",
        ),
        descriptor=AdminDescriptorSpec(
            description=(
                "Read, search, create, and edit CRM contacts, companies, and "
                "deals in HubSpot on the user's behalf."
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
                        "Generated on the same HubSpot app Auth settings page. "
                        "Treat this like a password."
                    ),
                    secret=True,
                ),
            ],
            setup_instructions=(
                "In HubSpot: create a developer account, then create an app "
                "(Apps → Create app). On the Auth tab, set the Redirect URL to "
                "this Onyx instance's callback URL "
                "(/craft/v1/apps/oauth/callback) and add the CRM contacts, "
                "companies, and deals read/write scopes. Copy the Client ID and "
                "Client Secret and paste them below."
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
        # HubSpot always returns a rotating refresh token and an access-token
        # lifetime on both the initial grant and refresh.
        if response_data.get("refresh_token"):
            creds["refresh_token"] = response_data["refresh_token"]
        if response_data.get("expires_in"):
            creds["expires_in"] = response_data["expires_in"]
        return creds
