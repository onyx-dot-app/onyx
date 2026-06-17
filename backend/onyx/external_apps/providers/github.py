from typing import Any

import requests

from onyx.configs.app_configs import EXT_APP_GITHUB_CLIENT_ID
from onyx.configs.app_configs import EXT_APP_GITHUB_CLIENT_SECRET
from onyx.db.enums import EndpointPolicy
from onyx.db.enums import ExternalAppType
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.providers.actions import EndpointSpec
from onyx.external_apps.providers.actions import ExternalAppAction
from onyx.external_apps.providers.actions import GraphQLOp
from onyx.external_apps.providers.actions import RestRoute
from onyx.external_apps.providers.base import AdminDescriptorSpec
from onyx.external_apps.providers.base import OAuthExternalAppProvider
from onyx.external_apps.providers.base import OAuthFlowSpec
from onyx.external_apps.providers.base import OAuthProviderSpec
from onyx.external_apps.providers.base import OnyxManagedExtApp
from onyx.external_apps.providers.base import OrgCredentialField
from onyx.external_apps.providers.base import token_response_error


class GitHubAction(ExternalAppAction):
    """Strongly-typed catalog ids for the GitHub provider."""

    USER_READ = "github.user.read"
    REPOS_READ = "github.repos.read"
    ISSUES_READ = "github.issues.read"
    PULLS_READ = "github.pulls.read"
    SEARCH_READ = "github.search.read"
    REPO_GRAPHQL_READ = "github.graphql.repo.read"
    REFS_READ = "github.refs.read"
    CONTENTS_READ = "github.contents.read"
    GIT_DATA_READ = "github.git_data.read"
    RELEASES_READ = "github.releases.read"
    ISSUES_CREATE = "github.issues.create"
    COMMENTS_CREATE = "github.comments.create"
    CONTENTS_WRITE = "github.contents.write"
    REFS_WRITE = "github.refs.write"
    PULLS_CREATE = "github.pulls.create"


