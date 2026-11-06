"""Jira Service Management connector for Onyx.

Pulls all tickets (requests) from a configured Atlassian Jira Service Management
project via the JSM REST API and indexes them as Onyx documents. Implements the
standard Onyx Load / Poll / Slim connector interfaces so it works in bulk and
incremental (background polling) flows.
"""

from __future__ import annotations

import ipaddress
import os
from datetime import datetime
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import (
    GenerateDocumentsOutput,
    GenerateSlimDocumentOutput,
    LoadConnector,
    PollConnector,
    SecondsSinceUnixEpoch,
    SlimConnector,
)
from onyx.connectors.jira_service_management.config import (
    has_balanced_parentheses,
    validate_project_key,
)
from onyx.connectors.models import (
    Document,
    SlimDocument,
    TextSection,
)
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger

logger = setup_logger()

_JSM_PAGE_SIZE = 50
_RETRY_STATUSES = [429, 500, 502, 503, 504]

_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]"}


def _is_loopback(host: str | None) -> bool:
    """Return True if host resolves to a local loopback IP or hostname."""
    if not host:
        return False
    host = host.lower().strip("[]")
    if host in _LOOPBACK_HOSTS:
        return True
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_loopback
    except ValueError:
        return False


def _validate_base_url(base_url: str) -> str:
    """Reject plaintext HTTP for non-loopback destinations and embedded credentials.

    The connector authenticates every request with its email + API token, so an
    ``http://`` base URL would put those credentials on the wire in cleartext
    (CWE-319). Plaintext is allowed only for localhost/loopback development.
    Embedded userinfo in the URL is also disallowed to prevent credential leakage.
    """
    parsed = urlparse(base_url)
    if parsed.username or parsed.password:
        raise ValueError(
            "Invalid Jira base_url: embedded credentials (userinfo) are not permitted; remove the user:password portion from the URL."
        )
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        raise ValueError(
            f"Invalid Jira base_url {base_url!r}: scheme must be http or https."
        )
    if scheme == "http" and not _is_loopback(parsed.hostname):
        raise ValueError(
            f"Insecure Jira base_url {base_url!r}: HTTPS is required for "
            "non-loopback hosts so credentials are never sent in plaintext."
        )
    return base_url.rstrip("/")


def _and_scope(project_key: str, request_jql: str | None) -> str:
    """Always AND the mandatory project scope in front of any user JQL.

    The user query is parenthesised so a top-level ``OR`` cannot escape the
    project clause. Unbalanced parentheses are rejected to prevent JQL breakout.
    """
    project_clause = f'project = "{project_key}"'
    user = (request_jql or "").strip()
    if not user:
        return project_clause
    if not has_balanced_parentheses(user):
        raise ValueError("Invalid request_jql: unbalanced parentheses detected.")
    return f"{project_clause} AND ({user})"


