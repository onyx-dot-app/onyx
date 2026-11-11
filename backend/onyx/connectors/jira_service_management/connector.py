"""Jira Service Management (JSM) connector for Onyx.

Fetches service desk issues and comments from a Jira Service Management project
using the Jira Cloud `/rest/api/3/search/jql` token-paginated API and
`/rest/api/3/issue/{key}/comment`, with bounded HTTP 429/5xx retry backoff,
project key validation, epoch-millisecond JQL time filtering, configurable SLA
field extraction, and Onyx `LoadConnector` / `PollConnector` batch generation.
"""

from __future__ import annotations

import base64
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import re
import time
from typing import Any, TypedDict
import urllib.error
import urllib.parse
import urllib.request

try:
    from onyx.configs.constants import DocumentSource
    from onyx.connectors.interfaces import (
        GenerateDocumentsOutput,
        LoadConnector,
        PollConnector,
        SecondsSinceUnixEpoch,
    )
    from onyx.connectors.models import Document, HierarchyNode, TextSection

    _HAS_ONYX = True
except ImportError:  # pragma: no cover - standalone test fallback
    _HAS_ONYX = False
    SecondsSinceUnixEpoch = float  # type: ignore[misc]
    GenerateDocumentsOutput = Iterator[list[Any]]  # type: ignore[misc]

    class LoadConnector:  # type: ignore[no-redef]
        """Fallback LoadConnector base class when running outside Onyx."""

    class PollConnector:  # type: ignore[no-redef]
        """Fallback PollConnector base class when running outside Onyx."""


PROJECT_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


class JiraPayload(TypedDict, total=False):
    """Typed dictionary representing a JSON response payload from Jira REST APIs."""

    issues: list[dict[str, Any]]
    nextPageToken: str
    isLast: bool
    comments: list[dict[str, Any]]
    total: int
    startAt: int
    maxResults: int
    error: str


HttpTransport = Callable[[str, dict[str, str]], tuple[int, dict[str, Any]]]


@dataclass
class JSMDocument:
    """Normalized Onyx document payload for a Jira Service Management ticket."""

    id: str
    title: str
    text: str
    link: str
    updated_at: str
    metadata: dict[str, str] = field(default_factory=dict)

    def to_onyx_document(self) -> Any:
        """Convert this JSM ticket record into an Onyx `Document` instance if Onyx is available."""
        if not _HAS_ONYX:
            return self
        doc_updated_at: datetime | None = None
        if self.updated_at:
            try:
                doc_updated_at = datetime.fromisoformat(
                    self.updated_at.replace("Z", "+00:00")
                ).astimezone(timezone.utc)
            except ValueError:
                doc_updated_at = None
        return Document(
            id=self.id,
            sections=[TextSection(link=self.link, text=self.text)],
            source=DocumentSource.JIRA,
            semantic_identifier=f"{self.id}: {self.title}",
            title=self.title,
            doc_updated_at=doc_updated_at,
            metadata=self.metadata,
        )


