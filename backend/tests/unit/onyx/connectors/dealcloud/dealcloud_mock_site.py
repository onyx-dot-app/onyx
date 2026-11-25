"""A local HTTP server that answers like a DealCloud site, built from the
public API docs and DealCloud's Python SDK. The connector's gateway talks to
it over real HTTP, so tests cover the token flow, the request shapes and the
parsing together.

It models what the docs state: client-credentials tokens bound to a scope
that expire, 5 calls per second for each API area with the reset time in a
header, one HTTP method per endpoint, the schema, the id listing, the change
history, the row query with its options, and the user groups.

It does not model who may read what: every answer is what a user who reads
all data would get. It cannot show how DealCloud answers a user with
narrower access.
"""

import json
import re
import threading
import time
from collections import defaultdict, deque
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import requests
from pydantic import BaseModel, Field

from onyx.connectors.dealcloud import source_operations

SITE_URL = "https://mock.dealcloud.test"
CLIENT_ID = "106"
API_KEY = "mock-api-key"

_API_PREFIX = "/api/rest"
_RATE_LIMIT_PER_SECOND = 5
_HISTORY_RETENTION = timedelta(days=183)
_MODIFIED_SINCE_FORMAT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
_ENTRY_ID_QUERY = re.compile(r"^EntryId in \(([\d,]*)\)$")
# DealCloud limits each area on its own. Schema calls need the data scope.
_SCOPE_BY_AREA = {
    "data": "data",
    "schema": "data",
    "user_management": "user_management",
}


def _area(path: str) -> str:
    if "/v1/management" in path:
        return "user_management"
    return "schema" if "/v4/schema" in path else "data"


class MockField(BaseModel):
    id: int
    api_name: str
    name: str
    field_type: int
    system_field_type: int = 0
    is_multi_select: bool = False


class MockEntryType(BaseModel):
    id: int
    api_name: str
    plural_name: str
    entry_list_type: int = 1
    fields: list[MockField]
    # Row values by entry id, keyed by field api name.
    entries: dict[int, dict[str, Any]] = Field(default_factory=dict)


class MockChange(BaseModel):
    entry_id: int
    name: str
    at: datetime
    is_deleted: bool


