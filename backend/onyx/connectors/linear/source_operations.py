"""Linear source-operations gateway: every Linear API call lives here.

The gateway owns the credential: a personal API key is sent as is, an OAuth
token is refreshed under the provider's rotation lock and written back, since
Linear spends the refresh token on use. Indexing, permission sync and the
capability checks all go through the operations below and nothing else talks
to api.linear.app.
"""

import time
from collections.abc import Iterator
from typing import Any

import requests

from onyx.configs.app_configs import LINEAR_CLIENT_ID, LINEAR_CLIENT_SECRET
from onyx.configs.constants import DocumentSource
from onyx.connectors.capabilities import CredentialCapability
from onyx.connectors.linear.access import member_emails
from onyx.connectors.linear.models import (
    IssueAccess,
    IssueAccessPage,
    IssueShare,
    LinearProject,
    LinearTeam,
    LinearUser,
    LinearViewer,
    WorkspaceUsers,
)
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.source_operations import (
    OperationConsumes,
    SourceOperations,
    source_operation,
)
from onyx.utils.logger import setup_logger
from onyx.utils.retry_wrapper import request_with_retries

logger = setup_logger()

_NUM_RETRIES: int = 5
_TIMEOUT: int = 60
_LINEAR_GRAPHQL_URL: str = "https://api.linear.app/graphql"
_LINEAR_TOKEN_URL: str = "https://api.linear.app/oauth/token"
API_KEY: str = "linear_api_key"
ACCESS_TOKEN: str = "access_token"
EXPIRE_AT: str = "expire_at"
REFRESH_TOKEN: str = "refresh_token"
EXPIRES_IN: str = "expires_in"
# An access token this close to expiry is refreshed before use.
_REFRESH_BUFFER_SECONDS: int = 300

# Linear caps a query's complexity at 10,000 points. A listing page fits at
# 100, a page of issue access fields at 250.
LISTING_PAGE_SIZE: int = 100
ACCESS_PAGE_SIZE: int = 250
# A walk still paging past this is a cursor cycling rather than ending.
_MAX_PAGES: int = 100_000

_PAGE_INFO: str = """
    pageInfo {
        hasNextPage
        endCursor
    }
"""
_USER_FIELDS: str = "email active guest app"
_VIEWER_QUERY: str = "query Viewer { viewer { guest } }"
_TEAMS_BY_KEY_QUERY: str = f"""
    query TeamsByKey($keys: [String!], $first: Int, $after: String) {{
        teams(first: $first, after: $after, filter: {{ key: {{ in: $keys }} }}) {{
            nodes {{ key }}
            {_PAGE_INFO}
        }}
    }}
"""
_PROJECTS_QUERY: str = f"""
    query ProjectsInScope($filter: ProjectFilter, $first: Int, $after: String) {{
        projects(first: $first, after: $after, filter: $filter) {{
            nodes {{ name slugId }}
            {_PAGE_INFO}
        }}
    }}
"""
_ISSUES_QUERY: str = f"""
    query IterateIssueBatches($first: Int, $after: String, $filter: IssueFilter) {{
        issues(orderBy: updatedAt, first: $first, after: $after, filter: $filter) {{
            nodes {{
                id
                createdAt
                updatedAt
                title
                priority
                estimate
                startedAt
                completedAt
                dueDate
                team {{ name }}
                project {{ name }}
                creator {{ name email }}
                assignee {{ name email }}
                identifier
                url
                state {{ name }}
                description
                comments {{ nodes {{ url body }} }}
            }}
            {_PAGE_INFO}
        }}
    }}
"""
_ISSUE_ACCESS_QUERY: str = f"""
    query IterateIssueAccess($first: Int, $after: String, $filter: IssueFilter) {{
        organization {{ id }}
        issues(orderBy: updatedAt, first: $first, after: $after, filter: $filter) {{
            nodes {{
                id
                inheritsSharedAccess
                parent {{ id }}
                team {{ id key visibility parent {{ id }} }}
                sharedAccess {{ sharedWithUsers {{ {_USER_FIELDS} }} }}
            }}
            {_PAGE_INFO}
        }}
    }}
"""
_ISSUE_SHARE_QUERY: str = f"""
    query IssueShare($id: String!) {{
        issue(id: $id) {{
            inheritsSharedAccess
            parent {{ id }}
            sharedAccess {{ sharedWithUsers {{ {_USER_FIELDS} }} }}
        }}
    }}
"""
_TEAMS_QUERY: str = f"""
    query IterateTeams($first: Int, $after: String) {{
        teams(first: $first, after: $after) {{
            nodes {{ id key visibility parent {{ id }} }}
            {_PAGE_INFO}
        }}
    }}
"""
_TEAM_MEMBERS_QUERY: str = f"""
    query IterateTeamMembers($teamId: String!, $first: Int, $after: String) {{
        team(id: $teamId) {{
            memberships(first: $first, after: $after) {{
                nodes {{ user {{ {_USER_FIELDS} }} }}
                {_PAGE_INFO}
            }}
        }}
    }}
"""
_USERS_QUERY: str = f"""
    query IterateUsers($first: Int, $after: String) {{
        organization {{ id userCount }}
        users(first: $first, after: $after) {{
            nodes {{ {_USER_FIELDS} }}
            {_PAGE_INFO}
        }}
    }}
"""


