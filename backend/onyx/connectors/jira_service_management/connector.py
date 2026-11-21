"""Jira Service Management connector (DRAFT for onyx-dot-app/onyx#2281).

Indexes service requests (tickets) from one Jira Service Management project
as Onyx documents: summary, description, public comments, and request
metadata (request type, status, reporter, assignee, priority).

Design notes
------------
- Self-contained on purpose: Onyx import boundaries forbid a connector from
  importing another connector, so nothing here imports the Jira connector.
  Shared behavior is re-implemented in miniature (ADF text extraction,
  datetime parsing, error mapping).
- Discovery runs through the Jira issue search (JQL), which is the only
  JSM-adjacent API that can filter by ``updated`` window; that is what makes
  polling possible. Request details and public comments come from the
  Service Desk API (``/rest/servicedeskapi``), which carries the
  request-type / portal view of a ticket.
- Credentials mirror the Jira connector convention: ``jira_user_email`` +
  ``jira_api_token`` (Cloud, basic auth) or a lone ``jira_api_token``
  (Server / Data Center personal access token, bearer auth).
"""

import time
from collections.abc import Generator
from datetime import datetime, timezone
from typing import Any

import requests
from typing_extensions import override

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    InsufficientPermissionsError,
    UnexpectedValidationError,
)
from onyx.connectors.interfaces import (
    GenerateSlimDocumentOutput,
    LoadConnector,
    PollConnector,
    SecondsSinceUnixEpoch,
    SlimConnector,
)
from onyx.connectors.models import (
    BasicExpertInfo,
    ConnectorMissingCredentialError,
    Document,
    SlimDocument,
    TextSection,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

_REQUEST_TIMEOUT_SECONDS = 60
_PAGE_SIZE = 50
# The Service Desk API caps `limit` at 50 for request lists.
_JSM_API = "rest/servicedeskapi"
_JIRA_API_V3 = "rest/api/3"
_JIRA_API_V2 = "rest/api/2"


class _JsmApiError(Exception):
    def __init__(self, status_code: int | None, body: str | None) -> None:
        super().__init__(f"JSM API error (HTTP {status_code}): {body}")
        self.status_code = status_code
        self.body = body


def _parse_jira_datetime(value: str | None) -> datetime | None:
    """Parse the ISO-8601 variants Jira returns into an aware datetime."""
    if not value:
        return None
    text = value.strip()
    # Jira Cloud writes offsets like +0000 (no colon); fromisoformat wants +00:00.
    if len(text) > 5 and (text[-5] in "+-") and text[-2] != ":":
        text = f"{text[:-2]}:{text[-2:]}"
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _adf_to_text(node: Any) -> str:
    """Flatten an Atlassian Document Format tree to plain text."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(_adf_to_text(child) for child in node)
    if not isinstance(node, dict):
        return ""
    node_type = node.get("type")
    if node_type == "text":
        return str(node.get("text", ""))
    if node_type == "hardBreak":
        return "\n"
    inner = _adf_to_text(node.get("content"))
    if node_type in {"paragraph", "heading", "listItem", "blockquote", "codeBlock"}:
        return inner + "\n"
    return inner


def _description_to_text(fields: dict[str, Any]) -> str:
    description = fields.get("description")
    if isinstance(description, str):
        return description
    if isinstance(description, dict):
        return _adf_to_text(description).strip()
    return ""


def _expert_info(user: Any) -> BasicExpertInfo | None:
    if not isinstance(user, dict):
        return None
    display_name = user.get("displayName")
    email = user.get("emailAddress")
    if not display_name and not email:
        return None
    return BasicExpertInfo(display_name=display_name, email=email)


class JiraServiceManagementConnector(LoadConnector, PollConnector, SlimConnector):
    """Indexes the requests of a single JSM service project."""

    def __init__(
        self,
        jira_base_url: str,
        project_key: str,
        batch_size: int = INDEX_BATCH_SIZE,
        include_internal_comments: bool = False,
    ) -> None:
        self.jira_base = jira_base_url.rstrip("/")
        self.project_key = project_key.strip()
        self.batch_size = batch_size
        self.include_internal_comments = include_internal_comments
        self._session: requests.Session | None = None
        self._service_desk_id: int | None = None

    # -- credentials / HTTP -------------------------------------------------

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        email = credentials.get("jira_user_email")
        token = credentials.get("jira_api_token")
        if not token:
            raise ConnectorMissingCredentialError("Jira Service Management")

        session = requests.Session()
        if email:
            session.auth = (email, token)
        else:
            session.headers["Authorization"] = f"Bearer {token}"
        session.headers["Accept"] = "application/json"
        self._session = session
        return None

    @property
    def _api_version(self) -> str:
        # Cloud credentials carry an account email; Server/DC PATs do not.
        return _JIRA_API_V3 if self._session and self._session.auth else _JIRA_API_V2

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if self._session is None:
            raise ConnectorMissingCredentialError("Jira Service Management")
        url = f"{self.jira_base}/{path.lstrip('/')}"
        try:
            response = self._session.get(
                url, params=params, timeout=_REQUEST_TIMEOUT_SECONDS
            )
        except requests.RequestException as e:
            raise _JsmApiError(None, str(e)) from e
        if response.status_code >= 400:
            raise _JsmApiError(response.status_code, response.text)
        if not response.content:
            return {}
        return response.json()

    # -- Service Desk API ----------------------------------------------------

    def _resolve_service_desk_id(self) -> int:
        if self._service_desk_id is not None:
            return self._service_desk_id
        start = 0
        while True:
            page = self._get(
                f"{_JSM_API}/servicedesk", params={"start": start, "limit": _PAGE_SIZE}
            )
            for desk in page.get("values", []):
                if desk.get("projectKey") == self.project_key:
                    self._service_desk_id = int(desk["id"])
                    return self._service_desk_id
            if page.get("isLastPage", True):
                break
            start = int(page.get("nextPageStart", start + _PAGE_SIZE))
        raise ConnectorValidationError(
            f"No Jira Service Management project with key '{self.project_key}' "
            "is visible to the configured credential."
        )

    def _fetch_request(self, issue_key: str) -> dict[str, Any]:
        """One service request with comments, request type and status."""
        return self._get(
            f"{_JSM_API}/request/{issue_key}",
            params={"expand": "comment,requestType,status,participant"},
        )

    # -- Jira search (discovery / polling) -----------------------------------

    def _search_issue_keys(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> Generator[str, None, None]:
        """Keys of project issues updated inside the window, oldest first."""
        start_dt = datetime.fromtimestamp(start, tz=timezone.utc)
        end_dt = datetime.fromtimestamp(end, tz=timezone.utc)
        # JQL date literals are minute-precision, in the API user's timezone;
        # the Jira connector's epoch-ms trick only works for `updated`
        # comparisons on fields that accept it, so use quoted literals here.
        jql = (
            f'project = "{self.project_key}" AND '
            f'updated >= "{start_dt:%Y-%m-%d %H:%M}" AND '
            f'updated <= "{end_dt:%Y-%m-%d %H:%M}" ORDER BY updated ASC'
        )
        offset = 0
        while True:
            page = self._get(
                f"{self._api_version}/search",
                params={
                    "jql": jql,
                    "fields": "key",
                    "startAt": offset,
                    "maxResults": _PAGE_SIZE,
                },
            )
            issues = page.get("issues", [])
            for issue in issues:
                yield str(issue["key"])
            offset += len(issues)
            if offset >= int(page.get("total", 0)) or not issues:
                return

    # -- document building ----------------------------------------------------

    def _request_to_document(self, request: dict[str, Any]) -> Document | None:
        fields = request.get("issueFields") or {}
        issue_key = str(request.get("issueKey") or fields.get("key") or "")
        if not issue_key:
            return None

        summary = str(fields.get("summary") or "")
        description = _description_to_text(fields)

        comment_texts: list[str] = []
        comments = (request.get("comment") or {}).get("values") or []
        for comment in comments:
            if not self.include_internal_comments and comment.get("public") is False:
                continue
            body = comment.get("body")
            text = body if isinstance(body, str) else _adf_to_text(body)
            if text:
                author = (comment.get("author") or {}).get("displayName")
                comment_texts.append(
                    f"Comment by {author}: {text}" if author else f"Comment: {text}"
                )

        content = description + "\n" + "\n".join(comment_texts)
        page_url = f"{self.jira_base}/browse/{issue_key}"

        metadata: dict[str, str | list[str]] = {"key": issue_key}
        people: list[BasicExpertInfo] = []

        request_type = (request.get("requestType") or {}).get("name")
        if request_type:
            metadata["request_type"] = str(request_type)
        status = (request.get("currentStatus") or {}).get("status")
        if status:
            metadata["status"] = str(status)

        reporter = _expert_info(request.get("reporter"))
        if reporter is not None:
            people.append(reporter)
            metadata["reporter"] = reporter.get_semantic_name()
        assignee = _expert_info(fields.get("assignee"))
        if assignee is not None:
            people.append(assignee)
            metadata["assignee"] = assignee.get_semantic_name()
        if priority := (fields.get("priority") or {}).get("name"):
            metadata["priority"] = str(priority)
        metadata["project"] = self.project_key
        metadata["project_name"] = str(
            (request.get("serviceDesk") or {}).get("projectName") or self.project_key
        )

        created = _parse_jira_datetime(request.get("createdDate", {}).get("iso8601"))
        updated = _parse_jira_datetime(fields.get("updated"))

        return Document(
            id=page_url,
            sections=[TextSection(link=page_url, text=content)],
            source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
            semantic_identifier=f"{issue_key}: {summary}",
            title=f"{issue_key} {summary}",
            doc_updated_at=updated,
            doc_created_at=created,
            primary_owners=people or None,
            metadata=metadata,
        )

    def _fetch_documents(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> Generator[Document, None, None]:
        # Resolve once up front so a bad project key fails fast, not per ticket.
        self._resolve_service_desk_id()
        batch: list[Document] = []
        for issue_key in self._search_issue_keys(start, end):
            try:
                request = self._fetch_request(issue_key)
            except _JsmApiError as e:
                self._raise_mapped(e)
                raise  # unreachable; keeps type checkers honest
            document = self._request_to_document(request)
            if document is not None:
                batch.append(document)
            if len(batch) >= self.batch_size:
                yield from batch
                batch = []
        yield from batch

    # -- connector interfaces --------------------------------------------------

    def load_from_state(self) -> Generator[Document, None, None]:
        # Epoch to "now + 1 day", the same convention the Jira connector uses
        # for slim listings, to absorb source-side timezone skew.
        yield from self._fetch_documents(0, time.time() + 24 * 3600)

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> Generator[Document, None, None]:
        yield from self._fetch_documents(start, end)

    def retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: Any = None,
    ) -> GenerateSlimDocumentOutput:
        start = start or 0
        end = end or time.time() + 24 * 3600
        batch: list[SlimDocument] = []
        for issue_key in self._search_issue_keys(start, end):
            batch.append(
                SlimDocument(id=f"{self.jira_base}/browse/{issue_key}")
            )
            if len(batch) >= self.batch_size:
                yield batch
                batch = []
        if batch:
            yield batch

    # -- validation -------------------------------------------------------------

    @staticmethod
    def _raise_mapped(error: _JsmApiError) -> None:
        if error.status_code == 401:
            raise CredentialExpiredError(
                "Jira Service Management credential appears to be expired or "
                "invalid (HTTP 401)."
            )
        if error.status_code == 403:
            raise InsufficientPermissionsError(
                "The Jira credential cannot read this service project (HTTP 403)."
            )
        raise UnexpectedValidationError(
            f"Unexpected Jira Service Management error: {error.body or error}"
        )

    def validate_connector_settings(self) -> None:
        if self._session is None:
            raise ConnectorMissingCredentialError("Jira Service Management")
        try:
            self._resolve_service_desk_id()
        except _JsmApiError as e:
            self._raise_mapped(e)


if __name__ == "__main__":
    import os

    connector = JiraServiceManagementConnector(
        jira_base_url=os.environ["JIRA_BASE_URL"],
        project_key=os.environ["JSM_PROJECT_KEY"],
    )
    connector.load_credentials(
        {
            "jira_user_email": os.environ["JIRA_USER_EMAIL"],
            "jira_api_token": os.environ["JIRA_API_TOKEN"],
        }
    )
    for doc in connector.load_from_state():
        print(doc.semantic_identifier)
