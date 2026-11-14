"""Jira Service Management (JSM) Connector for Onyx (Issue #2281)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
import html
import re
import time
from typing import Any
from urllib.parse import quote, urlparse, urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    InsufficientPermissionsError,
    UnexpectedValidationError,
)
from onyx.connectors.interfaces import (
    GenerateDocumentsOutput,
    GenerateSlimDocumentOutput,
    LoadConnector,
    PollConnector,
    SecondsSinceUnixEpoch,
    SlimConnector,
)
from onyx.connectors.jira_service_management.config import (
    DEFAULT_JSM_PAGE_LIMIT,
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
    ,
)
from onyx.connectors.models import (
    BasicExpertInfo,
    ConnectorMissingCredentialError,
    Document,
    HierarchyNode,
    SlimDocument,
    TextSection,
)
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger

logger = setup_logger()

MAX_JSM_PAGE_LIMIT = 100
RETRY_STATUS_CODES = (429, 500, 502, 503, 504)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_LINES_RE = re.compile(r"\n{3,}")
_JQL_SAFE_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _escape_jql_str(val: str) -> str:
    return val.replace("\\", "\\\\").replace('"', '\\"')


def _strip_html(raw_html: str) -> str:
    if not raw_html:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", raw_html, flags=re.IGNORECASE)
    text = re.sub(r"</p\s*>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<li\s*>", "- ", text, flags=re.IGNORECASE)
    text = re.sub(r"</li\s*>", "\n", text, flags=re.IGNORECASE)
    return html.unescape(_HTML_TAG_RE.sub("", text)).strip()


def extract_text_from_adf(node: Any) -> str:
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, (int, float, bool)):
        return str(node)
    if isinstance(node, list):
        return "".join(extract_text_from_adf(child) for child in node)
    if not isinstance(node, dict):
        return str(node)

    ntype = node.get("type", "")
    attrs = node.get("attrs") if isinstance(node.get("attrs"), dict) else {}
    content = node.get("content") if isinstance(node.get("content"), list) else []

    if ntype == "text":
        text = str(node.get("text", ""))
        for mark in node.get("marks") or []:
            if isinstance(mark, dict) and mark.get("type") == "link":
                m_attrs = mark.get("attrs") if isinstance(mark.get("attrs"), dict) else {}
                href = m_attrs.get("href")
                if href and href != text:
                    text = f"{text} ({href})"
        return text
    if ntype == "hardBreak":
        return "\n"
    if ntype == "rule":
        return "\n---\n"
    if ntype == "mention":
        return str(attrs.get("text") or attrs.get("id") or "")
    if ntype == "emoji":
        return str(attrs.get("text") or attrs.get("shortName") or "")
    if ntype in ("inlineCard", "blockCard", "embedCard"):
        if attrs.get("url"):
            return str(attrs["url"])
        data = attrs.get("data")
        return str(data["url"]) if isinstance(data, dict) and data.get("url") else ""
    if ntype == "status":
        st = attrs.get("text")
        return f"[{st}]" if st else ""
    if ntype == "date":
        ts = attrs.get("timestamp")
        if ts is not None:
            try:
                return datetime.fromtimestamp(float(ts) / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d")
            except (ValueError, TypeError, OSError):
                return str(ts)
        return ""
    if ntype == "heading":
        lvl = max(1, min(int(attrs.get("level", 1)), 6))
        inner = "".join(extract_text_from_adf(c) for c in content).strip()
        return f"{'#' * lvl} {inner}\n\n" if inner else ""
    if ntype == "paragraph":
        inner = "".join(extract_text_from_adf(c) for c in content).strip()
        return f"{inner}\n\n" if inner else ""
    if ntype == "blockquote":
        inner = "".join(extract_text_from_adf(c) for c in content).strip()
        return ("\n".join(f"> {l}" for l in inner.splitlines()) + "\n\n") if inner else ""
    if ntype == "panel":
        ptype = str(attrs.get("panelType", "info")).upper()
        inner = "".join(extract_text_from_adf(c) for c in content).strip()
        return f"[{ptype}] {inner}\n\n" if inner else ""
    if ntype == "codeBlock":
        lang = attrs.get("language") or ""
        return f"```{lang}\n{''.join(extract_text_from_adf(c) for c in content)}\n```\n\n"
    if ntype in ("bulletList", "orderedList"):
        start_num = int(attrs.get("order", 1))
        items: list[str] = []
        for idx, item in enumerate(content, start=start_num):
            it = extract_text_from_adf(item).strip()
            if it:
                lines = it.splitlines()
                pfx = "- " if ntype == "bulletList" else f"{idx}. "
                ind = "  " if ntype == "bulletList" else "   "
                items.append("\n".join([f"{pfx}{lines[0]}", *[f"{ind}{l}" for l in lines[1:]]]))
        return ("\n".join(items) + "\n\n") if items else ""
    if ntype == "listItem":
        return "".join(extract_text_from_adf(c) for c in content).strip() + "\n"
    if ntype == "table":
        rows = [extract_text_from_adf(r).strip() for r in content if extract_text_from_adf(r).strip()]
        return ("\n".join(rows) + "\n\n") if rows else ""
    if ntype == "tableRow":
        return " | ".join(extract_text_from_adf(cell).strip() for cell in content)
    if ntype in ("tableHeader", "tableCell"):
        return " ".join("".join(extract_text_from_adf(c) for c in content).strip().splitlines())
    if content:
        combined = "".join(extract_text_from_adf(c) for c in content)
        return _WHITESPACE_LINES_RE.sub("\n\n", combined).strip() if ntype == "doc" else combined
    if "value" in node:
        return extract_text_from_adf(node["value"])
    return node["text"] if isinstance(node.get("text"), str) else ""


def parse_jsm_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    if isinstance(value, dict):
        if value.get("epochMillis") is not None:
            try:
                return datetime.fromtimestamp(float(value["epochMillis"]) / 1000.0, tz=timezone.utc)
            except (ValueError, TypeError, OSError):
                pass
        for k in ("iso8601", "jira"):
            if isinstance(value.get(k), str) and value[k].strip():
                parsed = parse_jsm_datetime(value[k])
                if parsed is not None:
                    return parsed
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value) / 1000.0 if float(value) > 1e11 else float(value), tz=timezone.utc)
        except (ValueError, OSError):
            return None
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        iso = f"{raw[:-2]}:{raw[-2:]}" if re.search(r"[+-]\d{4}$", raw) else (f"{raw[:-1]}+00:00" if raw.endswith("Z") else raw)
        try:
            dt = datetime.fromisoformat(iso)
            return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
        except ValueError:
            try:
                return time_str_to_utc(raw)
            except Exception:
                return None
    return None


def extract_user_info(user_dict: dict[str, Any] | None) -> BasicExpertInfo | None:
    if not isinstance(user_dict, dict):
        return None
    name = user_dict.get("displayName") or user_dict.get("name") or user_dict.get("key") or None
    email = user_dict.get("emailAddress") or user_dict.get("email") or None
    if not name and not email:
        return None
    return BasicExpertInfo(
        display_name=str(name) if name else None,
        email=str(email) if email else None,
    )


def format_sla_metric(sla_record: dict[str, Any]) -> tuple[str, bool] | None:
    if not isinstance(sla_record, dict) or sla_record.get("errorMessage"):
        return None
    name = sla_record.get("name")
    if not name or not isinstance(name, str):
        return None
    ongoing = sla_record.get("ongoingCycle")
    completed = sla_record.get("completedCycles")
    if not isinstance(ongoing, dict) and not isinstance(completed, list):
        return None

    parts: list[str] = []
    breached = False
    if isinstance(ongoing, dict):
        cb = bool(ongoing.get("breached", False))
        breached = breached or cb
        st = "BREACHED" if cb else ("PAUSED" if ongoing.get("paused") else "ONGOING")
        bits = [f"status={st}"]
        for k, lbl in (("goalDuration", "goal"), ("elapsedTime", "elapsed"), ("remainingTime", "remaining")):
            v = ongoing.get(k, {}).get("friendly") if isinstance(ongoing.get(k), dict) else None
            if v:
                bits.append(f"{lbl}={v}")
        parts.append(f"Ongoing ({', '.join(bits)})")
    if isinstance(completed, list) and completed and isinstance(completed[-1], dict):
        last = completed[-1]
        cb = bool(last.get("breached", False))
        breached = breached or cb
        bits = [f"status={'BREACHED' if cb else 'MET'}"]
        for k, lbl in (("goalDuration", "goal"), ("elapsedTime", "elapsed")):
            v = last.get(k, {}).get("friendly") if isinstance(last.get(k), dict) else None
            if v:
                bits.append(f"{lbl}={v}")
        parts.append(f"Completed [{len(completed)} cycle(s), latest: {', '.join(bits)}]")
    if not parts:
        parts.append("No active or completed SLA cycles")
    return f"{name}: {'; '.join(parts)}", breached


def _format_request_field_value(raw_val: Any) -> str:
    if raw_val is None:
        return ""
    if isinstance(raw_val, str):
        return raw_val.strip()
    if isinstance(raw_val, (int, float, bool)):
        return str(raw_val)
    if isinstance(raw_val, list):
        return ", ".join(v for v in (_format_request_field_value(i) for i in raw_val) if v)
    if isinstance(raw_val, dict):
        if raw_val.get("type") == "doc" or "content" in raw_val:
            return extract_text_from_adf(raw_val).strip()
        if isinstance(raw_val.get("html"), str):
            return _strip_html(raw_val["html"])
        for k in ("label", "name", "displayName", "value", "text", "key"):
            if k in raw_val and isinstance(raw_val[k], (str, int, float)):
                return str(raw_val[k]).strip()
    return str(raw_val).strip()


def _validate_jsm_base_url(base_url: str) -> str:
    cleaned = (base_url or "").strip().rstrip("/")
    parsed = urlparse(cleaned)
    if not cleaned or parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ConnectorValidationError(f"Invalid Jira Service Management URL '{base_url}'.")
    return cleaned


class _ScopedJsmSession(requests.Session):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        p = urlsplit(base_url)
        self._scheme = p.scheme.lower()
        self._host = (p.hostname or "").lower()
        self._port = p.port if p.port is not None else (443 if self._scheme == "https" else 80)

    def send(self, request: requests.PreparedRequest, **kwargs: Any) -> requests.Response:
        if not request.url:
            raise ConnectorValidationError("Request has no destination URL.")
        p = urlsplit(request.url)
        host = (p.hostname or "").lower()
        port = p.port if p.port is not None else (443 if p.scheme.lower() == "https" else 80)
        if host != self._host or port != self._port:
            raise ConnectorValidationError(f"Refusing cross-origin request to '{host}:{port}'.")
        return super().send(request, **kwargs)


class JiraServiceManagementConnector(LoadConnector, PollConnector, SlimConnector):
    def __init__(
        self,
        jira_base_url: str,
        project_key: str | None = None,
        service_desk_ids: list[str] | None = None,
        request_types: list[str] | None = None,
        include_internal_comments: bool = False,
        include_sla_metrics: bool = True,
        include_attachments: bool = False,
        jql_query: str | None = None,
        scoped_token: bool = False,
        batch_size: int = INDEX_BATCH_SIZE,
        page_limit: int = DEFAULT_JSM_PAGE_LIMIT,
        request_timeout: int = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        self.jira_base_url = _validate_jsm_base_url(jira_base_url)
        self.project_key = project_key.strip() if project_key else None
        if self.project_key and not _JQL_SAFE_KEY_RE.match(self.project_key):
            raise ConnectorValidationError(f"Invalid project_key '{self.project_key}'.")
        self.service_desk_ids = [str(s).strip() for s in (service_desk_ids or []) if str(s).strip()]
        self.request_types = [rt.strip() for rt in (request_types or []) if rt.strip()]
        self.include_internal_comments = bool(include_internal_comments)
        self.include_sla_metrics = bool(include_sla_metrics)
        self.include_attachments = bool(include_attachments)
        self.jql_query = jql_query.strip() if jql_query else None
        self.scoped_token = bool(scoped_token)
        self.batch_size = max(1, int(batch_size or INDEX_BATCH_SIZE))
        self.page_limit = max(1, min(int(page_limit), MAX_JSM_PAGE_LIMIT))
        self.request_timeout = max(1, int(request_timeout))
        self._session: requests.Session | None = None
        self._is_cloud: bool = ".atlassian.net" in self.jira_base_url.lower()
        self._api_version: str = "3" if self._is_cloud else "2"
        self._service_desk_cache: dict[str, dict[str, Any]] = {}
        self._request_type_cache: dict[tuple[str, str], dict[str, Any]] = {}

    def id(self) -> str:
        scope = self.project_key or ",".join(self.service_desk_ids) or "all"
        return f"jira_service_management:{self.jira_base_url}:{scope}"

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        if not isinstance(credentials, dict):
            raise ConnectorValidationError("Credentials dictionary is required.")
        email = (credentials.get("jira_user_email") or credentials.get("jsm_user_email") or credentials.get("email") or "").strip()
        token = (credentials.get("jira_api_token") or credentials.get("jsm_api_token") or credentials.get("api_token") or "").strip()
        pat = (credentials.get("jira_pat") or credentials.get("jsm_pat") or credentials.get("personal_access_token") or credentials.get("access_token") or "").strip()
        if credentials.get("jira_api_version"):
            self._api_version = str(credentials["jira_api_version"]).strip()

        session = _ScopedJsmSession(self.jira_base_url)
        adapter = HTTPAdapter(max_retries=Retry(total=3, backoff_factor=1.0, status_forcelist=RETRY_STATUS_CODES, allowed_methods=frozenset(["GET", "POST"]), respect_retry_after_header=True))
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        headers = {"Accept": "application/json", "Content-Type": "application/json", "X-ExperimentalApi": "opt-in"}
        if pat and not email:
            headers["Authorization"] = f"Bearer {pat}"
        elif email and token:
            session.auth = (email, token)
        elif token and not email:
            headers["Authorization"] = f"Bearer {token}"
        else:
            raise ConnectorMissingCredentialError("JiraServiceManagement")
        session.headers.update(headers)
        self._session = session
        return None

    def _request_json(
        self, method: str, path_or_url: str, params: dict[str, Any] | None = None, json_body: dict[str, Any] | None = None, allow_status_codes: tuple[int, ...] = ()
    ) -> tuple[int, dict[str, Any]]:
        if self._session is None:
            raise ConnectorMissingCredentialError("JiraServiceManagement")
        url = path_or_url if path_or_url.startswith(("http://", "https://")) else f"{self.jira_base_url}/{path_or_url.lstrip('/')}"
        try:
            resp = self._session.request(method=method.upper(), url=url, params=params, json=json_body, timeout=self.request_timeout)
        except requests.RequestException as exc:
            raise UnexpectedValidationError(f"Network error communicating with JSM at {url}: {exc}") from exc

        if resp.status_code == 429:
            try:
                wait_s = min(max(float(resp.headers.get("Retry-After", "1")), 0.1), 60.0)
            except ValueError:
                wait_s = 1.0
            time.sleep(wait_s)
            resp = self._session.request(method=method.upper(), url=url, params=params, json=json_body, timeout=self.request_timeout)

        sc = resp.status_code
        if sc in allow_status_codes:
            try:
                data = resp.json() if resp.text else {}
            except ValueError:
                data = {}
            return sc, data if isinstance(data, dict) else {"values": data}
        if sc == 401:
            raise CredentialExpiredError(f"Authentication failed (401) at {url}.")
        if sc == 403:
            raise InsufficientPermissionsError(f"Insufficient permissions (403) at {url}.")
        if sc == 404:
            raise ConnectorValidationError(f"Resource not found (404) at {url}.")
        if sc >= 400:
            raise UnexpectedValidationError(f"JSM API returned HTTP {sc} for {url}: {(resp.text or '')[:300]}")
        try:
            payload = resp.json() if resp.text else {}
        except ValueError as exc:
            raise UnexpectedValidationError(f"Invalid JSON from {url}: {exc}") from exc
        return sc, payload if isinstance(payload, dict) else {"values": payload}

    def _paginate_servicedesk_endpoint(
        self, path: str, params: dict[str, Any] | None = None, allow_status_codes: tuple[int, ...] = ()
    ) -> Iterator[dict[str, Any]]:
        start, limit, base = 0, self.page_limit, dict(params or {})
        while True:
            sc, data = self._request_json("GET", path, params={**base, "start": start, "limit": limit}, allow_status_codes=allow_status_codes)
            if sc in allow_status_codes and sc >= 400:
                return
            values = data.get("values")
            if not isinstance(values, list) or not values:
                return
            for item in values:
                if isinstance(item, dict):
                    yield item
            if data.get("isLastPage") is True or int(data.get("size", len(values))) <= 0:
                return
            if data.get("isLastPage") is None and len(values) < limit:
                return
            start += len(values)

    def fetch_service_desks(self) -> list[dict[str, Any]]:
        desks: list[dict[str, Any]] = []
        target_ids = set(self.service_desk_ids)
        target_pk = self.project_key.upper() if self.project_key else None
        for desk in self._paginate_servicedesk_endpoint("/rest/servicedeskapi/servicedesk"):
            sd_id = str(desk.get("id", "")).strip()
            pk = str(desk.get("projectKey", "")).strip().upper()
            if sd_id:
                self._service_desk_cache[sd_id] = desk
            if (target_ids and sd_id not in target_ids) or (target_pk and pk and pk != target_pk):
                continue
            desks.append(desk)
        return desks

    def _get_request_type_info(self, sd_id: str, rt_id: str) -> dict[str, Any] | None:
        if not sd_id or not rt_id:
            return None
        if (sd_id, rt_id) not in self._request_type_cache:
            for rt in self._paginate_servicedesk_endpoint(f"/rest/servicedeskapi/servicedesk/{quote(sd_id)}/requesttype", allow_status_codes=(403, 404)):
                rid = str(rt.get("id", "")).strip()
                if rid:
                    self._request_type_cache[(sd_id, rid)] = rt
        return self._request_type_cache.get((sd_id, rt_id))

    def validate_connector_settings(self) -> None:
        desks = self.fetch_service_desks()
        if (self.project_key or self.service_desk_ids) and not desks:
            raise ConnectorValidationError(f"No matching JSM service desk found for '{self.project_key or self.service_desk_ids}'.")
        probe: dict[str, Any] = {"start": 0, "limit": 1}
        if desks and desks[0].get("id") is not None:
            probe["serviceDeskId"] = str(desks[0]["id"])
        self._request_json("GET", "/rest/servicedeskapi/request", params=probe)

    def validate_credentials(self) -> bool:
        try:
            self.validate_connector_settings()
            return True
        except (CredentialExpiredError, InsufficientPermissionsError):
            return False

    def _fetch_request_comments(self, key: str) -> list[dict[str, Any]]:
        params = {"public": "true", "internal": "true" if self.include_internal_comments else "false"}
        return [
            c for c in self._paginate_servicedesk_endpoint(f"/rest/servicedeskapi/request/{quote(str(key))}/comment", params=params, allow_status_codes=(403, 404))
            if bool(c.get("public", True)) or self.include_internal_comments
        ]

    def _fetch_request_slas(self, key: str) -> list[dict[str, Any]]:
        if not self.include_sla_metrics:
            return []
        return [
            s for s in self._paginate_servicedesk_endpoint(f"/rest/servicedeskapi/request/{quote(str(key))}/sla", allow_status_codes=(403, 404))
            if not s.get("errorMessage")
        ]

    def _fetch_jira_issue_details(self, key: str) -> dict[str, Any] | None:
        sc, data = self._request_json("GET", f"/rest/api/{self._api_version}/issue/{quote(str(key))}", params={"expand": "names,renderedFields"}, allow_status_codes=(403, 404))
        return None if sc in (403, 404) or not data else data

    def _build_jql(self, start: SecondsSinceUnixEpoch | None = None, end: SecondsSinceUnixEpoch | None = None) -> str:
        clauses: list[str] = []
        if self.project_key:
            clauses.append(f'project = "{self.project_key}"')
        elif self.service_desk_ids:
            if not self._service_desk_cache:
                self.fetch_service_desks()
            pkeys = [
                f'"{self._service_desk_cache[s]["projectKey"]}"'
                for s in self.service_desk_ids
                if s in self._service_desk_cache and self._service_desk_cache[s].get("projectKey")
            ]
            if not pkeys:
                raise ConnectorValidationError(
                    f"Unable to resolve project keys for configured service_desk_ids: {self.service_desk_ids}"
                )
            clauses.append(f"project IN ({', '.join(pkeys)})")
        if self.request_types:
            escaped_rts = ", ".join(f'"{_escape_jql_str(r)}"' for r in self.request_types)
            clauses.append(f'"Customer Request Type" IN ({escaped_rts})')
        if start is not None:
            clauses.append(f"updated >= {int(start * 1000)}")
        if end is not None:
            clauses.append(f"updated <= {int(end * 1000)}")
        if self.jql_query:
            clauses.append(f"({self.jql_query})")
        return f"{' AND '.join(clauses)} ORDER BY updated ASC" if clauses else "ORDER BY updated ASC"

    def _search_issues_via_jql(self, jql: str, fields: list[str] | None = None) -> Iterator[dict[str, Any]]:
        req_fields = ",".join(fields or ["*all"])
        if self._api_version == "3" and self._is_cloud:
            token: str | None = None
            while True:
                params: dict[str, Any] = {"jql": jql, "maxResults": self.page_limit, "fields": req_fields}
                if token:
                    params["nextPageToken"] = token
                sc, data = self._request_json("GET", "/rest/api/3/search/jql", params=params, allow_status_codes=(404, 405))
                if sc in (404, 405):
                    break
                issues = data.get("issues")
                if not isinstance(issues, list) or not issues:
                    return
                for issue in issues:
                    if isinstance(issue, dict):
                        yield issue
                token = data.get("nextPageToken")
                if data.get("isLast") is True or not token:
                    return
        start_at = 0
        while True:
            _, data = self._request_json("GET", f"/rest/api/{self._api_version}/search", params={"jql": jql, "startAt": start_at, "maxResults": self.page_limit, "fields": req_fields})
            issues = data.get("issues")
            if not isinstance(issues, list) or not issues:
                return
            for issue in issues:
                if isinstance(issue, dict):
                    yield issue
            total = int(data.get("total", len(issues)))
            start_at += len(issues)
            if start_at >= total or len(issues) < self.page_limit:
                return

    def _convert_request_to_document(
        self, request_obj: dict[str, Any], jira_issue: dict[str, Any] | None = None, comments: list[dict[str, Any]] | None = None, slas: list[dict[str, Any]] | None = None
    ) -> Document:
        issue_key = str(request_obj.get("issueKey") or (jira_issue or {}).get("key") or request_obj.get("issueId") or (jira_issue or {}).get("id") or "").strip()
        issue_id = str(request_obj.get("issueId") or (jira_issue or {}).get("id") or issue_key).strip()
        jfields: dict[str, Any] = jira_issue.get("fields", {}) if isinstance(jira_issue, dict) and isinstance(jira_issue.get("fields"), dict) else {}

        summary = str(request_obj.get("summary") or jfields.get("summary") or "").strip()
        desc_parts: list[str] = []
        extra_lines: list[str] = []
        for fe in request_obj.get("requestFieldValues") or []:
            if not isinstance(fe, dict):
                continue
            fid, label, rval, val = str(fe.get("fieldId", "")).strip(), str(fe.get("label") or fe.get("fieldId", "")).strip(), fe.get("renderedValue"), fe.get("value")
            if fid == "summary":
                if not summary and val:
                    summary = _format_request_field_value(val)
            elif fid == "description":
                dt = extract_text_from_adf(val) if isinstance(val, dict) and (val.get("type") == "doc" or "content" in val) else (_strip_html(rval["html"]) if isinstance(rval, dict) and isinstance(rval.get("html"), str) else _format_request_field_value(val))
                if dt:
                    desc_parts.append(dt)
            else:
                fv = _format_request_field_value(val)
                if fv:
                    extra_lines.append(f"{label}: {fv}")

        if not desc_parts and jfields.get("description") is not None:
            txt = extract_text_from_adf(jfields.get("description")).strip()
            if txt:
                desc_parts.append(txt)
        summary = summary or f"Request {issue_key}"
        links = request_obj.get("_links") if isinstance(request_obj.get("_links"), dict) else {}
        doc_link = links.get("agent") or links.get("web") or f"{self.jira_base_url}/browse/{issue_key}"

        sd_id, rt_id = str(request_obj.get("serviceDeskId") or "").strip(), str(request_obj.get("requestTypeId") or "").strip()
        sd_obj = self._service_desk_cache.get(sd_id, {})
        proj_obj = jfields.get("project") if isinstance(jfields.get("project"), dict) else {}
        proj_key = str(sd_obj.get("projectKey") or proj_obj.get("key") or self.project_key or (issue_key.split("-")[0] if "-" in issue_key else "")).strip()
        proj_name = str(sd_obj.get("projectName") or proj_obj.get("name") or proj_key).strip()

        exp_rt = request_obj.get("requestType") if isinstance(request_obj.get("requestType"), dict) else (self._get_request_type_info(sd_id, rt_id) or {})
        rt_name, rt_desc = str(exp_rt.get("name") or "").strip(), str(exp_rt.get("description") or "").strip()

        embedded_slas: list[dict[str, Any]] = []
        for cf in jfields.values():
            if isinstance(cf, dict):
                if not rt_name and isinstance(cf.get("requestType"), dict):
                    rt_name = str(cf["requestType"].get("name") or "").strip()
                    rt_desc = str(cf["requestType"].get("description") or "").strip()
                if "ongoingCycle" in cf or "completedCycles" in cf:
                    embedded_slas.append(cf)

        c_stat = request_obj.get("currentStatus") if isinstance(request_obj.get("currentStatus"), dict) else {}
        j_stat = jfields.get("status") if isinstance(jfields.get("status"), dict) else {}
        status_name = str(c_stat.get("status") or j_stat.get("name") or "").strip()
        status_cat = str(c_stat.get("statusCategory") or (j_stat.get("statusCategory", {}).get("name") if isinstance(j_stat.get("statusCategory"), dict) else "") or "").strip()
        priority_name = str((jfields.get("priority") or {}).get("name") or "").strip() if isinstance(jfields.get("priority"), dict) else ""
        issuetype_name = str((jfields.get("issuetype") or {}).get("name") or "").strip() if isinstance(jfields.get("issuetype"), dict) else ""
        labels = [str(l) for l in (jfields.get("labels") or []) if isinstance(l, (str, int))]

        rep_info = extract_user_info(request_obj.get("reporter") if isinstance(request_obj.get("reporter"), dict) else (jfields.get("reporter") if isinstance(jfields.get("reporter"), dict) else None))
        asg_info = extract_user_info(jfields.get("assignee") if isinstance(jfields.get("assignee"), dict) else None)
        created_dt = parse_jsm_datetime(request_obj.get("createdDate")) or parse_jsm_datetime(jfields.get("created"))
        updated_dt = parse_jsm_datetime(jfields.get("updated")) or parse_jsm_datetime(c_stat.get("statusDate")) or created_dt

        all_slas = list(slas or [])
        seen_sla = {str(s.get("name")) for s in all_slas if isinstance(s, dict)}
        for es in embedded_slas:
            if str(es.get("name")) not in seen_sla:
                all_slas.append(es)
        sla_lines, sla_names, any_breached = [], [], False
        for sr in all_slas:
            fmt = format_sla_metric(sr)
            if fmt is not None:
                sla_lines.append(fmt[0])
                any_breached = any_breached or fmt[1]
                sla_names.append(str(sr.get("name")))

        hdr = [f"[{issue_key}] {summary}"]
        if proj_name:
            hdr.append(f"Project: {proj_name} ({proj_key})")
        if rt_name:
            hdr.append(f"Request Type: {rt_name}" + (f" - {rt_desc}" if rt_desc else ""))
        if status_name:
            hdr.append(f"Status: {status_name}" + (f" ({status_cat})" if status_cat else ""))
        if priority_name:
            hdr.append(f"Priority: {priority_name}")
        if issuetype_name:
            hdr.append(f"Issue Type: {issuetype_name}")
        if rep_info:
            hdr.append(f"Reporter: {rep_info.get_semantic_name()}")
        if asg_info:
            hdr.append(f"Assignee: {asg_info.get_semantic_name()}")

        blocks = ["\n".join(hdr)]
        if desc_parts:
            blocks.append("Description:\n" + "\n\n".join(desc_parts))
        if extra_lines:
            blocks.append("Request Fields:\n" + "\n".join(extra_lines))
        if sla_lines:
            blocks.append("SLA Metrics:\n" + "\n".join(f"- {l}" for l in sla_lines))
        sections: list[TextSection] = [TextSection(link=doc_link, text="\n\n".join(blocks).strip())]

        for c in comments or []:
            if not isinstance(c, dict):
                continue
            pub = bool(c.get("public", True))
            if not pub and not self.include_internal_comments:
                continue
            rb, rend = c.get("body"), c.get("renderedBody")
            ctext = extract_text_from_adf(rb).strip() if isinstance(rb, dict) else (rb.strip() if isinstance(rb, str) and rb.strip() else (_strip_html(rend["html"]) if isinstance(rend, dict) and isinstance(rend.get("html"), str) else ""))
            if not ctext:
                continue
            ainfo = extract_user_info(c.get("author") if isinstance(c.get("author"), dict) else None)
            alabel = ainfo.get_semantic_name() if ainfo else "Unknown"
            cdt = parse_jsm_datetime(c.get("created"))
            if cdt and (updated_dt is None or cdt > updated_dt):
                updated_dt = cdt
            cid = str(c.get("id", "")).strip()
            sections.append(TextSection(link=f"{doc_link}?focusedCommentId={cid}" if cid else doc_link, text=f"[{'Public Comment' if pub else 'Internal Note'} by {alabel}]\n{ctext}"))

        meta: dict[str, str | list[str]] = {"issue_key": issue_key, "issue_id": issue_id}
        for k, v in (
            ("project", proj_key), ("project_name", proj_name), ("service_desk_id", sd_id), ("request_type_id", rt_id),
            ("request_type", rt_name), ("status", status_name), ("status_category", status_cat), ("priority", priority_name),
            ("issuetype", issuetype_name), ("reporter", rep_info.display_name if rep_info else None),
            ("reporter_email", rep_info.email if rep_info else None), ("assignee", asg_info.display_name if asg_info else None),
            ("assignee_email", asg_info.email if asg_info else None),
        ):
            if v:
                meta[k] = v
        if labels:
            meta["labels"] = labels
        if sla_lines:
            meta["sla_breached"] = "true" if any_breached else "false"
            meta["sla_metrics"] = sla_names

        return Document(
            id=doc_link,
            sections=sections,
            source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
            semantic_identifier=f"{issue_key}: {summary}",
            title=f"{issue_key} {summary}",
            doc_updated_at=updated_dt,
            doc_created_at=created_dt,
            primary_owners=[rep_info] if rep_info else None,
            secondary_owners=[asg_info] if asg_info else None,
            metadata=meta,
        )

    def _enrich_and_build_document(self, request_obj: dict[str, Any], jira_issue: dict[str, Any] | None = None) -> Document:
        key = str(request_obj.get("issueKey") or (jira_issue or {}).get("key") or request_obj.get("issueId") or "").strip()
        if jira_issue is None and key:
            jira_issue = self._fetch_jira_issue_details(key)
        return self._convert_request_to_document(
            request_obj=request_obj,
            jira_issue=jira_issue,
            comments=self._fetch_request_comments(key) if key else [],
            slas=self._fetch_request_slas(key) if key else [],
        )

    def _iter_service_desk_requests(self, start: SecondsSinceUnixEpoch | None = None, end: SecondsSinceUnixEpoch | None = None) -> Iterator[dict[str, Any]]:
        desks = self.fetch_service_desks()
        sd_ids = [str(d.get("id")) for d in desks if d.get("id") is not None] or self.service_desk_ids
        scopes: list[dict[str, Any]] = [{"serviceDeskId": sid} for sid in sd_ids] if sd_ids else [{}]
        rt_names, rt_ids = {r.lower() for r in self.request_types}, set(self.request_types)
        start_dt = datetime.fromtimestamp(start, tz=timezone.utc) if start is not None else None
        end_dt = datetime.fromtimestamp(end, tz=timezone.utc) if end is not None else None

        for base in scopes:
            for req in self._paginate_servicedesk_endpoint("/rest/servicedeskapi/request", params={**base, "expand": "requestType,serviceDesk,status,sla,participant"}):
                if self.project_key:
                    ik = str(req.get("issueKey") or "")
                    if ik and "-" in ik and ik.split("-")[0].upper() != self.project_key.upper():
                        continue
                if self.request_types:
                    rid = str(req.get("requestTypeId") or "")
                    rname = str((req.get("requestType") or {}).get("name") or "").lower() if isinstance(req.get("requestType"), dict) else ""
                    if rid not in rt_ids and rname not in rt_names:
                        continue
                if start_dt is not None or end_dt is not None:
                    st_obj = req.get("currentStatus") if isinstance(req.get("currentStatus"), dict) else {}
                    act_dt = parse_jsm_datetime(req.get("updatedDate")) or parse_jsm_datetime(st_obj.get("statusDate")) or parse_jsm_datetime(req.get("createdDate"))
                    if act_dt is not None:
                        if (start_dt is not None and act_dt < start_dt) or (end_dt is not None and act_dt > end_dt):
                            continue
                yield req

    def load_from_state(self) -> GenerateDocumentsOutput:
        batch: list[Document | HierarchyNode] = []
        for req in self._iter_service_desk_requests():
            batch.append(self._enrich_and_build_document(req))
            if len(batch) >= self.batch_size:
                yield batch
                batch = []
        if batch:
            yield batch

    def poll_source(self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch) -> GenerateDocumentsOutput:
        try:
            self.fetch_service_desks()
        except (InsufficientPermissionsError, ConnectorValidationError):
            pass
        jql = self._build_jql(start=start, end=end)
        batch: list[Document | HierarchyNode] = []
        seen: set[str] = set()
        
        try:
            first_issue = next(jql_iter, None)
        except (InsufficientPermissionsError, ConnectorValidationError):
            for req in self._iter_service_desk_requests(start=start, end=end):
                batch.append(self._enrich_and_build_document(req))
                if len(batch) >= self.batch_size:
                    yield batch
                    batch = []
            if batch:
                yield batch
            return

        if first_issue is not None:
            def _all_jql_issues() -> Iterator[dict[str, Any]]:
                yield first_issue
                yield from jql_iter

            for j_issue in _all_jql_issues():
                key = str(j_issue.get("key") or "").strip()
                if not key or key in seen:
                    continue
                seen.add(key)
                sc, req_obj = self._request_json("GET", f"/rest/servicedeskapi/request/{quote(key)}", params={"expand": "requestType,serviceDesk,status,sla"}, allow_status_codes=(403, 404))
                if sc in (403, 404) or not req_obj:
                    req_obj = {"issueId": j_issue.get("id"), "issueKey": key}
                batch.append(self._enrich_and_build_document(request_obj=req_obj, jira_issue=j_issue))
                if len(batch) >= self.batch_size:
                    yield batch
                    batch = []
            if batch:
                yield batch

    def retrieve_slim_documents(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        slim_batch: list[SlimDocument | HierarchyNode] = []
        for req in self._iter_service_desk_requests(start=start, end=end):
            if callback is not None and callback.should_stop():
                return
            key = str(req.get("issueKey") or req.get("issueId") or "").strip()
            if not key:
                continue
            links = req.get("_links") if isinstance(req.get("_links"), dict) else {}
            link = links.get("agent") or links.get("web") or f"{self.jira_base_url}/browse/{key}"
            slim_batch.append(SlimDocument(id=link, doc_created_at=parse_jsm_datetime(req.get("createdDate"))))
            if len(slim_batch) >= self.batch_size:
                if callback is not None:
                    callback.progress("retrieve_slim_documents", len(slim_batch))
                yield slim_batch
                slim_batch = []
        if slim_batch:
            if callback is not None:
                callback.progress("retrieve_slim_documents", len(slim_batch))
            yield slim_batch

    def retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        return self.retrieve_slim_documents(start=start, end=end, callback=callback)

    def retrieve_full_documents(self, slim_documents: list[SlimDocument]) -> GenerateDocumentsOutput:
        batch: list[Document | HierarchyNode] = []
        for slim_doc in slim_documents:
            key = slim_doc.id.split("?", 1)[0].split("#", 1)[0].rstrip("/").rsplit("/", 1)[-1]
            if not key:
                continue
            sc, req_obj = self._request_json("GET", f"/rest/servicedeskapi/request/{quote(key)}", params={"expand": "requestType,serviceDesk,status,sla"}, allow_status_codes=(404,))
            if sc == 404 or not req_obj:
                continue
            batch.append(self._enrich_and_build_document(req_obj))
            if len(batch) >= self.batch_size:
                yield batch
                batch = []
        if batch:
            yield batch
