import os
import re
import time
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any, cast
from urllib.parse import urlparse

import requests
from typing_extensions import override

from onyx.configs.app_configs import (
    INDEX_BATCH_SIZE,
    LINEAR_CLIENT_ID,
    LINEAR_CLIENT_SECRET,
)
from onyx.configs.constants import DocumentSource
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.cross_connector_utils.miscellaneous_utils import (
    get_oauth_callback_uri,
    time_str_to_utc,
)
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    InsufficientPermissionsError,
)
from onyx.connectors.interfaces import (
    CredentialsConnector,
    CredentialsProviderInterface,
    GenerateDocumentsOutput,
    GenerateSlimDocumentOutput,
    LoadConnector,
    NormalizationResult,
    OAuthConnector,
    PollConnector,
    SecondsSinceUnixEpoch,
    SlimConnectorWithPermSync,
)
from onyx.connectors.linear.access import (
    SharedAccessIndex,
    issue_access,
    member_emails,
)
from onyx.connectors.linear.models import (
    IssueShare,
    LinearTeam,
    LinearUser,
    WorkspaceMembers,
)
from onyx.connectors.models import (
    ConnectorMissingCredentialError,
    Document,
    HierarchyNode,
    ImageSection,
    SlimDocument,
    TextSection,
)
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger
from onyx.utils.retry_wrapper import request_with_retries

logger = setup_logger()

_NUM_RETRIES = 5
_TIMEOUT = 60
_LINEAR_GRAPHQL_URL = "https://api.linear.app/graphql"
_LINEAR_TOKEN_URL = "https://api.linear.app/oauth/token"
_API_KEY = "linear_api_key"
_ACCESS_TOKEN = "access_token"
_EXPIRE_AT = "expire_at"
_REFRESH_TOKEN = "refresh_token"
_EXPIRES_IN = "expires_in"
# An OAuth token this close to expiry is refreshed before its next use.
_REFRESH_BUFFER_SECONDS: int = 300


def _make_query(request_body: dict[str, Any], api_key: str) -> requests.Response:
    headers = {
        "Authorization": api_key,
        "Content-Type": "application/json",
    }

    for i in range(_NUM_RETRIES):
        try:
            response = requests.post(
                _LINEAR_GRAPHQL_URL,
                headers=headers,
                json=request_body,
                timeout=_TIMEOUT,
            )
            if not response.ok:
                raise RuntimeError(
                    f"Error fetching issues from Linear: {response.text}"
                )

            return response
        except Exception as e:
            if i == _NUM_RETRIES - 1:
                raise e

            logger.warning("A Linear GraphQL error occurred: %s. Retrying...", e)

    raise RuntimeError(
        "Unexpected execution when querying Linear. This should never happen."
    )


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


def _run_query(query: str, variables: dict[str, Any], api_key: str) -> dict[str, Any]:
    """The query's data. Linear answers 200 with an `errors` list for a bad
    query, so that is raised here rather than read as an empty result."""
    response = _make_query({"query": query, "variables": variables}, api_key)
    body: dict[str, Any] = response.json()
    if body.get("errors"):
        raise LinearGraphQLError(body["errors"])
    return body["data"]


# Linear caps a query's complexity at 10,000 points. A listing page fits at 100.
_LISTING_PAGE_SIZE: int = 100
# A walk still paging past this is a cursor cycling rather than ending.
_MAX_PAGES: int = 100_000

_PAGE_INFO: str = """
    pageInfo {
        hasNextPage
        endCursor
    }
"""
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
# A project URL ends in the slug and the project's slug id:
# https://linear.app/<workspace>/project/<slug>-<slug id>
_PROJECT_URL_SLUG_ID: re.Pattern[str] = re.compile(
    r"linear\.app/[^/]+/project/[^/?#]*?([0-9a-f]{12})(?:[/?#]|$)"
)


def _project_scope(entries: list[str] | None) -> tuple[list[str], list[str]]:
    """The project names, and the slug ids of the entries given as URLs."""
    names: set[str] = set()
    slug_ids: set[str] = set()
    for entry in entries or []:
        entry = entry.strip()
        if not entry:
            continue
        match = _PROJECT_URL_SLUG_ID.search(entry)
        if match:
            slug_ids.add(match.group(1))
        else:
            names.add(entry)
    return sorted(names), sorted(slug_ids)


