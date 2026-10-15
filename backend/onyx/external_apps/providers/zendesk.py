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
    OAuthExternalAppProvider,
    OAuthFlowSpec,
    OAuthProviderSpec,
    OrgCredentialField,
    TokenExchangeRequest,
)
from onyx.oauth.protocol import build_authorization_code_token_body

# Every Zendesk account lives on its own `<subdomain>.zendesk.com` host, so the
# OAuth endpoints and the skill's base URL both come from this field.
SUBDOMAIN_FIELD = "subdomain"
_ZENDESK_HOST_SUFFIX = ".zendesk.com"
# A DNS label, matched with `fullmatch`.
_SUBDOMAIN_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
_SCHEME_RE = re.compile(r"^https?://", re.IGNORECASE)

# Zendesk issues a refresh token only when the request names an expiry. A day
# sits inside its 300s–172800s range and its 30-day refresh-token lifetime.
_ACCESS_TOKEN_TTL_SECONDS = 86400


def normalise_subdomain(raw: object) -> str:
    """The bare account subdomain from what an admin typed — as often a pasted
    URL (``https://acme.zendesk.com/agent``) as the subdomain itself.

    Raises ``OnyxError(INVALID_INPUT)`` on anything that isn't a single DNS
    label: this value becomes a URL host, never interpolated unchecked."""
    value = raw.strip().lower() if isinstance(raw, str) else ""
    value = _SCHEME_RE.sub("", value)
    # Host only: drop path, query, fragment, credentials and port.
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


