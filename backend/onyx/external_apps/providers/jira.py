from typing import Any

from onyx.configs.app_configs import EXT_APP_JIRA_CLIENT_ID
from onyx.configs.app_configs import EXT_APP_JIRA_CLIENT_SECRET
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

# Atlassian Cloud's Jira REST API is versioned; v3 is the current stable
# version and models issue/comment bodies as Atlassian Document Format (ADF).
# Pinned across the provider and the sandbox skill so request-shaping stays
# consistent with what the OAuth exchange negotiated.
_JIRA_API_VERSION = "3"


class JiraAction(ExternalAppAction):
    """Strongly-typed catalog ids for the Jira (Atlassian Cloud) provider."""

    ACCESSIBLE_RESOURCES = "jira.accessible_resources.read"
    MYSELF = "jira.myself.read"
    PROJECTS_READ = "jira.projects.read"
    ISSUE_SEARCH = "jira.issues.search"
    ISSUE_READ = "jira.issues.read"
    ISSUE_TRANSITIONS_READ = "jira.issues.transitions.read"
    ISSUE_CREATE = "jira.issues.create"
    ISSUE_UPDATE = "jira.issues.update"
    ISSUE_TRANSITION = "jira.issues.transition"
    COMMENT_CREATE = "jira.comments.create"


# Jira Cloud is a path-addressed JSON REST API reached through Atlassian's
# gateway at https://api.atlassian.com; after OAuth the API calls are routed to
# a specific site as `/ex/jira/{cloud_id}/rest/api/3/...`, where `{cloud_id}` is
# resolved once from `/oauth/token/accessible-resources`. The action is the HTTP
# method + path template the proxy sees. A `{name}` segment matches one path
# segment (the cloud id, or an issue id/key). JQL search is a read expressed as
# both GET and POST on `.../search`, so it's catalogued separately from the
# create (`POST .../issue`) and the transition/comment writes it would otherwise
# sit near — distinct paths, and reads are auto-approved while writes ask.
_ENDPOINTS: list[EndpointSpec] = [
    EndpointSpec(
        id=JiraAction.ACCESSIBLE_RESOURCES,
        normalised_name="List accessible sites",
        description=(
            "List the Atlassian sites (cloud ids) the authorization can reach, "
            "used to resolve the cloud id for subsequent API calls."
        ),
        matches=(RestRoute(method="GET", path="/oauth/token/accessible-resources"),),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=JiraAction.MYSELF,
        normalised_name="Read the current user",
        description="Fetch the profile of the authenticated Jira user.",
        matches=(
            RestRoute(method="GET", path="/ex/jira/{cloud_id}/rest/api/3/myself"),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=JiraAction.PROJECTS_READ,
        normalised_name="Read projects",
        description="List all projects and page through projects via project search.",
        matches=(
            RestRoute(method="GET", path="/ex/jira/{cloud_id}/rest/api/3/project"),
            RestRoute(
                method="GET", path="/ex/jira/{cloud_id}/rest/api/3/project/search"
            ),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=JiraAction.ISSUE_SEARCH,
        normalised_name="Search issues",
        description=(
            "Search issues with JQL. Offered as a GET (query params) and a POST "
            "(JSON body); both are reads."
        ),
        matches=(
            RestRoute(method="GET", path="/ex/jira/{cloud_id}/rest/api/3/search"),
            RestRoute(method="POST", path="/ex/jira/{cloud_id}/rest/api/3/search"),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=JiraAction.ISSUE_READ,
        normalised_name="Read an issue",
        description="Fetch a single issue by its id or key.",
        matches=(
            RestRoute(
                method="GET",
                path="/ex/jira/{cloud_id}/rest/api/3/issue/{issue_id_or_key}",
            ),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=JiraAction.ISSUE_TRANSITIONS_READ,
        normalised_name="Read an issue's transitions",
        description="List the workflow transitions available on an issue.",
        matches=(
            RestRoute(
                method="GET",
                path="/ex/jira/{cloud_id}/rest/api/3/issue/{issue_id_or_key}/transitions",
            ),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=JiraAction.ISSUE_CREATE,
        normalised_name="Create an issue",
        description="Create a new issue in a project.",
        matches=(RestRoute(method="POST", path="/ex/jira/{cloud_id}/rest/api/3/issue"),),
    ),
    EndpointSpec(
        id=JiraAction.ISSUE_UPDATE,
        normalised_name="Update an issue",
        description="Update the fields of an existing issue.",
        matches=(
            RestRoute(
                method="PUT",
                path="/ex/jira/{cloud_id}/rest/api/3/issue/{issue_id_or_key}",
            ),
        ),
    ),
    EndpointSpec(
        id=JiraAction.ISSUE_TRANSITION,
        normalised_name="Transition an issue",
        description="Move an issue through a workflow transition (e.g. to Done).",
        matches=(
            RestRoute(
                method="POST",
                path="/ex/jira/{cloud_id}/rest/api/3/issue/{issue_id_or_key}/transitions",
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
                path="/ex/jira/{cloud_id}/rest/api/3/issue/{issue_id_or_key}/comment",
            ),
        ),
    ),
]


# Classic Jira scopes covering the reads and writes this provider catalogs.
# `offline_access` is required for Atlassian to issue a refresh token — access
# tokens expire in ~1h, so the lazy-refresh path needs it to mint fresh ones.
# Unlike HubSpot, Atlassian doesn't fail the authorize page on grantable scopes,
# so a single `scope` (no optional split) is sufficient.
_SCOPES = [
    "read:jira-work",
    "read:jira-user",
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
            scope=" ".join(_SCOPES),
            scope_param="scope",
            # `audience` targets Atlassian's API gateway, `response_type=code`
            # is the auth-code flow, and `prompt=consent` forces the consent
            # screen so a refresh token is (re)issued on every reconnect.
            extra_authorize_params={
                "audience": "api.atlassian.com",
                "response_type": "code",
                "prompt": "consent",
            },
        ),
        descriptor=AdminDescriptorSpec(
            description=(
                "Search, read, and write Jira issues, projects, comments, and "
                "transitions on the user's behalf."
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
                "integration. Add the Jira API to the app and enable the "
                "read:jira-work, read:jira-user, and write:jira-work scopes. "
                "Under Authorization, set the callback URL to this Onyx "
                "instance's callback (/craft/v1/apps/oauth/callback). Save, then "
                "copy the Client ID and Secret from Settings and paste them below."
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
        # Atlassian's documented token exchange uses a JSON body carrying the
        # client credentials (NOT HTTP Basic auth, unlike Notion). Override the
        # default RFC-6749 form-encoded request to send JSON with the client
        # creds in the body.
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
        creds: dict[str, Any] = {"access_token": access_token}
        # Atlassian returns a rotating refresh token (thanks to offline_access)
        # and a short expiry; keep them so the lazy-refresh path can mint fresh
        # access tokens. token_type is persisted for display when present.
        if response_data.get("token_type"):
            creds["token_type"] = response_data["token_type"]
        if response_data.get("refresh_token"):
            creds["refresh_token"] = response_data["refresh_token"]
        if response_data.get("expires_in"):
            creds["expires_in"] = response_data["expires_in"]
        return creds