class MockSite:
    def __init__(self) -> None:
        self.entry_types: dict[int, MockEntryType] = {}
        self.changes: dict[int, list[MockChange]] = defaultdict(list)
        # Active and inactive users: id -> (email, is_active).
        self.users: dict[int, tuple[str | None, bool]] = {}
        self.groups: dict[int, dict[str, Any]] = {}
        self.api_enabled = True
        self.user_management_enabled = True
        self.token_lifetime_seconds = 900
        self.enforce_rate_limit = False
        self.max_rows_per_query = 10_000
        self.requests: list[tuple[str, str]] = []
        self.rate_limited = 0
        self._tokens: dict[str, tuple[str, float]] = {}
        self._recent: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._token_count = 0

    def add_entry_type(self, entry_type: MockEntryType) -> None:
        self.entry_types[entry_type.id] = entry_type

    def put_entry(
        self, entry_type_id: int, entry_id: int, at: datetime, **values: Any
    ) -> None:
        with self._lock:
            self.entry_types[entry_type_id].entries[entry_id] = values
            self.changes[entry_type_id].append(
                MockChange(
                    entry_id=entry_id,
                    name=str(values.get("Name", entry_id)),
                    at=at,
                    is_deleted=False,
                )
            )

    def delete_entry(self, entry_type_id: int, entry_id: int, at: datetime) -> None:
        with self._lock:
            del self.entry_types[entry_type_id].entries[entry_id]
            self.changes[entry_type_id].append(
                MockChange(
                    entry_id=entry_id, name=str(entry_id), at=at, is_deleted=True
                )
            )

    def revoke_tokens(self) -> None:
        with self._lock:
            self._tokens.clear()

    def count(self, method: str, path_start: str) -> int:
        return sum(
            1
            for seen_method, path in self.requests
            if seen_method == method and path.startswith(path_start)
        )

    def issue_token(self, form: dict[str, list[str]]) -> tuple[int, Any]:
        client_id = form.get("client_id", [""])[0]
        secret = form.get("client_secret", [""])[0]
        scope = form.get("scope", [""])[0]
        grant = form.get("grant_type", [""])[0]
        if (
            grant != "client_credentials"
            or client_id != CLIENT_ID
            or secret != API_KEY
            or not self.api_enabled
        ):
            return 400, {"error": "invalid_client"}
        if scope not in {"data", "user_management"}:
            return 400, {"error": "invalid_scope"}
        if scope == "user_management" and not self.user_management_enabled:
            return 400, {"error": "invalid_scope"}
        with self._lock:
            self._token_count += 1
            token = f"token-{self._token_count}"
            self._tokens[token] = (
                scope,
                time.monotonic() + self.token_lifetime_seconds,
            )
        return 200, {
            "access_token": token,
            "token_type": "Bearer",
            "expires_in": self.token_lifetime_seconds,
        }

    def check_token(self, header: str | None, scope: str) -> int | None:
        """None when the bearer token may call the area, else the status."""
        token = (header or "").removeprefix("Bearer ")
        with self._lock:
            known = self._tokens.get(token)
        if known is None or time.monotonic() >= known[1]:
            return 401
        return None if known[0] == scope else 403

    def seconds_until_allowed(self, area: str) -> float | None:
        """None when the call fits the area's limit, else the time until its
        one second window has room."""
        if not self.enforce_rate_limit:
            return None
        now = time.monotonic()
        with self._lock:
            recent = self._recent[area]
            while recent and now - recent[0] >= 1.0:
                recent.popleft()
            if len(recent) >= _RATE_LIMIT_PER_SECOND:
                self.rate_limited += 1
                return 1.0 - (now - recent[0])
            recent.append(now)
            return None

    def _reference(
        self, entry_type: MockEntryType, entry_id: int, name: str, with_url: bool
    ) -> Any:
        reference: dict[str, Any] = {
            "type": 0,
            "id": entry_id,
            "name": name,
            "entryListId": entry_type.id,
        }
        if with_url:
            reference["url"] = f"{SITE_URL}/portal/pages/1/reports/1/entries/{entry_id}"
        return reference

    def _row(
        self, entry_type: MockEntryType, entry_id: int, wrap: bool, with_urls: bool
    ) -> dict[str, Any]:
        values = entry_type.entries[entry_id]
        row: dict[str, Any] = {"EntryId": entry_id}
        for field in entry_type.fields:
            value = values.get(field.api_name)
            if field.system_field_type == 9:
                value = self._reference(entry_type, entry_id, str(value), with_urls)
            elif field.is_multi_select and value is not None:
                items = value if isinstance(value, list) else [value]
                # Without wrapIntoArrays, a single value comes back bare.
                value = items if wrap or len(items) != 1 else items[0]
            row[field.api_name] = value
        return row

    def handle(
        self, method: str, path: str, query: dict[str, list[str]], body: Any
    ) -> tuple[int, Any]:
        parts = path.removeprefix(_API_PREFIX).strip("/").split("/")
        is_row_query = parts[:5] == ["v4", "data", "entrydata", "rows", "query"]
        if method != ("POST" if is_row_query else "GET"):
            return 405, {"message": f"{method} is not allowed on {path}"}
        if parts[:3] == ["v4", "schema", "entrytypes"]:
            if len(parts) == 3:
                return 200, [
                    {
                        "apiName": entry_type.api_name,
                        "singularName": entry_type.api_name,
                        "pluralName": entry_type.plural_name,
                        "entryListType": entry_type.entry_list_type,
                        "entryListSubType": 0,
                        "id": entry_type.id,
                        "name": entry_type.api_name,
                        "entryListId": -5,
                    }
                    for entry_type in self.entry_types.values()
                ]
            entry_type = self.entry_types.get(int(parts[3]))
            if entry_type is None or parts[4:] != ["fields"]:
                return 404, {"message": "not found"}
            return 200, [
                {
                    "apiName": field.api_name,
                    "fieldType": field.field_type,
                    "systemFieldType": field.system_field_type,
                    "id": field.id,
                    "name": field.name,
                    "entryListId": entry_type.id,
                    "isMultiSelect": field.is_multi_select,
                }
                for field in entry_type.fields
            ]
        if parts[:3] == ["v4", "schema", "users"]:
            active_only = query.get("activeOnly", ["false"])[0] == "true"
            return 200, [
                {"email": email, "id": user_id, "name": f"User {user_id}"}
                for user_id, (email, is_active) in self.users.items()
                if is_active or not active_only
            ]
        if is_row_query:
            return self._query_rows(self.entry_types.get(int(parts[5])), body)
        if parts[:3] == ["v4", "data", "entrydata"] and len(parts) >= 5:
            entry_type = self.entry_types.get(int(parts[3]))
            if entry_type is None:
                return 404, {"message": "not found"}
            if parts[4:] == ["entries"]:
                return 200, [
                    {
                        "id": entry_id,
                        "name": str(entry_id),
                        "entryListId": entry_type.id,
                    }
                    for entry_id in entry_type.entries
                ]
            if parts[4:] == ["entries", "allHistory"]:
                return self._history(entry_type, query)
        if parts[:4] == ["v1", "management", "user", "group"]:
            if len(parts) == 5:
                group = self.groups.get(int(parts[4]))
                return (200, group) if group else (404, {"message": "not found"})
            page_number = int(query.get("pageNumber", ["1"])[0])
            page_size = int(query.get("pageSize", ["1000"])[0])
            groups = list(self.groups.values())
            start = (page_number - 1) * page_size
            return 200, [
                {"id": group["id"], "name": group["name"]}
                for group in groups[start : start + page_size]
            ]
        return 404, {"message": f"no such endpoint {method} {path}"}

    def _history(
        self, entry_type: MockEntryType, query: dict[str, list[str]]
    ) -> tuple[int, Any]:
        raw = query.get("modifiedSince", [""])[0]
        if not _MODIFIED_SINCE_FORMAT.match(raw):
            return 400, {
                "message": "modifiedSince must be like 2020-04-26T01:16:40.030Z"
            }
        since = datetime.strptime(raw, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
            tzinfo=timezone.utc
        )
        floor = max(since, datetime.now(timezone.utc) - _HISTORY_RETENTION)
        latest: dict[int, MockChange] = {}
        for change in self.changes[entry_type.id]:
            if change.at >= floor:
                latest[change.entry_id] = change
        return 200, [
            {
                "isDeleted": change.is_deleted,
                "id": change.entry_id,
                "name": change.name,
                "entryListId": entry_type.id,
            }
            for change in latest.values()
        ]

    def _query_rows(
        self, entry_type: MockEntryType | None, body: Any
    ) -> tuple[int, Any]:
        if entry_type is None:
            return 404, {"message": "not found"}
        match = _ENTRY_ID_QUERY.match(str(body.get("query", "")))
        if match is None:
            return 400, {"message": f"unsupported query {body.get('query')!r}"}
        wanted = [int(entry_id) for entry_id in match.group(1).split(",") if entry_id]
        found = [entry_id for entry_id in wanted if entry_id in entry_type.entries]
        skip = int(body.get("skip", 0))
        limit = min(int(body.get("limit", 1000)), self.max_rows_per_query)
        # Newest first, so a caller that relied on the order would show it.
        page = sorted(found, reverse=True)[skip : skip + limit]
        wrap = bool(body.get("wrapIntoArrays", False))
        with_urls = bool(body.get("resolveReferenceUrls", False))
        return 200, {
            "totalRecords": len(found),
            "rows": [
                self._row(entry_type, entry_id, wrap, with_urls) for entry_id in page
            ],
        }


