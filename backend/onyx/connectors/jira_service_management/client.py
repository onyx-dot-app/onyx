"""Atlassian Jira Service Management (JSM) REST API client."""
from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterator


class JSMClientError(RuntimeError):
    """Raised when the Jira Service Management API returns an error response."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class JSMComment:
    comment_id: str
    body: str
    author_name: str
    author_email: str | None
    public: bool
    created_at: str


@dataclass
class JSMRequest:
    issue_id: str
    issue_key: str
    service_desk_id: str
    request_type_id: str
    summary: str
    description: str
    status: str
    reporter_name: str
    reporter_email: str | None
    created_at: str
    updated_at: str
    web_link: str
    comments: list[JSMComment] = field(default_factory=list)
    extra_fields: dict[str, Any] = field(default_factory=dict)



def _parse_utc_dt(value: str) -> datetime | None:
    if not value:
        return None
    normalized = value.strip().replace("Z", "+00:00")
    # Support Jira's "+0000" / "-0500" offset format on all Python versions
    if len(normalized) >= 5 and normalized[-5] in ("+", "-") and normalized[-4:].isdigit():
        normalized = f"{normalized[:-2]}:{normalized[-2:]}"
    try:
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def _select_latest_iso(candidates: list[str], fallback: str = "") -> str:
    parsed: list[tuple[datetime, str]] = []
    for ts in candidates:
        dt = _parse_utc_dt(ts)
        if dt is not None:
            parsed.append((dt, dt.isoformat()))
    if parsed:
        return max(parsed, key=lambda item: item[0])[1]
    return fallback


def normalize_base_url(base_url: str) -> str:
    cleaned = (base_url or "").strip().rstrip("/")
    parsed = urllib.parse.urlparse(cleaned)
    if parsed.scheme not in ("https", "http") or not parsed.netloc:
        raise ValueError("jira_base_url must be a valid http(s) URL (e.g. https://acme.atlassian.net)")
    return cleaned


class JSMClient:
    """Thin client for Jira Service Management REST API (/rest/servicedeskapi)."""

    def __init__(
        self,
        base_url: str,
        user_email: str | None = None,
        api_token: str | None = None,
        bearer_token: str | None = None,
        page_size: int = 50,
        timeout: int = 20,
        http_get: Callable[[str, dict[str, str], int], tuple[int, dict[str, Any]]] | None = None,
    ) -> None:
        self.base_url = normalize_base_url(base_url)
        self.page_size = max(1, min(100, int(page_size)))
        self.timeout = timeout
        self._http_get = http_get or self._default_http_get

        if bearer_token:
            self._auth_header = f"Bearer {bearer_token.strip()}"
        elif user_email and api_token:
            raw = f"{user_email.strip()}:{api_token.strip()}".encode("utf-8")
            self._auth_header = f"Basic {base64.b64encode(raw).decode('ascii')}"
        else:
            raise ValueError("Provide either (user_email + api_token) or bearer_token.")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": self._auth_header,
            "Accept": "application/json",
            "X-ExperimentalApi": "opt-in",
        }

    @staticmethod
    def _default_http_get(url: str, headers: dict[str, str], timeout: int) -> tuple[int, dict[str, Any]]:
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                return resp.status, (json.loads(raw) if raw.strip() else {})
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:400]
            raise JSMClientError(f"JSM API HTTP {exc.code}: {body}", status_code=exc.code) from exc

    def _get_json(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        if params:
            query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
            if query:
                url = f"{url}?{query}"
        status, payload = self._http_get(url, self._headers(), self.timeout)
        if status < 200 or status >= 300:
            raise JSMClientError(f"JSM API HTTP {status} on {path}", status_code=status)
        return payload

    def list_service_desks(self) -> list[dict[str, Any]]:
        desks: list[dict[str, Any]] = []
        start = 0
        while True:
            page = self._get_json(
                "/rest/servicedeskapi/servicedesk",
                {"start": start, "limit": self.page_size},
            )
            values = page.get("values") or []
            desks.extend(values)
            if page.get("isLastPage", True) or not values:
                break
            start += len(values)
        return desks

    def resolve_service_desk_id(self, project_key: str) -> str:
        target = (project_key or "").strip().upper()
        for desk in self.list_service_desks():
            if str(desk.get("projectKey", "")).upper() == target or str(desk.get("id", "")) == target:
                return str(desk["id"])
        raise JSMClientError(f"Service desk for project '{project_key}' not found.", status_code=404)

    def get_issue_updated_timestamp(self, issue_key: str) -> str:
        """Fetch the Jira issue's actual last-modified timestamp (fields.updated)."""
        try:
            data = self._get_json(
                f"/rest/api/3/issue/{urllib.parse.quote(issue_key)}",
                {"fields": "updated"},
            )
            return str((data.get("fields") or {}).get("updated") or "")
        except JSMClientError as exc:
            # Propagate rate-limit / transient / auth errors so polling never silently skips edited tickets.
            if exc.status_code != 404:
                raise
            return ""

    def list_request_comments(
        self,
        issue_key: str,
        include_internal: bool = False,
    ) -> list[JSMComment]:
        comments: list[JSMComment] = []
        start = 0
        while True:
            page = self._get_json(
                f"/rest/servicedeskapi/request/{urllib.parse.quote(issue_key)}/comment",
                {
                    "start": start,
                    "limit": self.page_size,
                    "public": "true",
                    "internal": "true" if include_internal else "false",
                },
            )
            values = page.get("values") or []
            for item in values:
                is_pub = bool(item.get("public", True))
                if not is_pub and not include_internal:
                    continue
                author = item.get("author") or {}
                comments.append(
                    JSMComment(
                        comment_id=str(item.get("id") or ""),
                        body=str(item.get("body") or "").strip(),
                        author_name=str(author.get("displayName") or author.get("name") or "Unknown"),
                        author_email=author.get("emailAddress"),
                        public=is_pub,
                        created_at=str((item.get("created") or {}).get("iso8601") or ""),
                    )
                )
            if page.get("isLastPage", True) or not values:
                break
            start += len(values)
        return comments

    def iter_requests(
        self,
        service_desk_id: str | None = None,
        include_comments: bool = True,
        include_internal_comments: bool = False,
    ) -> Iterator[JSMRequest]:
        start = 0
        while True:
            page = self._get_json(
                "/rest/servicedeskapi/request",
                {
                    "serviceDeskId": service_desk_id,
                    "start": start,
                    "limit": self.page_size,
                    "requestOwnership": "ALL_REQUESTS",
                },
            )
            values = page.get("values") or []
            for raw in values:
                issue_key = str(raw.get("issueKey") or "")
                field_map: dict[str, Any] = {}
                for fv in raw.get("requestFieldValues") or []:
                    fid = str(fv.get("fieldId") or "")
                    if fid:
                        field_map[fid] = fv.get("value")

                summary = str(field_map.get("summary") or issue_key)
                description = str(field_map.get("description") or "")
                status_obj = raw.get("currentStatus") or {}
                reporter = raw.get("reporter") or {}
                created_iso = str((raw.get("createdDate") or {}).get("iso8601") or "")
                status_iso = str((status_obj.get("statusDate") or {}).get("iso8601") or "")
                links = raw.get("_links") or {}
                web_link = str(links.get("web") or f"{self.base_url}/browse/{issue_key}")

                comments = (
                    self.list_request_comments(issue_key, include_internal=include_internal_comments)
                    if (include_comments and issue_key)
                    else []
                )

                # Resolve true Jira issue modification timestamp (description edits, field updates, comments)
                issue_updated_iso = self.get_issue_updated_timestamp(issue_key) if issue_key else ""
                candidates = [ts for ts in (issue_updated_iso, status_iso, created_iso) if ts]
                candidates.extend(c.created_at for c in comments if c.created_at)
                updated_iso = _select_latest_iso(candidates, fallback=created_iso)

                yield JSMRequest(
                    issue_id=str(raw.get("issueId") or issue_key),
                    issue_key=issue_key,
                    service_desk_id=str(raw.get("serviceDeskId") or service_desk_id or ""),
                    request_type_id=str(raw.get("requestTypeId") or ""),
                    summary=summary,
                    description=description,
                    status=str(status_obj.get("status") or ""),
                    reporter_name=str(reporter.get("displayName") or reporter.get("name") or ""),
                    reporter_email=reporter.get("emailAddress"),
                    created_at=created_iso,
                    updated_at=updated_iso,
                    web_link=web_link,
                    comments=comments,
                    extra_fields={k: v for k, v in field_map.items() if k not in ("summary", "description")},
                )

            if page.get("isLastPage", True) or not values:
                break
            start += len(values)
