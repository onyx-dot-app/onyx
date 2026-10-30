"""Jira Service Management connector for Onyx.

Pulls all tickets (requests) from a configured Atlassian Jira Service Management
project via the JSM REST API and indexes them as Onyx documents. Implements the
standard Onyx Load / Poll / Slim connector interfaces so it works in bulk and
incremental (background polling) flows.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any, Iterator
from urllib.parse import urljoin

import requests

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import (
    GenerateDocumentsOutput,
    GenerateSlimDocumentOutput,
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
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger

logger = setup_logger()

_JSM_PAGE_SIZE = 50
_RETRY_STATUSES = {429, 500, 502, 503, 504}

# Atlassian Cloud project keys start with an uppercase letter and contain only
# uppercase ASCII letters and digits. Reject anything else before we interpolate
# it into JQL, otherwise a quote could break out of the quoted value.
_PROJECT_KEY_RE = re.compile(r"^[A-Z][A-Z0-9]*$")


def _validate_project_key(project_key: str) -> str:
    if not _PROJECT_KEY_RE.match(project_key or ""):
        raise ValueError(
            f"Invalid Jira project key {project_key!r}: must start with an "
            "uppercase letter and contain only uppercase letters and digits."
        )
    return project_key


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
        request_jql: optional extra JQL to further scope tickets. It is always
            AND-ed with the mandatory ``project = "<project_key>"`` constraint so
            it can never widen the search outside the configured project.
        """
        self.base_url = base_url.rstrip("/")
        self.project_key = _validate_project_key(project_key)
        self.batch_size = batch_size
        # Always enforce the project scope; append custom JQL as an extra
        # parenthesised filter so `OR` inside it cannot escape the project.
        project_clause = f'project = "{self.project_key}"'
        if request_jql:
            self.request_jql = f"{project_clause} AND ({request_jql})"
        else:
            self.request_jql = project_clause

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
        import time

        url = urljoin(self.base_url + "/", path.lstrip("/"))
        last_err: Exception | None = None
        for attempt in range(4):
            try:
                resp = self._get_session().get(url, params=params, timeout=60)
                if resp.status_code in _RETRY_STATUSES:
                    time.sleep(min(2**attempt, 8))
                    continue
                resp.raise_for_status()
                return resp.json()
            except Exception as e:  # noqa: BLE001
                last_err = e
                time.sleep(min(2**attempt, 8))
        raise RuntimeError(f"JSM GET {url} failed after retries: {last_err}")

    def _search(self, jql: str, next_page_token: str | None) -> dict[str, Any]:
        # Jira Cloud's supported search endpoint is /rest/api/3/search/jql, which
        # paginates via an opaque `nextPageToken` rather than startAt/total.
        params: dict[str, Any] = {
            "jql": jql,
            "maxResults": _JSM_PAGE_SIZE,
            "fields": "summary,description,status,created,updated,reporter,assignee,priority",
        }
        if next_page_token:
            params["nextPageToken"] = next_page_token
        return self._get("/rest/api/3/search/jql", params=params)

    def _get_comments(self, issue_key: str) -> list[dict[str, Any]]:
        """Fetch ALL comments for an issue, following pagination metadata."""
        comments: list[dict[str, Any]] = []
        path = f"/rest/api/3/issue/{issue_key}/comment"
        start_at = 0
        while True:
            data = self._get(
                path, params={"maxResults": _JSM_PAGE_SIZE, "startAt": start_at}
            )
            page = data.get("comments", []) or []
            comments.extend(page)
            total = data.get("total")
            if not page:
                break
            start_at += len(page)
            if total is not None and start_at >= total:
                break
        return comments

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
                parts.append(
                    JiraServiceManagementConnector._adf_to_text(node.get("content", []))
                )
                parts.append("\n")
            else:
                parts.append(
                    JiraServiceManagementConnector._adf_to_text(node.get("content", []))
                )
            return "".join(parts)
        return ""

    def _issue_to_document(self, issue: dict[str, Any]) -> Document:
        fields = issue.get("fields", {})
        key = issue.get("key", "UNKNOWN")
        desc = self._adf_to_text(fields.get("description"))
        # Comments live on a separate (paginated) endpoint, not in the search
        # payload, so fetch them explicitly and include every page.
        comments = self._get_comments(key)
        comment_text = "\n".join(
            f"{c.get('author', {}).get('displayName', 'user')}: "
            f"{self._adf_to_text(c.get('body'))}"
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
    def _yield_batches(self, jql: str) -> GenerateDocumentsOutput:
        """Yield batches of Document objects per the GenerateDocumentsOutput
        contract (an iterator of ``list[Document | HierarchyNode]``).

        Conversion errors cannot be represented in that stream, so they are
        logged and dropped rather than emitted as non-conforming tuples.
        """
        next_page_token: str | None = None
        while True:
            data = self._search(jql, next_page_token)
            issues = data.get("issues", []) or []
            docs: list[Document] = []
            for issue in issues:
                key = issue.get("key", "?")
                try:
                    docs.append(self._issue_to_document(issue))
                except Exception as e:  # noqa: BLE001
                    # Surface the failure without breaking the document stream.
                    failure = ConnectorFailure(
                        failed_document=DocumentFailure(
                            document_id=key,
                            document_link=f"{self.base_url}/browse/{key}",
                        ),
                        failure_message=str(e),
                        exception=e,
                    )
                    logger.warning(f"Skipping JSM issue {key}: {failure.failure_message}")
            for i in range(0, len(docs), self.batch_size):
                yield docs[i : i + self.batch_size]
            # Continue while a cursor exists, even if a page was empty
            # (Jira may return an empty page with a nextPageToken).
            next_page_token = data.get("nextPageToken")
            if not next_page_token:
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

    def retrieve_all_slim_docs(
        self,
        start: float | None = None,
        end: float | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        jql = self.request_jql
        if start is not None and end is not None:
            s = datetime.fromtimestamp(start, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
            e = datetime.fromtimestamp(end, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
            jql = f'{self.request_jql} AND updated >= "{s}" AND updated <= "{e}"'
        next_page_token: str | None = None
        while True:
            if callback is not None and callback.should_stop():
                logger.info("Slim retrieval stop requested; halting.")
                break
            data = self._search(jql, next_page_token)
            issues = data.get("issues", []) or []
            ids = [SlimDocument(id=i["key"]) for i in issues]
            if ids:
                yield ids
                if callback is not None:
                    callback.progress("jira_service_management", len(ids))
            # Use the presence of a cursor, not page emptiness, to continue.
            next_page_token = data.get("nextPageToken")
            if not next_page_token:
                break


def _parse_ts(ts: str) -> datetime:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:  # noqa: BLE001
        try:
            return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%f%z")
        except Exception:  # noqa: BLE001
            return datetime.now(timezone.utc)


if __name__ == "__main__":
    from onyx.utils.variable_functionality import (
        set_is_ee_based_on_env_variable,
    )

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
    for batch in connector.load_from_state():
        print(f"batch of {len(batch)}: {[d.id for d in batch]}")
