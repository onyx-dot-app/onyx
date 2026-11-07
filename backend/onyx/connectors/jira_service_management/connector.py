from collections.abc import Generator
from datetime import datetime, timezone
from typing import Any
import requests
from requests.auth import HTTPBasicAuth

from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import GenerateDocumentsOutput, LoadConnector, PollConnector, SecondsSinceUnixEpoch
from onyx.connectors.models import ConnectorMissingCredentialError, Document, Section


class JSMConnector(LoadConnector, PollConnector):
    def __init__(self, base_url: str, project_key: str, batch_size: int = 50) -> None:
        self.base_url = base_url.rstrip("/")
        self.project_key = project_key
        self.batch_size = batch_size
        self.auth: HTTPBasicAuth | None = None

    def load_credentials(self, credentials: dict[str, Any]) -> None:
        email = credentials.get("jsm_user_email")
        token = credentials.get("jsm_api_token")
        if not email or not token:
            raise ConnectorMissingCredentialError("Jira Service Management requires jsm_user_email and jsm_api_token")
        self.auth = HTTPBasicAuth(email, token)

    def _fetch_issues(self, jql: str) -> Generator[list[dict[str, Any]], None, None]:
        if self.auth is None:
            raise ConnectorMissingCredentialError("Credentials not loaded")
        start_at = 0
        while True:
            resp = requests.get(
                f"{self.base_url}/rest/api/3/search",
                params={"jql": jql, "startAt": start_at, "maxResults": self.batch_size, "fields": "summary,description,comment,updated,status,reporter,assignee"},
                auth=self.auth,
                headers={"Accept": "application/json"},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            issues = data.get("issues", [])
            if not issues:
                break
            yield issues
            start_at += len(issues)
            if start_at >= data.get("total", 0):
                break

    def _issue_to_doc(self, issue: dict[str, Any]) -> Document:
        key = issue["key"]
        fields = issue.get("fields", {})
        summary = fields.get("summary") or key
        desc = str(fields.get("description") or "")
        comments = [
            str(c.get("body") or "")
            for c in (fields.get("comment", {}) or {}).get("comments", [])
        ]
        full_text = "\n\n".join(filter(None, [summary, desc, *comments]))
        updated_str = fields.get("updated")
        doc_updated_at = (
            datetime.strptime(updated_str, "%Y-%m-%dT%H:%M:%S.%f%z").astimezone(timezone.utc)
            if updated_str
            else None
        )
        link = f"{self.base_url}/browse/{key}"
        return Document(
            id=f"jsm:{key}",
            sections=[Section(link=link, text=full_text)],
            source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
            semantic_identifier=f"{key}: {summary}",
            doc_updated_at=doc_updated_at,
            metadata={"project_key": self.project_key, "status": (fields.get("status") or {}).get("name", "")},
        )

    def load_from_state(self) -> GenerateDocumentsOutput:
        jql = f'project = "{self.project_key}" ORDER BY updated ASC'
        for batch in self._fetch_issues(jql):
            yield [self._issue_to_doc(issue) for issue in batch]

    def poll_source(self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch) -> GenerateDocumentsOutput:
        start_str = datetime.fromtimestamp(start, tz=timezone.utc).strftime("%Y/%m/%d %H:%M")
        end_str = datetime.fromtimestamp(end, tz=timezone.utc).strftime("%Y/%m/%d %H:%M")
        jql = f'project = "{self.project_key}" AND updated >= "{start_str}" AND updated <= "{end_str}" ORDER BY updated ASC'
        for batch in self._fetch_issues(jql):
            yield [self._issue_to_doc(issue) for issue in batch]
