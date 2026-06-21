from typing import Any

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
from onyx.external_apps.providers.base import OrgCredentialField


class HubSpotAction(ExternalAppAction):
    """Strongly-typed catalog ids for the HubSpot provider."""

    ACCOUNT_READ = "hubspot.account.read"
    CONTACTS_READ = "hubspot.contacts.read"
    COMPANIES_READ = "hubspot.companies.read"
    DEALS_READ = "hubspot.deals.read"
    SEARCH_READ = "hubspot.search.read"
    CONTACTS_CREATE = "hubspot.contacts.create"
    CONTACTS_UPDATE = "hubspot.contacts.update"


# HubSpot's CRM is a path-addressed JSON REST API rooted at
# https://api.hubapi.com; the action is the HTTP method + path template. A
# `{name}` segment matches one path segment (an object id, etc.). HubSpot's
# `search` endpoints are POSTs that only read, so they carry an ALWAYS policy
# even though they are POSTs — the catalog keys on intent, not on the verb.
_ENDPOINTS: list[EndpointSpec] = [
    EndpointSpec(
        id=HubSpotAction.ACCOUNT_READ,
        normalised_name="Read the connected account",
        description="Read the authenticated HubSpot account's details.",
        matches=(RestRoute(method="GET", path="/account-info/v3/details"),),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=HubSpotAction.CONTACTS_READ,
        normalised_name="Read contacts",
        description="List contacts and fetch a single contact.",
        matches=(
            RestRoute(method="GET", path="/crm/v3/objects/contacts"),
            RestRoute(method="GET", path="/crm/v3/objects/contacts/{contactId}"),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=HubSpotAction.COMPANIES_READ,
        normalised_name="Read companies",
        description="List companies and fetch a single company.",
        matches=(
            RestRoute(method="GET", path="/crm/v3/objects/companies"),
            RestRoute(method="GET", path="/crm/v3/objects/companies/{companyId}"),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=HubSpotAction.DEALS_READ,
        normalised_name="Read deals",
        description="List deals and fetch a single deal.",
        matches=(
            RestRoute(method="GET", path="/crm/v3/objects/deals"),
            RestRoute(method="GET", path="/crm/v3/objects/deals/{dealId}"),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=HubSpotAction.SEARCH_READ,
        normalised_name="Search CRM objects",
        description="Search contacts, companies, and deals (a read-only POST).",
        matches=(
            RestRoute(method="POST", path="/crm/v3/objects/contacts/search"),
            RestRoute(method="POST", path="/crm/v3/objects/companies/search"),
            RestRoute(method="POST", path="/crm/v3/objects/deals/search"),
        ),
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
        description="Update an existing contact's properties.",
        matches=(
            RestRoute(method="PATCH", path="/crm/v3/objects/contacts/{contactId}"),
        ),
    ),
]


class HubSpotProvider(OAuthExternalAppProvider):
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
                    "crm.objects.deals.read",
                    "oauth",
                ]
            ),
            scope_param="scope",
        ),
        descriptor=AdminDescriptorSpec(
            description=(
                "Read contacts, companies, and deals, search the CRM, and "
                "create or update contacts in HubSpot on the user's behalf."
            ),
            upstream_url_patterns=["https://api\\.hubapi\\.com/.*"],
            auth_template={"Authorization": "Bearer {access_token}"},
            required_org_credential_fields=[
                OrgCredentialField(
                    key="client_id",
                    label="Client ID",
                    description=(
                        "Found on your HubSpot app's Auth settings page "
                        "(HubSpot developer account → Apps → your app → Auth)."
                    ),
                ),
                OrgCredentialField(
                    key="client_secret",
                    label="Client Secret",
                    description=(
                        "Found alongside the Client ID on the same Auth "
                        "settings page. Treat this like a password."
                    ),
                    secret=True,
                ),
            ],
            setup_instructions=(
                "In HubSpot: create a developer account, then Apps → Create app. "
                "On the Auth tab, add this Onyx instance's callback URL "
                "(/craft/v1/apps/oauth/callback) to Redirect URLs and select the "
                "CRM scopes (contacts read/write, companies read, deals read, "
                "oauth). Save, then paste the Client ID and Client Secret below."
            ),
        ),
        endpoint_catalog=_ENDPOINTS,
    )

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
        # HubSpot issues a rotating refresh token and a short-lived access
        # token (typically 30 minutes); both are present on the initial grant
        # and on refresh.
        if response_data.get("refresh_token"):
            creds["refresh_token"] = response_data["refresh_token"]
        if response_data.get("expires_in"):
            creds["expires_in"] = response_data["expires_in"]
        return creds