class LinearGraphQLError(RuntimeError):
    """Linear answered 200 with an `errors` list."""

    def __init__(self, errors: list[dict[str, Any]]) -> None:
        super().__init__(f"Linear GraphQL errors: {errors}")
        self.errors = errors

    @property
    def is_not_found(self) -> bool:
        """The queried entity does not exist or the token cannot see it."""
        return all(
            str(error.get("message", "")).startswith("Entity not found")
            for error in self.errors
        )


class LinearAuthError(RuntimeError):
    """Linear refused the credential itself."""


def _make_query(request_body: dict[str, Any], api_key: str) -> requests.Response:
    headers: dict[str, str] = {
        "Authorization": api_key,
        "Content-Type": "application/json",
    }
    for attempt in range(_NUM_RETRIES):
        try:
            response = requests.post(
                _LINEAR_GRAPHQL_URL,
                headers=headers,
                json=request_body,
                timeout=_TIMEOUT,
            )
            if response.status_code in (401, 403):
                raise LinearAuthError(f"Linear refused the credential: {response.text}")
            if not response.ok:
                raise RuntimeError(f"Error querying Linear: {response.text}")
            return response
        except LinearAuthError:
            raise
        except Exception as e:
            if attempt == _NUM_RETRIES - 1:
                raise
            logger.warning("A Linear GraphQL error occurred: %s. Retrying...", e)
    raise RuntimeError("Unexpected execution when querying Linear.")


def _run_query(query: str, variables: dict[str, Any], api_key: str) -> dict[str, Any]:
    """The query's data. Linear answers 200 with an `errors` list for a bad
    query, so that is raised here rather than read as an empty result."""
    response = _make_query({"query": query, "variables": variables}, api_key)
    body: dict[str, Any] = response.json()
    if body.get("errors"):
        raise LinearGraphQLError(body["errors"])
    return body["data"]