def _handler(site: MockSite) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002, ARG002
            return

        def _answer(
            self, status: int, body: Any, headers: dict[str, str] | None = None
        ) -> None:
            payload = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(payload)

        def _serve(self, method: str) -> None:
            url = urlsplit(self.path)
            raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            site.requests.append((method, url.path))
            if url.path == f"{_API_PREFIX}/v1/oauth/token":
                is_form = (self.headers.get("Content-Type") or "").startswith(
                    "application/x-www-form-urlencoded"
                )
                if method != "POST" or not is_form:
                    self._answer(400, {"error": "invalid_request"})
                    return
                status, body = site.issue_token(parse_qs(raw.decode()))
                self._answer(status, body)
                return
            area = _area(url.path)
            wait = site.seconds_until_allowed(area)
            if wait is not None:
                reset = datetime.now(timezone.utc) + timedelta(seconds=wait)
                self._answer(
                    429,
                    {
                        "message": "API calls quota exceeded! maximum admitted 5 per 1 second"
                    },
                    {
                        "X-Rate-Limit-Limit": "1s",
                        "X-Rate-Limit-Remaining": "0",
                        # Seven fraction digits and a Z, as DealCloud sends.
                        "X-Rate-Limit-Reset": reset.strftime("%Y-%m-%dT%H:%M:%S.%f")
                        + "0Z",
                    },
                )
                return
            denied = site.check_token(
                self.headers.get("Authorization"), _SCOPE_BY_AREA[area]
            )
            if denied is not None:
                self._answer(denied, {"message": "unauthorized"})
                return
            status, body = site.handle(
                method,
                url.path,
                parse_qs(url.query),
                json.loads(raw) if raw else None,
            )
            self._answer(status, body)

        def do_GET(self) -> None:  # noqa: N802
            self._serve("GET")

        def do_POST(self) -> None:  # noqa: N802
            self._serve("POST")

    return Handler


@contextmanager
def serve(site: MockSite) -> Iterator[None]:
    """Runs the site on a local port and sends the gateway's requests for
    SITE_URL to it. Only the address changes: the gateway still builds every
    URL, header and body, and reads every answer as a stream."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(site))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    local = f"http://127.0.0.1:{server.server_address[1]}"

    def forward(url: str, **kwargs: Any) -> requests.Response:
        if not url.startswith(SITE_URL):
            raise RuntimeError(f"Request left the mock site: {url}")
        for policy in (
            "allow_private_network",
            "block_loopback_and_link_local",
            "block_link_local_only",
            "https_only",
        ):
            kwargs.pop(policy)
        return requests.request(
            kwargs.pop("method"),
            local + url.removeprefix(SITE_URL),
            allow_redirects=False,
            **kwargs,
        )

    try:
        with patch.object(source_operations, "ssrf_safe_request", forward):
            yield
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
