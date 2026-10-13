import re
from collections.abc import Mapping
from typing import Any

from onyx.db.enums import EndpointPolicy, ExternalAppType
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.providers.actions import (
    EndpointSpec,
    ExternalAppAction,
    RestRoute,
)
from onyx.external_apps.providers.base import (
    AdminDescriptorSpec,
    AppInstanceConfig,
    OAuthEndpoints,
    OAuthExternalAppProvider,
    OAuthFlowSpec,
    OAuthProviderSpec,
    OrgCredentialField,
    TokenExchangeRequest,
)

# Every Zendesk account lives on its own `<subdomain>.zendesk.com` host, so the
# OAuth endpoints, the gateway's URL patterns, and the bundled skill's base URL
# are all derived from the subdomain an admin configures.
SUBDOMAIN_FIELD = "subdomain"
_ZENDESK_HOST_SUFFIX = ".zendesk.com"
# A DNS label: lowercase alphanumerics and inner hyphens, at most 63 characters.
_SUBDOMAIN_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
_SCHEME_RE = re.compile(r"^https?://", re.IGNORECASE)

# Zendesk mints 30-minute access tokens by default and only issues a refresh
# token when the token request names an expiry, so ask for one explicitly: a day
# (within Zendesk's 300s–172800s range) keeps refreshes rare while staying well
# inside the 30-day refresh-token lifetime.
_ACCESS_TOKEN_TTL_SECONDS = 86400


def normalise_subdomain(raw: object) -> str:
    """The bare account subdomain from what an admin typed, which is as often a
    pasted URL (``https://acme.zendesk.com/agent``) as the subdomain itself.

    Raises ``OnyxError(INVALID_INPUT)`` on anything that isn't a single DNS
    label — this value becomes a URL host, so it is never interpolated unchecked.
    """
    value = raw.strip().lower() if isinstance(raw, str) else ""
    value = _SCHEME_RE.sub("", value)
    # Keep the host only: drop any path, query, fragment, credentials and port.
    value = re.split(r"[/?#]", value, maxsplit=1)[0]
    value = value.rpartition("@")[2].partition(":")[0]
    value = value.removesuffix(_ZENDESK_HOST_SUFFIX)
    if not _SUBDOMAIN_RE.fullmatch(value):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Zendesk subdomain must be the account's own subdomain — the "
            "'acme' in https://acme.zendesk.com.",
        )
    return value


def _routes(method: str, *paths: str) -> tuple[RestRoute, ...]:
    """Recognition rules for ``paths``, each also in the ``.json`` suffix form
    Zendesk accepts interchangeably (``/api/v2/tickets.json``). A path ending in
    a ``{placeholder}`` needs no twin — the placeholder already matches the
    suffixed segment (``123.json``)."""
    routes: list[RestRoute] = []
    for path in paths:
        routes.append(RestRoute(method=method, path=path))
        if not path.endswith("}"):
            routes.append(RestRoute(method=method, path=f"{path}.json"))
    return tuple(routes)


class ZendeskAction(ExternalAppAction):
    """Strongly-typed catalog ids for the Zendesk provider."""

    TICKETS_READ = "zendesk.tickets.read"
    SEARCH = "zendesk.search"
    INCREMENTAL_EXPORT = "zendesk.incremental.read"
    TICKET_METRICS_READ = "zendesk.ticket_metrics.read"
    SATISFACTION_RATINGS_READ = "zendesk.satisfaction_ratings.read"
    USERS_READ = "zendesk.users.read"
    ORGANIZATIONS_READ = "zendesk.organizations.read"
    VIEWS_READ = "zendesk.views.read"
    TICKET_FIELDS_READ = "zendesk.ticket_fields.read"
    TICKETS_CREATE = "zendesk.tickets.create"
    TICKETS_UPDATE = "zendesk.tickets.update"
    TICKET_TAGS_UPDATE = "zendesk.tickets.tags.update"
    TICKETS_DELETE = "zendesk.tickets.delete"