class JiraServiceManagementConnector(LoadConnector, PollConnector):
    """Poll- and batch-capable Jira Service Management (JSM) connector."""

    def __init__(
        self,
        base_url: str = "",
        project_key: str = "ITSM",
        user_email: str = "",
        api_token: str = "",
        batch_size: int = 50,
        sla_custom_field_id: str = "customfield_10010",
        max_retries: int = 3,
        transport: HttpTransport | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        """Initialize the Jira Service Management connector and validate configuration."""
        self.base_url: str = base_url.rstrip("/")
        normalized_key = project_key.strip().upper()
        if not PROJECT_KEY_RE.match(normalized_key):
            raise ValueError(
                f"Invalid Jira project_key '{project_key}': must match ^[A-Z][A-Z0-9_]*$"
            )
        self.project_key: str = normalized_key
        self.user_email: str = user_email
        self.api_token: str = api_token
        self.batch_size: int = max(1, min(batch_size, 100))
        self.sla_custom_field_id: str = sla_custom_field_id
        self.max_retries: int = max(0, max_retries)
        self.sleep_fn: Callable[[float], None] = sleep_fn
        self.transport: HttpTransport = transport or self._default_transport

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        """Load Jira Service Management credentials from an Onyx credential dictionary."""
        if "jira_base_url" in credentials:
            self.base_url = str(credentials["jira_base_url"]).rstrip("/")
        if "jira_user_email" in credentials:
            self.user_email = str(credentials["jira_user_email"])
        if "jira_api_token" in credentials:
            self.api_token = str(credentials["jira_api_token"])
        return None

    def _headers(self) -> dict[str, str]:
        """Build HTTP request headers including Basic authentication when configured."""
        headers: dict[str, str] = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self.user_email and self.api_token:
            raw = f"{self.user_email}:{self.api_token}".encode("utf-8")
            headers["Authorization"] = f"Basic {base64.b64encode(raw).decode('ascii')}"
        return headers

    def _default_transport(
        self, url: str, headers: dict[str, str]
    ) -> tuple[int, dict[str, Any]]:
        """Execute an HTTP GET request with URL scheme validation and bounded 429/5xx retry backoff."""
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("https", "http") or not parsed.netloc:
            raise ValueError(f"Unsupported or invalid URL scheme in JSM request: {url}")

        attempt = 0
        while True:
            req = urllib.request.Request(url, headers=headers, method="GET")
            try:
                with urllib.request.urlopen(req, timeout=15.0) as resp:  # noqa: S310
                    return resp.status, json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                body = (
                    exc.read().decode("utf-8", errors="replace") if exc.fp else ""
                )
                if exc.code in (429, 500, 502, 503, 504) and attempt < self.max_retries:
                    retry_after_hdr = exc.headers.get("Retry-After") if exc.headers else None
                    delay = float(2**attempt)
                    if retry_after_hdr:
                        try:
                            delay = max(0.0, float(retry_after_hdr))
                        except ValueError:
                            pass
                    self.sleep_fn(delay)
                    attempt += 1
                    continue
                try:
                    return exc.code, json.loads(body)
                except Exception:
                    return exc.code, {"error": body[:200]}
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt < self.max_retries:
                    self.sleep_fn(float(2**attempt))
                    attempt += 1
                    continue
                return 503, {"error": str(exc)[:200]}

    def build_jql(
        self,
        start_timestamp: float | int | None = None,
        end_timestamp: float | int | None = None,
    ) -> str:
        """Build a project-scoped JQL query using epoch milliseconds for timezone-safe bounds."""
        clauses = [f'project = "{self.project_key}"']
        if start_timestamp is not None and start_timestamp > 0:
            start_ms = int(float(start_timestamp) * 1000)
            clauses.append(f"updated >= {start_ms}")
        if end_timestamp is not None and end_timestamp > 0:
            end_ms = int(float(end_timestamp) * 1000)
            clauses.append(f"updated <= {end_ms}")
        return " AND ".join(clauses) + " ORDER BY updated ASC"

    def iter_ticket_batches(
        self,
        start_timestamp: float | int | None = None,
        end_timestamp: float | int | None = None,
    ) -> Iterator[list[JSMDocument]]:
        """Yield pages of JSM tickets using `/rest/api/3/search/jql` and `nextPageToken` pagination."""
        next_page_token: str | None = None
        jql = self.build_jql(start_timestamp, end_timestamp)
        fields = f"summary,description,comment,status,priority,issuetype,reporter,updated,{self.sla_custom_field_id}"

        while True:
            query_params: dict[str, str | int] = {
                "jql": jql,
                "maxResults": self.batch_size,
                "fields": fields,
            }
            if next_page_token:
                query_params["nextPageToken"] = next_page_token

            params = urllib.parse.urlencode(query_params)
            url = f"{self.base_url}/rest/api/3/search/jql?{params}"
            status_code, payload = self.transport(url, self._headers())
            if status_code != 200:
                raise RuntimeError(f"JSM API error HTTP {status_code}: {payload}")

            token_val = payload.get("nextPageToken")
            is_last = bool(payload.get("isLast", False))
            if not is_last and next_page_token is not None and token_val == next_page_token:
                raise RuntimeError(
                    f"Infinite JSM pagination loop detected with unchanged nextPageToken: {token_val}"
                )

            raw_issues = payload.get("issues")
            issues = raw_issues if isinstance(raw_issues, list) else []
            batch = [
                self._parse_issue(issue)
                for issue in issues
                if isinstance(issue, dict)
            ]
            if batch:
                yield batch

            if is_last or not isinstance(token_val, str) or not token_val:
                break
            next_page_token = token_val

    def fetch_tickets(
        self,
        start_timestamp: float | int | None = None,
        end_timestamp: float | int | None = None,
    ) -> list[JSMDocument]:
        """Return all matching JSM tickets across all paginated search batches."""
        return [
            doc
            for batch in self.iter_ticket_batches(start_timestamp, end_timestamp)
            for doc in batch
        ]

    def load_from_state(self) -> GenerateDocumentsOutput:
        """Yield full batches of Onyx `Document` objects for the configured JSM project."""
        for batch in self.iter_ticket_batches():
            yield [doc.to_onyx_document() for doc in batch]

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        """Yield incremental batches of Onyx `Document` objects updated between `start` and `end`."""
        for batch in self.iter_ticket_batches(
            start_timestamp=start, end_timestamp=end
        ):
            yield [doc.to_onyx_document() for doc in batch]

    def _fetch_all_comments(
        self, issue_key: str, comment_field: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Return all comments for an issue, paginating `/rest/api/3/issue/{key}/comment` when truncated."""
        initial_raw = comment_field.get("comments")
        comments: list[dict[str, Any]] = [
            c for c in (initial_raw if isinstance(initial_raw, list) else []) if isinstance(c, dict)
        ]
        total_raw = comment_field.get("total")
        total = int(total_raw) if isinstance(total_raw, int) else len(comments)
        start_at = len(comments)

        while start_at < total and issue_key:
            params = urllib.parse.urlencode(
                {"startAt": start_at, "maxResults": self.batch_size}
            )
            url = f"{self.base_url}/rest/api/3/issue/{urllib.parse.quote(issue_key)}/comment?{params}"
            status_code, payload = self.transport(url, self._headers())
            if status_code != 200:
                raise RuntimeError(
                    f"JSM comment fetch failed for {issue_key}: HTTP {status_code}"
                )
            page_raw = payload.get("comments")
            page = [
                c
                for c in (page_raw if isinstance(page_raw, list) else [])
                if isinstance(c, dict)
            ]
            if not page:
                break
            comments.extend(page)
            start_at += len(page)

        return comments

    def _parse_issue(self, issue: dict[str, Any]) -> JSMDocument:
        """Transform a raw Jira Service Management issue dictionary into a `JSMDocument`."""
        key = str(issue.get("key") or "")
        raw_fields = issue.get("fields")
        fields = raw_fields if isinstance(raw_fields, dict) else {}
        summary = str(fields.get("summary") or "")
        desc = self._extract_text(fields.get("description"))

        raw_comment_field = fields.get("comment")
        comment_field = raw_comment_field if isinstance(raw_comment_field, dict) else {}
        comments_list = self._fetch_all_comments(key, comment_field)

        comment_lines: list[str] = []
        for comment_obj in comments_list:
            raw_author = comment_obj.get("author")
            author_dict = raw_author if isinstance(raw_author, dict) else {}
            author_name = str(author_dict.get("displayName") or "user")
            body_text = self._extract_text(comment_obj.get("body"))
            comment_lines.append(f"[{author_name}]: {body_text}")
        comments_text = "\n".join(comment_lines)

        raw_status = fields.get("status")
        status_dict = raw_status if isinstance(raw_status, dict) else {}
        status = str(status_dict.get("name") or "Open")

        raw_priority = fields.get("priority")
        priority_dict = raw_priority if isinstance(raw_priority, dict) else {}
        priority = str(priority_dict.get("name") or "Medium")

        raw_issue_type = fields.get("issuetype")
        issue_type_dict = raw_issue_type if isinstance(raw_issue_type, dict) else {}
        issue_type = str(issue_type_dict.get("name") or "Service Request")

        raw_reporter = fields.get("reporter")
        reporter_dict = raw_reporter if isinstance(raw_reporter, dict) else {}
        reporter = str(reporter_dict.get("displayName") or "Customer")

        updated = str(fields.get("updated") or "")
        raw_sla = fields.get(self.sla_custom_field_id)
        sla_field = raw_sla if isinstance(raw_sla, dict) else {}
        raw_cycle = sla_field.get("ongoingCycle")
        cycle_dict = raw_cycle if isinstance(raw_cycle, dict) else {}
        sla_breached = bool(cycle_dict.get("breached", False))

        full_text = f"[{key}] {summary}\nStatus: {status} | Priority: {priority} | Type: {issue_type}\n\n{desc}"
        if comments_text:
            full_text += f"\n\n--- Comments ---\n{comments_text}"

        return JSMDocument(
            id=f"jsm:{key}",
            title=f"{key}: {summary}",
            text=full_text.strip(),
            link=f"{self.base_url}/browse/{key}",
            updated_at=updated,
            metadata={
                "project": self.project_key,
                "status": status,
                "priority": priority,
                "issue_type": issue_type,
                "reporter": reporter,
                "sla_breached": str(sla_breached).lower(),
            },
        )

    @classmethod
    def _extract_text(cls, node: Any) -> str:
        """Extract plain text from Atlassian Document Format (ADF) structures or plain strings."""
        if node is None:
            return ""
        if isinstance(node, str):
            return node
        if isinstance(node, dict):
            if node.get("type") == "text":
                return str(node.get("text") or "")
            children = node.get("content")
            if isinstance(children, list):
                return " ".join(
                    filter(None, (cls._extract_text(c) for c in children))
                ).strip()
            return ""
        if isinstance(node, list):
            return " ".join(
                filter(None, (cls._extract_text(c) for c in node))
            ).strip()
        return str(node)
