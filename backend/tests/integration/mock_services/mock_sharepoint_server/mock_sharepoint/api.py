"""The Microsoft surface: Entra sign-in, Graph, SharePoint REST and download
URLs. Routing, auth, RU, latency and the handlers.

Every call goes through `MockMicrosoftApi.handle`.
"""

import asyncio
import base64
import bisect
import json
import random
import re
import time
import uuid
from collections import deque
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import parse_qsl, quote, unquote

from pydantic import BaseModel, Field

from . import content as content_mod
from .auth import (
    AppToken,
    DownloadToken,
    handle_token_request,
    instance_discovery,
    mint_download_token,
    openid_configuration,
    parse_access_token,
    parse_download_token,
)
from .corpus import (
    ENTRA_GROUP_TYPE,
    SITE_GROUP_TYPE,
    USER_TYPE,
    Corpus,
    CorpusError,
    FileRequest,
    MockDrive,
    MockEntraGroup,
    MockItem,
    MockPage,
    MockSite,
    MockUser,
    Principal,
    RoleAssignment,
    encode_path,
)
from .quota import RuCost, RuTracker, ThrottleDecision
from .responses import (
    MockResponse,
    graph_error,
    invalid_request,
    item_not_found,
    json_response,
    rest_error,
    rest_not_found,
    unauthenticated,
)
from .settings import GRAPH_BASE, GRAPH_HOST, MockSettings
from .stats import CallRecord, Stats

Surface = Literal["login", "graph", "sharepoint"]
# A SharePoint REST handler: the request, the site, and the groups its route
# pattern captured.
_RestHandler = Callable[..., MockResponse]
LatencyClass = Literal["token", "metadata", "list", "content", "rest"]

_KNOWN_PREFERENCES = frozenset(
    {
        "hierarchicalsharing",
        "deltashowremovedasdeleted",
        "deltatraversepermissiongaps",
        "deltashowsharingchanges",
    }
)
_CONTENT_REDIRECT_TTL_SECONDS = 300
_MAX_PAGE_SIZE = 5_000
_ROLE_NAMES = {
    1: "Limited Access",
    2: "Read",
    3: "Contribute",
    5: "Full Control",
    6: "Edit",
}
_GRAPH_ROLES = {1: "read", 2: "read", 3: "write", 5: "owner", 6: "write"}
_DISPLAY_NAME_FILTER = re.compile(r"^displayName eq '(.*)'$")
_RESYNC_MESSAGE = (
    "Resync required. Replace any local items with the server's version "
    "(including deletes) if you're sure that the service was up to date with "
    "your local changes when you last sync'd. Upload any local changes that "
    "the server doesn't know about."
)


class ApiRequest(BaseModel):
    method: str
    surface: Surface
    # The SharePoint host of a `sharepoint` call.
    host: str = ""
    # Decoded one time, without the leading slash or the query string.
    path: str
    query: dict[str, str]
    # Lower-case names.
    headers: dict[str, str]
    body: bytes = b""


class OpSpec(BaseModel):
    name: str
    cost: RuCost
    latency: LatencyClass


class WalkHook(BaseModel):
    """A change the server makes during a walk: after the Nth children or
    delta call on a drive, counted from when the hook is set."""

    id: int = 0
    drive_id: str
    op: Literal["children", "delta"] = "children"
    after_calls: int = Field(default=1, ge=1)
    action: Literal["create", "modify", "delete"] = "create"
    # The file to create.
    file: FileRequest | None = None
    # The file to modify or delete.
    file_id: str | None = None
    # New content of a modified file. None makes new generated content.
    text: str | None = None
    calls_seen: int = 0
    fired: bool = False
    result_file_id: str | None = None
    error: str | None = None


class _DeltaCursor(BaseModel):
    """The state in an opaque delta token."""

    # "next" continues an enumeration. "delta" starts the next one.
    kind: Literal["next", "delta"]
    drive_id: str
    generation: int
    # Only changes after this sequence number.
    since: int = 0
    # Only changes after this time (a timestamp token).
    since_time: datetime | None = None
    # The last sequence number an earlier page returned.
    after: int = 0
    top: int | None = None
    select: str | None = None


