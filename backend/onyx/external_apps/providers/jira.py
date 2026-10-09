from typing import Any

from onyx.configs.app_configs import (
    EXT_APP_JIRA_CLIENT_ID,
    EXT_APP_JIRA_CLIENT_SECRET,
)
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
    OnyxManagedExtApp,
    OrgCredentialField,
    TokenExchangeRequest,
)


class JiraAction(ExternalAppAction):
    """Strongly-typed catalog ids for the Jira (Atlassian Cloud) provider."""

    ACCESSIBLE_RESOURCES = "jira.accessible_resources"
    MYSELF = "jira.user.read"
    PROJECTS_READ = "jira.projects.read"
    ISSUES_SEARCH = "jira.issues.search"
    ISSUE_READ = "jira.issues.read"
    COMMENTS_READ = "jira.comments.read"
    ISSUE_CREATE = "jira.issues.create"
    ISSUE_UPDATE = "jira.issues.update"
    COMMENT_CREATE = "jira.comments.create"


# Jira Cloud is a path-addressed JSON REST API reached through Atlassian's API
# gateway at https://api.atlassian.com. Every call other than the site-discovery
# endpoint is scoped to a site by its cloud id and rooted at the v3 Jira Cloud
# base `/ex/jira/{cloud_id}/rest/api/3`. The action is the HTTP method + path
# template; a `{name}` segment matches one path segment (an issue id/key or the
# cloud id).
#
# The `{issue_id_or_key}` placeholder in ISSUE_READ / ISSUE_UPDATE matches ANY
# single segment — including a literal `search` — so a JQL search modelled as
# `GET .../issue/search` would collide with the issue read (both GETs on
# overlapping templates, and the matcher has no route precedence). To keep
# search unambiguously separate we catalogue it under the dedicated `/search`
# endpoint (which is one segment shorter than the issue-read template, so the
# two can never overlap), rather than any `.../issue/search`. This mirrors how
# the Confluence catalog splits its CQL search off the content read and how the
# HubSpot catalog splits its POST `/search`. Real Jira issue ids/keys (numeric
# ids or `PROJ-123` keys) never equal the literal `search`, and an issue's
# comments live on the distinct, longer `.../issue/{issue_id_or_key}/comment`
# template, so each route resolves to exactly one action.
_ENDPOINTS: list[EndpointSpec] = [
    EndpointSpec(
        id=JiraAction.ACCESSIBLE_RESOURCES,
        normalised_name="List accessible sites",
        description=(
            "List the Atlassian sites (Jira Cloud instances) the grant can "
            "reach, each with the cloud id used to scope every other call."
        ),
        matches=(RestRoute(method="GET", path="/oauth/token/accessible-resources"),),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=JiraAction.MYSELF,
        normalised_name="Read the current user",
        description="Fetch the authenticated user's Jira profile.",
        matches=(
            RestRoute(method="GET", path="/ex/jira/{cloud_id}/rest/api/3/myself"),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=JiraAction.PROJECTS_READ,
        normalised_name="Search/list projects",
        description=(
            "List the projects the user can see (each with its id, key, and name)."
        ),
        matches=(
            RestRoute(
                method="GET", path="/ex/jira/{cloud_id}/rest/api/3/project/search"
            ),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=JiraAction.ISSUES_SEARCH,
        normalised_name="Search issues with JQL",
        description=(
            "Search issues with JQL via the dedicated search endpoint, with "
            "optional field selection and pagination."
        ),
        matches=(
            RestRoute(method="GET", path="/ex/jira/{cloud_id}/rest/api/3/search"),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=JiraAction.ISSUE_READ,
        normalised_name="Read an issue",
        description=(
            "Fetch a single issue (by numeric id or PROJ-123 key), optionally "
            "selecting fields."
        ),
        matches=(
            RestRoute(
                method="GET",
                path="/ex/jira/{cloud_id}/rest/api/3/issue/{issue_id_or_key}",
            ),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=JiraAction.COMMENTS_READ,
        normalised_name="Read issue comments",
        description="List an issue's comments.",
        matches=(
            RestRoute(
                method="GET",
                path=("/ex/jira/{cloud_id}/rest/api/3/issue/{issue_id_or_key}/comment"),
            ),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=JiraAction.ISSUE_CREATE,
        normalised_name="Create an issue",
        description="Create a new issue in a project.",
        matches=(
            RestRoute(method="POST", path="/ex/jira/{cloud_id}/rest/api/3/issue"),
        ),
    ),
    EndpointSpec(
        id=JiraAction.ISSUE_UPDATE,
        normalised_name="Update an issue",
        description="Update an existing issue's fields (summary, description, labels, …).",
        matches=(
            RestRoute(
                method="PUT",
                path="/ex/jira/{cloud_id}/rest/api/3/issue/{issue_id_or_key}",
            ),
        ),
    ),
    EndpointSpec(
        id=JiraAction.COMMENT_CREATE,
        normalised_name="Add a comment",
        description="Add a comment to an issue.",
        matches=(
            RestRoute(
                method="POST",
                path=("/ex/jira/{cloud_id}/rest/api/3/issue/{issue_id_or_key}/comment"),
            ),
        ),
    ),
]


# Classic Jira Cloud scopes covering the read + write catalog above.
# `offline_access` is required so Atlassian issues a refresh token — access
# tokens expire in ~1h, and the lazy-refresh path needs one to mint fresh ones.
_REQUIRED_SCOPES = [
    "read:jira-user",
    "read:jira-work",
    "write:jira-work",
    "offline_access",
]


class JiraProvider(OAuthExternalAppProvider, OnyxManagedExtApp):
    spec = OAuthProviderSpec(
        app_type=ExternalAppType.JIRA,
        app_name="Jira",
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
                "integration. Add the Jira API to the app and enable the classic "
                "scopes (read:jira-user, read:jira-work, write:jira-work) plus "
                "offline_access. Under Authorization, set the callback URL to "
                "this Onyx instance's /craft/v1/apps/oauth/callback. Then copy "
                "the Client ID and Secret from Settings and paste them below."
            ),
        ),
        endpoint_catalog=_ENDPOINTS,
    )

    managed_org_credentials = {
        "client_id": EXT_APP_JIRA_CLIENT_ID,
        "client_secret": EXT_APP_JIRA_CLIENT_SECRET,
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
                "Jira OAuth response did not contain an access token.",
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