def _routes(methods: str | tuple[str, ...], *paths: str) -> tuple[RestRoute, ...]:
    """Recognition rules for ``paths``, each also in the ``.json`` suffix form
    Zendesk accepts interchangeably. A path ending in a ``{placeholder}`` needs
    no twin — the placeholder already matches ``123.json``."""
    routes: list[RestRoute] = []
    for method in (methods,) if isinstance(methods, str) else methods:
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
    TICKETS_DELETE = "zendesk.tickets.delete"
    HELP_CENTER_READ = "zendesk.help_center.read"
    HELP_CENTER_WRITE = "zendesk.help_center.write"
    SIDE_CONVERSATIONS_READ = "zendesk.side_conversations.read"
    SIDE_CONVERSATIONS_WRITE = "zendesk.side_conversations.write"
    MACROS_READ = "zendesk.macros.read"
    MACROS_WRITE = "zendesk.macros.write"


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
            "Change a ticket's fields, tags, or add a comment to it — Zendesk "
            "adds both public replies and internal notes through a ticket "
            "update."
        ),
        # Tags share this action: Zendesk sets them both on `/tags` and through
        # a `tags` field on a plain update, and the matcher sees path only, so a
        # separate tag action would be bypassable on the other route.
        matches=(
            *_routes(
                "PUT",
                "/api/v2/tickets/{ticket_id}",
                "/api/v2/tickets/update_many",
                "/api/v2/tickets/{ticket_id}/tags",
            ),
            *_routes("POST", "/api/v2/tickets/{ticket_id}/tags"),
            *_routes("DELETE", "/api/v2/tickets/{ticket_id}/tags"),
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
    EndpointSpec(
        id=ZendeskAction.HELP_CENTER_READ,
        normalised_name="Read Help Center",
        description="Read articles, sections, and article translations.",
        matches=_routes(
            "GET",
            "/api/v2/help_center/{resource...}",
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=ZendeskAction.HELP_CENTER_WRITE,
        normalised_name="Write Help Center content",
        description="Create, edit, publish, or delete Help Center content.",
        matches=_routes(
            ("POST", "PUT", "PATCH", "DELETE"),
            "/api/v2/help_center/{resource...}",
        ),
        default_policy=EndpointPolicy.ASK,
    ),
    EndpointSpec(
        id=ZendeskAction.SIDE_CONVERSATIONS_READ,
        normalised_name="Read side conversations",
        description="Read conversations and their messages within a ticket.",
        matches=_routes(
            "GET",
            "/api/v2/tickets/{ticket_id}/side_conversations",
            "/api/v2/tickets/{ticket_id}/side_conversations/{resource...}",
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=ZendeskAction.SIDE_CONVERSATIONS_WRITE,
        normalised_name="Write side conversations",
        description="Start, reply to, or update side conversations, including messages to external recipients.",
        matches=_routes(
            ("POST", "PUT", "PATCH", "DELETE"),
            "/api/v2/tickets/{ticket_id}/side_conversations",
            "/api/v2/tickets/{ticket_id}/side_conversations/{resource...}",
        ),
        default_policy=EndpointPolicy.ASK,
    ),
    EndpointSpec(
        id=ZendeskAction.MACROS_READ,
        normalised_name="Read macros",
        description="Read saved replies and macro actions.",
        matches=_routes(
            "GET",
            "/api/v2/macros",
            "/api/v2/macros/{resource...}",
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=ZendeskAction.MACROS_WRITE,
        normalised_name="Write macros",
        description="Create, edit, or delete saved replies and macro actions.",
        matches=_routes(
            ("POST", "PUT", "PATCH", "DELETE"),
            "/api/v2/macros",
            "/api/v2/macros/{resource...}",
        ),
        default_policy=EndpointPolicy.ASK,
    ),
]

# Search and ticket audits require broad read access. Writes use resource scopes.
_SCOPES = [
    "read",
    "tickets:write",
    "hc:write",
    "side_conversations:write",
    "macros:write",
]


class ZendeskProvider(OAuthExternalAppProvider):
    """Zendesk Support, connected with the deployment's own OAuth client.

    Not an ``OnyxManagedExtApp``: Zendesk registers OAuth clients per account on
    that account's own host, so there is no client for Onyx to own centrally."""

    spec = OAuthProviderSpec(
        app_type=ExternalAppType.ZENDESK,
        app_name="Zendesk",
        oauth=OAuthFlowSpec(
            # `resolve_oauth_flow` fills `{subdomain}` before either is used.
            authorize_url="https://{subdomain}.zendesk.com/oauth/authorizations/new",
            token_url="https://{subdomain}.zendesk.com/oauth/tokens",
            scope=" ".join(_SCOPES),
            scope_param="scope",
            supports_pkce=True,
        ),
        descriptor=AdminDescriptorSpec(
            # The write path resolves this template from restored credentials.
            upstream_url_patterns=[r"https://{subdomain}\.zendesk\.com/api/v2/.*"],
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
                        "Admin Center → APIs → OAuth clients."
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
                "In Zendesk, open Admin Center → APIs → OAuth clients and add a client. "
                "Set Client kind to Confidential. Onyx uses PKCE together with the client secret. "
                "Add these allowed scopes to the client: "
                f"{', '.join(_SCOPES)}. "
                "The read scope allows reading all Zendesk data and is required for search and ticket audits. "
                "The tickets:write scope allows creating, updating, and deleting tickets. "
                "The hc:write scope allows Help Center changes, side_conversations:write allows ticket side conversations, "
                "and macros:write allows saved reply changes. "
                "Onyx asks for approval before writes by default. "
                "Help Center and side conversations also require the relevant Zendesk features and user permissions. "
                "All listed scopes must be allowed, even if you do not use every feature. "
                "After changing allowed scopes, reconnect Zendesk in Onyx to grant them. "
                "Set the Redirect URL to this Onyx instance's full callback URL "
                "(https://<your-onyx-domain>/craft/v1/apps/oauth/callback). "
                "Copy the Secret when Zendesk shows it; it is shown only once. "
                "Then enter your subdomain, the client's Unique identifier, and the Secret below. "
                "The subdomain selects the Zendesk account this app can access."
            ),
        ),
        endpoint_catalog=_ENDPOINTS,
    )

    # /oauth/tokens takes a JSON body for the exchange and the refresh alike.
    refresh_json_encoded = True

    def resolve_upstream_url_patterns(
        self,
        org_credentials: Mapping[str, str],
        submitted: list[str],  # noqa: ARG002 — the account owns its host
    ) -> list[str]:
        subdomain = normalise_subdomain(org_credentials.get(SUBDOMAIN_FIELD))
        return [
            pattern.replace("{subdomain}", re.escape(subdomain))
            for pattern in self.spec.descriptor.upstream_url_patterns
        ]

    def skill_template_values(
        self, org_credentials: Mapping[str, str]
    ) -> dict[str, str]:
        subdomain = normalise_subdomain(org_credentials.get(SUBDOMAIN_FIELD))
        return {"base_url": f"https://{subdomain}{_ZENDESK_HOST_SUFFIX}"}

    def resolve_oauth_flow(self, org_credentials: Mapping[str, str]) -> OAuthFlowSpec:
        subdomain = normalise_subdomain(org_credentials.get(SUBDOMAIN_FIELD))
        return self.spec.oauth.model_copy(
            update={
                "authorize_url": self.spec.oauth.authorize_url.format(
                    subdomain=subdomain
                ),
                "token_url": self.spec.oauth.token_url.format(subdomain=subdomain),
            }
        )

    def build_token_exchange_request(
        self,
        code: str,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        *,
        code_verifier: str | None = None,
    ) -> TokenExchangeRequest:
        return TokenExchangeRequest(
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            body={
                **build_authorization_code_token_body(
                    code=code,
                    client_id=client_id,
                    client_secret=client_secret,
                    redirect_uri=redirect_uri,
                    code_verifier=code_verifier,
                ),
                "scope": self.spec.oauth.scope,
                # Without an explicit expiry, an older client issues no refresh
                # token at all.
                "expires_in": _ACCESS_TOKEN_TTL_SECONDS,
            },
            json_encoded=True,
        )

    def build_refresh_request(
        self, refresh_token: str, client_id: str, client_secret: str
    ) -> dict[str, Any]:
        return {
            **super().build_refresh_request(refresh_token, client_id, client_secret),
            # Re-stated per refresh; Zendesk rotates the refresh token with it.
            "expires_in": _ACCESS_TOKEN_TTL_SECONDS,
        }