# The Zendesk Support API is a path-addressed JSON REST API under
# `/api/v2`; the action is the HTTP method + path template.
_ENDPOINTS: list[EndpointSpec] = [
    EndpointSpec(
        id=ZendeskAction.TICKETS_READ,
        normalised_name="Read tickets",
        description="List and fetch tickets, their comments, and their audits.",
        matches=_routes(
            "GET",
            "/api/v2/tickets",
            "/api/v2/tickets/{ticket_id}",
            "/api/v2/tickets/{ticket_id}/comments",
            "/api/v2/tickets/{ticket_id}/audits",
            "/api/v2/tickets/{ticket_id}/related",
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=ZendeskAction.SEARCH,
        normalised_name="Search",
        description="Search tickets, users, and organizations with Zendesk query syntax.",
        matches=_routes("GET", "/api/v2/search", "/api/v2/search/export"),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=ZendeskAction.INCREMENTAL_EXPORT,
        normalised_name="Read ticket changes since a cursor",
        description=(
            "Page the incremental export of tickets changed since a given time "
            "or cursor — how a scheduled task picks up only what moved."
        ),
        matches=_routes(
            "GET",
            "/api/v2/incremental/tickets",
            "/api/v2/incremental/tickets/cursor",
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=ZendeskAction.TICKET_METRICS_READ,
        normalised_name="Read ticket metrics",
        description=(
            "Read reply, resolution, and handling times for tickets (SLA "
            "reporting inputs)."
        ),
        matches=_routes(
            "GET",
            "/api/v2/ticket_metrics",
            "/api/v2/ticket_metrics/{ticket_metric_id}",
            "/api/v2/tickets/{ticket_id}/metrics",
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=ZendeskAction.SATISFACTION_RATINGS_READ,
        normalised_name="Read satisfaction ratings",
        description="Read the CSAT ratings and comments end users left on tickets.",
        matches=_routes(
            "GET",
            "/api/v2/satisfaction_ratings",
            "/api/v2/satisfaction_ratings/{rating_id}",
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=ZendeskAction.USERS_READ,
        normalised_name="Read users",
        description=(
            "List, search, and fetch agents and end users, including the "
            "connected user's own profile."
        ),
        matches=_routes(
            "GET",
            "/api/v2/users",
            "/api/v2/users/{user_id}",
            "/api/v2/users/{user_id}/organizations",
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=ZendeskAction.ORGANIZATIONS_READ,
        normalised_name="Read organizations",
        description="List, search, and fetch organizations and their tickets.",
        matches=_routes(
            "GET",
            "/api/v2/organizations",
            "/api/v2/organizations/{organization_id}",
            "/api/v2/organizations/{organization_id}/tickets",
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=ZendeskAction.VIEWS_READ,
        normalised_name="Read views",
        description="List views and the tickets each one holds.",
        matches=_routes(
            "GET",
            "/api/v2/views",
            "/api/v2/views/{view_id}",
            "/api/v2/views/{view_id}/tickets",
            "/api/v2/views/{view_id}/execute",
            "/api/v2/views/{view_id}/count",
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=ZendeskAction.TICKET_FIELDS_READ,
        normalised_name="Read ticket fields",
        description=(
            "Read the ticket field definitions needed to interpret custom field "
            "ids on a ticket."
        ),
        matches=_routes(
            "GET",
            "/api/v2/ticket_fields",
            "/api/v2/ticket_fields/{ticket_field_id}",
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=ZendeskAction.TICKETS_CREATE,
        normalised_name="Create a ticket",
        description="Open a new ticket.",
        matches=_routes("POST", "/api/v2/tickets", "/api/v2/tickets/create_many"),
    ),
    EndpointSpec(
        id=ZendeskAction.TICKETS_UPDATE,
        normalised_name="Update a ticket",
        description=(
            "Change a ticket's fields or add a comment to it — Zendesk adds "
            "both public replies and internal notes through a ticket update."
        ),
        matches=_routes(
            "PUT",
            "/api/v2/tickets/{ticket_id}",
            "/api/v2/tickets/update_many",
        ),
    ),
    EndpointSpec(
        id=ZendeskAction.TICKET_TAGS_UPDATE,
        normalised_name="Change a ticket's tags",
        description="Add or replace the tags on a ticket.",
        matches=(
            *_routes("PUT", "/api/v2/tickets/{ticket_id}/tags"),
            *_routes("POST", "/api/v2/tickets/{ticket_id}/tags"),
        ),
    ),
    EndpointSpec(
        id=ZendeskAction.TICKETS_DELETE,
        normalised_name="Delete a ticket",
        description="Permanently remove a ticket.",
        matches=_routes(
            "DELETE",
            "/api/v2/tickets/{ticket_id}",
            "/api/v2/tickets/destroy_many",
        ),
    ),
]

# Resource scopes rather than Zendesk's broad `read`/`write`, so the grant
# covers the catalog above and nothing else. Zendesk has no optional-scope
# mechanism: every scope named here must be grantable, so this stays to
# features every Support plan has.
_SCOPES = [
    "tickets:read",
    "tickets:write",
    "users:read",
    "organizations:read",
    "ticket_views:read",
    "satisfaction_ratings:read",
]


class ZendeskProvider(OAuthExternalAppProvider):
    """Zendesk Support, connected with the deployment's own OAuth client.

    Not an ``OnyxManagedExtApp``: Zendesk's authorize and token endpoints live
    on the customer's own `<subdomain>.zendesk.com` host and its OAuth clients
    are registered per account, so there is nothing for Onyx to own centrally.
    An admin registers the client in their Zendesk admin center and fills in the
    subdomain and client credentials.
    """

    spec = OAuthProviderSpec(
        app_type=ExternalAppType.ZENDESK,
        app_name="Zendesk",
        oauth=OAuthFlowSpec(
            # Per-account hosts; `resolve_oauth_endpoints` fills in `{subdomain}`
            # from the app's organization credentials before either is used.
            authorize_url="https://{subdomain}.zendesk.com/oauth/authorizations/new",
            token_url="https://{subdomain}.zendesk.com/oauth/tokens",
            scope=" ".join(_SCOPES),
            scope_param="scope",
            extra_authorize_params={"response_type": "code"},
        ),
        descriptor=AdminDescriptorSpec(
            # Resolved per account by `resolve_instance`. There is no
            # account-agnostic Zendesk host to fall back to, so the static list
            # stays empty rather than naming one that must never match.
            upstream_url_patterns=[],
            auth_template={"Authorization": "Bearer {access_token}"},
            required_org_credential_fields=[
                OrgCredentialField(
                    key=SUBDOMAIN_FIELD,
                    label="Subdomain",
                    description=(
                        "Your Zendesk account's subdomain — the 'acme' in "
                        "https://acme.zendesk.com."
                    ),
                ),
                OrgCredentialField(
                    key="client_id",
                    label="Unique identifier",
                    description=(
                        "The OAuth client's Unique identifier, from Zendesk "
                        "Admin Center → Apps and integrations → APIs → "
                        "Zendesk API → OAuth Clients."
                    ),
                ),
                OrgCredentialField(
                    key="client_secret",
                    label="Secret",
                    description=(
                        "Shown once when the OAuth client is created. Treat "
                        "this like a password."
                    ),
                    secret=True,
                ),
            ],
            setup_instructions=(
                "In Zendesk: Admin Center → Apps and integrations → APIs → "
                "Zendesk API → OAuth Clients → add a client. Set its Redirect "
                "URL to this Onyx instance's callback URL "
                "(/craft/v1/apps/oauth/callback) and copy the Secret when "
                "Zendesk shows it — it is shown only once. Then fill in your "
                "subdomain, the client's Unique identifier, and the Secret "
                "below. The agent is granted read access to tickets, users, "
                "organizations, views, and satisfaction ratings, plus write "
                "access to tickets."
            ),
        ),
        endpoint_catalog=_ENDPOINTS,
    )

    # Zendesk's /oauth/tokens takes a JSON body for both the code exchange and
    # the refresh.
    refresh_json_encoded = True

    def _subdomain(self, org_credentials: Mapping[str, str]) -> str:
        return normalise_subdomain(org_credentials.get(SUBDOMAIN_FIELD))

    def resolve_instance(self, org_credentials: Mapping[str, str]) -> AppInstanceConfig:
        subdomain = self._subdomain(org_credentials)
        host = f"{subdomain}{_ZENDESK_HOST_SUFFIX}"
        return AppInstanceConfig(
            # The configured account only: a pattern spanning *.zendesk.com
            # would let a prompt-injected agent spend this tenant's token on
            # someone else's Zendesk account.
            upstream_url_patterns=[rf"https://{re.escape(host)}/api/v2/.*"],
            skill_template_values={"base_url": f"https://{host}"},
        )

    def resolve_oauth_endpoints(
        self, org_credentials: Mapping[str, str]
    ) -> OAuthEndpoints:
        subdomain = self._subdomain(org_credentials)
        return OAuthEndpoints(
            authorize_url=self.spec.oauth.authorize_url.format(subdomain=subdomain),
            token_url=self.spec.oauth.token_url.format(subdomain=subdomain),
        )

    def build_token_exchange_request(
        self, code: str, client_id: str, client_secret: str, redirect_uri: str
    ) -> TokenExchangeRequest:
        return TokenExchangeRequest(
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            body={
                "grant_type": "authorization_code",
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
                "scope": self.spec.oauth.scope,
                # Without an explicit expiry an older Zendesk client mints a
                # non-expiring access token and no refresh token at all.
                "expires_in": _ACCESS_TOKEN_TTL_SECONDS,
            },
            json_encoded=True,
        )

    def build_refresh_request(
        self, refresh_token: str, client_id: str, client_secret: str
    ) -> dict[str, Any]:
        return {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            # Same reason as the code exchange: each refresh re-states the
            # expiry, and Zendesk rotates the refresh token with it.
            "expires_in": _ACCESS_TOKEN_TTL_SECONDS,
        }

    def extract_credentials(self, response_data: dict[str, Any]) -> dict[str, Any]:
        access_token = response_data.get("access_token")
        if not access_token:
            raise OnyxError(
                OnyxErrorCode.BAD_GATEWAY,
                "Zendesk OAuth response did not contain an access token.",
            )
        creds: dict[str, Any] = {
            "access_token": access_token,
            "token_type": response_data.get("token_type"),
            "scope": response_data.get("scope"),
        }
        # Present whenever the client is configured for expiring tokens; absent
        # for a legacy client, which reads downstream as a non-expiring token.
        for key in ("refresh_token", "expires_in"):
            if response_data.get(key):
                creds[key] = response_data[key]
        return creds