# A page of these access fields fits under the complexity cap at 250 issues.
_ACCESS_PAGE_SIZE = 250
# Every walked issue id stays in memory until the walk ends, with the shares
# that name anyone. Past this many the workspace is worth a look.
_RETAINED_ISSUES_WARNING: int = 250_000
_USER_FIELDS = "email active guest app"

_ISSUE_ACCESS_QUERY = f"""
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
_TEAMS_QUERY = f"""
    query IterateTeams($first: Int, $after: String) {{
        teams(first: $first, after: $after) {{
            nodes {{ id key visibility parent {{ id }} }}
            {_PAGE_INFO}
        }}
    }}
"""
_TEAM_MEMBERS_QUERY = f"""
    query IterateTeamMembers($teamId: String!, $first: Int, $after: String) {{
        team(id: $teamId) {{
            memberships(first: $first, after: $after) {{
                nodes {{ user {{ {_USER_FIELDS} }} }}
                {_PAGE_INFO}
            }}
        }}
    }}
"""
_USERS_QUERY = f"""
    query IterateUsers($first: Int, $after: String) {{
        organization {{ id userCount }}
        users(first: $first, after: $after) {{
            nodes {{ {_USER_FIELDS} }}
            {_PAGE_INFO}
        }}
    }}
"""
_ISSUE_SHARE_QUERY = f"""
    query IssueShare($id: String!) {{
        issue(id: $id) {{
            inheritsSharedAccess
            parent {{ id }}
            sharedAccess {{ sharedWithUsers {{ {_USER_FIELDS} }} }}
        }}
    }}
