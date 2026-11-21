from datetime import datetime
from datetime import timezone
from typing import Any
from typing import Iterator

import requests
from pydantic import BaseModel

from danswer.configs.app_configs import INDEX_BATCH_SIZE
from danswer.configs.constants import DocumentSource
from danswer.connectors.interfaces import GenerateDocumentsOutput
from danswer.connectors.interfaces import LoadConnector
from danswer.connectors.interfaces import PollConnector
from danswer.connectors.interfaces import SecondsSinceUnixEpoch
from danswer.connectors.models import ConnectorMissingCredentialError
from danswer.connectors.models import Document
from danswer.connectors.models import Section
from danswer.utils.logger import setup_logger

logger = setup_logger()


class JiraServiceManagementConnectorCredentials(BaseModel):
    jira_base_url: str
    jira_email: str
    jira_api_token: str
    jsm_project_key: str


class JiraServiceManagementConnector(LoadConnector, PollConnector):
    def __init__(
        self,
        jsm_project_key: str,
        jira_base_url: str,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        self.jsm_project_key = jsm_project_key
        self.jira_base_url = jira_base_url.rstrip("/")
        self.batch_size = batch_size
        self.jira_email: str | None = None
        self.jira_api_token: str | None = None

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        parsed = JiraServiceManagementConnectorCredentials(**credentials)
        self.jira_email = parsed.jira_email
        self.jira_api_token = parsed.jira_api_token
        self.jira_base_url = parsed.jira_base_url.rstrip("/")
        self.jsm_project_key = parsed.jsm_project_key
        return None

    def _get_auth(self) -> tuple[str, str]:
        if not self.jira_email or not self.jira_api_token:
            raise ConnectorMissingCredentialError("Jira Service Management")
        return (self.jira_email, self.jira_api_token)

    def _fetch_tickets(
        self, start: datetime | None = None, end: datetime | None = None
    ) -> Iterator[dict[str, Any]]:
        auth = self._get_auth()
        headers = {"Accept": "application/json"}

        jql_parts = [f'project = "{self.jsm_project_key}"']
        if start is not None:
            start_str = start.strftime("%Y-%m-%d %H:%M")
            jql_parts.append(f'updated >= "{start_str}"')
        if end is not None:
            end_str = end.strftime("%Y-%m-%d %H:%M")
            jql_parts.append(f'updated <= "{end_str}"')
        jql = " AND ".join(jql_parts) + " ORDER BY updated ASC"

        start_at = 0
        max_results = 50
        while True:
            url = f"{self.jira_base_url}/rest/api/3/search"
            params = {
                "jql": jql,
                "startAt": start_at,
                "maxResults": max_results,
                "fields": "summary,description,status,priority,reporter,assignee,"
                "created,updated,issuetype,comment,labels",
            }
            response = requests.get(
                url, headers=headers, params=params, auth=auth, timeout=60
            )
            response.raise_for_status()
            data = response.json()

            issues = data.get("issues", [])
            if not issues:
                break

            for issue in issues:
                yield issue

            start_at += len(issues)
            if start_at >= data.get("total", 0):
                break

    @staticmethod
    def _extract_text_from_adf(node: Any) -> str:
        """Recursively extract plain text from Atlassian Document Format."""
        if node is None:
            return ""
        if isinstance(node, str):
            return node
        if isinstance(node, list):
            return "".join(JiraServiceManagementConnector._extract_text_from_adf(n) for n in node)
        if isinstance(node, dict):
            node_type = node.get("type")
            if node_type == "text":
                return node.get("text", "")
            if node_type == "hardBreak":
                return "\n"
            if node_type == "paragraph":
                content = JiraServiceManagementConnector._extract_text_from_adf(
                    node.get("content", [])
                )
                return content + "\n"
            if node_type in ("bulletList", "orderedList"):
                items = []
                for item in node.get("content", []):
                    items.append(
                        JiraServiceManagementConnector._extract_text_from_adf(item)
                    )
                return "\n".join(items) + "\n"
            if node_type == "listItem":
                return "- " + JiraServiceManagementConnector._extract_text_from_adf(
                    node.get("content", [])
                )
            return JiraServiceManagementConnector._extract_text_from_adf(
                node.get("content", [])
            )
        return ""

    def _issue_to_document(self, issue: dict[str, Any]) -> Document | None:
        fields = issue.get("fields", {})
        issue_key = issue.get("key")
        if not issue_key:
            return None

        summary = fields.get("summary") or ""
        description_raw = fields.get("description")
        if isinstance(description_raw, dict):
            description = self._extract_text_from_adf(description_raw)
        else:
            description = description_raw or ""

        status = (fields.get("status") or {}).get("name", "")
        priority = (fields.get("priority") or {}).get("name", "")
        issue_type = (fields.get("issuetype") or {}).get("name", "")
        reporter = (fields.get("reporter") or {}).get("displayName", "")
        assignee = (fields.get("assignee") or {}).get("displayName", "")
        labels = fields.get("labels") or []

        comments_text_parts: list[str] = []
        comments = (fields.get("comment") or {}).get("comments", []) or []
        for comment in comments:
            author = (comment.get("author") or {}).get("displayName", "Unknown")
            body_raw = comment.get("body")
            if isinstance(body_raw, dict):
                body = self._extract_text_from_adf(body_raw)
            else:
                body = body_raw or ""
            comments_text_parts.append(f"{author}: {body}")

        sections: list[Section] = []
        header_lines = [
            f"Ticket: {issue_key}",
            f"Summary: {summary}",
            f"Type: {issue_type}",
            f"Status: {status}",
            f"Priority: {priority}",
            f"Reporter: {reporter}",
            f"Assignee: {assignee}",
        ]
        if labels:
            header_lines.append(f"Labels: {', '.join(labels)}")
        sections.append(Section(link=f"{self.jira_base_url}/browse/{issue_key}", text="\n".join(header_lines)))

        if description.strip():
            sections.append(
                Section(
                    link=f"{self.jira_base_url}/browse/{issue_key}",
                    text=f"Description:\n{description.strip()}",
                )
            )

        if comments_text_parts:
            sections.append(
                Section(
                    link=f"{self.jira_base_url}/browse/{issue_key}",
                    text="Comments:\n" + "\n\n".join(comments_text_parts),
                )
            )

        updated = fields.get("updated")
        semantic_identifier = f"{issue_key}: {summary}" if summary else issue_key

        return Document(
            id=f"jira-service-management-{issue_key}",
            sections=sections,
            source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
            semantic_identifier=semantic_identifier,
            metadata={
                "project": self.jsm_project_key,
                "issue_key": issue_key,
                "status": status,
                "priority": priority,
                "issue_type": issue_type,
                "updated": updated or "",
            },
        )

    def _yield_documents(
        self, start: datetime | None = None, end: datetime | None = None
    ) -> GenerateDocumentsOutput:
        batch: list[Document] = []
        for issue in self._fetch_tickets(start=start, end=end):
            doc = self._issue_to_document(issue)
            if doc is None:
                continue
            batch.append(doc)
            if len(batch) >= self.batch_size:
                yield batch
                batch = []
        if batch:
            yield batch

    def load_from_state(self) -> GenerateDocumentsOutput:
        return self._yield_documents()

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        start_dt = datetime.fromtimestamp(start, tz=timezone.utc)
        end_dt = datetime.fromtimestamp(end, tz=timezone.utc)
        return self._yield_documents(start=start_dt, end=end_dt)
