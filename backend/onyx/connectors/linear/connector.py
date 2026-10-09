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
from onyx.connectors.cross_connector_utils.miscellaneous_utils import (
    get_oauth_callback_uri,
    time_str_to_utc,
)
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.interfaces import (
    GenerateDocumentsOutput,
    LoadConnector,
    NormalizationResult,
    OAuthConnector,
    PollConnector,
    SecondsSinceUnixEpoch,
)
from onyx.connectors.models import (
    ConnectorMissingCredentialError,
    Document,
    HierarchyNode,
    ImageSection,
    TextSection,
)
from onyx.utils.logger import setup_logger
from onyx.utils.retry_wrapper import request_with_retries

logger = setup_logger()

_NUM_RETRIES = 5
_TIMEOUT = 60
_LINEAR_GRAPHQL_URL = "https://api.linear.app/graphql"
_ACCESS_TOKEN = "access_token"
_EXPIRE_AT = "expire_at"
_REFRESH_TOKEN = "refresh_token"
_EXPIRES_IN = "expires_in"


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


def _run_query(query: str, variables: dict[str, Any], api_key: str) -> dict[str, Any]:
    """The query's data. Linear answers 200 with an `errors` list for a bad
    query, so that is raised here rather than read as an empty result."""
    response = _make_query({"query": query, "variables": variables}, api_key)
    body: dict[str, Any] = response.json()
    if body.get("errors"):
        raise RuntimeError(f"Linear GraphQL errors: {body['errors']}")
    return body["data"]


# Linear caps a query's complexity at 10,000 points. A listing page fits at 100.
_LISTING_PAGE_SIZE = 100
# A walk still paging past this is a cursor cycling rather than ending.
_MAX_PAGES = 100_000

_PAGE_INFO = """
    pageInfo {
        hasNextPage
        endCursor
    }
"""
_TEAMS_BY_KEY_QUERY = f"""
    query TeamsByKey($keys: [String!], $first: Int, $after: String) {{
        teams(first: $first, after: $after, filter: {{ key: {{ in: $keys }} }}) {{
            nodes {{ key }}
            {_PAGE_INFO}
        }}
    }}
"""
_PROJECTS_QUERY = f"""
    query ProjectsInScope($filter: ProjectFilter, $first: Int, $after: String) {{
        projects(first: $first, after: $after, filter: $filter) {{
            nodes {{ name slugId }}
            {_PAGE_INFO}
        }}
    }}
"""
# A project URL ends in the slug and the project's slug id:
# https://linear.app/<workspace>/project/<slug>-<slug id>
_PROJECT_URL_SLUG_ID = re.compile(
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


class LinearConnector(LoadConnector, PollConnector, OAuthConnector):
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
        self.linear_api_key: str | None = None

    def _api_key(self) -> str:
        if self.linear_api_key is None:
            raise ConnectorMissingCredentialError("Linear")
        return self.linear_api_key

    def validate_connector_settings(self) -> None:
        """A team or project Linear does not answer for is misspelled or is in
        a private team the token's user is not in. Linear hides both the same
        way, so the messages name the two causes."""
        if self.team_keys:
            self._validate_teams()
        project_filter: dict[str, Any] | None = self._project_filter()
        if project_filter is not None:
            self._validate_projects(project_filter)

    def _validate_teams(self) -> None:
        found: set[str] = {
            team["key"]
            for data in self._pages(
                _TEAMS_BY_KEY_QUERY, {"keys": self.team_keys}, ("teams",)
            )
            for team in data["teams"]["nodes"]
        }
        missing: list[str] = sorted(set(self.team_keys) - found)
        if missing:
            raise ConnectorValidationError(
                f"Linear teams not found: {', '.join(missing)}. Check the key, "
                "or connect as a member if the team is private."
            )

    def _validate_projects(self, project_filter: dict[str, Any]) -> None:
        projects: list[dict[str, Any]] = [
            project
            for data in self._pages(
                _PROJECTS_QUERY, {"filter": project_filter}, ("projects",)
            )
            for project in data["projects"]["nodes"]
        ]
        found_names: set[str] = {project["name"] for project in projects}
        found_slug_ids: set[str] = {project["slugId"] for project in projects}
        missing: list[str] = sorted(
            (set(self.project_names) - found_names)
            | (set(self.project_slug_ids) - found_slug_ids)
        )
        if missing:
            raise ConnectorValidationError(
                f"Linear projects not found: {', '.join(missing)}. Check the "
                "name or URL, or connect as a member if the project's team is "
                "private."
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

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        new_credentials = None

        if "linear_api_key" in credentials:
            self.linear_api_key = cast(str, credentials["linear_api_key"])
        elif _ACCESS_TOKEN in credentials:
            if _EXPIRE_AT not in credentials:
                self.linear_api_key = "Bearer " + cast(str, credentials[_ACCESS_TOKEN])
            elif credentials[_EXPIRE_AT] < time.time() + 300:  # 5-minute buffer
                new_credentials = self.refresh_token(credentials)
                self.linear_api_key = "Bearer " + cast(
                    str, new_credentials[_ACCESS_TOKEN]
                )
            elif credentials[_EXPIRE_AT] >= time.time():
                self.linear_api_key = "Bearer " + cast(str, credentials[_ACCESS_TOKEN])
        else:
            # May need to handle case in the future if the OAuth flow expires
            raise ConnectorMissingCredentialError("Linear")

        return new_credentials

    def refresh_token(self, credentials: dict[str, Any]) -> dict[str, Any]:
        if _REFRESH_TOKEN not in credentials:
            raise ConnectorMissingCredentialError("Linear")

        data = {
            _REFRESH_TOKEN: credentials[_REFRESH_TOKEN],
            "client_id": LINEAR_CLIENT_ID,
            "client_secret": LINEAR_CLIENT_SECRET,
            "grant_type": _REFRESH_TOKEN,
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
            raise RuntimeError(f"Failed to refresh token: {response.text}")

        token_data = response.json()

        expire_at = time.time() + token_data[_EXPIRES_IN]

        # Per RFC 6749 §6, the refresh response MAY omit refresh_token, in
        # which case the existing one remains valid. Linear currently rotates
        # refresh tokens on every refresh, but fall back defensively so a
        # missing field doesn't force a full re-OAuth.
        return {
            _ACCESS_TOKEN: token_data[_ACCESS_TOKEN],
            _EXPIRE_AT: int(expire_at),
            _REFRESH_TOKEN: token_data.get(_REFRESH_TOKEN, credentials[_REFRESH_TOKEN]),
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
