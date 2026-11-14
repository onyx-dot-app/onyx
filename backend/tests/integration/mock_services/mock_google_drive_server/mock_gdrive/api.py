"""The Google API surface: routing, auth, quotas, latency and the handlers.

Every call, including each part of a batch request, goes through
`MockGoogleApi.handle`.
"""

import asyncio
import base64
import hashlib
import json
import random
import re
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Iterable
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from . import content as content_mod
from .auth import (
    DIRECTORY_GROUP_SCOPES,
    DIRECTORY_USER_SCOPES,
    DOCS_SCOPES,
    DRIVE_CONTENT_SCOPES,
    DRIVE_METADATA_SCOPES,
    Principal,
    authenticate,
)
from .corpus import Corpus, MockFile, MockPermission, MockUser
from .fields import FieldsError, apply_mask, parse_fields
from .query import (
    QueryError,
    matches,
    parse_query,
    required_parent,
    resolve_parent,
)
from .quota import Bucket, QuotaTracker, RateLimitDecision, UnitCost
from .responses import (
    MockResponse,
    bad_request,
    directory_forbidden,
    drive_not_found,
    file_not_found,
    google_error,
    insufficient_scopes,
    json_response,
    rpc_error,
    unauthenticated,
)
from .settings import (
    DOC_MIME,
    FOLDER_MIME,
    GOOGLE_NATIVE_MIMES,
    SHEET_MIME,
    SLIDES_MIME,
    MockSettings,
)
from .stats import Stats

LatencyClass = Literal["metadata", "list", "content", "docs_api"]

_LIST_CACHE_ENTRIES = 512
_DEFAULT_FILE_FIELDS = "kind,id,name,mimeType"
_DEFAULT_FILE_LIST_FIELDS = (
    "kind,incompleteSearch,nextPageToken,files(kind,id,name,mimeType)"
)
_DEFAULT_DRIVE_FIELDS = "kind,id,name"
_DEFAULT_DRIVE_LIST_FIELDS = "kind,nextPageToken,drives(kind,id,name)"
_DEFAULT_PERMISSION_LIST_FIELDS = "kind,nextPageToken,permissions(kind,id,type,role)"
_WEB_VIEW_LINKS = {
    DOC_MIME: "https://docs.google.com/document/d/{}/edit?usp=drivesdk",
    SHEET_MIME: "https://docs.google.com/spreadsheets/d/{}/edit?usp=drivesdk",
    SLIDES_MIME: "https://docs.google.com/presentation/d/{}/edit?usp=drivesdk",
    FOLDER_MIME: "https://drive.google.com/drive/folders/{}",
}
_FILE_WEB_VIEW_LINK = "https://drive.google.com/file/d/{}/view?usp=drivesdk"


class ApiRequest(BaseModel):
    method: str
    # Without the leading slash or the query string.
    path: str
    query: dict[str, str]
    # Lower-case names.
    headers: dict[str, str]


class OpSpec(BaseModel):
    name: str
    bucket: Bucket
    cost: UnitCost
    latency: LatencyClass
    scopes: frozenset[str]


Handler = Callable[
    ["MockGoogleApi", ApiRequest, Principal, dict[str, str]], Awaitable[MockResponse]
]


def _op(
    name: str,
    bucket: Bucket,
    cost: UnitCost,
    latency: LatencyClass,
    scopes: frozenset[str],
) -> OpSpec:
    return OpSpec(name=name, bucket=bucket, cost=cost, latency=latency, scopes=scopes)


def _flag(query: dict[str, str], name: str) -> bool:
    return query.get(name, "").lower() == "true"


