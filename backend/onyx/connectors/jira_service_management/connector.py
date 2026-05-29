"""Connector for Jira Service Management (JSM).

Jira Service Management is Atlassian's ITSM solution. This connector
pulls in customer requests/tickets from JSM service desk projects using
the JSM REST API (servicedeskapi).

Docs: https://developer.atlassian.com/cloud/jira/service-desk/rest/
"""

import base64
from collections.abc import Generator
from collections.abc import Iterator
from datetime import datetime
from datetime import timezone
from typing import Any

import requests
from typing_extensions import override

from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from onyx.utils.logger import setup_logger

logger = setup_logger()

_JSM_API_BASE = "/rest/servicedeskapi"
_PAGE_SIZE = 50


class JiraServiceManagementConnector(LoadConnector, PollConnector):
    """Connector that pulls tickets from Jira Service Management projects."""

    def __init__(self) -> None:
        self.jira_base_url: str | None = None
        self.jira_email: str | None = None
        self.jira_token: str | None = None
        self.project_keys: list[str] = []

    @override
    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self.jira_base_url = credentials.get("jira_base_url", "").rstrip("/")
        self.jira_email = credentials.get("jira_email", "")
        self.jira_token = credentials.get("jira_token", "")
        project_keys_raw = credentials.get("project_keys", "")
        self.project_keys = [k.strip() for k in project_keys_raw.split(",") if k.strip()]

        if not self.jira_base_url or not self.jira_email or not self.jira_token:
            raise ConnectorMissingCredentialError("JiraServiceManagement")

        if not self.project_keys:
            raise ConnectorMissingCredentialError("JiraServiceManagement")

        return None

    def _get_headers(self) -> dict[str, str]:
        auth_bytes = f"{self.jira_email}:{self.jira_token}".encode()
        return {
            "Accept": "application/json",
            "Authorization": f"Basic {base64.b64encode(auth_bytes).decode()}",
        }

    def _list_service_desks(self) -> list[dict[str, Any]]:
        """Fetch all service desks with pagination."""
        all_desks: list[dict[str, Any]] = []
        start = 0
        while True:
            url = f"{self.jira_base_url}{_JSM_API_BASE}/servicedesk?start={start}&limit={_PAGE_SIZE}"
            try:
                resp = requests.get(url, headers=self._get_headers(), timeout=30)
                resp.raise_for_status()
                data = resp.json()
                all_desks.extend(data.get("values", []))
                if data.get("isLastPage", True):
                    break
                start += _PAGE_SIZE
            except Exception as e:
                logger.warning(f"Failed to list service desks at offset {start}: {e}")
                break
        return all_desks

    def _sd_request_to_jira_issue(self, item: dict[str, Any]) -> dict[str, Any]:
        """Convert a JSM Service Desk API request item to a Jira-issue-like dict.

        The Service Desk API returns items with `requestFieldValues`, while
        `_build_document` expects a Jira issue structure with `fields.summary`,
        `fields.description`, etc. This normalizes the format.
        """
        issue_key = item.get("issueKey", "")

        fields: dict[str, Any] = {}

        # Map requestFieldValues to standard Jira fields
        for rfv in item.get("requestFieldValues", []):
            field_id = rfv.get("fieldId", "")
            value = rfv.get("value")
            if field_id == "summary":
                fields["summary"] = str(value) if value else "No summary"
            elif field_id == "description":
                fields["description"] = str(value) if value else ""

        # Use issueKey as summary fallback
        if "summary" not in fields:
            fields["summary"] = f"JSM Request {issue_key}" if issue_key else "No summary"

        # Map currentStatus
        current_status = item.get("currentStatus", {})
        if isinstance(current_status, dict):
            status_name = current_status.get("status", "Unknown")
            fields["status"] = {"name": status_name}
            fields["statusCategory"] = current_status.get("statusCategory", "")
        else:
            fields["status"] = {"name": str(current_status) if current_status else "Unknown"}

        # Map createdDate
        created_date = item.get("createdDate", {})
        if isinstance(created_date, dict):
            fields["created"] = created_date.get("jira", "")
        elif isinstance(created_date, str):
            fields["created"] = created_date

        return {
            "id": item.get("issueId", ""),
            "key": issue_key,
            "fields": fields,
        }

    def _fetch_sd_requests(self, project_key: str) -> list[dict[str, Any]]:
        """Fetch customer requests from JSM using the Service Desk API (full load)."""
        all_requests: list[dict[str, Any]] = []
        desks = self._list_service_desks()

        service_desk_id = None
        for desk in desks:
            if desk.get("projectKey") == project_key:
                service_desk_id = desk["id"]
                break

        if not service_desk_id:
            logger.warning(f"No service desk found for project {project_key}")
            return []

        start = 0
        while True:
            req_url = (
                f"{self.jira_base_url}{_JSM_API_BASE}/servicedesk/{service_desk_id}/request"
                f"?start={start}&limit={_PAGE_SIZE}"
            )
            try:
                resp = requests.get(req_url, headers=self._get_headers(), timeout=30)
                resp.raise_for_status()
                data = resp.json()
                for item in data.get("values", []):
                    all_requests.append(self._sd_request_to_jira_issue(item))
                if data.get("isLastPage", True):
                    break
                start += _PAGE_SIZE
            except Exception as e:
                logger.warning(f"Failed to fetch requests for desk {service_desk_id}: {e}")
                break

        return all_requests

    def _fetch_via_jql(
        self,
        project_key: str,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch JSM tickets via Jira JQL, optionally filtered by time range."""
        jql = f'project = "{project_key}" AND issuetype in standardIssueTypes()'
        if start_time:
            jql += f' AND updated >= "{start_time.strftime("%Y-%m-%d %H:%M")}"'
        if end_time:
            jql += f' AND updated <= "{end_time.strftime("%Y-%m-%d %H:%M")}"'

        url = f"{self.jira_base_url}/rest/api/3/search"
        all_issues: list[dict[str, Any]] = []
        start_at = 0

        while True:
            params = {
                "jql": jql,
                "startAt": start_at,
                "maxResults": _PAGE_SIZE,
                "fields": "summary,description,status,priority,created,updated,reporter,assignee,comment",
            }
            try:
                resp = requests.get(
                    url, headers=self._get_headers(), params=params, timeout=30
                )
                resp.raise_for_status()
                data = resp.json()
                all_issues.extend(data.get("issues", []))
                if start_at + _PAGE_SIZE >= data.get("total", 0):
                    break
                start_at += _PAGE_SIZE
            except Exception as e:
                logger.warning(f"JQL search failed for {project_key}: {e}")
                break

        return all_issues

    def _fetch_requests(
        self,
        project_key: str,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch requests for a project, trying Service Desk API first, falling back to JQL.

        When a time range is provided, always uses JQL (server-side filtering)
        since the Service Desk API doesn't natively support time-based filtering
        on its request endpoint.
        """
        # For time-filtered queries (poll), use JQL directly for efficiency
        if start_time or end_time:
            return self._fetch_via_jql(project_key, start_time=start_time, end_time=end_time)

        # For full loads (load_from_state), try SD API first, fall back to JQL
        result = self._fetch_sd_requests(project_key)
        if result:
            return result
        return self._fetch_via_jql(project_key)

    def _build_document(self, issue: dict[str, Any], project_key: str) -> Document:
        """Convert a JSM request/issue into an Onyx Document."""
        fields = issue.get("fields", {})
        key = issue.get("key", "")
        summary = fields.get("summary", "No summary")
        description = fields.get("description", "")

        # Extract text from description (could be ADF or plain text)
        desc_text = ""
        if isinstance(description, str):
            desc_text = description
        elif isinstance(description, dict):
            desc_text = self._extract_adf_text(description)

        status = fields.get("status", {})
        status_name = status.get("name", "Unknown") if isinstance(status, dict) else str(status)
        priority = fields.get("priority", {})
        priority_name = priority.get("name", "None") if isinstance(priority, dict) else str(priority)
        created = fields.get("created", "")
        updated = fields.get("updated", "")

        # Build document content
        content_parts = [
            f"# {key}: {summary}",
            f"Status: {status_name}",
            f"Priority: {priority_name}",
            "",
            desc_text,
        ]

        # Add comments if available
        comment_field = fields.get("comment", {})
        if isinstance(comment_field, dict):
            comments = comment_field.get("comments", [])
            if comments:
                content_parts.append("\n## Comments")
                for comment in comments:
                    author = comment.get("author", {}).get("displayName", "Unknown")
                    body = comment.get("body", "")
                    if isinstance(body, dict):
                        body = self._extract_adf_text(body)
                    content_parts.append(f"\n**{author}:** {body}")

        content = "\n".join(content_parts)

        metadata: dict[str, str] = {
            "key": key,
            "project_key": project_key,
            "status": status_name,
            "priority": priority_name,
            "type": "jira_service_management",
        }

        doc = Document(
            id=f"jsm:{project_key}:{key}",
            sections=[TextSection(link=f"{self.jira_base_url}/browse/{key}", text=content)],
            source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
            semantic_identifier=f"{key}: {summary}",
            metadata=metadata,
            doc_updated_at=time_str_to_utc(updated) if updated else None,
        )

        return doc

    @staticmethod
    def _extract_adf_text(adf: dict) -> str:
        """Extract plain text from Atlassian Document Format."""
        texts: list[str] = []

        def _extract(node: dict) -> None:
            if node.get("type") == "text":
                text = node.get("text", "")
                if text:
                    texts.append(text)
            elif node.get("type") == "inlineCard" and node.get("attrs", {}).get("url"):
                texts.append(node["attrs"]["url"])
            for child in node.get("content", []):
                _extract(child)
            if node.get("type") in ("paragraph", "heading"):
                texts.append("\n")

        _extract(adf)
        return "".join(texts).strip()

    @override
    def load_from_state(self) -> GenerateDocumentsOutput:
        """Load all documents from the configured JSM projects."""
        if not self.project_keys:
            return

        for project_key in self.project_keys:
            logger.info(f"Loading JSM requests for project: {project_key}")
            requests_data = self._fetch_requests(project_key)
            batch: list[Document] = []
            for req_data in requests_data:
                doc = self._build_document(req_data, project_key)
                batch.append(doc)
                if len(batch) >= 10:
                    yield batch
                    batch = []
            if batch:
                yield batch

    @override
    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        """Poll for updated documents within a time range using server-side filtering."""
        start_dt = datetime.fromtimestamp(start, tz=timezone.utc)
        end_dt = datetime.fromtimestamp(end, tz=timezone.utc)

        if not self.project_keys:
            return

        for project_key in self.project_keys:
            logger.info(f"Polling JSM requests for project: {project_key}")
            # Both paths (SD API and JQL) go through _fetch_requests now, keeping
            # load/poll scope consistent. Time-filtered calls use JQL for efficiency.
            all_requests = self._fetch_requests(project_key, start_time=start_dt, end_time=end_dt)
            batch: list[Document] = []
            for req_data in all_requests:
                doc = self._build_document(req_data, project_key)
                batch.append(doc)
                if len(batch) >= 10:
                    yield batch
                    batch = []
            if batch:
                yield batch
