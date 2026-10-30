"""Jira Service Management connector for Onyx.

Pulls all tickets (requests) from a configured Atlassian Jira Service Management
project via the JSM REST API and indexes them as Onyx documents. Implements the
standard Onyx Load / Poll / Slim connector interfaces so it works in bulk and
incremental (background polling) flows.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Generator
from urllib.parse import urljoin, quote

import requests

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import (
    GenerateDocumentsOutput,
    LoadConnector,
    PollConnector,
    SlimConnector,
)
from onyx.connectors.models import (
    ConnectorFailure,
    Document,
    DocumentFailure,
    SlimDocument,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

# JSM "request" status categories we map to a single indexed status string.
_JSM_PAGE_SIZE = 50
_RETRY_STATUSES = {429, 500, 502, 503, 504}


class JiraServiceManagementConnector(LoadConnector, PollConnector, SlimConnector):
    def __init__(
        self,
        base_url: str,
        project_key: str,
        batch_size: int = INDEX_BATCH_SIZE,
        request_jql: str | None = None,
    ) -> None:
        """base_url: e.g. https://yourcompany.atlassian.net
        project_key: the JSM project key, e.g. "SUPPORT"
        request_jql: optional extra JQL to further scope tickets.
        """
        self.base_url = base_url.rstrip("/")
        self.project_key = project_key
        self.batch_size = batch_size
        # Default JQL: all service requests in the project.
        self.request_jql = request_jql or f'project = "{project_key}"'

        self.email: str | None = None
        self.api_token: str | None = None
        self._session: requests.Session | None = None

    # ---- auth ---------------------------------------------------------
    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self.email = credentials["jira_user_email"]
        self.api_token = credentials["jira_api_token"]
        if not self.email or not self.api_token:
            raise ValueError("jira_user_email and jira_api_token are required")
        return None

    def _get_session(self) -> requests.Session:
        if self._session is None:
            s = requests.Session()
            s.auth = (self.email, self.api_token)
            s.headers.update({"Accept": "application/json"})
            self._session = s
        return self._session

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = urljoin(self.base_url + "/", path.lstrip("/"))
        last_err: Exception | None = None
        for attempt in range(4):
            try:
                resp = self._get_session().get(url, params=params, timeout=60)
                if resp.status_code in _RETRY_STATUSES:
                    time.sleep(min(2 ** attempt, 8))
                    continue
                resp.raise_for_status()
                return resp.json()
            except Exception as e:  # noqa: BLE001
                last_err = e
                time.sleep(min(2 ** attempt, 8))
        raise RuntimeError(f"JSM GET {url} failed after retries: {last_err}")

    def _search(self, jql: str, start_at: int, max_results: int) -> dict[str, Any]:
        # JSM uses the Jira Cloud search API scoped to service-desk request types.
        return self._get(
            "/rest/api/3/search",
            params={
                "jql": jql,
                "startAt": start_at,
                "maxResults": max_results,
                "fields": "summary,description,status,created,updated,reporter,assignee,priority,comment",
            },
        )

    # ---- document building -------------------------------------------
    @staticmethod
    def _adf_to_text(node: Any) -> str:
        """Flatten Atlassian Document Format (ADF) JSON into plain text."""
        if node is None:
            return ""
        if isinstance(node, str):
            return node
        if isinstance(node, list):
            return " ".join(JiraServiceManagementConnector._adf_to_text(n) for n in node)
        if isinstance(node, dict):
            if node.get("type") == "text":
                return node.get("text", "")
            parts = []
            if node.get("type") in ("paragraph", "heading", "listItem"):
                parts.append(JiraServiceManagementConnector._adf_to_text(node.get("content", [])))
                parts.append("\n")
            else:
                parts.append(JiraServiceManagementConnector._adf_to_text(node.get("content", [])))
            return "".join(parts)
        return ""

    def _issue_to_document(self, issue: dict[str, Any]) -> Document:
        fields = issue.get("fields", {})
        key = issue.get("key", "UNKNOWN")
        desc = self._adf_to_text(fields.get("description"))
        comments = fields.get("comment", {}).get("comments", []) or []
        comment_text = "\n".join(
            f"{c.get('author', {}).get('displayName', 'user')}: {self._adf_to_text(c.get('body'))}"
            for c in comments
        )
        full_text = (
            f"Summary: {fields.get('summary', '')}\n\n"
            f"Description:\n{desc}\n\n"
            f"Comments:\n{comment_text}"
        ).strip()
        status = (fields.get("status") or {}).get("name", "unknown")
        created = fields.get("created") or datetime.now(timezone.utc).isoformat()
        updated = fields.get("updated") or created
        return Document(
            id=key,
            sections=[{"link": f"{self.base_url}/browse/{key}", "text": full_text}],
            source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
            semantic_identifier=f"{key}: {fields.get('summary', '')}",
            metadata={
                "status": status,
                "priority": (fields.get("priority") or {}).get("name", ""),
                "created": created,
                "updated": updated,
                "project": self.project_key,
            },
            doc_updated_at=_parse_ts(updated),
        )

    # ---- flows --------------------------------------------------------
    def _yield_batches(
        self, jql: str
    ) -> GenerateDocumentsOutput:
        start = 0
        while True:
            data = self._search(jql, start, _JSM_PAGE_SIZE)
            issues = data.get("issues", [])
            docs: list[Document] = []
            for issue in issues:
                try:
                    docs.append(self._issue_to_document(issue))
                except Exception as e:  # noqa: BLE001
                    yield [], [DocumentFailure(document_id=issue.get("key", "?"), error=str(e))]
            if docs:
                # chunk into batch_size
                for i in range(0, len(docs), self.batch_size):
                    yield docs[i : i + self.batch_size], []
            total = data.get("total", 0)
            start += _JSM_PAGE_SIZE
            if start >= total or not issues:
                break

    def load_from_state(self) -> GenerateDocumentsOutput:
        yield from self._yield_batches(self.request_jql)

    def poll_source(
        self, start: float | None, end: float | None
    ) -> GenerateDocumentsOutput:
        if start is None or end is None:
            yield from self.load_from_state()
            return
        s = datetime.fromtimestamp(start, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        e = datetime.fromtimestamp(end, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        jql = f'{self.request_jql} AND updated >= "{s}" AND updated <= "{e}"'
        yield from self._yield_batches(jql)

    def retrieve_all_slim_documents(
        self, start: float | None = None, end: float | None = None
    ) -> Generator[list[SlimDocument], None, None]:
        jql = self.request_jql
        if start is not None and end is not None:
            s = datetime.fromtimestamp(start, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
            e = datetime.fromtimestamp(end, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
            jql = f'{self.request_jql} AND updated >= "{s}" AND updated <= "{e}"'
        start_at = 0
        while True:
            data = self._search(jql, start_at, _JSM_PAGE_SIZE)
            issues = data.get("issues", [])
            ids = [SlimDocument(id=i["key"]) for i in issues]
            if ids:
                yield ids
            start_at += _JSM_PAGE_SIZE
            if start_at >= data.get("total", 0) or not issues:
                break


def _parse_ts(ts: str) -> datetime:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:  # noqa: BLE001
        return datetime.now(timezone.utc)


if __name__ == "__main__":
    from onyx.utils.variable_functionality import set_is_ee_based_on_env_variable

    set_is_ee_based_on_env_variable()

    connector = JiraServiceManagementConnector(
        base_url=os.environ["JSM_BASE_URL"],
        project_key=os.environ["JSM_PROJECT_KEY"],
    )
    connector.load_credentials(
        {
            "jira_user_email": os.environ["JSM_EMAIL"],
            "jira_api_token": os.environ["JSM_API_TOKEN"],
        }
    )
    for batch, failures in connector.load_from_state():
        print(f"batch of {len(batch)}: {[d.id for d in batch]}")
        for f in failures:
            print("failure:", f)
