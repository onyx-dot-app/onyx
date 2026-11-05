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
from urllib.parse import urljoin, urlparse

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

_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]"}


def _validate_project_key(project_key: str) -> str:
    if not _PROJECT_KEY_RE.match(project_key or ""):
        raise ValueError(
            f"Invalid Jira project key {project_key!r}: must start with an "
            "uppercase letter and contain only uppercase letters and digits."
        )
    return project_key


def _is_loopback(host: str | None) -> bool:
    if not host:
        return False
    host = host.lower()
    if host in _LOOPBACK_HOSTS:
        return True
    # 127.0.0.0/8
    return host.startswith("127.")


def _validate_base_url(base_url: str) -> str:
    """Reject plaintext HTTP for non-loopback destinations.

    The connector authenticates every request with its email + API token, so an
    ``http://`` base URL would put those credentials on the wire in cleartext
    (CWE-319). Plaintext is allowed only for localhost/loopback development.
    """
    parsed = urlparse(base_url)
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
    project clause.
    """
    project_clause = f'project = "{project_key}"'
    user = (request_jql or "").strip()
    if not user:
        return project_clause
    return f"{project_clause} AND ({user})"


class JiraServiceManagementConnector(LoadConnector, PollConnector, SlimConnector):
    def __init__(
        self,
        base_url: str,
        project_key: str,
        batch_size: int = INDEX_BATCH_SIZE,
        request_jql: str | None = None,
    ) -> None:
        self.base_url = _validate_base_url(base_url)
        self.project_key = _validate_project_key(project_key)
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

    # ------------------------------------------------------------------ HTTP
    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = urljoin(self.base_url + "/", path.lstrip("/"))
        resp = self._session.get(url, params=params, timeout=60)
        if resp.status_code in _RETRY_STATUSES:
            logger.warning(
                "JSM API transient status %s for %s", resp.status_code, url
            )
        resp.raise_for_status()
        return resp.json()

    def _search(self, jql: str, next_page_token: str | None) -> dict[str, Any]:
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
            for child in node.get("content", []) or []:
                parts.append(self._flatten_adf(child))
            text = " ".join(p for p in parts if p).strip()
            return text
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
        key = issue["key"]
        fields = issue.get("fields", {}) or {}
        summary = fields.get("summary") or key

        text_parts: list[str] = [summary]
        body = self._flatten_adf(fields.get("description"))
        if body:
            text_parts.append(body)
        for comment in self._get_comments(key):
            author = (comment.get("author") or {}).get("displayName") or "Unknown"
            text = self._flatten_adf(comment.get("body"))
            if text:
                text_parts.append(f"{author}: {text}")

        link = f"{self.base_url}/browse/{key}"
        updated = fields.get("updated")
        doc_updated_at = None
        if updated:
            try:
                doc_updated_at = datetime.fromisoformat(
                    updated.replace("Z", "+00:00")
                )
            except ValueError:
                doc_updated_at = None

        return Document(
            id=key,
            sections=[{"link": link, "text": "\n\n".join(text_parts)}],
            source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
            semantic_identifier=summary,
            metadata={
                "project": self.project_key,
                "status": (fields.get("status") or {}).get("name", ""),
                "priority": (fields.get("priority") or {}).get("name", ""),
                "created": fields.get("created", ""),
            },
            doc_updated_at=doc_updated_at,
        )

    # ------------------------------------------------------------- Iteration
    def _yield_batches(self, jql: str) -> GenerateDocumentsOutput:
        """Yield ``list[Document]`` batches (GenerateDocumentsOutput contract).

        Conversion errors are logged via ConnectorFailure; they are never
        emitted as non-conforming tuples.
        """
        batch: list[Document] = []
        next_page_token: str | None = None
        seen_tokens: set[str] = set()
        while True:
            page = self._search(jql, next_page_token)
            for issue in page.get("issues", []) or []:
                try:
                    batch.append(self._issue_to_document(issue))
                except Exception as e:  # noqa: BLE001
                    logger.warning(
                        "Failed to convert issue %s: %s", issue.get("key"), e
                    )
                    yield [
                        ConnectorFailure(
                            failed_document=DocumentFailure(
                                document_id=str(issue.get("key", "")),
                                document_link=(
                                    f"{self.base_url}/browse/{issue.get('key', '')}"
                                ),
                            ),
                            failure_message=f"Failed to convert issue: {e}",
                            exception=e,
                        )
                    ]  # type: ignore[list-item]
                if len(batch) >= self.batch_size:
                    yield batch
                    batch = []
            nxt = page.get("nextPageToken")
            # Continue on cursor presence even for empty pages, but guard
            # against a repeated token causing an infinite loop.
            if not nxt or nxt in seen_tokens:
                break
            seen_tokens.add(nxt)
            next_page_token = nxt
        if batch:
            yield batch

    # ------------------------------------------------------------ Interfaces
    def load_from_state(self) -> GenerateDocumentsOutput:
        yield from self._yield_batches(self.request_jql)

    def poll_source(self, start: float, end: float) -> GenerateDocumentsOutput:
        start_dt = datetime.fromtimestamp(start, tz=timezone.utc)
        end_dt = datetime.fromtimestamp(end, tz=timezone.utc)
        time_filter = (
            f'updated >= "{start_dt.strftime("%Y-%m-%d %H:%M")}" '
            f'AND updated <= "{end_dt.strftime("%Y-%m-%d %H:%M")}"'
        )
        yield from self._yield_batches(f"{self.request_jql} AND {time_filter}")

    def retrieve_all_slim_docs(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        slim: list[SlimDocument] = []
        next_page_token: str | None = None
        seen_tokens: set[str] = set()
        while True:
            page = self._search(self.request_jql, next_page_token)
            for issue in page.get("issues", []) or []:
                slim.append(SlimDocument(id=str(issue.get("key"))))
            if callback is not None:
                if callback.should_stop():
                    logger.info("Slim indexing stop requested; halting early.")
                    break
                if slim:
                    callback.progress("jira_service_management", len(slim))
            nxt = page.get("nextPageToken")
            if not nxt or nxt in seen_tokens:
                break
            seen_tokens.add(nxt)
            next_page_token = nxt
            if slim:
                yield slim
                slim = []
        if slim:
            yield slim