# GitHub's REST API is a path-addressed JSON API rooted at
# https://api.github.com; the action is the method + path template. A `{name}`
# segment matches one path segment (owner / repo / issue number, etc.).
#
# `gh` also drives commands through GraphQL (POST /graphql), so actions carry
# GraphQLOp rules too; gh's repo-scoped reads collapse onto REPO_GRAPHQL_READ.
_ENDPOINTS: list[EndpointSpec] = [
    EndpointSpec(
        id=GitHubAction.USER_READ,
        normalised_name="Read the connected user",
        description="Read the authenticated user's profile.",
        matches=(
            RestRoute(method="GET", path="/user"),
            GraphQLOp(operation_type="query", field="viewer"),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=GitHubAction.REPOS_READ,
        normalised_name="Read repositories",
        description="List the user's repositories and fetch a single repo.",
        matches=(
            RestRoute(method="GET", path="/user/repos"),
            RestRoute(method="GET", path="/repos/{owner}/{repo}"),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=GitHubAction.ISSUES_READ,
        normalised_name="Read issues",
        description="List a repo's issues and fetch a single issue with its comments.",
        matches=(
            RestRoute(method="GET", path="/repos/{owner}/{repo}/issues"),
            RestRoute(method="GET", path="/repos/{owner}/{repo}/issues/{number}"),
            RestRoute(
                method="GET", path="/repos/{owner}/{repo}/issues/{number}/comments"
            ),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=GitHubAction.PULLS_READ,
        normalised_name="Read pull requests",
        description="List a repo's pull requests and fetch a single pull request.",
        matches=(
            RestRoute(method="GET", path="/repos/{owner}/{repo}/pulls"),
            RestRoute(method="GET", path="/repos/{owner}/{repo}/pulls/{number}"),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=GitHubAction.SEARCH_READ,
        normalised_name="Search",
        description="Search repositories, issues, and pull requests.",
        matches=(
            RestRoute(method="GET", path="/search/repositories"),
            RestRoute(method="GET", path="/search/issues"),
            GraphQLOp(operation_type="query", field="search"),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=GitHubAction.REPO_GRAPHQL_READ,
        normalised_name="Read repos, issues, and PRs via the GitHub CLI",
        description=(
            "Read repository-scoped data (the repo, its issues, and its pull "
            "requests) through GitHub's GraphQL API — the path `gh repo/pr/issue "
            "view` and `list` take."
        ),
        matches=(
            GraphQLOp(operation_type="query", field="repository"),
            GraphQLOp(operation_type="query", field="repositoryOwner"),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=GitHubAction.REFS_READ,
        normalised_name="Read branches and refs",
        description="List branches and read a branch or git ref (its SHA).",
        matches=(
            RestRoute(method="GET", path="/repos/{owner}/{repo}/branches"),
            # Branch/ref names contain slashes, so the tail is a multi-segment wildcard.
            RestRoute(method="GET", path="/repos/{owner}/{repo}/branches/{branch...}"),
            RestRoute(method="GET", path="/repos/{owner}/{repo}/git/ref/{ref...}"),
            RestRoute(method="GET", path="/repos/{owner}/{repo}/git/refs"),
            RestRoute(method="GET", path="/repos/{owner}/{repo}/git/refs/{ref...}"),
            RestRoute(
                method="GET", path="/repos/{owner}/{repo}/git/matching-refs/{ref...}"
            ),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=GitHubAction.CONTENTS_READ,
        normalised_name="Read file contents",
        description="Read a file or directory's contents (and the README).",
        matches=(
            RestRoute(method="GET", path="/repos/{owner}/{repo}/contents"),
            RestRoute(method="GET", path="/repos/{owner}/{repo}/contents/{path...}"),
            RestRoute(method="GET", path="/repos/{owner}/{repo}/readme"),
            RestRoute(method="GET", path="/repos/{owner}/{repo}/readme/{dir...}"),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=GitHubAction.GIT_DATA_READ,
        normalised_name="Read commits and git objects",
        description="Read commits, trees, and blobs (the git object graph).",
        matches=(
            RestRoute(method="GET", path="/repos/{owner}/{repo}/git/trees/{sha}"),
            RestRoute(method="GET", path="/repos/{owner}/{repo}/git/blobs/{sha}"),
            RestRoute(method="GET", path="/repos/{owner}/{repo}/git/commits/{sha}"),
            RestRoute(method="GET", path="/repos/{owner}/{repo}/commits"),
            RestRoute(method="GET", path="/repos/{owner}/{repo}/commits/{ref...}"),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=GitHubAction.RELEASES_READ,
        normalised_name="Read releases",
        description="List releases and read a single release, asset, or tag.",
        matches=(
            RestRoute(method="GET", path="/repos/{owner}/{repo}/releases"),
            RestRoute(method="GET", path="/repos/{owner}/{repo}/releases/{release...}"),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=GitHubAction.ISSUES_CREATE,
        normalised_name="Create an issue",
        description="Open a new issue in a repository.",
        matches=(
            RestRoute(method="POST", path="/repos/{owner}/{repo}/issues"),
            GraphQLOp(operation_type="mutation", field="createIssue"),
        ),
    ),
    EndpointSpec(
        id=GitHubAction.COMMENTS_CREATE,
        normalised_name="Comment on an issue",
        description="Add a comment to an issue or pull request.",
        matches=(
            RestRoute(
                method="POST", path="/repos/{owner}/{repo}/issues/{number}/comments"
            ),
            GraphQLOp(operation_type="mutation", field="addComment"),
        ),
    ),
    EndpointSpec(
        id=GitHubAction.CONTENTS_WRITE,
        normalised_name="Create, update, or delete files",
        description="Write or delete a file in a repository (a single-file commit).",
        matches=(
            RestRoute(method="PUT", path="/repos/{owner}/{repo}/contents/{path...}"),
            RestRoute(method="DELETE", path="/repos/{owner}/{repo}/contents/{path...}"),
        ),
    ),
    EndpointSpec(
        id=GitHubAction.REFS_WRITE,
        normalised_name="Create, update, or delete branches",
        description="Create a branch/ref, move it, or delete it.",
        matches=(
            RestRoute(method="POST", path="/repos/{owner}/{repo}/git/refs"),
            RestRoute(method="PATCH", path="/repos/{owner}/{repo}/git/refs/{ref...}"),
            RestRoute(method="DELETE", path="/repos/{owner}/{repo}/git/refs/{ref...}"),
        ),
    ),
    EndpointSpec(
        id=GitHubAction.PULLS_CREATE,
        normalised_name="Open a pull request",
        description="Open a new pull request.",
        matches=(
            RestRoute(method="POST", path="/repos/{owner}/{repo}/pulls"),
            GraphQLOp(operation_type="mutation", field="createPullRequest"),
        ),
    ),
]


class GitHubProvider(OAuthExternalAppProvider, OnyxManagedExtApp):
    spec = OAuthProviderSpec(
        app_type=ExternalAppType.GITHUB,
        app_name="GitHub",
        oauth=OAuthFlowSpec(
            authorize_url="https://github.com/login/oauth/authorize",
            token_url="https://github.com/login/oauth/access_token",
            scope=" ".join(["repo", "read:org", "read:user"]),
            scope_param="scope",
        ),
        descriptor=AdminDescriptorSpec(
            description=(
                "Read repositories, issues, and pull requests, open new issues, "
                "and add comments in GitHub on the user's behalf."
            ),
            upstream_url_patterns=["https://api\\.github\\.com/.*"],
            auth_template={"Authorization": "Bearer {access_token}"},
            required_org_credential_fields=[
                OrgCredentialField(
                    key="client_id",
                    label="Client ID",
                    description=(
                        "Found on your GitHub OAuth app's settings page "
                        "(Settings → Developer settings → OAuth Apps)."
                    ),
                ),
                OrgCredentialField(
                    key="client_secret",
                    label="Client Secret",
                    description=(
                        "Generated on the same OAuth app settings page. "
                        "Treat this like a password."
                    ),
                    secret=True,
                ),
            ],
            setup_instructions=(
                "In GitHub: Settings → Developer settings → OAuth Apps → New "
                "OAuth App. Set the Authorization callback URL to this Onyx "
                "instance's callback URL (/craft/v1/apps/oauth/callback). Save, "
                "then generate a client secret. Paste the Client ID and Client "
                "Secret below. The agent is granted the repo, read:org, and "
                "read:user scopes."
            ),
        ),
        endpoint_catalog=_ENDPOINTS,
    )

    managed_org_credentials = {
        "client_id": EXT_APP_GITHUB_CLIENT_ID,
        "client_secret": EXT_APP_GITHUB_CLIENT_SECRET,
    }

    # GitHub signals a dead refresh token with `bad_refresh_token` rather than
    # RFC-6749's `invalid_grant`; treat it as terminal so the user reconnects.
    terminal_refresh_errors = frozenset({"invalid_grant", "bad_refresh_token"})

    def classify_token_response(
        self, response: requests.Response, body: dict[str, Any]
    ) -> str | None:
        # GitHub returns HTTP 200 with an `{"error": "..."}` body on failure
        # (e.g. `bad_verification_code`, `bad_refresh_token`), so the generic
        # non-2xx check wouldn't catch it. Surface the machine-readable code so
        # terminal-vs-transient classification can match it.
        if isinstance(body, dict) and body.get("error"):
            return str(body["error"])
        return token_response_error(response, body)

    def extract_credentials(self, response_data: dict[str, Any]) -> dict[str, Any]:
        access_token = response_data.get("access_token")
        if not access_token:
            raise OnyxError(
                OnyxErrorCode.BAD_GATEWAY,
                "GitHub OAuth response did not contain an access token.",
            )
        creds: dict[str, Any] = {
            "access_token": access_token,
            "scope": response_data.get("scope"),
            "token_type": response_data.get("token_type"),
        }
        # Present only when the OAuth app has expiring user tokens enabled
        # (GitHub Apps); classic OAuth app tokens don't expire and omit these.
        if response_data.get("refresh_token"):
            creds["refresh_token"] = response_data["refresh_token"]
        if response_data.get("expires_in"):
            creds["expires_in"] = response_data["expires_in"]
        return creds
