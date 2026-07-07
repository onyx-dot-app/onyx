from typing import Any
from urllib.parse import quote

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
from onyx.external_apps.providers.base import parse_granted_scopes
from onyx.external_apps.providers.base import token_response_error
from onyx.utils.logger import setup_logger

logger = setup_logger()

# HubSpot's token response omits the granted scopes, so the actual per-user
# grant (which diverges under `optional_scope`) is read from the token-info
# endpoint, which returns a `scopes` array.
_TOKEN_INFO_URL = "https://api.hubapi.com/oauth/v1/access-tokens/{access_token}"

# Bounded so a slow/hung token-info call can't pin the OAuth connect flow.
_TOKEN_INFO_TIMEOUT_SECONDS = 15.0


class HubspotAction(ExternalAppAction):
    """Strongly-typed catalog ids for the HubSpot provider."""

    OWNERS_READ = "hubspot.owners.read"
    CONTACTS_READ = "hubspot.contacts.read"
    COMPANIES_READ = "hubspot.companies.read"
    DEALS_READ = "hubspot.deals.read"
    CRM_SEARCH = "hubspot.crm.search"
    CONTACTS_WRITE = "hubspot.contacts.write"
    COMPANIES_WRITE = "hubspot.companies.write"
    DEALS_WRITE = "hubspot.deals.write"


# HubSpot's CRM is a path-addressed JSON REST API rooted at
# https://api.hubapi.com; the action is the HTTP method + path template. A
# `{name}` segment matches one path segment (an object id). CRM search is a
# read that's expressed as a POST to `.../{object}/search`, so it's catalogued
# separately from the create (`POST .../{object}`) it would otherwise collide
# with — different paths, and `search` is auto-approved while writes ask.
_ENDPOINTS: list[EndpointSpec] = [
    EndpointSpec(
        id=HubspotAction.OWNERS_READ,
        normalised_name="Read owners",
        description="List CRM owners and fetch a single owner.",
        matches=(
            RestRoute(method="GET", path="/crm/v3/owners"),
            RestRoute(method="GET", path="/crm/v3/owners/{owner_id}"),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=HubspotAction.CONTACTS_READ,
        normalised_name="Read contacts",
        description="List contacts and fetch a single contact.",
        matches=(
            RestRoute(method="GET", path="/crm/v3/objects/contacts"),
            RestRoute(method="GET", path="/crm/v3/objects/contacts/{contact_id}"),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=HubspotAction.COMPANIES_READ,
        normalised_name="Read companies",
        description="List companies and fetch a single company.",
        matches=(
            RestRoute(method="GET", path="/crm/v3/objects/companies"),
            RestRoute(method="GET", path="/crm/v3/objects/companies/{company_id}"),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=HubspotAction.DEALS_READ,
        normalised_name="Read deals",
        description="List deals and fetch a single deal.",
        matches=(
            RestRoute(method="GET", path="/crm/v3/objects/deals"),
            RestRoute(method="GET", path="/crm/v3/objects/deals/{deal_id}"),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=HubspotAction.CRM_SEARCH,
        normalised_name="Search the CRM",
        description="Search contacts, companies, and deals by filters.",
        matches=(
            RestRoute(method="POST", path="/crm/v3/objects/contacts/search"),
            RestRoute(method="POST", path="/crm/v3/objects/companies/search"),
            RestRoute(method="POST", path="/crm/v3/objects/deals/search"),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=HubspotAction.CONTACTS_WRITE,
        normalised_name="Create or update contacts",
        description="Create a new contact or update an existing one.",
        matches=(
            RestRoute(method="POST", path="/crm/v3/objects/contacts"),
            RestRoute(method="PATCH", path="/crm/v3/objects/contacts/{contact_id}"),
        ),
    ),
    EndpointSpec(
        id=HubspotAction.COMPANIES_WRITE,
        normalised_name="Create or update companies",
        description="Create a new company or update an existing one.",
        matches=(
            RestRoute(method="POST", path="/crm/v3/objects/companies"),
            RestRoute(method="PATCH", path="/crm/v3/objects/companies/{company_id}"),
        ),
    ),
    EndpointSpec(
        id=HubspotAction.DEALS_WRITE,
        normalised_name="Create or update deals",
        description="Create a new deal or update an existing one.",
        matches=(
            RestRoute(method="POST", path="/crm/v3/objects/deals"),
            RestRoute(method="PATCH", path="/crm/v3/objects/deals/{deal_id}"),
        ),
    ),
]


# `oauth` is mandatory for the auth-code flow; the reads cover the CRM objects
# this provider catalogs. Every HubSpot tier can grant these.
_REQUIRED_SCOPES = [
    "oauth",
    "crm.objects.owners.read",
    "crm.objects.contacts.read",
    "crm.objects.companies.read",
    "crm.objects.deals.read",
]

# Optional, read-only/free tiers can't grant writes, and HubSpot
# fails the whole authorize page on any ungrantable required scope. As optional
# scopes it drops what the account lacks, so everyone can still connect.
_OPTIONAL_WRITE_SCOPES = [
    "crm.objects.contacts.write",
    "crm.objects.companies.write",
    "crm.objects.deals.write",
]


class HubspotProvider(OAuthExternalAppProvider, OnyxManagedExtApp):
    spec = OAuthProviderSpec(
        app_type=ExternalAppType.HUBSPOT,
        app_name="HubSpot",
        oauth=OAuthFlowSpec(
            authorize_url="https://app.hubspot.com/oauth/authorize",
            token_url="https://api.hubapi.com/oauth/v1/token",
            scope=" ".join(_REQUIRED_SCOPES),
            scope_param="scope",
            optional_scope=" ".join(_OPTIONAL_WRITE_SCOPES),
        ),
        descriptor=AdminDescriptorSpec(
            description=(
                "Read and manage HubSpot CRM contacts, companies, and deals "
                "on the user's behalf."
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
                "the CRM contacts, companies, and deals read/write scopes plus "
                "the owners read scope. Save, then paste the Client ID and "
                "Client Secret below."
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
        # HubSpot's token endpoint returns a non-2xx with a machine-readable
        # `status` (e.g. `BAD_REFRESH_TOKEN`, `BAD_AUTH_CODE`) rather than the
        # OAuth `error` field the generic helper looks for. Surface that code so
        # terminal-vs-transient classification can match it.
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
        # HubSpot always returns a rotating refresh token and an expiry; keep
        # them so the lazy-refresh path can mint fresh access tokens.
        if response_data.get("refresh_token"):
            creds["refresh_token"] = response_data["refresh_token"]
        if response_data.get("expires_in"):
            creds["expires_in"] = response_data["expires_in"]
        return creds

    def extract_granted_scopes(self, response_data: dict[str, Any]) -> list[str] | None:
        """Reads the grant from the token-info endpoint. Best-effort: any
        network/HTTP/JSON error returns ``None`` (grant unknown) rather than
        breaking connect.
        """
        access_token = response_data.get("access_token")
        if not access_token:
            return None
        try:
            response = requests.get(
                _TOKEN_INFO_URL.format(access_token=quote(access_token, safe="")),
                timeout=_TOKEN_INFO_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            body = response.json()
        except (requests.RequestException, ValueError) as exc:
            logger.warning(
                "Could not fetch HubSpot granted scopes from the token-info "
                "endpoint; recording the grant as unknown: %s",
                exc,
            )
            return None
        return parse_granted_scopes(
            body.get("scopes") if isinstance(body, dict) else None
        )
