"""Connector for Jira Service Management (JSM).

Jira Service Management is Atlassian's ITSM solution. This connector
pulls in customer requests/tickets from JSM service desk projects using
the JSM REST API (servicedeskapi).

Docs: https://developer.atlassian.com/cloud/jira/service-desk/rest/
"""

import json
from collections.abc import Generator
from collections.abc import Iterator
from datetime import datetime
from datetime import timezone
from typing import Any

import requests
from typing_extensions import override

from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
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
            raise ConnectorMissingCredentialError(
                "JiraServiceManagement", 
                detail="At least one project key must be specified"
            )

        return None

    def _get_headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Authorization": f"Basic {base64.b64encode(f'{self.jira_email}:{self.jira_token}'.encode()).decode()}",
        }

    def _fetch_requests(self, project_key: str) -> list[dict[str, Any]]:
        """Fetch customer requests from a JSM project using the Service Desk API."""
        all_requests: list[dict[str, Any]] = []
        start = 0
        # First we need the service desk ID for the project
        sd_url = f"{self.jira_base_url}{_JSM_API_BASE}/servicedesk"
        try:
            resp = requests.get(sd_url, headers=self._get_headers(), timeout=30)
            resp.raise_for_status()
            desks = resp.json().get("values", [])
        except Exception as e:
            logger.warning(f"Failed to list service desks: {e}")
            return []

        # Find the service desk matching our project key
        service_desk_id = None
        for desk in desks:
            if desk.get("projectKey") == project_key:
                service_desk_id = desk["id"]
                break

        if not service_desk_id:
            logger.warning(f"No service desk found for project {project_key}")
            # Fall back to JQL-based search
            return self._fetch_via_jql(project_key)

        # Fetch requests from the service desk
        while True:
            req_url = (
                f"{self.jira_base_url}{_JSM_API_BASE}/servicedesk/{service_desk_id}/request"
                f"?start={start}&limit={_PAGE_SIZE}"
            )
            try:
                resp = requests.get(req_url, headers=self._get_headers(), timeout=30)
                resp.raise_for_status()
                data = resp.json()
                all_requests.extend(data.get("values", []))
                if data.get("isLastPage", True):
                    break
                start += _PAGE_SIZE
            except Exception as e:
                logger.warning(f"Failed to fetch requests for desk {service_desk_id}: {e}")
                break

        return all_requests

    def _fetch_via_jql(self, project_key: str) -> list[dict[str, Any]]:
        """Fallback: fetch JSM tickets via Jira JQL (they are still Jira issues)."""
        jql = f'project = "{project_key}" AND issuetype in standardIssueTypes()'
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

        status = fields.get("status", {}).get("name", "Unknown") if fields.get("status") else "Unknown"
        priority = fields.get("priority", {}).get("name", "None") if fields.get("priority") else "None"
        created = fields.get("created", "")
        updated = fields.get("updated", "")

        # Build document content
        content_parts = [
            f"# {key}: {summary}",
            f"Status: {status}",
            f"Priority: {priority}",
            "",
            desc_text,
        ]

        # Add comments if available
        comment_field = fields.get("comment", {})
        if isinstance(comment_field, dict):
            comments = comment_field.get("comments", [])
            if comments:
                content_parts.append("
## Comments")
                for comment in comments:
                    author = comment.get("author", {}).get("displayName", "Unknown")
                    body = comment.get("body", "")
                    if isinstance(body, dict):
                        body = self._extract_adf_text(body)
                    content_parts.append(f"
**{author}:** {body}")

        content = "
".join(content_parts)

        metadata = {
            "key": key,
            "project_key": project_key,
            "status": status,
            "priority": priority,
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
                texts.append("
")

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
        """Poll for updated documents within a time range."""
        from datetime import datetime, timezone
        
        start_dt = datetime.fromtimestamp(start, tz=timezone.utc)
        end_dt = datetime.fromtimestamp(end, tz=timezone.utc)

        if not self.project_keys:
            return

        for project_key in self.project_keys:
            logger.info(f"Polling JSM requests for project: {project_key}")
            all_requests = self._fetch_requests(project_key)
            batch: list[Document] = []
            for req_data in all_requests:
                fields = req_data.get("fields", {})
                updated_str = fields.get("updated", "")
                if updated_str:
                    try:
                        updated_dt = datetime.fromisoformat(updated_str.replace("Z", "+00:00"))
                        if start_dt <= updated_dt <= end_dt:
                            doc = self._build_document(req_data, project_key)
                            batch.append(doc)
                    except ValueError:
                        doc = self._build_document(req_data, project_key)
                        batch.append(doc)
                if len(batch) >= 10:
                    yield batch
                    batch = []
            if batch:
                yield batch