class JiraServiceManagementConnector(LoadConnector, PollConnector, SlimConnector):
    def __init__(
        self,
        base_url: str,
        project_key: str,
        batch_size: int = INDEX_BATCH_SIZE,
        request_jql: str | None = None,
    ) -> None:
        """Initialize the Jira Service Management connector with scoped configuration."""
        self.base_url = _validate_base_url(base_url)
        self.project_key = validate_project_key(project_key)
        self.batch_size = batch_size
        self.request_jql = _and_scope(self.project_key, request_jql)

        self.email = os.environ.get("JSM_EMAIL")
        self.api_token = os.environ.get("JSM_API_TOKEN")
        self._session = requests.Session()
        if self.email and self.api_token:
            self._session.auth = (self.email, self.api_token)
        self._session.headers.update(
            {"Accept": "application/json", "Content-Type": "application/json"}
        )

        retry_strategy = Retry(
            total=5,
            backoff_factor=1,
            status_forcelist=_RETRY_STATUSES,
            respect_retry_after_header=True,
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        """Load API email and token credentials and bind them to the session auth."""
        self.email = (
            credentials.get("jsm_email") or credentials.get("email") or self.email
        )
        self.api_token = (
            credentials.get("jsm_api_token")
            or credentials.get("api_token")
            or self.api_token
        )
        if self.email and self.api_token:
            self._session.auth = (self.email, self.api_token)
        return None

    # ------------------------------------------------------------------ HTTP
    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Send a GET request to the Jira REST API with retry handling and detailed error logging."""
        url = urljoin(self.base_url + "/", path.lstrip("/"))
        resp = self._session.get(url, params=params, timeout=60)
        if not resp.ok:
            error_body = resp.text[:1000]
            logger.error(
                "JSM API error %s for %s: %s", resp.status_code, url, error_body
            )
            try:
                resp.raise_for_status()
            except requests.HTTPError as e:
                raise requests.HTTPError(
                    f"{e} - Response body: {error_body}", response=resp
                ) from e
        return resp.json()

    def _search(self, jql: str, next_page_token: str | None) -> dict[str, Any]:
        """Execute a paginated JQL search via Jira Cloud REST API v3."""
        params: dict[str, Any] = {
            "jql": jql,
            "maxResults": _JSM_PAGE_SIZE,
            "fields": "summary,description,status,priority,created,updated,reporter",
        }
        if next_page_token:
            params["nextPageToken"] = next_page_token
        return self._get("/rest/api/3/search/jql", params=params)

    # --------------------------------------------------------------- Convert
    def _flatten_adf(self, node: Any) -> str:
        """Flatten an Atlassian Document Format tree to plain text."""
        if node is None:
            return ""
        if isinstance(node, str):
            return node
        if isinstance(node, list):
            return "\n".join(self._flatten_adf(n) for n in node).strip()
        if isinstance(node, dict):
            parts: list[str] = []
            if node.get("type") == "text" and "text" in node:
                parts.append(str(node["text"]))
            parts.extend(
                self._flatten_adf(child) for child in node.get("content", []) or []
            )
            return "\n".join(p for p in parts if p).strip()
        return ""

    def _get_comments(self, issue_key: str) -> list[dict[str, Any]]:
        """Fetch all comments, following startAt until ``total`` is exhausted."""
        collected: list[dict[str, Any]] = []
        start_at = 0
        while True:
            page = self._get(
                f"/rest/api/3/issue/{issue_key}/comment",
                params={"startAt": start_at, "maxResults": _JSM_PAGE_SIZE},
            )
            batch = page.get("comments", []) or []
            collected.extend(batch)
            start_at += len(batch)
            total = page.get("total", start_at)
            if not batch or start_at >= total:
                break
        return collected

    def _issue_to_document(self, issue: dict[str, Any]) -> Document:
        """Convert a Jira issue dictionary into a searchable Onyx Document."""
        key = str(issue["key"])
        fields = issue.get("fields") or {}
        summary = str(fields.get("summary") or "")

        text_parts: list[str] = []
        if summary:
            text_parts.append(f"Summary: {summary}")

        description = self._flatten_adf(fields.get("description"))
        if description:
            text_parts.append(f"Description:\n{description}")

        comments = self._get_comments(key)
        for comment in comments:
            author = (comment.get("author") or {}).get("displayName") or "Unknown"
            text = self._flatten_adf(comment.get("body"))
            if text:
                text_parts.append(f"{author}: {text}")

        link = f"{self.base_url}/browse/{key}"
        updated = fields.get("updated")
        doc_updated_at = None
        if updated:
            try:
                doc_updated_at = datetime.fromisoformat(updated)
            except ValueError:
                doc_updated_at = None

        return Document(
            id=link,
            sections=[TextSection(text="\n\n".join(text_parts), link=link)],
            source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
            semantic_identifier=summary,
            metadata={
                "project": self.project_key,
                "key": key,
                "status": (fields.get("status") or {}).get("name", ""),
                "priority": (fields.get("priority") or {}).get("name", ""),
                "created": fields.get("created", ""),
            },
            doc_updated_at=doc_updated_at,
        )

    # ------------------------------------------------------------- Iteration
    def _yield_batches(self, jql: str) -> GenerateDocumentsOutput:
        """Yield ``list[Document]`` batches (GenerateDocumentsOutput contract)."""
        batch: list[Document] = []
        next_page_token: str | None = None
        seen_tokens: set[str] = set()
        while True:
            page = self._search(jql, next_page_token)
            for issue in page.get("issues", []) or []:
                try:
                    batch.append(self._issue_to_document(issue))
                except requests.exceptions.JSONDecodeError:
                    raise
                except (KeyError, TypeError, ValueError) as e:
                    logger.warning(
                        "Failed to convert issue %s: %s", issue.get("key"), e
                    )
                    continue
                if len(batch) >= self.batch_size:
                    yield batch
                    batch = []
            nxt = page.get("nextPageToken")
            if not nxt:
                break
            if nxt in seen_tokens:
                raise RuntimeError(
                    f"Detected cycle in pagination cursor: token {nxt!r} was already seen."
                )
            seen_tokens.add(nxt)
            next_page_token = nxt
        if batch:
            yield batch

    # ------------------------------------------------------------ Interfaces
    def load_from_state(self) -> GenerateDocumentsOutput:
        """Bulk load all documents within the configured project scope."""
        yield from self._yield_batches(self.request_jql)

    def poll_source(self, start: float, end: float) -> GenerateDocumentsOutput:
        """Incrementally pull documents modified within the given epoch timestamp range."""
        time_filter = f"updated >= {int(start * 1000)} AND updated <= {int(end * 1000)}"
        yield from self._yield_batches(f"{self.request_jql} AND {time_filter}")

    def retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        end: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        """Retrieve all document IDs for deletion sync, notifying heartbeat callbacks."""
        # Full project listing is intentional: Jira Cloud nextPageToken cursor
        # pagination provides all project keys for deletion sync.
        slim: list[SlimDocument] = []
        next_page_token: str | None = None
        seen_tokens: set[str] = set()
        while True:
            page = self._search(self.request_jql, next_page_token)
            slim.extend(
                SlimDocument(id=f"{self.base_url}/browse/{issue.get('key')}")
                for issue in page.get("issues", []) or []
            )
            if callback is not None:
                if callback.should_stop():
                    logger.info("Slim indexing stop requested; halting early.")
                    raise RuntimeError(
                        "Jira Service Management slim retrieval: stop signal detected"
                    )
                if slim:
                    callback.progress("jira_service_management", len(slim))
            nxt = page.get("nextPageToken")
            if not nxt:
                break
            if nxt in seen_tokens:
                raise RuntimeError(
                    f"Detected cycle in pagination cursor: token {nxt!r} was already seen."
                )
            seen_tokens.add(nxt)
            next_page_token = nxt
            if slim:
                yield slim
                slim = []
        if slim:
            yield slim
