from datetime import datetime, timezone
from typing import Any, Generator
import requests

from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import (
    CheckpointedConnector,
    ConnectorCheckpoint,
    GenerateDocumentsOutput,
    SecondsSinceUnixEpoch,
)
from onyx.connectors.models import ConnectorFailure, Document, TextSection, BasicExpertInfo


class JSMConnectorCheckpoint(ConnectorCheckpoint):
    start_offset: int = 0


class JiraServiceManagementConnector(CheckpointedConnector[JSMConnectorCheckpoint]):
    """Connector for Atlassian Jira Service Management (JSM) REST API (`/rest/servicedeskapi` & `/rest/api/3/search`)."""

    def __init__(
        self,
        base_url: str,
        project_key: str = "",
        service_desk_id: str = "",
        batch_size: int = 50,
        include_comments: bool = True,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.project_key = project_key.strip()
        self.service_desk_id = service_desk_id.strip()
        self.batch_size = batch_size
        self.include_comments = include_comments
        self._email: str = ""
        self._api_token: str = ""

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self._email = str(credentials.get("jira_user_email") or credentials.get("jsm_user_email") or "").strip()
        self._api_token = str(credentials.get("jira_api_token") or credentials.get("jsm_api_token") or "").strip()
        return None

    def build_dummy_checkpoint(self) -> JSMConnectorCheckpoint:
        return JSMConnectorCheckpoint(has_more=True, start_offset=0)

    def validate_connector_settings(self) -> None:
        if not self.base_url:
            raise ValueError("Jira Service Management base_url is required.")
        resp = requests.get(
            f"{self.base_url}/rest/servicedeskapi/info",
            auth=(self._email, self._api_token),
            headers={"Accept": "application/json"},
            timeout=15,
        )
        resp.raise_for_status()

    def _build_jql(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> str:
        clauses: list[str] = []
        if self.project_key:
            clauses.append(f'project = "{self.project_key}"')
        if start is not None:
            dt_start = datetime.fromtimestamp(start, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
            clauses.append(f'updated >= "{dt_start}"')
        if end is not None:
            dt_end = datetime.fromtimestamp(end, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
            clauses.append(f'updated <= "{dt_end}"')
        where = " AND ".join(clauses)
        return f"{where} ORDER BY updated ASC" if where else "ORDER BY updated ASC"

    def _issue_to_document(self, issue: dict[str, Any]) -> Document:
        key = str(issue.get("key") or issue.get("id") or "UNKNOWN")
        fields = issue.get("fields") or {}
        summary = str(fields.get("summary") or key)
        description = fields.get("description") or ""
        if isinstance(description, dict):
            description = self._extract_adf_text(description)
        status_name = str((fields.get("status") or {}).get("name") or "")
        priority_name = str((fields.get("priority") or {}).get("name") or "")
        req_type = str(((fields.get("customfield_10010") or {}).get("requestType") or {}).get("name") or "Service Request")

        body_parts = [
            f"Ticket: {key} - {summary}",
            f"Status: {status_name} | Priority: {priority_name} | Request Type: {req_type}",
            f"Description:
{description}",
        ]
        if self.include_comments:
            comments = ((fields.get("comment") or {}).get("comments")) or []
            for c in comments:
                c_body = c.get("body") or ""
                if isinstance(c_body, dict):
                    c_body = self._extract_adf_text(c_body)
                author = ((c.get("author") or {}).get("displayName")) or "Agent"
                body_parts.append(f"Comment ({author}): {c_body}")

        full_text = "

".join(p for p in body_parts if p.strip())
        link = f"{self.base_url}/browse/{key}"
        reporter = fields.get("reporter") or {}
        owners = (
            [BasicExpertInfo(display_name=reporter.get("displayName"), email=reporter.get("emailAddress"))]
            if reporter
            else None
        )
        updated_str = fields.get("updated")
        doc_updated_at = None
        if isinstance(updated_str, str):
            try:
                doc_updated_at = datetime.fromisoformat(updated_str.replace("Z", "+00:00"))
            except ValueError:
                pass

        return Document(
            id=f"jsm:{key}",
            sections=[TextSection(link=link, text=full_text)],
            source=DocumentSource.JIRA,
            semantic_identifier=f"{key}: {summary}",
            doc_updated_at=doc_updated_at,
            primary_owners=owners,
            metadata={
                "ticket_key": key,
                "status": status_name,
                "priority": priority_name,
                "request_type": req_type,
                "project_key": self.project_key,
            },
        )

    @classmethod
    def _extract_adf_text(cls, node: dict[str, Any]) -> str:
        texts: list[str] = []
        if node.get("type") == "text" and "text" in node:
            texts.append(str(node["text"]))
        for child in node.get("content") or []:
            if isinstance(child, dict):
                texts.append(cls._extract_adf_text(child))
        return " ".join(t for t in texts if t).strip()

    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: JSMConnectorCheckpoint,
    ) -> GenerateDocumentsOutput:
        jql = self._build_jql(start=start, end=end)
        resp = requests.get(
            f"{self.base_url}/rest/api/3/search",
            params={
                "jql": jql,
                "startAt": checkpoint.start_offset,
                "maxResults": self.batch_size,
                "fields": "summary,description,status,priority,comment,reporter,updated,customfield_10010",
            },
            auth=(self._email, self._api_token),
            headers={"Accept": "application/json"},
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
        issues = payload.get("issues") or []
        total = int(payload.get("total") or 0)

        for issue in issues:
            try:
                yield self._issue_to_document(issue)
            except Exception as e:
                yield ConnectorFailure(
                    failed_document=None,
                    failure_message=f"Failed to parse JSM ticket {issue.get('key')}: {e}",
                )

        next_offset = checkpoint.start_offset + len(issues)
        has_more = next_offset < total and len(issues) > 0
        return JSMConnectorCheckpoint(has_more=has_more, start_offset=next_offset)
