from datetime import datetime
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
from danswer.connectors.models import Document
from danswer.connectors.models import Section
from danswer.utils.logger import setup_logger

logger = setup_logger()


class JiraServiceManagementConnectorCredentials(BaseModel):
    jira_base_url: str
    jira_email: str
    jira_api_token: str
    jira_project_key: str


class JiraServiceManagementConnector(LoadConnector, PollConnector):
    def __init__(
        self,
        jira_base_url: str,
        jira_email: str,
        jira_api_token: str,
        jira_project_key: str,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        self.jira_base_url = jira_base_url.rstrip("/")
        self.jira_email = jira_email
        self.jira_api_token = jira_api_token
        self.jira_project_key = jira_project_key
        self.batch_size = batch_size

    def _get_auth(self) -> tuple[str, str]:
        return (self.jira_email, self.jira_api_token)

    def _fetch_tickets(
        self, start_at: int = 0, start: datetime | None = None
    ) -> dict[str, Any]:
        url = f"{self.jira_base_url}/rest/api/3/search"
        jql = f'project = "{self.jira_project_key}" ORDER BY created ASC'
        if start is not None:
            jql = (
                f'project = "{self.jira_project_key}" '
                f'AND updated >= "{start.strftime("%Y-%m-%d %H:%M")}" '
                f"ORDER BY created ASC"
            )

        params = {
            "jql": jql,
            "startAt": start_at,
            "maxResults": self.batch_size,
            "fields": "summary,description,status,priority,issuetype,created,updated,reporter,assignee,comment",
        }

        response = requests.get(
            url,
            params=params,
            auth=self._get_auth(),
            headers={"Accept": "application/json"},
            timeout=60,
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _extract_text_from_adf(node: Any) -> str:
        """Recursively extract plain text from Atlassian Document Format."""
        if node is None:
            return ""
        if isinstance(node, str):
            return node
        if isinstance(node, list):
            return " ".join(
                JiraServiceManagementConnector._extract_text_from_adf(item)
                for item in node
            )
        if isinstance(node, dict):
            if node.get("type") == "text":
                return node.get("text", "")
            if "content" in node:
                return JiraServiceManagementConnector._extract_text_from_adf(
                    node["content"]
                )
        return ""

    def _ticket_to_document(self, ticket: dict[str, Any]) -> Document:
        fields = ticket.get("fields", {})
        ticket_key = ticket.get("key", "")
        summary = fields.get("summary", "") or ""

        description = self._extract_text_from_adf(fields.get("description"))

        status = (fields.get("status") or {}).get("name", "")
        priority = (fields.get("priority") or {}).get("name", "")
        issue_type = (fields.get("issuetype") or {}).get("name", "")
        reporter = (fields.get("reporter") or {}).get("displayName", "")
        assignee = (fields.get("assignee") or {}).get("displayName", "")

        comments_text = ""
        comment_field = fields.get("comment") or {}
        for comment in comment_field.get("comments", []):
            author = (comment.get("author") or {}).get("displayName", "")
            body = self._extract_text_from_adf(comment.get("body"))
            comments_text += f"\n{author}: {body}"

        metadata: dict[str, str | list[str]] = {
            "project": self.jira_project_key,
            "status": status,
            "priority": priority,
            "issue_type": issue_type,
            "reporter": reporter,
            "assignee": assignee,
        }

        sections = [
            Section(link=f"{self.jira_base_url}/browse/{ticket_key}", text=summary),
        ]
        if description:
            sections.append(
                Section(
                    link=f"{self.jira_base_url}/browse/{ticket_key}",
                    text=description,
                )
            )
        if comments_text:
            sections.append(
                Section(
                    link=f"{self.jira_base_url}/browse/{ticket_key}",
                    text=comments_text.strip(),
                )
            )

        updated_at = fields.get("updated")
        if updated_at:
            metadata["updated"] = updated_at

        return Document(
            id=f"{self.jira_base_url}/browse/{ticket_key}",
            sections=sections,
            source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
            semantic_identifier=f"{ticket_key}: {summary}",
            metadata=metadata,
        )

    def _yield_documents(
        self, start: datetime | None = None
    ) -> Iterator[Document]:
        start_at = 0
        while True:
            data = self._fetch_tickets(start_at=start_at, start=start)
            tickets = data.get("issues", [])
            if not tickets:
                break

            for ticket in tickets:
                yield self._ticket_to_document(ticket)

            start_at += len(tickets)
            total = data.get("total", 0)
            if start_at >= total:
                break

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        parsed = JiraServiceManagementConnectorCredentials(**credentials)
        self.jira_base_url = parsed.jira_base_url.rstrip("/")
        self.jira_email = parsed.jira_email
        self.jira_api_token = parsed.jira_api_token
        self.jira_project_key = parsed.jira_project_key
        return None

    def load_from_state(self) -> GenerateDocumentsOutput:
        for doc in self._yield_documents():
            yield [doc]

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        start_datetime = datetime.fromtimestamp(start)
        for doc in self._yield_documents(start=start_datetime):
            yield [doc]
