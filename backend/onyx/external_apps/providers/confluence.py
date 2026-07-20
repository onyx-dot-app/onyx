from typing import Any

from onyx.configs.app_configs import EXT_APP_CONFLUENCE_CLIENT_ID
from onyx.configs.app_configs import EXT_APP_CONFLUENCE_CLIENT_SECRET
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
from onyx.external_apps.providers.base import TokenExchangeRequest


class ConfluenceAction(ExternalAppAction):
    """Strongly-typed catalog ids for the Confluence (Atlassian Cloud) provider."""

    ACCESSIBLE_RESOURCES = "confluence.accessible_resources"
    CURRENT_USER = "confluence.user.read"
    SPACES_READ = "confluence.spaces.read"
    CONTENT_SEARCH = "confluence.content.search"
    CONTENT_LIST = "confluence.content.list"
    CONTENT_READ = "confluence.content.read"
    CONTENT_CHILDREN_READ = "confluence.content.children.read"
    CONTENT_CREATE = "confluence.content.create"
    CONTENT_UPDATE = "confluence.content.update"
    CONTENT_DELETE = "confluence.content.delete"


# Confluence Cloud is a path-addressed JSON REST API reached through Atlassian's
# API gateway at https://api.atlassian.com. Every call other than the
# site-discovery endpoint is scoped to a site by its cloud id and rooted at the
# classic Confluence Cloud base `/ex/confluence/{cloud_id}/wiki/rest/api`. The
# action is the HTTP method + path template; a `{name}` segment matches one path
# segment (a content id / child type / cloud id).
#
# The `{content_id}` placeholder in CONTENT_READ / CONTENT_UPDATE /
# CONTENT_DELETE matches ANY single segment — including a literal `search` — so a
# CQL content search modelled as `GET .../content/search` would collide with the
# content read (both GETs on overlapping templates, and the matcher has no route
# precedence). To keep search unambiguously separate we catalogue it under the
# dedicated site search endpoint `.../wiki/rest/api/search` (which accepts the
# same `cql` param and is one segment shorter than the content-read template, so
# the two can never overlap), rather than the colliding `.../content/search`.
# This mirrors how the HubSpot catalog splits its POST `/search` read off the
# object-create write to avoid an overlap. Real Confluence content ids are
# numeric, so `.../content/{content_id}` only ever matches a content read in
# practice.
_ENDPOINTS: list[EndpointSpec] = [
    EndpointSpec(
        id=ConfluenceAction.ACCESSIBLE_RESOURCES,
        normalised_name="List accessible sites",
        description=(
            "List the Atlassian sites (Confluence Cloud instances) the grant can "
            "reach, each with the cloud id used to scope every other call."
        ),
        matches=(RestRoute(method="GET", path="/oauth/token/accessible-resources"),),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=ConfluenceAction.CURRENT_USER,
        normalised_name="Read the current user",
        description="Fetch the authenticated user's Confluence profile.",
        matches=(
            RestRoute(
                method="GET",
                path="/ex/confluence/{cloud_id}/wiki/rest/api/user/current",
            ),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=ConfluenceAction.SPACES_READ,
        normalised_name="Read spaces",
        description="List the spaces the user can see (each with its key and name).",
        matches=(
            RestRoute(
                method="GET", path="/ex/confluence/{cloud_id}/wiki/rest/api/space"
            ),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=ConfluenceAction.CONTENT_SEARCH,
        normalised_name="Search content",
        description=(
            "Search pages, blog posts, and comments with CQL via the dedicated "
            "search endpoint."
        ),
        matches=(
            RestRoute(
                method="GET", path="/ex/confluence/{cloud_id}/wiki/rest/api/search"
            ),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=ConfluenceAction.CONTENT_LIST,
        normalised_name="List content",
        description="List content (pages / blog posts), optionally filtered by space.",
        matches=(
            RestRoute(
                method="GET", path="/ex/confluence/{cloud_id}/wiki/rest/api/content"
            ),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=ConfluenceAction.CONTENT_READ,
        normalised_name="Read content",
        description=(
            "Fetch a single piece of content (page / blog post / comment) by id, "
            "optionally expanding its body, version, and space."
        ),
        matches=(
            RestRoute(
                method="GET",
                path="/ex/confluence/{cloud_id}/wiki/rest/api/content/{content_id}",
            ),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=ConfluenceAction.CONTENT_CHILDREN_READ,
        normalised_name="Read content children",
        description="List a piece of content's children of a given type (pages, comments, …).",
        matches=(
            RestRoute(
                method="GET",
                path=(
                    "/ex/confluence/{cloud_id}/wiki/rest/api/content/"
                    "{content_id}/child/{child_type}"
                ),
            ),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=ConfluenceAction.CONTENT_CREATE,
        normalised_name="Create content",
        description="Create a new page, blog post, or comment.",
        matches=(
            RestRoute(
                method="POST", path="/ex/confluence/{cloud_id}/wiki/rest/api/content"
            ),
        ),
    ),
    EndpointSpec(
        id=ConfluenceAction.CONTENT_UPDATE,
        normalised_name="Update content",
        description="Update an existing piece of content (title, body, or version).",
        matches=(
            RestRoute(
                method="PUT",
                path="/ex/confluence/{cloud_id}/wiki/rest/api/content/{content_id}",
            ),
        ),
    ),
    EndpointSpec(
        id=ConfluenceAction.CONTENT_DELETE,
        normalised_name="Delete content",
        description="Delete (trash) a piece of content by id.",
        matches=(
            RestRoute(
                method="DELETE",
                path="/ex/confluence/{cloud_id}/wiki/rest/api/content/{content_id}",
            ),
        ),
    ),
]


# Classic Confluence Cloud scopes covering the read + write catalog above.
# `offline_access` is required so Atlassian issues a refresh token — access
# tokens expire in ~1h, and the lazy-refresh path needs one to mint fresh ones.
_REQUIRED_SCOPES = [
    "read:confluence-content.all",
    "read:confluence-space.summary",
    "read:confluence-user",
    "write:confluence-content",
    "offline_access",
]


class ConfluenceProvider(OAuthExternalAppProvider, OnyxManagedExtApp):
    spec = OAuthProviderSpec(
        app_type=ExternalAppType.CONFLUENCE,
        app_name="Confluence",
        oauth=OAuthFlowSpec(
            authorize_url="https://auth.atlassian.com/authorize",
            token_url="https://auth.atlassian.com/oauth/token",
            scope=" ".join(_REQUIRED_SCOPES),
            scope_param="scope",
            # `audience` targets Atlassian's API gateway, `prompt=consent`
            # guarantees a refresh token is (re)issued on every authorization.
            extra_authorize_params={
                "audience": "api.atlassian.com",
                "response_type": "code",
                "prompt": "consent",
            },
        ),
        descriptor=AdminDescriptorSpec(
            description=(
                "Search, read, and write Confluence Cloud pages, blog posts, and "
                "comments on the user's behalf."
            ),
            upstream_url_patterns=["https://api\\.atlassian\\.com/.*"],
            auth_template={"Authorization": "Bearer {access_token}"},
            required_org_credential_fields=[
                OrgCredentialField(
                    key="client_id",
                    label="Client ID",
                    description=(
                        "Found on your Atlassian OAuth 2.0 (3LO) app's Settings "
                        "page (developer.atlassian.com → your app → Settings)."
                    ),
                ),
                OrgCredentialField(
                    key="client_secret",
                    label="Client Secret",
                    description=(
                        "Found alongside the Client ID on the app's Settings "
                        "page. Treat this like a password."
                    ),
                    secret=True,
                ),
            ],
            setup_instructions=(
                "In Atlassian: developer.atlassian.com → Create → OAuth 2.0 "
                "integration. Add the Confluence API to the app and enable the "
                "classic scopes (read:confluence-content.all, "
                "read:confluence-space.summary, read:confluence-user, "
                "write:confluence-content) plus offline_access. Under "
                "Authorization, set the callback URL to this Onyx instance's "
                "/craft/v1/apps/oauth/callback. Then copy the Client ID and "
                "Secret from Settings and paste them below."
            ),
        ),
        endpoint_catalog=_ENDPOINTS,
    )

    managed_org_credentials = {
        "client_id": EXT_APP_CONFLUENCE_CLIENT_ID,
        "client_secret": EXT_APP_CONFLUENCE_CLIENT_SECRET,
    }

    def build_token_exchange_request(
        self, code: str, client_id: str, client_secret: str, redirect_uri: str
    ) -> TokenExchangeRequest:
        # Atlassian's documented token exchange takes a JSON body carrying the
        # client credentials (NOT HTTP Basic and NOT form-encoded), so override
        # the default RFC-6749 form request. Mirrors Notion's JSON override but
        # without the Basic auth header.
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
            },
            json_encoded=True,
        )

    def extract_credentials(self, response_data: dict[str, Any]) -> dict[str, Any]:
        access_token = response_data.get("access_token")
        if not access_token:
            raise OnyxError(
                OnyxErrorCode.BAD_GATEWAY,
                "Confluence OAuth response did not contain an access token.",
            )
        creds: dict[str, Any] = {
            "access_token": access_token,
            "token_type": response_data.get("token_type"),
        }
        # Atlassian returns a rotating refresh token (when offline_access was
        # granted) and a ~1h expiry; keep them so the lazy-refresh path can mint
        # fresh access tokens without a reconnect.
        if response_data.get("refresh_token"):
            creds["refresh_token"] = response_data["refresh_token"]
        if response_data.get("expires_in"):
            creds["expires_in"] = response_data["expires_in"]
        return creds
