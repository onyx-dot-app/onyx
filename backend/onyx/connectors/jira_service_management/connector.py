from datetime import datetime, timezone
from typing import Any

import requests

from onyx.configs.app_configs import INDEX_BATCH_SIZE, REQUEST_TIMEOUT_SECONDS
from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.rate_limit_wrapper import rl_requests
from onyx.connectors.exceptions import (
    CredentialExpiredError,
    InsufficientPermissionsError,
)
from onyx.connectors.interfaces import (
    GenerateDocumentsOutput,
    LoadConnector,
    PollConnector,
    SecondsSinceUnixEpoch,
)
from onyx.connectors.jira.utils import (
    build_jira_url,
    get_comment_strs,
    get_issue_field,
    get_named_field,
    rich_text,
)
from onyx.connectors.models import (
    ConnectorMissingCredentialError,
    Document,
    TextSection,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

JSM_SEARCH_ENDPOINT = "/rest/api/3/search"
PAGE_SIZE = 100
# Jira Service Management stores the "Customer Request Type" in a custom
# field; 10010 is the conventional id on most instances.
REQUEST_TYPE_FIELD = "customfield_10010"


def _jql_timestamp(epoch: SecondsSinceUnixEpoch) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime(
        "%Y-%m-%d %H:%M"
    )


def _build_jsm_jql(
    project_name: str,
    start: SecondsSinceUnixEpoch | None = None,
    end: SecondsSinceUnixEpoch | None = None,
) -> str:
    clauses = [f'project = "{project_name}"']
    if start is not None:
        clauses.append(f'updated >= "{_jql_timestamp(start)}"')
    if end is not None:
        clauses.append(f'updated <= "{_jql_timestamp(end)}"')
    return " AND ".join(clauses) + " ORDER BY updated ASC"


def _parse_timestamp(raw: str | None) -> datetime | None:
    if not raw:
        return None
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _display_name(fields: dict[str, Any], field: str) -> str | None:
    value = fields.get(field)
    if isinstance(value, dict):
        name = value.get("displayName") or value.get("name")
        if isinstance(name, str) and name:
            return name
    return None


def _request_type(issue: dict[str, Any]) -> str | None:
    value = get_issue_field(issue, REQUEST_TYPE_FIELD)
    if isinstance(value, str) and value:
        return value
    return None


def _issue_to_document(
    issue: dict[str, Any], jira_base_url: str
) -> Document:
    issue_key = issue["key"]
    fields = issue.get("fields") or {}

    summary = rich_text(fields.get("summary"))
    description = rich_text(fields.get("description"))
    status = get_named_field(issue, "status") or ""
    priority = get_named_field(issue, "priority") or ""
    issue_type = get_named_field(issue, "issuetype") or ""
    request_type = _request_type(issue) or ""
    reporter = _display_name(fields, "reporter") or ""
    assignee = _display_name(fields, "assignee") or ""
    created = _parse_timestamp(fields.get("created"))
    updated = _parse_timestamp(fields.get("updated"))
    comments = get_comment_strs(issue)

    lines: list[str] = []
    if summary:
        lines.append(f"## {summary}\n")

    overview = [f"{label}: {value}" for label, value in (
        ("Status", status),
        ("Priority", priority),
        ("Request Type", request_type),
        ("Type", issue_type),
        ("Reporter", reporter),
        ("Assignee", assignee),
        ("Created", fields.get("created", "")),
        ("Updated", fields.get("updated", "")),
    ) if value]
    if overview:
        lines.append("\n".join(overview) + "\n")

    if description:
        lines.append("### Description\n" + description + "\n")

    if comments:
        rendered_comments = "\n\n".join(comments)
        lines.append("### Comments\n" + rendered_comments + "\n")

    text = "\n".join(lines)

    metadata: dict[str, Any] = {
        "status": status,
        "priority": priority,
        "issue_type": issue_type,
        "request_type": request_type,
        "reporter": reporter,
        "assignee": assignee,
        "jira_issue_key": issue_key,
    }

    return Document(
        id=f"jsm-{issue_key}",
        sections=[
            TextSection(
                link=build_jira_url(jira_base_url, issue_key),
                text=text,
            )
        ],
        source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
        semantic_identifier=summary or issue_key,
        doc_updated_at=updated,
        doc_created_at=created,
        metadata=metadata,
    )


class JiraServiceManagementApiClient:
    def __init__(
        self,
        jira_base_url: str,
        jira_user_email: str | None,
        jira_api_token: str,
    ) -> None:
        self.jira_base_url = jira_base_url.rstrip("/")
        # An email selects Atlassian Cloud (basic auth with an API token);
        # without one the token is a Data Center personal access token.
        if jira_user_email:
            self.auth: tuple[str, str] | None = (jira_user_email, jira_api_token)
            self.headers = {"Accept": "application/json"}
        else:
            self.auth = None
            self.headers = {
                "Accept": "application/json",
                "Authorization": f"Bearer {jira_api_token}",
            }

    def search(self, jql: str, start_at: int) -> dict[str, Any]:
        url = self.jira_base_url + JSM_SEARCH_ENDPOINT
        params = {
            "jql": jql,
            "startAt": start_at,
            "maxResults": PAGE_SIZE,
            "validateQuery": "warn",
        }
        # rl_requests waits and retries on 429 (honoring Retry-After)
        response = rl_requests.get(
            url,
            params=params,
            auth=self.auth,
            headers=self.headers,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        if response.status_code == 401:
            raise CredentialExpiredError(
                "Jira Service Management credentials are invalid or expired"
            )
        if response.status_code == 403:
            raise InsufficientPermissionsError(
                "Jira Service Management credentials lack permission "
                "to search this project"
            )
        response.raise_for_status()
        return response.json()


class JiraServiceManagementConnector(LoadConnector, PollConnector):
    """Indexes the customer requests of one Jira Service Management project.

    Requests are Jira issues under the hood, so the standard Jira platform
    search API is used with a JQL clause scoped to the project; JSM-specific
    fields (customer request type, SLAs visible on the issue) are kept as
    document metadata where present.
    """

    def __init__(
        self,
        project_name: str,
        jira_base_url: str,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        self.project_name = project_name
        self.batch_size = batch_size
        self.jira_base_url = jira_base_url.rstrip("/")
        self.client: JiraServiceManagementApiClient | None = None

    def load_credentials(self, credentials: dict[str, Any]) -> None:
        jira_user_email = credentials.get("jira_user_email")
        jira_api_token = credentials.get("jira_api_token")
        if not jira_api_token:
            raise ConnectorMissingCredentialError(
                "Jira Service Management API token"
            )
        self.client = JiraServiceManagementApiClient(
            jira_base_url=self.jira_base_url,
            jira_user_email=jira_user_email,
            jira_api_token=jira_api_token,
        )

    def _fetch_requests(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> GenerateDocumentsOutput:
        if not self.client:
            raise ConnectorMissingCredentialError("Jira Service Management")

        jql = _build_jsm_jql(self.project_name, start=start, end=end)
        current_batch: list[Document] = []
        start_at = 0
        total: int | None = None

        try:
            while total is None or start_at < total:
                page = self.client.search(jql, start_at)
                issues = page.get("issues", [])
                total = int(page.get("total", len(issues) + start_at))

                for issue in issues:
                    current_batch.append(
                        _issue_to_document(issue, self.client.jira_base_url)
                    )
                    if len(current_batch) >= self.batch_size:
                        yield current_batch
                        current_batch = []

                if not issues:
                    break
                start_at += len(issues)

            if current_batch:
                yield current_batch

        except requests.RequestException as e:
            logger.error(
                "Error fetching Jira Service Management requests: %s", str(e)
            )
            raise

    def load_from_state(self) -> GenerateDocumentsOutput:
        return self._fetch_requests()

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        return self._fetch_requests(start=start, end=end)


if __name__ == "__main__":
    import os

    connector = JiraServiceManagementConnector(
        project_name=os.environ["JSM_PROJECT_NAME"],
        jira_base_url=os.environ["JSM_BASE_URL"],
    )
    connector.load_credentials(
        {
            "jira_base_url": os.environ["JSM_BASE_URL"],
            "jira_user_email": os.environ.get("JSM_USER_EMAIL", ""),
            "jira_api_token": os.environ["JSM_API_TOKEN"],
        }
    )
    document_batches = connector.load_from_state()
    print(next(document_batches))