def refresh_oauth_token(credentials: dict[str, Any]) -> dict[str, Any]:
    """The credential after one refresh. Per RFC 6749 section 6 the response
    may omit the refresh token, in which case the stored one stays valid;
    Linear rotates it on every refresh today."""
    if REFRESH_TOKEN not in credentials:
        raise ConnectorMissingCredentialError("Linear")
    response = request_with_retries(
        method="POST",
        url=_LINEAR_TOKEN_URL,
        data={
            REFRESH_TOKEN: credentials[REFRESH_TOKEN],
            "client_id": LINEAR_CLIENT_ID,
            "client_secret": LINEAR_CLIENT_SECRET,
            "grant_type": REFRESH_TOKEN,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        backoff=0,
        delay=0.1,
    )
    if not response.ok:
        raise RuntimeError(f"Failed to refresh token: {response.text}")
    token_data: dict[str, Any] = response.json()
    return {
        ACCESS_TOKEN: token_data[ACCESS_TOKEN],
        EXPIRE_AT: int(time.time() + token_data[EXPIRES_IN]),
        REFRESH_TOKEN: token_data.get(REFRESH_TOKEN, credentials[REFRESH_TOKEN]),
    }


def is_expiring(credentials: dict[str, Any]) -> bool:
    """An OAuth credential that must be refreshed before its next use."""
    return (
        ACCESS_TOKEN in credentials
        and EXPIRE_AT in credentials
        and credentials[EXPIRE_AT] < time.time() + _REFRESH_BUFFER_SECONDS
    )


def _authorization(credentials: dict[str, Any]) -> str:
    if API_KEY in credentials:
        return str(credentials[API_KEY])
    if ACCESS_TOKEN in credentials:
        return f"Bearer {credentials[ACCESS_TOKEN]}"
    raise ConnectorMissingCredentialError("Linear")


def _user(node: dict[str, Any]) -> LinearUser:
    return LinearUser.model_validate(node)


def _team(node: dict[str, Any]) -> LinearTeam:
    parent: dict[str, Any] | None = node["parent"]
    return LinearTeam(
        id=node["id"],
        key=node["key"],
        visibility=node["visibility"],
        parent_id=parent["id"] if parent else None,
    )


def _share(node: dict[str, Any]) -> IssueShare:
    parent: dict[str, Any] | None = node["parent"]
    return IssueShare(
        parent_id=parent["id"] if parent else None,
        inherits=node["inheritsSharedAccess"],
        emails=member_emails(
            _user(user) for user in node["sharedAccess"]["sharedWithUsers"]
        ),
    )


class LinearSourceOperations(SourceOperations):
    source = DocumentSource.LINEAR
    sdk_modules = ("requests",)
    config_keys = frozenset()

    _authorization_cache: str | None = None
    _authorization_expires_at: float | None = None

    def _api_key(self) -> str:
        """The Authorization header value, refreshing an expiring OAuth token
        under the provider's lock so two syncs never both redeem it."""
        now: float = time.time()
        if self._authorization_cache is not None and (
            self._authorization_expires_at is None
            or self._authorization_expires_at >= now + _REFRESH_BUFFER_SECONDS
        ):
            return self._authorization_cache
        credentials: dict[str, Any] = self.credentials_provider.get_credentials()
        if is_expiring(credentials):
            with self.credentials_provider:
                credentials = self.credentials_provider.get_credentials()
                if is_expiring(credentials):
                    credentials = refresh_oauth_token(credentials)
                    self.credentials_provider.set_credentials(credentials)
        self._authorization_cache = _authorization(credentials)
        self._authorization_expires_at = credentials.get(EXPIRE_AT)
        return self._authorization_cache

    def _pages(
        self,
        query: str,
        variables: dict[str, Any],
        path: tuple[str, ...],
        page_size: int = LISTING_PAGE_SIZE,
    ) -> Iterator[dict[str, Any]]:
        """Each page's data, following the connection at `path` to its end."""
        cursor: str | None = None
        for _ in range(_MAX_PAGES):
            data: dict[str, Any] = _run_query(
                query,
                {**variables, "first": page_size, "after": cursor},
                self._api_key(),
            )
            yield data
            connection: dict[str, Any] = data
            for key in path:
                connection = connection[key]
            page_info: dict[str, Any] = connection["pageInfo"]
            if not page_info["hasNextPage"]:
                return
            if page_info["endCursor"] == cursor:
                raise RuntimeError(f"Linear stopped advancing the {path[-1]} cursor")
            cursor = page_info["endCursor"]
        raise RuntimeError(f"Linear kept paging {path[-1]} past {_MAX_PAGES} pages")

    @source_operation(
        capabilities=(
            CredentialCapability.INDEXING,
            CredentialCapability.DOC_PERMISSION_SYNC,
            CredentialCapability.EXTERNAL_GROUP_SYNC,
        ),
        consumes=OperationConsumes.CREDENTIAL,
    )
    def get_viewer(self) -> LinearViewer:
        data: dict[str, Any] = _run_query(_VIEWER_QUERY, {}, self._api_key())
        return LinearViewer.model_validate(data["viewer"])

    @source_operation(
        capabilities=(CredentialCapability.INDEXING,),
        consumes=OperationConsumes.CONFIG,
    )
    def list_team_keys(self, *, keys: list[str]) -> set[str]:
        """The configured keys Linear answers for."""
        return {
            team["key"]
            for data in self._pages(_TEAMS_BY_KEY_QUERY, {"keys": keys}, ("teams",))
            for team in data["teams"]["nodes"]
        }

    @source_operation(
        capabilities=(CredentialCapability.INDEXING,),
        consumes=OperationConsumes.CONFIG,
    )
    def list_projects(self, *, project_filter: dict[str, Any]) -> list[LinearProject]:
        return [
            LinearProject(name=project["name"], slug_id=project["slugId"])
            for data in self._pages(
                _PROJECTS_QUERY, {"filter": project_filter}, ("projects",)
            )
            for project in data["projects"]["nodes"]
        ]

    @source_operation(
        capabilities=(CredentialCapability.INDEXING,),
        consumes=OperationConsumes.CONFIG,
    )
    def iterate_issues(
        self, *, issue_filter: dict[str, Any], page_size: int
    ) -> Iterator[list[dict[str, Any]]]:
        """Pages of raw issue nodes with their comments."""
        for data in self._pages(
            _ISSUES_QUERY, {"filter": issue_filter}, ("issues",), page_size
        ):
            yield data["issues"]["nodes"]

    @source_operation(
        capabilities=(CredentialCapability.DOC_PERMISSION_SYNC,),
        consumes=OperationConsumes.CONFIG,
    )
    def iterate_issue_access(
        self, *, issue_filter: dict[str, Any], page_size: int = ACCESS_PAGE_SIZE
    ) -> Iterator[IssueAccessPage]:
        for data in self._pages(
            _ISSUE_ACCESS_QUERY, {"filter": issue_filter}, ("issues",), page_size
        ):
            yield IssueAccessPage(
                organization_id=data["organization"]["id"],
                issues=[
                    IssueAccess(
                        id=node["id"], team=_team(node["team"]), share=_share(node)
                    )
                    for node in data["issues"]["nodes"]
                ],
            )

    @source_operation(
        capabilities=(CredentialCapability.DOC_PERMISSION_SYNC,),
        consumes=OperationConsumes.CREDENTIAL,
    )
    def get_issue_share(self, *, issue_id: str) -> IssueShare:
        """The shares of an ancestor the scoped walk left out. One the token
        cannot see grants nothing, which is the safe side for access. Any
        other failure raises, so an outage never reads as revoked access."""
        try:
            data: dict[str, Any] = _run_query(
                _ISSUE_SHARE_QUERY, {"id": issue_id}, self._api_key()
            )
        except LinearGraphQLError as e:
            if not e.is_not_found:
                raise
            logger.warning(
                "Linear parent issue %s is not visible to the token, so its "
                "sub-issues inherit no shared readers",
                issue_id,
            )
            return IssueShare(parent_id=None, inherits=False, emails=set())
        return _share(data["issue"])

    @source_operation(
        capabilities=(CredentialCapability.EXTERNAL_GROUP_SYNC,),
        consumes=OperationConsumes.CREDENTIAL,
    )
    def list_teams(self) -> list[LinearTeam]:
        return [
            _team(node)
            for data in self._pages(_TEAMS_QUERY, {}, ("teams",))
            for node in data["teams"]["nodes"]
        ]

    @source_operation(
        capabilities=(CredentialCapability.EXTERNAL_GROUP_SYNC,),
        consumes=OperationConsumes.CREDENTIAL,
    )
    def list_team_members(self, *, team_id: str) -> list[LinearUser]:
        return [
            _user(node["user"])
            for data in self._pages(
                _TEAM_MEMBERS_QUERY, {"teamId": team_id}, ("team", "memberships")
            )
            for node in data["team"]["memberships"]["nodes"]
        ]

    @source_operation(
        capabilities=(CredentialCapability.EXTERNAL_GROUP_SYNC,),
        consumes=OperationConsumes.CREDENTIAL,
    )
    def list_workspace_users(self) -> WorkspaceUsers:
        users: list[LinearUser] = []
        organization_id: str = ""
        user_count: int = 0
        for data in self._pages(_USERS_QUERY, {}, ("users",)):
            organization_id = data["organization"]["id"]
            user_count = data["organization"]["userCount"]
            users.extend(_user(node) for node in data["users"]["nodes"])
        return WorkspaceUsers(
            organization_id=organization_id, user_count=user_count, users=users
        )