"""
_VIEWER_QUERY = "query Viewer { viewer { guest } }"


def _share(node: dict[str, Any]) -> IssueShare:
    parent: dict[str, Any] | None = node["parent"]
    return IssueShare(
        parent_id=parent["id"] if parent else None,
        inherits=node["inheritsSharedAccess"],
        emails=member_emails(
            LinearUser.model_validate(user)
            for user in node["sharedAccess"]["sharedWithUsers"]
        ),
    )


def _team(node: dict[str, Any]) -> LinearTeam:
    parent: dict[str, Any] | None = node["parent"]
    return LinearTeam(
        id=node["id"],
        key=node["key"],
        visibility=node["visibility"],
        parent_id=parent["id"] if parent else None,
    )


def refresh_oauth_token(credentials: dict[str, Any]) -> dict[str, Any]:
    """The credential after one refresh. Per RFC 6749 section 6 the response
    may omit the refresh token, in which case the stored one stays valid;
    Linear rotates it on every refresh today."""
    if _REFRESH_TOKEN not in credentials:
        raise ConnectorMissingCredentialError("Linear")
    response = request_with_retries(
        method="POST",
        url=_LINEAR_TOKEN_URL,
        data={
            _REFRESH_TOKEN: credentials[_REFRESH_TOKEN],
            "client_id": LINEAR_CLIENT_ID,
            "client_secret": LINEAR_CLIENT_SECRET,
            "grant_type": _REFRESH_TOKEN,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        backoff=0,
        delay=0.1,
    )
    if not response.ok:
        raise RuntimeError(f"Failed to refresh token: {response.text}")
    token_data: dict[str, Any] = response.json()
    return {
        _ACCESS_TOKEN: token_data[_ACCESS_TOKEN],
        _EXPIRE_AT: int(time.time() + token_data[_EXPIRES_IN]),
        _REFRESH_TOKEN: token_data.get(_REFRESH_TOKEN, credentials[_REFRESH_TOKEN]),
    }


def is_expiring(credentials: dict[str, Any]) -> bool:
    """An OAuth credential that must be refreshed before its next use."""
    return (
        _ACCESS_TOKEN in credentials
        and _EXPIRE_AT in credentials
        and credentials[_EXPIRE_AT] < time.time() + _REFRESH_BUFFER_SECONDS
    )


def _authorization(credentials: dict[str, Any]) -> str:
    if _API_KEY in credentials:
        return str(credentials[_API_KEY])
    if _ACCESS_TOKEN in credentials:
        return f"Bearer {credentials[_ACCESS_TOKEN]}"
    raise ConnectorMissingCredentialError("Linear")


class LinearConnector(
    LoadConnector,
    PollConnector,
    OAuthConnector,
    SlimConnectorWithPermSync,
    CredentialsConnector,
):
    supports_manual_credentials = True

    def __init__(
        self,
        team_keys: list[str] | None = None,
        projects: list[str] | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        # Linear matches keys case-sensitively and only ever issues upper case.
        self.team_keys = sorted(
            {key.strip().upper() for key in team_keys or [] if key.strip()}
        )
        self.project_names, self.project_slug_ids = _project_scope(projects)
        self.batch_size = batch_size
        self._credentials_provider: CredentialsProviderInterface | None = None
        self._authorization_cache: str | None = None
        self._authorization_expires_at: float | None = None

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        """Manual credentials. An expiring OAuth token is refreshed here and
        handed back so the caller can store it; the DB provider path refreshes
        on first use instead."""
        refreshed: dict[str, Any] | None = None
        if is_expiring(credentials):
            refreshed = refresh_oauth_token(credentials)
            credentials = refreshed
        self.set_credentials_provider(
            OnyxStaticCredentialsProvider(
                None, DocumentSource.LINEAR.value, credentials
            )
        )
        return refreshed

    def set_credentials_provider(
        self, credentials_provider: CredentialsProviderInterface
    ) -> None:
        self._credentials_provider = credentials_provider
        self._authorization_cache = None
        self._authorization_expires_at = None

    def _api_key(self) -> str:
        """The Authorization header value, refreshing an expiring OAuth token
        under the provider's lock so two syncs never both redeem it."""
        if self._credentials_provider is None:
            raise ConnectorMissingCredentialError("Linear")
        now: float = time.time()
        if self._authorization_cache is not None and (
            self._authorization_expires_at is None
            or self._authorization_expires_at >= now + _REFRESH_BUFFER_SECONDS
        ):
            return self._authorization_cache
        credentials: dict[str, Any] = self._credentials_provider.get_credentials()
        if is_expiring(credentials):
            with self._credentials_provider:
                credentials = self._credentials_provider.get_credentials()
                if is_expiring(credentials):
                    credentials = refresh_oauth_token(credentials)
                    self._credentials_provider.set_credentials(credentials)
        self._authorization_cache = _authorization(credentials)
        self._authorization_expires_at = credentials.get(_EXPIRE_AT)
        return self._authorization_cache

    def validate_connector_settings(self) -> None:
        """A team or project Linear does not answer for is misspelled or is in
        a private team the token's user is not in. Linear hides both the same
        way, so one message names every missing entry and the two causes."""
        missing_teams: list[str] = self._missing_teams() if self.team_keys else []
        project_filter: dict[str, Any] | None = self._project_filter()
        missing_projects: list[str] = (
            self._missing_projects(project_filter) if project_filter is not None else []
        )
        if not missing_teams and not missing_projects:
            return
        problems: list[str] = []
        if missing_teams:
            problems.append(f"Linear teams not found: {', '.join(missing_teams)}.")
        if missing_projects:
            problems.append(
                f"Linear projects not found: {', '.join(missing_projects)}."
            )
        raise ConnectorValidationError(
            f"{' '.join(problems)} Check each key, name or URL, or connect as a "
            "member if the team is private."
        )

    def _missing_teams(self) -> list[str]:
        found: set[str] = {
            team["key"]
            for data in self._pages(
                _TEAMS_BY_KEY_QUERY, {"keys": self.team_keys}, ("teams",)
            )
            for team in data["teams"]["nodes"]
        }
        return sorted(set(self.team_keys) - found)

    def _missing_projects(self, project_filter: dict[str, Any]) -> list[str]:
        projects: list[dict[str, Any]] = [
            project
            for data in self._pages(
                _PROJECTS_QUERY, {"filter": project_filter}, ("projects",)
            )
            for project in data["projects"]["nodes"]
        ]
        found_names: set[str] = {project["name"] for project in projects}
        found_slug_ids: set[str] = {project["slugId"] for project in projects}
        return sorted(
            (set(self.project_names) - found_names)
            | (set(self.project_slug_ids) - found_slug_ids)
        )

    def _project_filter(self) -> dict[str, Any] | None:
        clauses: list[dict[str, Any]] = []
        if self.project_names:
            clauses.append({"name": {"in": self.project_names}})
        if self.project_slug_ids:
            clauses.append({"slugId": {"in": self.project_slug_ids}})
        if not clauses:
            return None
        return clauses[0] if len(clauses) == 1 else {"or": clauses}

    def _issue_filter(
        self, start: datetime | None = None, end: datetime | None = None
    ) -> dict[str, Any]:
        updated_at: dict[str, str] = {}
        if start is not None:
            updated_at["gte"] = start.isoformat()
        if end is not None:
            updated_at["lte"] = end.isoformat()
        issue_filter: dict[str, Any] = {"updatedAt": updated_at}
        if self.team_keys:
            issue_filter["team"] = {"key": {"in": self.team_keys}}
        project_filter: dict[str, Any] | None = self._project_filter()
        if project_filter is not None:
            issue_filter["project"] = project_filter
        return issue_filter

    def _pages(
        self,
        query: str,
        variables: dict[str, Any],
        path: tuple[str, ...],
        page_size: int = _LISTING_PAGE_SIZE,
    ) -> Iterator[dict[str, Any]]:
        """Each page's data, following the connection at `path` to its end."""
        api_key: str = self._api_key()
        cursor: str | None = None
        for _ in range(_MAX_PAGES):
            data: dict[str, Any] = _run_query(
                query, {**variables, "first": page_size, "after": cursor}, api_key
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

    def retrieve_all_slim_docs_perm_sync(
        self,
        start: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        end: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        callback: IndexingHeartbeatInterface | None = None,  # noqa: ARG002
    ) -> GenerateSlimDocumentOutput:
        """Every issue the token can read, with who may read it. The doc sync
        makes any indexed issue this does not list private, so the window is
        ignored. A sub-issue that inherits sharing waits for the walk to end,
        since its parent can page after it."""
        shares: SharedAccessIndex = SharedAccessIndex(self._issue_share)
        warned: bool = False
        inheriting: list[tuple[str, LinearTeam]] = []
        organization_id: str = ""
        for data in self._pages(
            _ISSUE_ACCESS_QUERY,
            {"filter": self._issue_filter()},
            ("issues",),
            _ACCESS_PAGE_SIZE,
        ):
            organization_id = data["organization"]["id"]
            docs: list[SlimDocument | HierarchyNode] = []
            for node in data["issues"]["nodes"]:
                team: LinearTeam = _team(node["team"])
                share: IssueShare = _share(node)
                shares.record(node["id"], share)
                if share.inherits:
                    inheriting.append((node["id"], team))
                    continue
                docs.append(
                    SlimDocument(
                        id=node["id"],
                        external_access=issue_access(
                            team, organization_id, share.emails
                        ),
                    )
                )
            yield docs
            if not warned and len(shares) > _RETAINED_ISSUES_WARNING:
                warned = True
                logger.warning(
                    "Linear permission sync is keeping %s walked issues in memory "
                    "until the walk ends",
                    len(shares),
                )
        for start in range(0, len(inheriting), _ACCESS_PAGE_SIZE):
            yield [
                SlimDocument(
                    id=issue_id,
                    external_access=issue_access(
                        team, organization_id, shares.emails_for(issue_id)
                    ),
                )
                for issue_id, team in inheriting[start : start + _ACCESS_PAGE_SIZE]
            ]

    def _issue_share(self, issue_id: str) -> IssueShare:
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

    def list_teams(self) -> list[LinearTeam]:
        return [
            _team(node)
            for data in self._pages(_TEAMS_QUERY, {}, ("teams",))
            for node in data["teams"]["nodes"]
        ]

    def team_member_emails(self, team_id: str) -> set[str]:
        return member_emails(
            LinearUser.model_validate(node["user"])
            for data in self._pages(
                _TEAM_MEMBERS_QUERY, {"teamId": team_id}, ("team", "memberships")
            )
            for node in data["team"]["memberships"]["nodes"]
        )

    def workspace_members(self) -> WorkspaceMembers:
        """Raises on a listing shorter than the workspace's own count: a group
        filled from part of it would revoke access for everyone left out."""
        users: list[LinearUser] = []
        expected: int = 0
        organization_id: str = ""
        for data in self._pages(_USERS_QUERY, {}, ("users",)):
            organization_id = data["organization"]["id"]
            expected = data["organization"]["userCount"]
            users.extend(
                LinearUser.model_validate(node) for node in data["users"]["nodes"]
            )
        if len(users) < expected:
            raise RuntimeError(
                f"Linear listed {len(users)} of the {expected} users it reported"
            )
        return WorkspaceMembers(
            organization_id=organization_id,
            emails=member_emails(user for user in users if not user.guest),
        )

    def probe_perm_sync_access(self) -> None:
        """Raises for a guest token, which cannot see the workspace's members."""
        if _run_query(_VIEWER_QUERY, {}, self._api_key())["viewer"]["guest"]:
            raise InsufficientPermissionsError(
                "The connected Linear user is a guest. Connect as a workspace "
                "member who belongs to every private team to index."
            )

    @classmethod
    def oauth_id(cls) -> DocumentSource:
        return DocumentSource.LINEAR

    @classmethod
    def oauth_authorization_url(
        cls,
        base_domain: str,
        state: str,
        additional_kwargs: dict[str, str],  # noqa: ARG003
        code_challenge: str | None = None,  # noqa: ARG003
    ) -> str:
        if not LINEAR_CLIENT_ID:
            raise ValueError("LINEAR_CLIENT_ID environment variable must be set")

        callback_uri = get_oauth_callback_uri(base_domain, DocumentSource.LINEAR.value)
        return (
            f"https://linear.app/oauth/authorize"
            f"?client_id={LINEAR_CLIENT_ID}"
            f"&redirect_uri={callback_uri}"
            f"&response_type=code"
            f"&scope=read"
            f"&state={state}"
            f"&prompt=consent"  # prompts user for access; allows choosing workspace
        )

    @classmethod
    def oauth_code_to_token(
        cls,
        base_domain: str,
        code: str,
        additional_kwargs: dict[str, str],  # noqa: ARG003
        code_verifier: str | None = None,  # noqa: ARG003
    ) -> dict[str, Any]:
        data = {
            "code": code,
            "redirect_uri": get_oauth_callback_uri(
                base_domain, DocumentSource.LINEAR.value
            ),
            "client_id": LINEAR_CLIENT_ID,
            "client_secret": LINEAR_CLIENT_SECRET,
            "grant_type": "authorization_code",
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        response = request_with_retries(
            method="POST",
            url="https://api.linear.app/oauth/token",
            data=data,
            headers=headers,
            backoff=0,
            delay=0.1,
        )
        if not response.ok:
            raise RuntimeError(f"Failed to exchange code for token: {response.text}")

        token_data = response.json()

        expire_at = time.time() + token_data[_EXPIRES_IN]

        return {
            _ACCESS_TOKEN: token_data[_ACCESS_TOKEN],
            _EXPIRE_AT: int(expire_at),
            _REFRESH_TOKEN: token_data[_REFRESH_TOKEN],
        }

    def _process_issues(
        self, start_str: datetime | None = None, end_str: datetime | None = None
    ) -> GenerateDocumentsOutput:
        query = """
            query IterateIssueBatches($first: Int, $after: String, $filter: IssueFilter) {
                issues(
                    orderBy: updatedAt,
                    first: $first,
                    after: $after,
                    filter: $filter
                ) {
                    edges {
                        node {
                            id
                            createdAt
                            updatedAt
                            archivedAt
                            number
                            title
                            priority
                            estimate
                            sortOrder
                            startedAt
                            completedAt
                            startedTriageAt
                            triagedAt
                            canceledAt
                            autoClosedAt
                            autoArchivedAt
                            dueDate
                            slaStartedAt
                            slaBreachesAt
                            trashed
                            snoozedUntilAt
                            team {
                                name
                            }
                            project {
                                name
                            }
                            creator {
                                name
                                email
                            }
                            assignee {
                                name
                                email
                            }
                            previousIdentifiers
                            subIssueSortOrder
                            priorityLabel
                            identifier
                            url
                            branchName
                            state {
                                id
                                name
                            }
                            customerTicketCount
                            description
                            comments {
                                nodes {
                                    url
                                    body
                                }
                            }
                        }
                    }
                    pageInfo {
                        hasNextPage
                        endCursor
                    }
                }
            }
        """

        for data in self._pages(
            query,
            {"filter": self._issue_filter(start_str, end_str)},
            ("issues",),
            self.batch_size,
        ):
            logger.debug("Raw response from Linear: %s", data)
            edges: list[dict[str, Any]] = data["issues"]["edges"]

            documents: list[Document | HierarchyNode] = []
            for edge in edges:
                node = edge["node"]
                # Create sections for description and comments
                sections = [
                    TextSection(
                        link=node["url"],
                        text=node["description"] or "",
                    )
                ]

                # Add comment sections
                sections.extend(
                    TextSection(
                        link=node["url"],
                        text=comment["body"] or "",
                    )
                    for comment in node["comments"]["nodes"]
                )

                # Cast the sections list to the expected type
                typed_sections = cast(list[TextSection | ImageSection], sections)

                # Extract team name for hierarchy
                team_name = (node.get("team") or {}).get("name") or "Unknown Team"
                identifier = node.get("identifier", node["id"])

                documents.append(
                    Document(
                        id=node["id"],
                        sections=typed_sections,
                        source=DocumentSource.LINEAR,
                        semantic_identifier=f"[{node['identifier']}] {node['title']}",
                        title=node["title"],
                        doc_updated_at=time_str_to_utc(node["updatedAt"]),
                        # NOTE: doc_created_at population not yet verified against live data
                        doc_created_at=time_str_to_utc(node["createdAt"]),
                        doc_metadata={
                            "hierarchy": {
                                "source_path": [team_name],
                                "team_name": team_name,
                                "identifier": identifier,
                            }
                        },
                        metadata={
                            k: str(v)
                            for k, v in {
                                "team": (node.get("team") or {}).get("name"),
                                "project": (node.get("project") or {}).get("name"),
                                "creator": node.get("creator"),
                                "assignee": node.get("assignee"),
                                "state": (node.get("state") or {}).get("name"),
                                "priority": node.get("priority"),
                                "estimate": node.get("estimate"),
                                "started_at": node.get("startedAt"),
                                "completed_at": node.get("completedAt"),
                                "created_at": node.get("createdAt"),
                                "due_date": node.get("dueDate"),
                            }.items()
                            if v is not None
                        },
                    )
                )
            yield documents

    def load_from_state(self) -> GenerateDocumentsOutput:
        yield from self._process_issues()

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        start_time = datetime.fromtimestamp(start, tz=timezone.utc)
        end_time = datetime.fromtimestamp(end, tz=timezone.utc)

        yield from self._process_issues(start_str=start_time, end_str=end_time)

    @classmethod
    @override
    def normalize_url(cls, url: str) -> NormalizationResult:
        """Extract Linear issue identifier from URL.

        Linear URLs are like: https://linear.app/team/issue/IDENTIFIER/...
        Returns the identifier (e.g., "DAN-2327") which can be used to match Document.link.
        """
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()

        if "linear.app" not in netloc:
            return NormalizationResult(normalized_url=None, use_default=False)

        # Extract identifier from path: /team/issue/IDENTIFIER/...
        # Pattern: /{team}/issue/{identifier}/...
        path_parts = [p for p in parsed.path.split("/") if p]
        if len(path_parts) >= 3 and path_parts[1] == "issue":
            identifier = path_parts[2]
            # Validate identifier format (e.g., "DAN-2327")
            if re.match(r"^[A-Z]+-\d+$", identifier):
                return NormalizationResult(normalized_url=identifier, use_default=False)

        return NormalizationResult(normalized_url=None, use_default=False)


if __name__ == "__main__":
    connector = LinearConnector()
    connector.load_credentials({"linear_api_key": os.environ["LINEAR_API_KEY"]})

    document_batches = connector.load_from_state()
    print(next(document_batches))
