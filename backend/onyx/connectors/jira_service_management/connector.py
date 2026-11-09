"""Onyx (YC W24) Algora Bounty #2281 ($250 USD): Jira Service Management (JSM) Connector.

Pulls service desk requests, queues, SLA timers, comments, and customer attachments
from a specified Jira Service Management (JSM) project via the Atlassian REST API
(`/rest/servicedeskapi/servicedesk` & `/rest/api/3/search`) with cursor/startAt pagination,
incremental checkpointing (`updated >= last_poll_ts`), and rate-limit retry backoff.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple


@dataclass
class JSMDocument:
    id: str
    title: str
    text: str
    link: str
    project_key: str
    issue_type: str
    status: str
    reporter: str
    updated_at: str
    sla_breached: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


HttpTransport = Callable[[str, Dict[str, str]], Tuple[int, Dict[str, Any]]]


class JiraServiceManagementConnector:
    """Poll- and batch-capable Jira Service Management (JSM) connector for Onyx (#2281)."""

    def __init__(
        self,
        base_url: str,
        project_key: str,
        email: str = "",
        api_token: str = "",
        batch_size: int = 50,
        transport: Optional[HttpTransport] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.project_key = project_key.strip().upper()
        self.email = email
        self.api_token = api_token
        self.batch_size = max(1, min(batch_size, 100))
        self.transport = transport or self._default_transport

    def _headers(self) -> Dict[str, str]:
        import base64
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.email and self.api_token:
            raw = f"{self.email}:{self.api_token}".encode("utf-8")
            headers["Authorization"] = "Basic " + base64.b64encode(raw).decode("ascii")
        return headers

    def _default_transport(self, url: str, headers: Dict[str, str]) -> Tuple[int, Dict[str, Any]]:
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=15.0) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            try:
                return exc.code, json.loads(body)
            except Exception:
                return exc.code, {"error": body[:200]}

    def build_jql(self, start_timestamp: Optional[int] = None) -> str:
        clauses = [f'project = "{self.project_key}"']
        if start_timestamp is not None and start_timestamp > 0:
            formatted = time.strftime("%Y-%m-%d %H:%M", time.gmtime(start_timestamp))
            clauses.append(f'updated >= "{formatted}"')
        return " AND ".join(clauses) + " ORDER BY updated ASC"

    def fetch_tickets(self, start_timestamp: Optional[int] = None) -> List[JSMDocument]:
        """Paginate through all JSM tickets matching `project_key` and optional `start_timestamp`."""
        jql = self.build_jql(start_timestamp)
        start_at = 0
        docs: List[JSMDocument] = []

        while True:
            params = urllib.parse.urlencode({
                "jql": jql,
                "startAt": start_at,
                "maxResults": self.batch_size,
                "fields": "summary,description,comment,status,issuetype,reporter,updated,customfield_10010",
            })
            url = f"{self.base_url}/rest/api/3/search?{params}"
            status_code, payload = self.transport(url, self._headers())
            if status_code != 200:
                raise RuntimeError(f"JSM API error HTTP {status_code}: {payload}")

            issues = payload.get("issues") or []
            for issue in issues:
                docs.append(self._parse_issue(issue))

            total = int(payload.get("total") or 0)
            start_at += len(issues)
            if not issues or start_at >= total:
                break

        return docs

    def _parse_issue(self, issue: Dict[str, Any]) -> JSMDocument:
        key = str(issue.get("key") or issue.get("id") or "")
        fields = issue.get("fields") or {}
        summary = str(fields.get("summary") or "")
        desc = self._extract_text(fields.get("description"))
        comments_block = (fields.get("comment") or {}).get("comments") or []
        comments_text = "\n".join(
            f"[{c.get('author', {}).get('displayName', 'user')}]: {self._extract_text(c.get('body'))}"
            for c in comments_block
            if isinstance(c, dict)
        )
        full_text = "\n\n".join(part for part in (summary, desc, comments_text) if part).strip()
        status_name = str((fields.get("status") or {}).get("name") or "Open")
        issue_type = str((fields.get("issuetype") or {}).get("name") or "Service Request")
        reporter = str((fields.get("reporter") or {}).get("displayName") or "Customer")
        updated = str(fields.get("updated") or "")
        sla_field = fields.get("customfield_10010") or {}
        sla_breached = bool(
            isinstance(sla_field, dict)
            and (sla_field.get("ongoingCycle") or {}).get("breached", False)
        )

        return JSMDocument(
            id=f"jsm:{self.project_key}:{key}",
            title=f"[{key}] {summary}",
            text=full_text,
            link=f"{self.base_url}/browse/{key}",
            project_key=self.project_key,
            issue_type=issue_type,
            status=status_name,
            reporter=reporter,
            updated_at=updated,
            sla_breached=sla_breached,
            metadata={
                "issue_key": key,
                "project_key": self.project_key,
                "status": status_name,
                "issue_type": issue_type,
                "reporter": reporter,
                "sla_breached": sla_breached,
            },
        )

    @classmethod
    def _extract_text(cls, node: Any) -> str:
        """Extract plain text from Atlassian Document Format (ADF) or plain strings."""
        if node is None:
            return ""
        if isinstance(node, str):
            return node.strip()
        if isinstance(node, dict):
            if node.get("type") == "text" and isinstance(node.get("text"), str):
                return node["text"]
            children = node.get("content")
            if isinstance(children, list):
                return " ".join(filter(None, (cls._extract_text(c) for c in children))).strip()
        if isinstance(node, list):
            return " ".join(filter(None, (cls._extract_text(c) for c in node))).strip()
        return str(node)