def rfc3339(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%S.") + f"{value.microsecond // 1000:03d}Z"


def _encode_page_token(offset: int, key: str) -> str:
    raw = json.dumps({"o": offset, "k": key}).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_page_token(token: str | None, key: str) -> int | None:
    """The offset in a page token, 0 without one, None if it is not valid for
    this listing."""
    if not token:
        return 0
    try:
        payload = json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
    except ValueError:
        return None
    if not isinstance(payload, dict) or payload.get("k") != key:
        return None
    offset = payload.get("o")
    return offset if isinstance(offset, int) and offset >= 0 else None


def _paginate(
    items: list[Any],
    query: dict[str, str],
    key: str,
    default_size: int,
    max_size: int,
    size_param: str,
) -> tuple[list[Any], str | None] | MockResponse:
    raw_size = query.get(size_param)
    try:
        size = int(raw_size) if raw_size else default_size
    except ValueError:
        return bad_request(f"Invalid value for {size_param}", size_param)
    if size < 1 or size > max_size:
        return bad_request(
            f"Invalid {size_param} value: {size}. Values must be within the range: [1, {max_size}]",
            size_param,
        )
    offset = _decode_page_token(query.get("pageToken"), key)
    if offset is None:
        return bad_request("Invalid Value", "pageToken")
    page = items[offset : offset + size]
    next_token = (
        _encode_page_token(offset + size, key) if offset + size < len(items) else None
    )
    return page, next_token


def _masked(payload: dict[str, Any], fields: str | None, default: str) -> MockResponse:
    try:
        mask = parse_fields(fields or default)
    except FieldsError as e:
        return bad_request(str(e), "fields")
    return json_response(200, apply_mask(payload, mask))


def _range_response(
    data: bytes, mime_type: str, range_header: str | None, file_id: str
) -> MockResponse:
    total = len(data)
    headers = {"content-type": mime_type}
    match = re.fullmatch(r"bytes=(\d+)-(\d*)", (range_header or "").strip())
    if match is None or total == 0:
        return MockResponse(
            status=200, body=data, headers=headers, content_file_id=file_id
        )
    start = int(match.group(1))
    end = min(int(match.group(2)) if match.group(2) else total - 1, total - 1)
    if start >= total:
        headers["content-range"] = f"bytes */{total}"
        return MockResponse(status=416, headers=headers)
    headers["content-range"] = f"bytes {start}-{end}/{total}"
    return MockResponse(
        status=206, body=data[start : end + 1], headers=headers, content_file_id=file_id
    )


class MockGoogleApi:
    def __init__(self, settings: MockSettings) -> None:
        self.settings = settings
        self.corpus = Corpus(settings.corpus)
        self.corpus_version = 0
        self.quota = QuotaTracker(settings.quota)
        self.stats = Stats()
        self._rng = random.Random()
        self._list_cache: OrderedDict[tuple[Any, ...], list[str]] = OrderedDict()

    # -- control --------------------------------------------------------

    def regenerate(self, settings: MockSettings) -> None:
        self.settings = settings
        self.corpus = Corpus(settings.corpus)
        self.corpus_version += 1
        self._list_cache.clear()
        self.quota.reset()
        self.stats.reset()

    def update_settings(self, settings: MockSettings) -> None:
        self.settings = settings
        self.quota.update_settings(settings.quota)

    def touch(self, count: int) -> list[str]:
        ids = self.corpus.touch(count, self._rng)
        self.corpus_version += 1
        self._list_cache.clear()
        return ids

    # -- dispatch -------------------------------------------------------

    async def handle(self, request: ApiRequest) -> MockResponse:
        started = time.monotonic()
        route = _match_route(request)
        if route is None:
            return google_error(404, f"Not Found: /{request.path}", "notFound")
        spec, handler, params = route
        principal = authenticate(request.headers, self.corpus)
        if principal is None:
            response = unauthenticated()
            self._record(spec, response, 0, None, started)
            return response
        if not principal.scopes & spec.scopes:
            response = insufficient_scopes()
            self._record(spec, response, 0, principal.email, started)
            return response

        faults = self.settings.faults
        if faults.server_error_rate and self._rng.random() < faults.server_error_rate:
            status = self._rng.choice([500, 503])
            response = google_error(
                status,
                "Backend Error" if status == 500 else "Service Unavailable",
                "backendError",
            )
            await self._sleep(spec.latency, 0)
            self._record(spec, response, 0, principal.email, started)
            return response

        charge = self.quota.charge(spec.bucket, spec.cost)
        decision = self.quota.consume(
            spec.bucket, charge, principal.email, time.monotonic()
        )
        if decision is not None:
            response = self._rate_limited(decision)
            if self.settings.latency.enabled:
                await asyncio.sleep(self.settings.latency.rate_limited_ms / 1000)
            self._record(spec, response, 0, principal.email, started)
            return response

        response = await handler(self, request, principal, params)
        await self._sleep(spec.latency, len(response.body))
        units = self.quota.unit_cost(spec.cost) if spec.bucket == "drive" else 0
        self._record(spec, response, units, principal.email, started)
        return response

    def _rate_limited(self, decision: RateLimitDecision) -> MockResponse:
        quota = self.settings.quota
        headers: dict[str, str] = {}
        if quota.retry_after_seconds is not None:
            headers["retry-after"] = str(quota.retry_after_seconds)
        if decision.bucket == "docs":
            limit = "per user" if decision.scope == "user" else ""
            response = rpc_error(
                429,
                "Quota exceeded for quota metric 'Read requests' and limit "
                f"'Read requests per minute{(' ' + limit) if limit else ''}' of "
                "service 'docs.googleapis.com'.",
                "RESOURCE_EXHAUSTED",
            )
            response.headers.update(headers)
        elif decision.scope == "user":
            response = google_error(
                quota.user_limit_status,
                "User rate limit exceeded.",
                "userRateLimitExceeded",
                domain="usageLimits",
                headers=headers,
            )
        else:
            response = google_error(
                429,
                "Rate Limit Exceeded",
                "rateLimitExceeded",
                domain="usageLimits",
                api_status="RESOURCE_EXHAUSTED",
                headers=headers,
            )
        response.rate_limited = True
        return response

    async def _sleep(self, latency: LatencyClass, nbytes: int) -> None:
        settings = self.settings.latency
        if not settings.enabled:
            return
        base_ms = {
            "metadata": settings.metadata_ms,
            "list": settings.list_ms,
            "content": settings.content_ms,
            "docs_api": settings.docs_api_ms,
        }[latency]
        factor = 1 + self._rng.uniform(-settings.jitter, settings.jitter)
        seconds = base_ms * factor / 1000 + nbytes / settings.bandwidth_bytes_per_second
        if seconds > 0:
            await asyncio.sleep(seconds)

    def _record(
        self,
        spec: OpSpec,
        response: MockResponse,
        units: int,
        user: str | None,
        started: float,
    ) -> None:
        self.stats.record(
            op=spec.name,
            status=response.status,
            units=units,
            nbytes=len(response.body),
            duration_ms=(time.monotonic() - started) * 1000,
            user=user,
            rate_limited=response.rate_limited,
            content_file_id=response.content_file_id,
        )

    # -- resources ------------------------------------------------------

    def _resolve(self, file_id: str, me: str) -> MockFile | None:
        if file_id == "root":
            return self.corpus.root_of(me)
        return self.corpus.files.get(file_id)

    def permission_resource(
        self, permission: MockPermission, details: dict[str, Any] | None
    ) -> dict[str, Any]:
        resource: dict[str, Any] = {
            "kind": "drive#permission",
            "id": permission.id,
            "type": permission.type,
            "role": permission.role,
            "deleted": False,
        }
        if permission.email_address:
            resource["emailAddress"] = permission.email_address
            user = self.corpus.account(permission.email_address)
            group = self.corpus.groups.get(permission.email_address)
            resource["displayName"] = (
                user.full_name if user else (group.name if group else "")
            )
        if permission.domain:
            resource["domain"] = permission.domain
        if permission.allow_file_discovery is not None:
            resource["allowFileDiscovery"] = permission.allow_file_discovery
        if details is not None:
            resource["permissionDetails"] = [details]
        return resource

    def file_permissions(self, file: MockFile) -> list[dict[str, Any]]:
        """Every permission of an item. A shared drive item also lists the
        drive's members, as inherited permissions."""
        if file.drive_id is None:
            return [self.permission_resource(p, None) for p in file.permissions]
        resources: list[dict[str, Any]] = []
        drive = self.corpus.drives[file.drive_id]
        for member in drive.members:
            details = {
                "permissionType": "member",
                "role": member.role,
                "inherited": not file.is_root,
            }
            if not file.is_root:
                details["inheritedFrom"] = drive.id
            resources.append(self.permission_resource(member, details))
        for permission in file.permissions:
            details = {
                "permissionType": "file",
                "role": permission.role,
                "inherited": False,
            }
            resources.append(self.permission_resource(permission, details))
        return resources

    def file_resource(self, file: MockFile, me: str) -> dict[str, Any]:
        corpus = self.corpus
        resource: dict[str, Any] = {
            "kind": "drive#file",
            "id": file.id,
            "name": file.name,
            "mimeType": file.mime_type,
            "trashed": False,
            "createdTime": rfc3339(file.created_time),
            "modifiedTime": rfc3339(file.modified_time),
            "webViewLink": _WEB_VIEW_LINKS.get(
                file.mime_type, _FILE_WEB_VIEW_LINK
            ).format(file.id),
        }
        parents = [p for p in file.parents if corpus.can_read(me, corpus.files[p])]
        if parents:
            resource["parents"] = parents
        if file.drive_id is not None:
            resource["driveId"] = file.drive_id
        owner = corpus.account(file.owner) if file.owner is not None else None
        if owner is not None:
            resource["owners"] = [
                {
                    "kind": "drive#user",
                    "displayName": owner.full_name,
                    "emailAddress": owner.email,
                    "me": owner.email == me,
                    "permissionId": owner.permission_id,
                }
            ]
        permissions = self.file_permissions(file)
        resource["permissionIds"] = [p["id"] for p in permissions]
        # Google lists permissions only to users who can share the item, and
        # never for shared drive items.
        if corpus.can_share(me, file):
            resource["permissions"] = permissions
        if file.is_content and file.mime_type not in GOOGLE_NATIVE_MIMES:
            resource["size"] = str(file.content_bytes)
        if file.shortcut_target_id is not None:
            target = corpus.files[file.shortcut_target_id]
            resource["shortcutDetails"] = {
                "targetId": target.id,
                "targetMimeType": target.mime_type,
            }
        return resource

    def user_resource(self, user: MockUser) -> dict[str, Any]:
        return {
            "kind": "admin#directory#user",
            "id": user.id,
            "primaryEmail": user.email,
            "name": {
                "givenName": user.given_name,
                "familyName": user.family_name,
                "fullName": user.full_name,
            },
            "isAdmin": user.is_admin,
            "isDelegatedAdmin": False,
            "suspended": False,
            "archived": False,
            "orgUnitPath": "/",
            "customerId": "C0mock00",
        }

    # -- listing --------------------------------------------------------

    def list_ids(
        self,
        me: str,
        corpora: str,
        drive_id: str | None,
        include_all_drives: bool,
        q: str,
        order_by: str,
    ) -> list[str]:
        key = (
            self.corpus_version,
            me,
            corpora,
            drive_id,
            include_all_drives,
            q,
            order_by,
        )
        cached = self._list_cache.get(key)
        if cached is not None:
            self._list_cache.move_to_end(key)
            return cached
        node = parse_query(q)
        corpus = self.corpus
        visible = self._visibility(me, corpora, drive_id, include_all_drives)
        parent = required_parent(node)
        candidates: Iterable[str]
        if parent is not None:
            parent = resolve_parent(parent, me, corpus)
            candidates = (f for f in corpus.children.get(parent, []) if visible(f))
        else:
            candidates = self._corpus_ids(me, corpora, drive_id, include_all_drives)
        ids = [
            file_id
            for file_id in candidates
            if not corpus.files[file_id].is_root
            and matches(node, corpus.files[file_id], me, corpus)
        ]
        self._sort(ids, order_by)
        self._list_cache[key] = ids
        if len(self._list_cache) > _LIST_CACHE_ENTRIES:
            self._list_cache.popitem(last=False)
        return ids

    def _visibility(
        self, me: str, corpora: str, drive_id: str | None, include_all_drives: bool
    ) -> Callable[[str], bool]:
        corpus = self.corpus
        mine = corpus.user_corpus.get(me, set())
        if corpora == "drive":
            return lambda f: corpus.files[f].drive_id == drive_id
        if corpora == "allDrives" and include_all_drives:
            member_drives = set(corpus.member_drive_ids(me))
            return lambda f: f in mine or corpus.files[f].drive_id in member_drives
        if corpora == "domain":
            return lambda f: (
                f in mine
                or any(p.type == "domain" for p in corpus.files[f].permissions)
            )
        return lambda f: f in mine

    def _corpus_ids(
        self, me: str, corpora: str, drive_id: str | None, include_all_drives: bool
    ) -> Iterable[str]:
        corpus = self.corpus
        if corpora == "drive" and drive_id is not None:
            return list(corpus.drive_files.get(drive_id, []))
        ordered = [f for f in corpus.files if f in corpus.user_corpus.get(me, set())]
        if corpora == "allDrives" and include_all_drives:
            for member_drive in corpus.member_drive_ids(me):
                ordered.extend(
                    f
                    for f in corpus.drive_files[member_drive]
                    if f not in corpus.user_corpus.get(me, set())
                )
        elif corpora == "domain":
            visible = self._visibility(me, corpora, drive_id, include_all_drives)
            ordered = [f for f in corpus.files if visible(f)]
        return ordered

    def _sort(self, ids: list[str], order_by: str) -> None:
        files = self.corpus.files
        for clause in reversed([c.strip() for c in order_by.split(",") if c.strip()]):
            field, _, direction = clause.partition(" ")
            reverse = direction.strip().lower() == "desc"
            if field in (
                "modifiedTime",
                "modifiedByMeTime",
                "viewedByMeTime",
                "recency",
            ):
                ids.sort(key=lambda f: files[f].modified_time, reverse=reverse)
            elif field == "createdTime":
                ids.sort(key=lambda f: files[f].created_time, reverse=reverse)
            elif field in ("name", "name_natural"):
                ids.sort(key=lambda f: files[f].name, reverse=reverse)
            elif field == "folder":
                ids.sort(key=lambda f: not files[f].is_folder, reverse=reverse)


# -- handlers -------------------------------------------------------------


async def files_list(
    api: MockGoogleApi, req: ApiRequest, me: Principal, _: dict[str, str]
) -> MockResponse:
    query = req.query
    corpora = query.get("corpora", "user")
    drive_id = query.get("driveId")
    include_all = _flag(query, "includeItemsFromAllDrives")
    if corpora not in ("user", "drive", "allDrives", "domain"):
        return bad_request(f"Invalid Value: corpora={corpora}", "corpora")
    if (corpora == "drive") != (drive_id is not None):
        return bad_request(
            "The driveId parameter must be specified if and only if corpora is set to drive.",
            "driveId",
        )
    if corpora == "drive":
        if not include_all or not _flag(query, "supportsAllDrives"):
            return bad_request(
                "The includeItemsFromAllDrives parameter must be set to true when "
                "corpora is set to drive.",
                "includeItemsFromAllDrives",
            )
        if drive_id not in api.corpus.drives or not api.corpus.is_drive_member(
            me.email, drive_id
        ):
            return drive_not_found(drive_id or "")
    q = query.get("q", "")
    order_by = query.get("orderBy", "")
    try:
        ids = api.list_ids(me.email, corpora, drive_id, include_all, q, order_by)
    except QueryError:
        return bad_request("Invalid Value", "q")
    key = hashlib.sha1(
        f"{me.email}|{corpora}|{drive_id}|{include_all}|{q}|{order_by}".encode()
    ).hexdigest()[:16]
    page = _paginate(ids, query, key, 100, 1000, "pageSize")
    if isinstance(page, MockResponse):
        return page
    page_ids, next_token = page
    payload: dict[str, Any] = {
        "kind": "drive#fileList",
        "incompleteSearch": False,
        "files": [api.file_resource(api.corpus.files[f], me.email) for f in page_ids],
    }
    if next_token:
        payload["nextPageToken"] = next_token
    return _masked(payload, query.get("fields"), _DEFAULT_FILE_LIST_FIELDS)


async def files_get(
    api: MockGoogleApi, req: ApiRequest, me: Principal, params: dict[str, str]
) -> MockResponse:
    file = api._resolve(params["file_id"], me.email)
    if file is None or not api.corpus.can_read(me.email, file):
        return file_not_found(params["file_id"])
    return _masked(
        api.file_resource(file, me.email), req.query.get("fields"), _DEFAULT_FILE_FIELDS
    )


async def files_get_media(
    api: MockGoogleApi, req: ApiRequest, me: Principal, params: dict[str, str]
) -> MockResponse:
    file = api._resolve(params["file_id"], me.email)
    if file is None or not api.corpus.can_read(me.email, file):
        return file_not_found(params["file_id"])
    if not file.is_content or file.mime_type in GOOGLE_NATIVE_MIMES:
        return google_error(
            403,
            "Only files with binary content can be downloaded. Use Export with "
            "Docs Editors files.",
            "fileNotDownloadable",
            location="alt",
        )
    rendered = await asyncio.to_thread(
        content_mod.render, api.settings.corpus.seed, file, file.mime_type
    )
    return _range_response(
        rendered.data, rendered.mime_type, req.headers.get("range"), file.id
    )


async def files_export(
    api: MockGoogleApi, req: ApiRequest, me: Principal, params: dict[str, str]
) -> MockResponse:
    file = api._resolve(params["file_id"], me.email)
    if file is None or not api.corpus.can_read(me.email, file):
        return file_not_found(params["file_id"])
    mime_type = req.query.get("mimeType")
    if not mime_type:
        return google_error(
            400, "Required parameter: mimeType", "required", location="mimeType"
        )
    if file.mime_type not in GOOGLE_NATIVE_MIMES:
        return google_error(
            403, "Export only supports Docs Editors files.", "fileNotExportable"
        )
    if mime_type not in content_mod.EXPORT_FORMATS[file.mime_type]:
        return bad_request("The requested conversion is not supported.", "convertTo")
    rendered = await asyncio.to_thread(
        content_mod.render, api.settings.corpus.seed, file, mime_type
    )
    if len(rendered.data) > content_mod.EXPORT_SIZE_LIMIT_BYTES:
        return google_error(
            403, "This file is too large to be exported.", "exportSizeLimitExceeded"
        )
    return _range_response(
        rendered.data, rendered.mime_type, req.headers.get("range"), file.id
    )


async def permissions_list(
    api: MockGoogleApi, req: ApiRequest, me: Principal, params: dict[str, str]
) -> MockResponse:
    target_id = params["file_id"]
    corpus = api.corpus
    if target_id in corpus.drives:
        domain_admin = _flag(req.query, "useDomainAdminAccess") and me.is_admin
        if not (domain_admin or corpus.is_drive_member(me.email, target_id)):
            return file_not_found(target_id)
        permissions = api.file_permissions(corpus.files[target_id])
    else:
        file = api._resolve(target_id, me.email)
        if file is None or not corpus.can_read(me.email, file):
            return file_not_found(target_id)
        permissions = api.file_permissions(file)
    page = _paginate(permissions, req.query, f"perm:{target_id}", 100, 100, "pageSize")
    if isinstance(page, MockResponse):
        return page
    items, next_token = page
    payload: dict[str, Any] = {"kind": "drive#permissionList", "permissions": items}
    if next_token:
        payload["nextPageToken"] = next_token
    return _masked(payload, req.query.get("fields"), _DEFAULT_PERMISSION_LIST_FIELDS)


async def permissions_get(
    api: MockGoogleApi, req: ApiRequest, me: Principal, params: dict[str, str]
) -> MockResponse:
    file = api._resolve(params["file_id"], me.email)
    if file is None or not api.corpus.can_read(me.email, file):
        return file_not_found(params["file_id"])
    for permission in api.file_permissions(file):
        if permission["id"] == params["permission_id"]:
            return _masked(permission, req.query.get("fields"), "kind,id,type,role")
    return google_error(
        404,
        f"Permission not found: {params['permission_id']}.",
        "notFound",
        location="permissionId",
    )


async def drives_list(
    api: MockGoogleApi, req: ApiRequest, me: Principal, _: dict[str, str]
) -> MockResponse:
    corpus = api.corpus
    if _flag(req.query, "useDomainAdminAccess"):
        if not me.is_admin:
            return google_error(
                403, "The user does not have administrator privileges.", "forbidden"
            )
        drive_ids = list(corpus.drives)
    else:
        drive_ids = corpus.member_drive_ids(me.email)
    page = _paginate(drive_ids, req.query, f"drives:{me.email}", 10, 100, "pageSize")
    if isinstance(page, MockResponse):
        return page
    items, next_token = page
    payload: dict[str, Any] = {
        "kind": "drive#driveList",
        "drives": [
            {
                "kind": "drive#drive",
                "id": d,
                "name": corpus.drives[d].name,
                "createdTime": rfc3339(corpus.drives[d].created_time),
                "hidden": False,
            }
            for d in items
        ],
    }
    if next_token:
        payload["nextPageToken"] = next_token
    return _masked(payload, req.query.get("fields"), _DEFAULT_DRIVE_LIST_FIELDS)


async def drives_get(
    api: MockGoogleApi, req: ApiRequest, me: Principal, params: dict[str, str]
) -> MockResponse:
    corpus = api.corpus
    drive = corpus.drives.get(params["drive_id"])
    domain_admin = _flag(req.query, "useDomainAdminAccess") and me.is_admin
    if drive is None or not (
        domain_admin or corpus.is_drive_member(me.email, drive.id)
    ):
        return drive_not_found(params["drive_id"])
    payload = {
        "kind": "drive#drive",
        "id": drive.id,
        "name": drive.name,
        "createdTime": rfc3339(drive.created_time),
        "hidden": False,
    }
    return _masked(payload, req.query.get("fields"), _DEFAULT_DRIVE_FIELDS)


async def about_get(
    api: MockGoogleApi, req: ApiRequest, me: Principal, _: dict[str, str]
) -> MockResponse:
    if not req.query.get("fields"):
        return google_error(
            400,
            "The 'fields' parameter is required for this method.",
            "required",
            location="fields",
        )
    user = api.corpus.users.get(me.email)
    payload = {
        "kind": "drive#about",
        "user": {
            "kind": "drive#user",
            "displayName": user.full_name if user else me.email,
            "emailAddress": me.email,
            "me": True,
            "permissionId": user.permission_id if user else "",
        },
    }
    return _masked(payload, req.query.get("fields"), "kind,user")


async def users_list(
    api: MockGoogleApi, req: ApiRequest, me: Principal, _: dict[str, str]
) -> MockResponse:
    if not me.is_admin:
        return directory_forbidden()
    query = req.query
    domain = query.get("domain")
    if not domain and not query.get("customer"):
        return google_error(400, "Bad Request", "badRequest")
    if domain and domain != api.corpus.domain:
        return google_error(404, "Domain not found.", "notFound")
    users = list(api.corpus.users.values())
    search = query.get("query", "").strip()
    if search:
        match = re.fullmatch(r"isAdmin\s*=\s*(true|false)", search, re.IGNORECASE)
        if match is None:
            return google_error(400, "Invalid Input", "invalid")
        wanted = match.group(1).lower() == "true"
        users = [u for u in users if u.is_admin == wanted]
    page = _paginate(users, query, f"users:{search}", 100, 500, "maxResults")
    if isinstance(page, MockResponse):
        return page
    items, next_token = page
    payload: dict[str, Any] = {
        "kind": "admin#directory#users",
        "users": [api.user_resource(u) for u in items],
    }
    if next_token:
        payload["nextPageToken"] = next_token
    return _masked(payload, query.get("fields"), "*")


async def users_get(
    api: MockGoogleApi, req: ApiRequest, me: Principal, params: dict[str, str]
) -> MockResponse:
    key = params["user_key"]
    user = api.corpus.users.get(key) or next(
        (u for u in api.corpus.users.values() if u.id == key), None
    )
    if not me.is_admin and (user is None or user.email != me.email):
        return directory_forbidden()
    if user is None:
        return google_error(404, "Resource Not Found: userKey", "notFound")
    return _masked(api.user_resource(user), req.query.get("fields"), "*")


async def groups_list(
    api: MockGoogleApi, req: ApiRequest, me: Principal, _: dict[str, str]
) -> MockResponse:
    if not me.is_admin:
        return directory_forbidden()
    query = req.query
    groups = list(api.corpus.groups.values())
    user_key = query.get("userKey")
    if user_key:
        groups = [g for g in groups if user_key in g.member_emails]
    elif not query.get("domain") and not query.get("customer"):
        return google_error(400, "Bad Request", "badRequest")
    page = _paginate(groups, query, f"groups:{user_key}", 200, 200, "maxResults")
    if isinstance(page, MockResponse):
        return page
    items, next_token = page
    payload: dict[str, Any] = {
        "kind": "admin#directory#groups",
        "groups": [
            {
                "kind": "admin#directory#group",
                "id": g.id,
                "email": g.email,
                "name": g.name,
                "directMembersCount": str(len(g.member_emails)),
                "adminCreated": True,
            }
            for g in items
        ],
    }
    if next_token:
        payload["nextPageToken"] = next_token
    return _masked(payload, query.get("fields"), "*")


async def members_list(
    api: MockGoogleApi, req: ApiRequest, me: Principal, params: dict[str, str]
) -> MockResponse:
    if not me.is_admin:
        return directory_forbidden()
    group = api.corpus.groups.get(params["group_key"]) or next(
        (g for g in api.corpus.groups.values() if g.id == params["group_key"]), None
    )
    if group is None:
        return google_error(404, "Resource Not Found: groupKey", "notFound")
    page = _paginate(
        group.member_emails, req.query, f"members:{group.id}", 200, 200, "maxResults"
    )
    if isinstance(page, MockResponse):
        return page
    items, next_token = page
    payload: dict[str, Any] = {
        "kind": "admin#directory#members",
        "members": [
            {
                "kind": "admin#directory#member",
                "id": api.corpus.users[email].id,
                "email": email,
                "role": "MEMBER",
                "type": "USER",
                "status": "ACTIVE",
            }
            for email in items
        ],
    }
    if next_token:
        payload["nextPageToken"] = next_token
    return _masked(payload, req.query.get("fields"), "*")


async def documents_get(
    api: MockGoogleApi, req: ApiRequest, me: Principal, params: dict[str, str]
) -> MockResponse:
    file = api.corpus.files.get(params["document_id"])
    if file is None or not api.corpus.can_read(me.email, file):
        return rpc_error(404, "Requested entity was not found.", "NOT_FOUND")
    if file.mime_type != DOC_MIME:
        return rpc_error(
            400,
            "This operation is not supported for this document",
            "FAILED_PRECONDITION",
        )
    document = await asyncio.to_thread(
        content_mod.docs_api_document,
        api.settings.corpus.seed,
        file,
        _flag(req.query, "includeTabsContent"),
    )
    response = json_response(200, document)
    response.content_file_id = file.id
    return response


# -- routing --------------------------------------------------------------

_DRIVE = DRIVE_METADATA_SCOPES
_ROUTES: list[tuple[str, re.Pattern[str], OpSpec, Handler]] = [
    (
        "GET",
        re.compile(r"drive/v3/files"),
        _op("drive.files.list", "drive", "list", "list", _DRIVE),
        files_list,
    ),
    (
        "GET",
        re.compile(r"drive/v3/files/(?P<file_id>[^/]+)/export"),
        _op("drive.files.export", "drive", "content", "content", DRIVE_CONTENT_SCOPES),
        files_export,
    ),
    (
        "GET",
        re.compile(r"drive/v3/files/(?P<file_id>[^/]+)/permissions"),
        _op("drive.permissions.list", "drive", "list", "list", _DRIVE),
        permissions_list,
    ),
    (
        "GET",
        re.compile(
            r"drive/v3/files/(?P<file_id>[^/]+)/permissions/(?P<permission_id>[^/]+)"
        ),
        _op("drive.permissions.get", "drive", "read", "metadata", _DRIVE),
        permissions_get,
    ),
    (
        "GET",
        re.compile(r"drive/v3/files/(?P<file_id>[^/]+)"),
        _op("drive.files.get", "drive", "read", "metadata", _DRIVE),
        files_get,
    ),
    (
        "GET",
        re.compile(r"drive/v3/drives"),
        _op("drive.drives.list", "drive", "list", "list", _DRIVE),
        drives_list,
    ),
    (
        "GET",
        re.compile(r"drive/v3/drives/(?P<drive_id>[^/]+)"),
        _op("drive.drives.get", "drive", "read", "metadata", _DRIVE),
        drives_get,
    ),
    (
        "GET",
        re.compile(r"drive/v3/about"),
        _op("drive.about.get", "drive", "read", "metadata", _DRIVE),
        about_get,
    ),
    (
        "GET",
        re.compile(r"admin/directory/v1/users"),
        _op("admin.users.list", "admin", "none", "list", DIRECTORY_USER_SCOPES),
        users_list,
    ),
    (
        "GET",
        re.compile(r"admin/directory/v1/users/(?P<user_key>[^/]+)"),
        _op("admin.users.get", "admin", "none", "metadata", DIRECTORY_USER_SCOPES),
        users_get,
    ),
    (
        "GET",
        re.compile(r"admin/directory/v1/groups"),
        _op("admin.groups.list", "admin", "none", "list", DIRECTORY_GROUP_SCOPES),
        groups_list,
    ),
    (
        "GET",
        re.compile(r"admin/directory/v1/groups/(?P<group_key>[^/]+)/members"),
        _op("admin.members.list", "admin", "none", "list", DIRECTORY_GROUP_SCOPES),
        members_list,
    ),
    (
        "GET",
        re.compile(r"v1/documents/(?P<document_id>[^/]+)"),
        _op("docs.documents.get", "docs", "none", "docs_api", DOCS_SCOPES),
        documents_get,
    ),
]
_MEDIA_SPEC = _op(
    "drive.files.get_media", "drive", "content", "content", DRIVE_CONTENT_SCOPES
)


def _match_route(request: ApiRequest) -> tuple[OpSpec, Handler, dict[str, str]] | None:
    for method, pattern, spec, handler in _ROUTES:
        if method != request.method:
            continue
        match = pattern.fullmatch(request.path)
        if match is None:
            continue
        if handler is files_get and request.query.get("alt") == "media":
            return _MEDIA_SPEC, files_get_media, match.groupdict()
        return spec, handler, match.groupdict()
    return None
