"""Jira Service Management (JSM) connector for Onyx.

Indexes service desk tickets/requests from JSM projects, including
SLA status, request types, and customer information.
"""
from collections.abc import Iterator
from datetime import datetime
from datetime import timezone
from typing import Any

import requests
from requests.auth import HTTPBasicAuth

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.app_configs import JSM_CONNECTOR_LABELS_TO_SKIP
from onyx.configs.app_configs import JSM_CONNECTOR_MAX_TICKET_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.jira_service_management.utils import format_sla_as_text
from onyx.connectors.jira_service_management.utils import get_request_details
from onyx.connectors.jira_service_management.utils import get_sla_information
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from onyx.utils.logger import setup_logger

logger = setup_logger()

_JSM_ID_PREFIX = "JSM_"
_JIRA_REST_API = "/rest/api/3"
_JSM_PAGE_SIZE = 50

# Characters that must not appear in project keys passed to JQL
_JQL_UNSAFE = frozenset('"\'\\;')


def _build_issue_url(base_url: str, issue_key: str) -> str:
    return f"{base_url}/browse/{issue_key}"


def _extract_text_from_field(field: Any) -> str:
    """Extract plain text from a Jira field (ADF or string)."""
    if field is None:
        return ""
    if isinstance(field, str):
        return field
    if isinstance(field, dict):
        # Atlassian Document Format (ADF)
        texts: list[str] = []
        for block in field.get("content", []):
            for inline in block.get("content", []):
                if inline.get("type") == "text":
                    texts.append(inline.get("text", ""))
        return " ".join(texts)
    return str(field)


def _handle_http_error(response: requests.Response, context: str) -> None:
    """Raise a typed connector exception based on HTTP status code."""
    status = response.status_code
    if status == 401:
        raise CredentialExpiredError(
            f"JSM credentials are expired or invalid (401) while {context}."
        )
    if status == 403:
        raise InsufficientPermissionsError(
            f"Insufficient permissions (403) while {context}."
        )
    if status == 400:
        raise ConnectorValidationError(
            f"Bad request (400) while {context}: {response.text}"
        )
    response.raise_for_status()