def _encode(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode(value: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def graph_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _graph_url(path: str, params: dict[str, str]) -> str:
    """A Graph URL on the real host, for a link in a response."""
    query = "&".join(f"{key}={quote(value, safe='')}" for key, value in params.items())
    return f"{GRAPH_BASE}/{path}" + (f"?{query}" if query else "")


def _page_size(query: dict[str, str], default: int) -> int | None:
    """The page size a call asks for. None for a $top that is not valid."""
    raw = query.get("$top")
    if raw is None:
        return default
    if not raw.isdigit() or int(raw) < 1:
        return None
    return min(int(raw), _MAX_PAGE_SIZE)


def _select(payload: dict[str, Any], select: str | None) -> dict[str, Any]:
    """Applies $select to one entity. `id` and the annotations stay."""
    if not select:
        return payload
    fields = {field.strip() for field in select.split(",")}
    if "content.downloadUrl" in fields:
        fields.add("@microsoft.graph.downloadUrl")
    return {
        key: value
        for key, value in payload.items()
        if key in fields
        or key == "id"
        or (key.startswith("@") and key != "@microsoft.graph.downloadUrl")
    }


async def _wait(seconds: float) -> None:
    """The latency the settings ask for."""
    await asyncio.sleep(seconds)  # test-flakes: allow the mock's set latency


def _odata_literal(value: str) -> str:
    """The text of a quoted OData string literal."""
    return value.replace("''", "'")


class MockMicrosoftApi:
    def __init__(self, settings: MockSettings) -> None:
        self.settings = settings
        self.corpus = Corpus(settings.corpus)
        self.quota = RuTracker(settings.quota)
        self.stats = Stats()
        self.hooks: list[WalkHook] = []
        self.unmatched: deque[str] = deque(maxlen=50)
        # Delta tokens of an older generation answer 410 Gone.
        self.delta_generation = 0
        self._rng = random.Random(settings.corpus.seed ^ 0x5EED)

    def update_settings(self, settings: MockSettings) -> None:
        self.settings = settings
        self.quota.update_settings(settings.quota)

    def regenerate(self, settings: MockSettings) -> None:
        self.settings = settings
        self.corpus = Corpus(settings.corpus)
        self.quota = RuTracker(settings.quota)
        self.hooks = []
        self.unmatched.clear()
        self.delta_generation = 0
        self.stats.reset()

    def touch(self, count: int, file_ids: list[str] | None) -> list[str]:
        return self.corpus.touch(count, file_ids, self._rng)

    def add_hook(self, hook: WalkHook) -> WalkHook:
        if hook.drive_id not in self.corpus.drives:
            raise CorpusError(f"No drive {hook.drive_id}")
        if hook.action == "create" and hook.file is None:
            raise CorpusError("A create hook needs `file`")
        if hook.action != "create" and hook.file_id is None:
            raise CorpusError(f"A {hook.action} hook needs `file_id`")
        armed = hook.model_copy(
            update={"id": len(self.hooks) + 1, "calls_seen": 0, "fired": False}
        )
        self.hooks.append(armed)
        return armed

    def _run_hooks(self, op: Literal["children", "delta"], drive_id: str) -> None:
        for hook in self.hooks:
            if hook.fired or hook.op != op or hook.drive_id != drive_id:
                continue
            hook.calls_seen += 1
            if hook.calls_seen < hook.after_calls:
                continue
            hook.fired = True
            try:
                if hook.action == "create" and hook.file is not None:
                    hook.result_file_id = self.corpus.add_file(hook.file).id
                elif hook.action == "modify" and hook.file_id is not None:
                    self.corpus.modify_file(hook.file_id, hook.text)
                    hook.result_file_id = hook.file_id
                elif hook.file_id is not None:
                    self.corpus.delete_item(hook.file_id)
                    hook.result_file_id = hook.file_id
            except CorpusError as e:
                hook.error = str(e)

    # --- the request pipeline ---

    async def handle(self, request: ApiRequest) -> MockResponse:
        started = time.monotonic()
        user_agent = request.headers.get("user-agent")
        if request.surface == "login":
            return await self._handle_login(request, started)

        route = self._route(request)
        if route is None:
            self.unmatched.append(f"{request.method} {request.surface}/{request.path}")
            name = f"{'graph' if request.surface == 'graph' else 'rest'}.unmatched"
            response = (
                graph_error(400, "BadRequest", "Resource not found for the segment.")
                if request.surface == "graph"
                else rest_not_found("Cannot find resource for the request.")
            )
            self.stats.record(
                CallRecord(op=name, status=response.status, user_agent=user_agent)
            )
            return response
        spec, handler = route

        def record(
            response: MockResponse,
            app: str | None,
            ru: int = 0,
            during_pause: bool = False,
        ) -> MockResponse:
            self.stats.record(
                CallRecord(
                    op=spec.name,
                    status=response.status,
                    ru=ru,
                    nbytes=len(response.body),
                    duration_ms=(time.monotonic() - started) * 1000,
                    app=app,
                    throttled=response.throttled,
                    during_pause=during_pause,
                    downloaded_item_id=response.downloaded_item_id,
                    canvas_expanded="canvaslayout"
                    in request.query.get("$expand", "").lower(),
                    user_agent=user_agent,
                )
            )
            return response

        app_or_refusal = self._authenticate(request, spec)
        if isinstance(app_or_refusal, MockResponse):
            return record(app_or_refusal, None)
        app = app_or_refusal

        faults = self.settings.faults
        if faults.server_error_rate and self._rng.random() < faults.server_error_rate:
            status = self._rng.choice([500, 503])
            await self._sleep(spec.latency, 0)
            return record(
                graph_error(
                    status,
                    "generalException" if status == 500 else "serviceNotAvailable",
                    "The service is temporarily unavailable.",
                ),
                app,
            )

        cost = self.quota.cost(spec.cost)
        # The download host is not Graph: the Graph limits and the pause of
        # the app do not apply to a download URL.
        decision = (
            None
            if spec.name == "download_url.get"
            else self.quota.consume(app, cost, time.monotonic())
        )
        if decision is not None:
            if self.settings.latency.enabled:
                await _wait(self.settings.latency.throttled_ms / 1000)
            charged = cost if self.settings.quota.count_throttled_calls else 0
            return record(
                self._throttled(decision), app, charged, decision.scope == "pause"
            )

        response = handler(request)
        await self._sleep(spec.latency, len(response.body))
        return record(response, app, cost)

    async def _handle_login(self, request: ApiRequest, started: float) -> MockResponse:
        tenant, _, rest = request.path.partition("/")
        corpus = self.corpus
        known = frozenset(
            {
                corpus.tenant_id.lower(),
                f"{corpus.settings.tenant}.onmicrosoft.com",
                "common",
                "organizations",
            }
        )
        if request.path == "common/discovery/instance":
            op, response = (
                "login.instance_discovery",
                json_response(200, instance_discovery()),
            )
        elif rest in (
            "v2.0/.well-known/openid-configuration",
            ".well-known/openid-configuration",
        ):
            op = "login.openid_configuration"
            if tenant.lower() in known:
                response = json_response(200, openid_configuration(tenant))
            else:
                response = json_response(
                    400,
                    {
                        "error": "invalid_tenant",
                        "error_description": f"AADSTS90002: Tenant '{tenant}' not "
                        "found.",
                    },
                )
        elif rest == "oauth2/v2.0/token" and request.method == "POST":
            op = "login.token"
            form = dict(parse_qsl(request.body.decode(), keep_blank_values=True))
            response = handle_token_request(
                form, tenant, known, corpus.tenant_id, self.settings.auth
            )
        else:
            op, response = "login.unmatched", json_response(404, {"error": "not_found"})
            self.unmatched.append(f"{request.method} login/{request.path}")
        if self.settings.latency.enabled:
            await _wait(self.settings.latency.token_ms / 1000)
        self.stats.record(
            CallRecord(
                op=op,
                status=response.status,
                nbytes=len(response.body),
                duration_ms=(time.monotonic() - started) * 1000,
                user_agent=request.headers.get("user-agent"),
            )
        )
        return response

    def _authenticate(self, request: ApiRequest, spec: OpSpec) -> str | MockResponse:
        """The app of the call, or the refusal to send."""
        if spec.name == "download_url.get":
            download = parse_download_token(request.query.get("tempauth"))
            if download is None:
                return rest_error(401, "-2147024891", "Access denied.")
            return download.app
        token = parse_access_token(request.headers.get("authorization"))
        if token is None or token.tenant_id != self.corpus.tenant_id:
            if request.surface == "graph":
                return unauthenticated()
            return rest_error(401, "-2147024891", "Access denied.")
        if request.surface == "graph":
            if token.audience != f"https://{GRAPH_HOST}":
                return unauthenticated(
                    "Access token validation failure. Invalid audience."
                )
            return token.app
        return self._check_rest_token(request, token)

    def _check_rest_token(
        self, request: ApiRequest, token: AppToken
    ) -> str | MockResponse:
        if token.audience.lower() != f"https://{request.host}".lower():
            return json_response(
                401,
                {
                    "error_description": f"Invalid audience Uri '{token.audience}'.",
                },
            )
        if self.settings.auth.rest_requires_certificate and not token.certificate:
            return json_response(
                401,
                {
                    "error_description": "Unsupported app only token.",
                },
            )
        return token.app

    def _throttled(self, decision: ThrottleDecision) -> MockResponse:
        status = self.settings.quota.throttle_status
        headers: dict[str, str] = {}
        if decision.retry_after is not None:
            headers["retry-after"] = str(decision.retry_after)
        if status == 503:
            code = "serviceNotAvailable"
        elif decision.scope == "day":
            code = "activityLimitReached"
        else:
            code = "TooManyRequests"
        response = graph_error(status, code, "The request has been throttled.", headers)
        response.throttled = True
        return response

    async def _sleep(self, latency: LatencyClass, nbytes: int) -> None:
        settings = self.settings.latency
        if not settings.enabled:
            return
        base_ms = {
            "token": settings.token_ms,
            "metadata": settings.metadata_ms,
            "list": settings.list_ms,
            "content": settings.content_ms,
            "rest": settings.rest_ms,
        }[latency]
        factor = 1 + self._rng.uniform(-settings.jitter, settings.jitter)
        transfer = nbytes / settings.bandwidth_bytes_per_second
        await _wait(base_ms * factor / 1000 + transfer)

    # --- routing ---

    def _route(
        self, request: ApiRequest
    ) -> tuple[OpSpec, Callable[[ApiRequest], MockResponse]] | None:
        if request.method != "GET":
            return None
        if request.surface == "graph":
            version, _, path = request.path.partition("/")
            if version != "v1.0":
                return None
            return self._route_graph(path.rstrip("/"), "token" in request.query)
        return self._route_sharepoint(request)

    def _route_graph(
        self, path: str, has_token: bool
    ) -> tuple[OpSpec, Callable[[ApiRequest], MockResponse]] | None:
        def op(
            name: str,
            cost: RuCost,
            latency: LatencyClass,
            handler: Callable[[ApiRequest], MockResponse],
        ) -> tuple[OpSpec, Callable[[ApiRequest], MockResponse]]:
            return OpSpec(name=name, cost=cost, latency=latency), handler

        parts = path.split("/")
        head = parts[0]
        if head == "sites" and len(parts) >= 2:
            if parts[1] == "getAllSites" and len(parts) == 2:
                return op("graph.sites.list", "other", "list", self._list_sites)
            if ":" in path:
                # sites/{hostname}:/{server-relative path}
                host, _, site_path = path[len("sites/") :].partition(":")
                site_path = site_path.rstrip(":")
                return op(
                    "graph.site.get",
                    "other",
                    "metadata",
                    lambda _r: self._get_site(
                        self.corpus.site_by_path(host, site_path)
                    ),
                )
            site_id = parts[1]
            rest = parts[2:]
            if not rest:
                if site_id == "root":
                    return op(
                        "graph.site.get", "other", "metadata", self._get_root_site
                    )
                return op(
                    "graph.site.get",
                    "other",
                    "metadata",
                    lambda _r: self._get_site(self.corpus.site_by_graph_id(site_id)),
                )
            if rest == ["drives"]:
                return op(
                    "graph.site.drives",
                    "other",
                    "list",
                    lambda r: self._list_drives(r, site_id),
                )
            if rest[0] == "pages":
                tail = [part for part in rest[1:] if part != "microsoft.graph.sitePage"]
                if not tail:
                    return op(
                        "graph.site.pages.list",
                        "other",
                        "list",
                        lambda r: self._list_pages(r, site_id),
                    )
                if len(tail) == 1:
                    return op(
                        "graph.site.page.get",
                        "other",
                        "metadata",
                        lambda r: self._get_page(r, site_id, tail[0]),
                    )
            return None

        if head == "drives" and len(parts) >= 2:
            return self._route_drive(parts[1], parts[2:], has_token, op)

        if head == "groups":
            if len(parts) == 1:
                return op("graph.groups.list", "other", "list", self._list_groups)
            group_id = parts[1]
            if len(parts) == 2:
                return op(
                    "graph.group.get",
                    "other",
                    "metadata",
                    lambda r: self._get_group(r, group_id),
                )
            if parts[2] in ("members", "transitiveMembers") and len(parts) <= 4:
                transitive = parts[2] == "transitiveMembers"
                cast = parts[3] if len(parts) == 4 else None
                if cast not in (None, "microsoft.graph.group", "microsoft.graph.user"):
                    return None
                return op(
                    "graph.group.transitive_members"
                    if transitive
                    else "graph.group.members",
                    "other",
                    "list",
                    lambda r: self._list_group_members(r, group_id, transitive, cast),
                )
            return None

        if head == "users" and len(parts) == 1:
            return op("graph.users.list", "other", "list", self._list_users)
        if head == "users" and len(parts) == 2:
            return op(
                "graph.user.get",
                "other",
                "metadata",
                lambda r: self._get_user(r, parts[1]),
            )
        match = re.fullmatch(r"users\('(.*)'\)", path)
        if match:
            identifier = _odata_literal(match.group(1))
            return op(
                "graph.user.get",
                "other",
                "metadata",
                lambda r: self._get_user(r, identifier),
            )
        return None

    def _route_drive(
        self,
        drive_id: str,
        rest: list[str],
        has_token: bool,
        op: Callable[..., tuple[OpSpec, Callable[[ApiRequest], MockResponse]]],
    ) -> tuple[OpSpec, Callable[[ApiRequest], MockResponse]] | None:
        if not rest:
            return op(
                "graph.drive.get",
                "other",
                "metadata",
                lambda r: self._get_drive(r, drive_id),
            )

        # An item is named by id, as the root, or by path: root:/{path}:
        locate: Callable[[MockDrive], MockItem | None]
        if rest[0] == "items" and len(rest) >= 2:
            item_id = rest[1]
            action = rest[2:]

            def locate(drive: MockDrive) -> MockItem | None:
                item = self.corpus.items.get(item_id)
                if item is None or item.deleted or item.drive_id != drive.id:
                    return None
                return item

        elif rest[0] == "root":
            action = rest[1:]

            def locate(drive: MockDrive) -> MockItem | None:
                return self.corpus.items[drive.root_id]

        elif rest[0] == "root:":
            joined = "/".join(rest[1:])
            item_path, separator, tail = joined.partition(":/")
            if not separator:
                item_path, tail = joined.rstrip(":"), ""
            action = [tail] if tail else []

            def locate(drive: MockDrive) -> MockItem | None:
                return self.corpus.item_by_path(drive, item_path)

        else:
            return None

        def with_item(
            handler: Callable[[ApiRequest, MockDrive, MockItem], MockResponse],
        ) -> Callable[[ApiRequest], MockResponse]:
            def run(request: ApiRequest) -> MockResponse:
                drive = self.corpus.drives.get(drive_id)
                item = locate(drive) if drive is not None else None
                if drive is None or item is None:
                    return item_not_found()
                return handler(request, drive, item)

            return run

        if not action:
            return op(
                "graph.item.get", "item_get", "metadata", with_item(self._get_item)
            )
        if action == ["children"]:
            return op(
                "graph.drive.children",
                "list_children",
                "list",
                with_item(self._list_children),
            )
        if action == ["delta"] and rest[0] == "root":
            return op(
                "graph.drive.delta",
                "delta_with_token" if has_token else "delta_without_token",
                "list",
                with_item(self._delta),
            )
        if action == ["content"]:
            return op(
                "graph.item.content", "download", "content", with_item(self._content)
            )
        if action == ["permissions"]:
            return op(
                "graph.item.permissions",
                "permission",
                "list",
                with_item(self._list_permissions),
            )
        if action == ["listItem"]:
            return op(
                "graph.item.list_item",
                "item_get",
                "metadata",
                with_item(self._list_item),
            )
        return None

    def _route_sharepoint(
        self, request: ApiRequest
    ) -> tuple[OpSpec, Callable[[ApiRequest], MockResponse]] | None:
        path = request.path
        lower = path.lower()
        if lower.endswith("/_layouts/15/download.aspx"):
            return (
                OpSpec(name="download_url.get", cost="download_url", latency="content"),
                self._download,
            )
        marker = lower.find("/_api/")
        if marker < 0:
            return None
        site_path, api = path[:marker], path[marker + len("/_api/") :].rstrip("/")
        routes: list[tuple[str, str, _RestHandler]] = [
            (r"web", "rest.web.get", self._rest_web),
            (r"web/roleassignments", "rest.role_assignments", self._rest_web_roles),
            (
                r"web/lists/getbyid\('([^']+)'\)/roleassignments",
                "rest.role_assignments",
                self._rest_list_roles,
            ),
            (
                r"web/lists/getbyid\('([^']+)'\)/items(?:/getbyid)?\((\d+)\)"
                r"/roleassignments",
                "rest.role_assignments",
                self._rest_item_roles,
            ),
            (
                r"web/getfilebyserverrelativeurl\('(.+)'\)/listitemallfields"
                r"/roleassignments",
                "rest.role_assignments",
                self._rest_file_roles,
            ),
            (
                r"web/getfolderbyid\('([^']+)'\)/listitemallfields/roleassignments",
                "rest.role_assignments",
                self._rest_folder_roles,
            ),
            (
                r"web/sitegroups/getbyname\('(.+)'\)/users",
                "rest.site_group_users",
                self._rest_group_users,
            ),
            (
                r"web/getfolderbyserverrelativepath\(decodedurl=@a\)",
                "rest.folder.get",
                self._rest_folder,
            ),
        ]
        for pattern, name, handler in routes:
            found = re.fullmatch(pattern, api, flags=re.IGNORECASE)
            if found is None:
                continue
            arguments = found.groups()

            def run(
                request: ApiRequest,
                handler: _RestHandler = handler,
                arguments: tuple[str, ...] = arguments,
            ) -> MockResponse:
                site = self.corpus.site_by_path(request.host, site_path)
                if site is None or site.personal:
                    return rest_not_found("The site does not exist.")
                return handler(request, site, *arguments)

            return OpSpec(name=name, cost="rest", latency="rest"), run
        return None

    # --- paging ---

    def _paged(
        self,
        request: ApiRequest,
        values: list[Any],
        default_size: int,
        path: str,
    ) -> MockResponse | tuple[list[Any], str | None]:
        """One page of a Graph collection and its next link."""
        size = _page_size(request.query, default_size)
        if size is None:
            return invalid_request("Invalid value for $top.")
        offset = 0
        skiptoken = request.query.get("$skiptoken")
        if skiptoken is not None:
            cursor = _decode(skiptoken)
            if cursor is None or not isinstance(cursor.get("o"), int):
                return invalid_request("The $skiptoken is not valid.")
            offset = cursor["o"]
        page = values[offset : offset + size]
        if offset + size >= len(values):
            return page, None
        params = {k: v for k, v in request.query.items() if k != "$skiptoken"}
        params["$skiptoken"] = _encode({"o": offset + size})
        return page, _graph_url(path, params)

    # --- Graph: sites, drives, pages ---

    def _site_json(self, site: MockSite) -> dict[str, Any]:
        host = site.web_url.split("/")[2]
        payload: dict[str, Any] = {
            "id": self.corpus.site_graph_id(site),
            "createdDateTime": graph_time(site.created),
            "lastModifiedDateTime": graph_time(site.created),
            "name": site.name.rpartition("/")[2],
            "displayName": site.display_name,
            "webUrl": site.web_url,
            "siteCollection": {"hostname": host},
        }
        if site.personal:
            payload["isPersonalSite"] = True
        return payload

    def _list_sites(self, request: ApiRequest) -> MockResponse:
        sites = [self._site_json(site) for site in self.corpus.sites.values()]
        paged = self._paged(
            request,
            sites,
            self.settings.paging.sites_page_size,
            "sites/getAllSites",
        )
        if isinstance(paged, MockResponse):
            return paged
        page, next_link = paged
        payload: dict[str, Any] = {
            "@odata.context": f"{GRAPH_BASE}/$metadata#sites",
            "value": page,
        }
        if next_link:
            payload["@odata.nextLink"] = next_link
        return json_response(200, payload)

    def _get_site(self, site: MockSite | None) -> MockResponse:
        if site is None:
            return item_not_found()
        return json_response(200, self._site_json(site))

    def _get_root_site(self, _request: ApiRequest) -> MockResponse:
        corpus = self.corpus
        host = corpus.sharepoint_host
        site_guid = uuid.uuid5(uuid.NAMESPACE_DNS, f"{corpus.tenant_id}.site")
        web_guid = uuid.uuid5(uuid.NAMESPACE_DNS, f"{corpus.tenant_id}.web")
        created = graph_time(corpus.settings.base_time)
        return json_response(
            200,
            {
                "id": f"{host},{site_guid},{web_guid}",
                "createdDateTime": created,
                "lastModifiedDateTime": created,
                "name": "",
                "displayName": "Communication site",
                "webUrl": f"https://{host}",
                "root": {},
                "siteCollection": {"hostname": host},
            },
        )

    def _drive_json(self, drive: MockDrive, expand_list: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": drive.id,
            "name": drive.name,
            "description": "",
            "driveType": "documentLibrary",
            "webUrl": self.corpus.drive_web_url(drive),
            "createdDateTime": graph_time(drive.created),
            "lastModifiedDateTime": graph_time(drive.created),
        }
        if expand_list:
            payload["list"] = {"id": drive.list_id}
        return payload

    def _list_drives(self, request: ApiRequest, site_id: str) -> MockResponse:
        site = self.corpus.site_by_graph_id(site_id)
        if site is None:
            return item_not_found()
        expand = request.query.get("$expand", "")
        expand_list = expand == "list" or expand.startswith("list(")
        select = request.query.get("$select")
        if select and expand_list:
            select += ",list"
        drives = [
            _select(self._drive_json(self.corpus.drives[drive_id], expand_list), select)
            for drive_id in site.drive_ids
        ]
        return json_response(
            200, {"@odata.context": f"{GRAPH_BASE}/$metadata#drives", "value": drives}
        )

    def _get_drive(self, request: ApiRequest, drive_id: str) -> MockResponse:
        drive = self.corpus.drives.get(drive_id)
        if drive is None:
            return item_not_found()
        expand = request.query.get("$expand", "")
        return json_response(
            200,
            _select(
                self._drive_json(drive, expand.startswith("list")),
                request.query.get("$select"),
            ),
        )

    def _user_identity(self, user: MockUser) -> dict[str, Any]:
        return {
            "user": {
                "id": user.object_id,
                "displayName": user.display_name,
                "email": user.user_principal_name,
            }
        }

    def _page_json(self, page: MockPage, expand_canvas: bool) -> dict[str, Any]:
        corpus = self.corpus
        author = self._user_identity(corpus.users[page.author])
        payload: dict[str, Any] = {
            "@odata.type": "#microsoft.graph.sitePage",
            "id": page.id,
            "name": page.name,
            "title": page.title,
            "description": page.description,
            "webUrl": corpus.page_web_url(page),
            "createdDateTime": graph_time(page.created),
            "lastModifiedDateTime": graph_time(page.modified),
            "pageLayout": "article",
            "createdBy": author,
            "lastModifiedBy": author,
            "parentReference": {
                "siteId": corpus.site_graph_id(corpus.sites[page.site_name])
            },
        }
        if expand_canvas:
            first, second, third = content_mod.page_paragraphs(
                corpus.settings.seed, page.id, 3
            )
            payload["canvasLayout"] = {
                "horizontalSections": [
                    {
                        "layout": "oneColumn",
                        "id": "1",
                        "emphasis": "none",
                        "columns": [
                            {
                                "id": "1",
                                "width": 12,
                                "webparts": [
                                    {
                                        "@odata.type": "#microsoft.graph.textWebPart",
                                        "id": str(
                                            uuid.uuid5(uuid.NAMESPACE_OID, page.id)
                                        ),
                                        "innerHtml": f"<h2>{page.title}</h2>"
                                        f"<p>{first}</p><p>{second}</p>",
                                    },
                                    {
                                        "@odata.type": "#microsoft.graph.standardWebPart",
                                        "id": str(
                                            uuid.uuid5(
                                                uuid.NAMESPACE_OID, page.id + "s"
                                            )
                                        ),
                                        "webPartType": "mock-web-part",
                                        "data": {
                                            "title": f"{page.title} links",
                                            "description": "Quick links",
                                            "serverProcessedContent": {
                                                "searchablePlainTexts": [
                                                    {
                                                        "key": "items[0].title",
                                                        "value": third,
                                                    }
                                                ]
                                            },
                                        },
                                    },
                                ],
                            }
                        ],
                    }
                ]
            }
        return payload

    def _corrupt_canvas(self) -> MockResponse:
        return invalid_request("Invalid request")

    def _list_pages(self, request: ApiRequest, site_id: str) -> MockResponse:
        site = self.corpus.site_by_graph_id(site_id)
        if site is None:
            return item_not_found()
        expand = "canvaslayout" in request.query.get("$expand", "").lower()
        pages = [self.corpus.pages[page_id] for page_id in site.page_ids]
        # One corrupt page fails the expansion of the whole listing.
        if expand and any(page.corrupt_canvas for page in pages):
            return self._corrupt_canvas()
        path = f"sites/{self.corpus.site_graph_id(site)}/pages/microsoft.graph.sitePage"
        paged = self._paged(
            request, pages, self.settings.paging.site_pages_page_size, path
        )
        if isinstance(paged, MockResponse):
            return paged
        page_items, next_link = paged
        payload: dict[str, Any] = {
            "@odata.context": f"{GRAPH_BASE}/$metadata#sites('{site_id}')/pages",
            "value": [self._page_json(page, expand) for page in page_items],
        }
        if next_link:
            payload["@odata.nextLink"] = next_link
        return json_response(200, payload)

    def _get_page(
        self, request: ApiRequest, site_id: str, page_id: str
    ) -> MockResponse:
        site = self.corpus.site_by_graph_id(site_id)
        page = self.corpus.pages.get(page_id)
        if site is None or page is None or page.site_name != site.name:
            return item_not_found()
        expand = "canvaslayout" in request.query.get("$expand", "").lower()
        if expand and page.corrupt_canvas:
            return self._corrupt_canvas()
        return json_response(200, self._page_json(page, expand))

    # --- Graph: drive items ---

    def _download_url(self, item: MockItem, app: str, ttl_seconds: int) -> str:
        site = self.corpus.site_of(self.corpus.drives[item.drive_id])
        token = mint_download_token(
            DownloadToken(
                drive_id=item.drive_id,
                item_id=item.id,
                app=app,
                expires_at=time.time() + ttl_seconds,
            )
        )
        return (
            f"{site.web_url}/_layouts/15/download.aspx?UniqueId={item.unique_id}"
            f"&Translate=false&tempauth={token}&ApiVersion=2.0"
        )

    def _app_of(self, request: ApiRequest) -> str:
        token = parse_access_token(request.headers.get("authorization"))
        if token is None:
            raise RuntimeError("Bug: a handler ran for a call with no token")
        return token.app

    def _shared_facet(
        self, item: MockItem, hierarchical: bool, sharing_changed: bool
    ) -> dict[str, Any] | None:
        scope = item.sharing_links[0].scope if item.sharing_links else "users"
        if hierarchical:
            # Only a permission root carries the facet: the library root and
            # each item with unique permissions. An item whose sharing
            # changed to inherited gets an empty facet, as Graph documents.
            if item.is_root or item.unique_assignments is not None:
                return {"scope": scope}
            return {} if sharing_changed else None
        return {"scope": scope} if item.sharing_links else None

    def _item_json(
        self,
        item: MockItem,
        app: str,
        select: str | None,
        hierarchical: bool = False,
        sharing_changed: bool = False,
    ) -> dict[str, Any]:
        corpus = self.corpus
        drive = corpus.drives[item.drive_id]
        site = corpus.site_of(drive)
        tag = f"{{{item.unique_id.upper()}}},{item.version}"
        modified_by = self._user_identity(corpus.users[item.modified_by])
        payload: dict[str, Any] = {
            "id": item.id,
            "name": item.name,
            "createdDateTime": graph_time(item.created),
            "lastModifiedDateTime": graph_time(item.modified),
            "eTag": f'"{tag}"',
            "cTag": f'"c:{tag}"',
            "webUrl": corpus.item_web_url(item),
            "size": item.size,
            "createdBy": modified_by,
            "lastModifiedBy": modified_by,
            "fileSystemInfo": {
                "createdDateTime": graph_time(item.created),
                "lastModifiedDateTime": graph_time(item.modified),
            },
            "sharepointIds": {
                "listId": drive.list_id,
                "listItemId": str(item.list_item_id),
                "listItemUniqueId": item.unique_id,
                "siteId": site.site_guid,
                "siteUrl": site.web_url,
                "tenantId": corpus.tenant_id,
                "webId": site.web_guid,
            },
        }
        parent: dict[str, Any] = {
            "driveType": "documentLibrary",
            "driveId": drive.id,
            "siteId": site.site_guid,
        }
        if item.parent_id is not None:
            folder = corpus.items[item.parent_id]
            folder_path = encode_path("/".join(corpus.path_names(folder)))
            parent["id"] = folder.id
            parent["name"] = folder.name if not folder.is_root else drive.name
            parent["path"] = f"/drives/{drive.id}/root:" + (
                f"/{folder_path}" if folder_path else ""
            )
        else:
            payload["root"] = {}
        payload["parentReference"] = parent
        if item.deleted:
            payload["deleted"] = {"state": "deleted"}
            del payload["webUrl"]
        elif item.is_folder:
            payload["folder"] = {"childCount": len(corpus.children[item.id])}
        else:
            payload["file"] = {"mimeType": item.mime_type}
            payload["@microsoft.graph.downloadUrl"] = self._download_url(
                item, app, self.settings.faults.download_url_ttl_seconds
            )
        shared = (
            None
            if item.deleted
            else self._shared_facet(item, hierarchical, sharing_changed)
        )
        if shared is not None:
            payload["shared"] = shared
        return _select(payload, select)

    def _get_item(
        self, request: ApiRequest, _drive: MockDrive, item: MockItem
    ) -> MockResponse:
        return json_response(
            200,
            self._item_json(item, self._app_of(request), request.query.get("$select")),
        )

    def _list_item(
        self, _request: ApiRequest, drive: MockDrive, item: MockItem
    ) -> MockResponse:
        site = self.corpus.site_of(drive)
        return json_response(
            200,
            {
                "id": str(item.list_item_id),
                "createdDateTime": graph_time(item.created),
                "lastModifiedDateTime": graph_time(item.modified),
                "webUrl": self.corpus.item_web_url(item),
                "parentReference": {"siteId": self.corpus.site_graph_id(site)},
                "contentType": {"name": "Folder" if item.is_folder else "Document"},
            },
        )

    def _list_children(
        self, request: ApiRequest, drive: MockDrive, item: MockItem
    ) -> MockResponse:
        if not item.is_folder:
            return invalid_request("The item is not a folder.")
        path = f"drives/{drive.id}/items/{item.id}/children"
        paged = self._paged(
            request,
            self.corpus.live_children(item.id),
            self.settings.paging.children_page_size,
            path,
        )
        if isinstance(paged, MockResponse):
            return paged
        children, next_link = paged
        app = self._app_of(request)
        select = request.query.get("$select")
        payload: dict[str, Any] = {
            "@odata.context": f"{GRAPH_BASE}/$metadata#drives('{drive.id}')/items",
            "value": [self._item_json(child, app, select) for child in children],
        }
        if next_link:
            payload["@odata.nextLink"] = next_link
        # After the page is built, so this page does not show the change.
        self._run_hooks("children", drive.id)
        return json_response(200, payload)

    def _delta_gone(self, drive: MockDrive, cursor: _DeltaCursor) -> MockResponse:
        params: dict[str, str] = {}
        if cursor.top is not None:
            params["$top"] = str(cursor.top)
        if cursor.select:
            params["$select"] = cursor.select
        location = _graph_url(f"drives/{drive.id}/root/delta", params)
        return graph_error(
            410, "resyncRequired", _RESYNC_MESSAGE, {"location": location}
        )

    def _delta_cursor(
        self, request: ApiRequest, drive: MockDrive
    ) -> _DeltaCursor | MockResponse:
        """The enumeration a delta call asks for, or the refusal to send."""
        query = request.query
        top = _page_size(query, 200)
        if top is None:
            return invalid_request("Invalid value for $top.")
        asked_top = top if "$top" in query else None
        select = query.get("$select")
        raw = query.get("token")
        fresh = _DeltaCursor(
            kind="next",
            drive_id=drive.id,
            generation=self.delta_generation,
            top=asked_top,
            select=select,
        )
        if raw is None:
            return fresh
        if raw == "latest":
            return fresh.model_copy(update={"kind": "delta", "since": self.corpus.seq})

        decoded = _decode(raw)
        if decoded is not None:
            try:
                cursor = _DeltaCursor.model_validate(decoded)
            except ValueError:
                return self._delta_gone(drive, fresh)
            # The query of this call wins over the one in the token.
            cursor.top = asked_top if asked_top is not None else cursor.top
            cursor.select = select if select is not None else cursor.select
            expired = cursor.generation != self.delta_generation or (
                self.settings.faults.expire_delta_tokens and cursor.kind == "delta"
            )
            if expired or cursor.drive_id != drive.id:
                return self._delta_gone(drive, cursor)
            return cursor

        try:
            since_time = datetime.fromisoformat(raw)
        except ValueError:
            return self._delta_gone(drive, fresh)
        if since_time.tzinfo is None:
            since_time = since_time.replace(tzinfo=timezone.utc)
        if self.settings.faults.expire_delta_tokens:
            return self._delta_gone(drive, fresh)
        return fresh.model_copy(update={"since_time": since_time})

    def _delta(
        self, request: ApiRequest, drive: MockDrive, _item: MockItem
    ) -> MockResponse:
        preferences = {
            part.strip().lower()
            for part in request.headers.get("prefer", "").split(",")
            if part.strip()
        }
        applied = sorted(preferences & _KNOWN_PREFERENCES)
        headers = {"preference-applied": ", ".join(applied)} if applied else {}
        cursor = self._delta_cursor(request, drive)
        if isinstance(cursor, MockResponse):
            return cursor

        corpus = self.corpus
        top = cursor.top or 200
        items: list[MockItem] = []
        more = False
        # `token=latest` gives no items, only a link for the changes after now.
        if request.query.get("token") != "latest":
            log = corpus.change_log.get(drive.id, [])
            start = bisect.bisect_right(
                log, (max(cursor.since, cursor.after), "\uffff")
            )
            full_enumeration = cursor.since == 0 and cursor.since_time is None
            for index in range(start, len(log)):
                seq, item_id = log[index]
                item = corpus.items[item_id]
                if item.changed_seq != seq:
                    continue
                if item.deleted and full_enumeration:
                    continue
                if cursor.since_time and item.changed_at <= cursor.since_time:
                    continue
                if len(items) == top:
                    more = True
                    break
                items.append(item)

        app = self._app_of(request)
        hierarchical = "hierarchicalsharing" in preferences
        show_sharing = "deltashowsharingchanges" in preferences
        value: list[dict[str, Any]] = []
        for item in items:
            # A sequence cursor compares sequence numbers, a time cursor
            # compares times.
            sharing_changed = bool(
                cursor.since and item.sharing_changed_seq > cursor.since
            ) or bool(
                cursor.since_time
                and item.sharing_changed_at
                and item.sharing_changed_at > cursor.since_time
            )
            payload = self._item_json(
                item, app, cursor.select, hierarchical, sharing_changed
            )
            if show_sharing and sharing_changed:
                payload["@microsoft.graph.sharedChanged"] = "True"
            value.append(payload)

        body: dict[str, Any] = {
            "@odata.context": f"{GRAPH_BASE}/$metadata#Collection(driveItem)",
            "value": value,
        }
        if more:
            token = cursor.model_copy(
                update={"kind": "next", "after": items[-1].changed_seq}
            )
            body["@odata.nextLink"] = self._delta_link(drive, token)
        else:
            token = _DeltaCursor(
                kind="delta",
                drive_id=drive.id,
                generation=self.delta_generation,
                since=corpus.seq,
                top=cursor.top,
                select=cursor.select,
            )
            body["@odata.deltaLink"] = self._delta_link(drive, token)
        # After the page is built, so this page does not show the change.
        self._run_hooks("delta", drive.id)
        return json_response(200, body, headers)

    def _delta_link(self, drive: MockDrive, cursor: _DeltaCursor) -> str:
        token = _encode(cursor.model_dump(mode="json", exclude_none=True))
        return _graph_url(f"drives/{drive.id}/root/delta", {"token": token})

    def _content(
        self, request: ApiRequest, _drive: MockDrive, item: MockItem
    ) -> MockResponse:
        if item.is_folder:
            return invalid_request("The item is a folder.")
        if self.settings.faults.content_redirect:
            location = self._download_url(
                item, self._app_of(request), _CONTENT_REDIRECT_TTL_SECONDS
            )
            return MockResponse(status=302, headers={"location": location})
        return self._file_bytes(item, request.headers.get("range"))

    def _file_bytes(self, item: MockItem, range_header: str | None) -> MockResponse:
        if item.text is not None:
            data = content_mod.render_text_file(item.name, item.text)
        else:
            data = content_mod.render_file(
                self.corpus.settings.seed, item.id, item.version, item.name, item.size
            )
        headers = {
            "content-type": item.mime_type or "application/octet-stream",
            "accept-ranges": "bytes",
        }
        found = re.fullmatch(r"bytes=(\d+)-(\d*)", range_header or "")
        if found and int(found.group(1)) < len(data):
            first = int(found.group(1))
            last = min(int(found.group(2) or len(data) - 1), len(data) - 1)
            headers["content-range"] = f"bytes {first}-{last}/{len(data)}"
            return MockResponse(
                status=206, body=data[first : last + 1], headers=headers
            )
        return MockResponse(
            status=200, body=data, headers=headers, downloaded_item_id=item.id
        )

    def _download(self, request: ApiRequest) -> MockResponse:
        """The pre-authenticated download URL. It needs no Authorization
        header, and it stops working when its token expires."""
        token = parse_download_token(request.query.get("tempauth"))
        if token is None:
            raise RuntimeError("Bug: the download ran for a call with no token")
        if token.expires_at <= time.time():
            return rest_error(
                self.settings.faults.download_url_expired_status,
                "-2147024891, System.UnauthorizedAccessException",
                "The download URL is expired.",
            )
        faults = self.settings.faults
        if faults.download_url_throttled_calls > 0:
            faults.download_url_throttled_calls -= 1
            throttled = rest_error(
                self.settings.quota.throttle_status,
                "activityLimitReached",
                "The request has been throttled.",
            )
            throttled.headers["Retry-After"] = str(
                faults.download_url_retry_after_seconds
            )
            return throttled
        item = self.corpus.items.get(token.item_id)
        if item is None or item.deleted or item.is_folder:
            return rest_not_found()
        return self._file_bytes(item, request.headers.get("range"))

    def _list_permissions(
        self, request: ApiRequest, drive: MockDrive, item: MockItem
    ) -> MockResponse:
        corpus = self.corpus
        site = corpus.site_of(drive)
        inherited = item.unique_assignments is None
        # The site group of a sharing link is listed as the link.
        link_suffixes = tuple(f".{link.id}" for link in item.sharing_links)
        permissions: list[dict[str, Any]] = [
            {
                "id": link.id,
                "roles": ["read" if link.type == "view" else "write"],
                "shareId": f"u!{_encode({'l': link.id})}",
                "hasPassword": False,
                "link": {
                    "scope": link.scope,
                    "type": link.type,
                    "webUrl": f"https://{corpus.sharepoint_host}/:u:/s/"
                    f"{site.name}/E{link.id.replace('-', '')}",
                    "preventsDownload": False,
                },
            }
            for link in item.sharing_links
        ]
        for assignment in corpus.item_assignments(item):
            principal = assignment.principal
            if principal.kind == "site_group" and principal.key.endswith(link_suffixes):
                continue
            identity = {
                "displayName": corpus.principal_title(principal),
                "loginName": corpus.principal_login_name(principal),
            }
            kind = {"user": "user", "site_group": "siteGroup"}.get(
                principal.kind, "group"
            )
            permission: dict[str, Any] = {
                "id": _encode({"p": corpus.principal_login_name(principal)}),
                "roles": sorted({_GRAPH_ROLES[k] for k in assignment.role_kinds}),
                "grantedToV2": {kind: identity},
            }
            if inherited:
                permission["inheritedFrom"] = {}
            permissions.append(permission)
        path = f"drives/{drive.id}/items/{item.id}/permissions"
        paged = self._paged(
            request, permissions, self.settings.paging.directory_page_size, path
        )
        if isinstance(paged, MockResponse):
            return paged
        page, next_link = paged
        payload: dict[str, Any] = {"value": page}
        if next_link:
            payload["@odata.nextLink"] = next_link
        return json_response(200, payload)

    # --- Graph: directory ---

    def _group_json(self, group: MockEntraGroup) -> dict[str, Any]:
        return {
            "@odata.type": "#microsoft.graph.group",
            "id": group.id,
            "displayName": group.display_name,
            "securityEnabled": group.security_enabled,
            "mailEnabled": not group.security_enabled,
            "groupTypes": ["Unified"] if group.m365 else [],
            "mail": None,
            "visibility": "Private" if group.m365 else None,
        }

    def _user_json(self, user: MockUser) -> dict[str, Any]:
        return {
            "@odata.type": "#microsoft.graph.user",
            "id": user.object_id,
            "displayName": user.display_name,
            "userPrincipalName": user.user_principal_name,
            "mail": user.email,
            "userType": "Member",
            "accountEnabled": True,
        }

    def _directory_page(
        self, request: ApiRequest, values: list[dict[str, Any]], path: str
    ) -> MockResponse:
        paged = self._paged(
            request, values, self.settings.paging.directory_page_size, path
        )
        if isinstance(paged, MockResponse):
            return paged
        page, next_link = paged
        select = request.query.get("$select")
        payload: dict[str, Any] = {
            "@odata.context": f"{GRAPH_BASE}/$metadata#directoryObjects",
            "value": [_select(entry, select) for entry in page],
        }
        if next_link:
            payload["@odata.nextLink"] = next_link
        return json_response(200, payload)

    def _list_groups(self, request: ApiRequest) -> MockResponse:
        groups = list(self.corpus.entra_groups.values())
        expression = request.query.get("$filter")
        if expression is not None:
            found = _DISPLAY_NAME_FILTER.match(expression.strip())
            if found is None:
                return graph_error(
                    400, "Request_UnsupportedQuery", "Unsupported filter clause."
                )
            name = _odata_literal(found.group(1))
            groups = [group for group in groups if group.display_name == name]
        return self._directory_page(
            request, [self._group_json(group) for group in groups], "groups"
        )

    def _group_not_found(self, group_id: str) -> MockResponse:
        return graph_error(
            404,
            "Request_ResourceNotFound",
            f"Resource '{group_id}' does not exist or one of its queried "
            "reference-property objects are not present.",
        )

    def _get_group(self, request: ApiRequest, group_id: str) -> MockResponse:
        group = self.corpus.entra_groups.get(group_id)
        if group is None:
            return self._group_not_found(group_id)
        return json_response(
            200, _select(self._group_json(group), request.query.get("$select"))
        )

    def _list_group_members(
        self, request: ApiRequest, group_id: str, transitive: bool, cast: str | None
    ) -> MockResponse:
        corpus = self.corpus
        group = corpus.entra_groups.get(group_id)
        if group is None:
            return self._group_not_found(group_id)
        user_ids: list[str] = []
        group_ids: list[str] = []
        queue: deque[MockEntraGroup] = deque([group])
        visited = {group.id}
        while queue:
            current = queue.popleft()
            user_ids.extend(u for u in current.member_user_ids if u not in user_ids)
            for nested_id in current.member_group_ids:
                if nested_id in visited:
                    continue
                visited.add(nested_id)
                group_ids.append(nested_id)
                if transitive:
                    queue.append(corpus.entra_groups[nested_id])
        members: list[dict[str, Any]] = []
        if cast != "microsoft.graph.group":
            members += [self._user_json(corpus.users[u]) for u in user_ids]
        if cast != "microsoft.graph.user":
            members += [self._group_json(corpus.entra_groups[g]) for g in group_ids]
        segment = "transitiveMembers" if transitive else "members"
        path = f"groups/{group_id}/{segment}" + (f"/{cast}" if cast else "")
        return self._directory_page(request, members, path)

    def _find_user(self, identifier: str) -> MockUser | None:
        for user in self.corpus.users.values():
            if identifier.lower() in (
                user.object_id,
                user.user_principal_name.lower(),
                user.email.lower(),
            ):
                return user
        return None

    def _get_user(self, request: ApiRequest, identifier: str) -> MockResponse:
        user = self._find_user(identifier)
        if user is None:
            return self._group_not_found(identifier)
        return json_response(
            200, _select(self._user_json(user), request.query.get("$select"))
        )

    def _list_users(self, request: ApiRequest) -> MockResponse:
        users = [self._user_json(user) for user in self.corpus.users.values()]
        return self._directory_page(request, users, "users")

    # --- SharePoint REST ---

    def _rest_principal(self, site: MockSite, principal: Principal) -> dict[str, Any]:
        corpus = self.corpus
        title = corpus.principal_title(principal)
        login_name = corpus.principal_login_name(principal)
        if principal.kind == "site_group":
            group = site.site_groups.get(principal.key)
            return {
                "__metadata": {"type": "SP.Group"},
                "Id": group.sp_id if group else 0,
                "IsHiddenInUI": False,
                "LoginName": login_name,
                "Title": title,
                "PrincipalType": SITE_GROUP_TYPE,
                "OwnerTitle": title,
            }
        payload: dict[str, Any] = {
            "__metadata": {"type": "SP.User"},
            "IsHiddenInUI": False,
            "LoginName": login_name,
            "Title": title,
            "IsSiteAdmin": False,
        }
        if principal.kind == "user":
            user = corpus.users[principal.key]
            payload.update(
                {
                    "Id": user.sp_id,
                    "PrincipalType": USER_TYPE,
                    "Email": user.user_principal_name,
                    "UserPrincipalName": user.user_principal_name,
                }
            )
        else:
            sp_id = (
                corpus.entra_groups[principal.key].sp_id
                if principal.kind == "entra_group"
                else 5
            )
            payload.update(
                {
                    "Id": sp_id,
                    "PrincipalType": ENTRA_GROUP_TYPE,
                    "Email": "",
                    "UserPrincipalName": None,
                }
            )
        return payload

    def _rest_page(
        self, request: ApiRequest, results: list[dict[str, Any]]
    ) -> MockResponse:
        """One page of a verbose OData collection, with its `__next` link."""
        raw_top = request.query.get("$top")
        if raw_top is not None and (not raw_top.isdigit() or int(raw_top) < 1):
            return rest_error(
                400,
                "-1, Microsoft.SharePoint.Client.InvalidClientQueryException",
                "The $top value is not valid.",
            )
        size = int(raw_top) if raw_top else self.settings.paging.rest_page_size
        offset_text = request.query.get("$skiptoken", "0")
        offset = int(offset_text) if offset_text.isdigit() else 0
        page = results[offset : offset + size] if size else results[offset:]
        body: dict[str, Any] = {"results": page}
        if size and offset + size < len(results):
            params = {k: v for k, v in request.query.items() if k != "$skiptoken"}
            params["$skiptoken"] = str(offset + size)
            query = "&".join(f"{k}={quote(v, safe='')}" for k, v in params.items())
            body["__next"] = f"https://{request.host}/{quote(request.path)}?{query}"
        return json_response(200, {"d": body})

    def _rest_web_roles(self, request: ApiRequest, site: MockSite) -> MockResponse:
        return self._rest_assignments(request, site, site.assignments)

    def _rest_list_roles(
        self, request: ApiRequest, site: MockSite, list_id: str
    ) -> MockResponse:
        drive = self.corpus.drive_by_list_id(site, list_id)
        if drive is None:
            return rest_not_found("List does not exist.")
        return self._rest_assignments(
            request, site, self.corpus.drive_assignments(drive)
        )

    def _rest_item_roles(
        self, request: ApiRequest, site: MockSite, list_id: str, list_item_id: str
    ) -> MockResponse:
        item = self.corpus.item_by_list_item_id(site, list_id, int(list_item_id))
        if item is None:
            return rest_not_found("Item does not exist.")
        return self._rest_assignments(request, site, self.corpus.item_assignments(item))

    def _rest_file_roles(
        self, request: ApiRequest, site: MockSite, file_url: str
    ) -> MockResponse:
        # The argument is a URL path, which SharePoint decodes.
        file_path = unquote(_odata_literal(file_url))
        target = self.corpus.resolve_server_relative(site, file_path)
        if target is None:
            return rest_not_found()
        return self._rest_assignments(request, site, self.corpus.assignments_of(target))

    def _rest_folder_roles(
        self, request: ApiRequest, site: MockSite, unique_id: str
    ) -> MockResponse:
        item = self.corpus.item_by_unique_id(site, unique_id)
        if item is None or not item.is_folder:
            return rest_not_found()
        return self._rest_assignments(request, site, self.corpus.item_assignments(item))

    def _rest_assignments(
        self, request: ApiRequest, site: MockSite, assignments: list[RoleAssignment]
    ) -> MockResponse:
        expand = {
            e.strip().lower() for e in request.query.get("$expand", "").split(",")
        }
        base = f"{site.web_url}/_api/Web/RoleAssignments"
        results: list[dict[str, Any]] = []
        for assignment in assignments:
            member = self._rest_principal(site, assignment.principal)
            uri = f"{base}/GetByPrincipalId({member['Id']})"
            entry: dict[str, Any] = {
                "__metadata": {"type": "SP.RoleAssignment", "uri": uri},
                "PrincipalId": member["Id"],
                "Member": {"__deferred": {"uri": f"{uri}/Member"}},
                "RoleDefinitionBindings": {
                    "__deferred": {"uri": f"{uri}/RoleDefinitionBindings"}
                },
            }
            if "member" in expand:
                entry["Member"] = member
            if "roledefinitionbindings" in expand:
                entry["RoleDefinitionBindings"] = {
                    "results": [
                        {
                            "__metadata": {"type": "SP.RoleDefinition"},
                            "Id": 1073741800 + kind,
                            "Name": _ROLE_NAMES.get(kind, "Custom"),
                            "Description": "",
                            "Hidden": kind == 1,
                            "Order": kind,
                            "RoleTypeKind": kind,
                        }
                        for kind in assignment.role_kinds
                    ]
                }
            results.append(entry)
        return self._rest_page(request, results)

    def _rest_group_users(
        self, request: ApiRequest, site: MockSite, group_name: str
    ) -> MockResponse:
        group = site.site_groups.get(_odata_literal(group_name))
        if group is None:
            return rest_error(
                404,
                "-2146232832, Microsoft.SharePoint.SPException",
                "Group cannot be found.",
            )
        users = [self._rest_principal(site, member) for member in group.members]
        return self._rest_page(request, users)

    def _rest_folder(self, request: ApiRequest, site: MockSite) -> MockResponse:
        alias = request.query.get("@a", "")
        if len(alias) < 2 or not (alias.startswith("'") and alias.endswith("'")):
            return rest_error(
                400,
                "-1, Microsoft.SharePoint.Client.InvalidClientQueryException",
                "The parameter alias @a is not valid.",
            )
        target = self.corpus.resolve_server_relative(site, _odata_literal(alias[1:-1]))
        if not isinstance(target, MockItem) or not target.is_folder:
            return rest_not_found()
        payload: dict[str, Any] = {
            "__metadata": {"type": "SP.Folder"},
            "UniqueId": target.unique_id,
        }
        if "$select" not in request.query:
            payload.update(
                {
                    "Name": target.name,
                    "Exists": True,
                    "ItemCount": len(self.corpus.children[target.id]),
                }
            )
        return json_response(200, {"d": payload})

    def _rest_web(self, _request: ApiRequest, site: MockSite) -> MockResponse:
        return json_response(
            200,
            {
                "d": {
                    "__metadata": {"type": "SP.Web"},
                    "Id": site.web_guid,
                    "Title": site.display_name,
                    "Url": site.web_url,
                    "ServerRelativeUrl": "/" + site.web_url.split("/", 3)[3],
                }
            },
        )