class JiraServiceManagementConnector(PollConnector, LoadConnector):
    """Connector that indexes Jira Service Management service desk requests.

    Differences from the standard Jira connector:
    - Scoped to projects with ``projectTypeKey = "service_desk"``
    - Enriches each ticket with JSM-specific data: request type,
      participants, and SLA status via the Service Desk REST API
    - Uses ``jsm_user_email`` / ``jsm_api_token`` credentials so JSM
      instances can be configured independently from Jira Software
    """

    def __init__(
        self,
        jsm_base_url: str,
        project_key: str | None = None,
        labels_to_skip: list[str] | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        self.jsm_base_url = jsm_base_url.rstrip("/")
        self.project_key = project_key
        self.labels_to_skip: set[str] = set(
            labels_to_skip if labels_to_skip is not None else JSM_CONNECTOR_LABELS_TO_SKIP
        )
        self.batch_size = batch_size
        self._auth: HTTPBasicAuth | None = None

    # ------------------------------------------------------------------
    # Credential loading
    # ------------------------------------------------------------------

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        user_email = credentials.get("jsm_user_email")
        api_token = credentials.get("jsm_api_token")
        if not user_email or not api_token:
            raise ConnectorMissingCredentialError(
                "Jira Service Management requires 'jsm_user_email' and "
                "'jsm_api_token' credentials."
            )
        self._auth = HTTPBasicAuth(str(user_email), str(api_token))
        return None

    # ------------------------------------------------------------------
    # JQL helpers
    # ------------------------------------------------------------------

    def _build_jql(
        self,
        updated_after: datetime | None = None,
        updated_before: datetime | None = None,
    ) -> str:
        conditions: list[str] = []

        if self.project_key:
            sanitized = "".join(
                c for c in self.project_key if c not in _JQL_UNSAFE
            )
            if not sanitized:
                raise ConnectorValidationError(
                    f"Project key '{self.project_key}' contains only invalid characters."
                )
            conditions.append(f'project = "{sanitized}"')
            conditions.append("projectType = service_desk")
        else:
            conditions.append("projectType = service_desk")

        if updated_after:
            conditions.append(
                f"updated >= '{updated_after.strftime('%Y-%m-%d %H:%M')}'"
            )
        if updated_before:
            conditions.append(
                f"updated <= '{updated_before.strftime('%Y-%m-%d %H:%M')}'"
            )

        return " AND ".join(conditions) + " ORDER BY updated ASC"

    def _search_jql(
        self, jql: str, start_at: int = 0, max_results: int = _JSM_PAGE_SIZE
    ) -> dict[str, Any]:
        url = f"{self.jsm_base_url}{_JIRA_REST_API}/search"
        response = requests.get(
            url,
            auth=self._auth,
            headers={"Accept": "application/json"},
            params={
                "jql": jql,
                "startAt": start_at,
                "maxResults": max_results,
                "fields": (
                    "summary,description,comment,status,priority,"
                    "assignee,reporter,created,updated,labels,"
                    "issuetype,project,resolutiondate,duedate"
                ),
            },
            timeout=15,
        )
        if response.status_code == 429:
            raise requests.exceptions.HTTPError(
                f"Rate limited by Jira API at offset {start_at}", response=response
            )
        _handle_http_error(response, f"JQL search: {jql}")
        return response.json()

    # ------------------------------------------------------------------
    # Document construction
    # ------------------------------------------------------------------

    def _build_document(self, issue: dict[str, Any]) -> Document | None:
        fields = issue.get("fields", {})
        issue_key = issue.get("key", "")
        if not issue_key:
            return None

        # Skip labelled issues
        labels: list[str] = fields.get("labels", []) or []
        if self.labels_to_skip and any(lbl in self.labels_to_skip for lbl in labels):
            logger.info(f"Skipping {issue_key} — label in skip list.")
            return None

        summary: str = fields.get("summary", "")
        description = _extract_text_from_field(fields.get("description"))

        # Comments
        comment_parts: list[str] = []
        for c in (fields.get("comment") or {}).get("comments", []):
            author = (c.get("author") or {}).get("displayName", "Unknown")
            body = _extract_text_from_field(c.get("body"))
            if body:
                comment_parts.append(f"[{author}]: {body}")

        # JSM-specific enrichment (best-effort, never fatal)
        jsm_lines: list[str] = []
        request_type_name = ""
        try:
            rd = get_request_details(self.jsm_base_url, self._auth, issue_key)
            request_type_name = (rd.get("requestType") or {}).get("name", "")
            participants = (rd.get("participants") or {}).get("values", [])
            if request_type_name:
                jsm_lines.append(f"Request Type: {request_type_name}")
            if participants:
                names = [p.get("displayName", "") for p in participants]
                jsm_lines.append(f"Participants: {', '.join(names)}")
        except Exception:
            logger.warning(
                f"Failed to fetch JSM request details for {issue_key}",
                exc_info=True,
            )

        sla_text = ""
        try:
            sla_data = get_sla_information(self.jsm_base_url, self._auth, issue_key)
            sla_text = format_sla_as_text(sla_data)
        except Exception:
            logger.warning(
                f"Failed to fetch SLA information for {issue_key}",
                exc_info=True,
            )

        # Assemble full document text
        content_parts: list[str] = []
        if description:
            content_parts.append(f"Description:\n{description}")
        if comment_parts:
            content_parts.append("Comments:\n" + "\n".join(comment_parts))
        if jsm_lines:
            content_parts.append("\n".join(jsm_lines))
        if sla_text:
            content_parts.append(sla_text)

        full_text = "\n\n".join(content_parts) if content_parts else summary

        # Enforce max ticket size after all content (including JSM enrichment) is assembled
        if len(full_text.encode("utf-8")) > JSM_CONNECTOR_MAX_TICKET_SIZE:
            logger.info(f"Skipping {issue_key} — exceeds max ticket size.")
            return None

        # Metadata
        metadata: dict[str, str | list[str]] = {}
        if status_obj := fields.get("status"):
            metadata["status"] = status_obj.get("name", "")
        if priority_obj := fields.get("priority"):
            metadata["priority"] = priority_obj.get("name", "")
        if assignee_obj := fields.get("assignee"):
            metadata["assignee"] = assignee_obj.get("displayName", "")
        if reporter_obj := fields.get("reporter"):
            metadata["reporter"] = reporter_obj.get("displayName", "")
        if project_obj := fields.get("project"):
            metadata["project"] = project_obj.get("key", "")
            metadata["project_name"] = project_obj.get("name", "")
        if labels:
            metadata["labels"] = labels
        if request_type_name:
            metadata["request_type"] = request_type_name
        if rd_date := fields.get("resolutiondate"):
            metadata["resolution_date"] = rd_date

        page_url = _build_issue_url(self.jsm_base_url, issue_key)
        updated_str: str = fields.get("updated", "")
        doc_updated_at: datetime | None = None
        if updated_str:
            try:
                doc_updated_at = datetime.fromisoformat(
                    updated_str.replace("Z", "+00:00")
                )
            except ValueError:
                pass

        return Document(
            id=_JSM_ID_PREFIX + page_url,
            sections=[TextSection(link=page_url, text=full_text)],
            source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
            semantic_identifier=f"{issue_key}: {summary}",
            title=f"{issue_key} {summary}",
            doc_updated_at=doc_updated_at,
            metadata=metadata,
        )

    # ------------------------------------------------------------------
    # Pagination driver
    # ------------------------------------------------------------------

    def _iter_documents(
        self,
        updated_after: datetime | None = None,
        updated_before: datetime | None = None,
    ) -> Iterator[list[Document]]:
        if self._auth is None:
            raise ConnectorMissingCredentialError("Jira Service Management")

        jql = self._build_jql(updated_after, updated_before)
        logger.info(f"JSM connector JQL: {jql}")

        start_at = 0
        page_size = min(self.batch_size, _JSM_PAGE_SIZE)
        total = 0

        while True:
            try:
                result = self._search_jql(jql, start_at=start_at, max_results=page_size)
            except requests.exceptions.HTTPError as exc:
                if exc.response is not None and exc.response.status_code == 429:
                    logger.warning(
                        "Rate limited by Jira API at offset %d/%d — "
                        "partial results returned. Indexing will resume on next poll.",
                        start_at,
                        total,
                    )
                    break
                raise
            issues = result.get("issues", [])
            total: int = result.get("total", 0)

            logger.info(
                f"JSM: fetched {len(issues)} issues (offset {start_at}/{total})"
            )

            if not issues:
                break

            doc_batch: list[Document] = []
            for raw_issue in issues:
                try:
                    doc = self._build_document(raw_issue)
                    if doc is not None:
                        doc_batch.append(doc)
                except Exception as exc:
                    logger.warning(
                        f"Failed to process JSM issue "
                        f"{raw_issue.get('key', '?')}: {exc}"
                    )

            if doc_batch:
                yield doc_batch

            start_at += len(issues)
            if start_at >= total:
                break

    # ------------------------------------------------------------------
    # LoadConnector / PollConnector interface
    # ------------------------------------------------------------------

    def load_from_state(self) -> GenerateDocumentsOutput:
        yield from self._iter_documents()

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        start_dt = datetime.fromtimestamp(start, tz=timezone.utc)
        end_dt = datetime.fromtimestamp(end, tz=timezone.utc)
        yield from self._iter_documents(start_dt, end_dt)

    def validate_connector_settings(self) -> None:
        if self._auth is None:
            raise ConnectorMissingCredentialError("Jira Service Management")
        try:
            result = self._search_jql(self._build_jql(), max_results=1)
            if "issues" not in result:
                raise ConnectorValidationError(
                    "Unexpected response from Jira Service Management API."
                )
        except (CredentialExpiredError, InsufficientPermissionsError):
            raise
        except ConnectorValidationError:
            raise
        except Exception as exc:
            raise ConnectorValidationError(
                f"Could not connect to Jira Service Management: {exc}"
            ) from exc



