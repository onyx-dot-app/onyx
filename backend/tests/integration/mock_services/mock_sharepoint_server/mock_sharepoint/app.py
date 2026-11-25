"""The mock Microsoft Graph and SharePoint REST server.

Run it from the mock_sharepoint_server directory (one worker: the corpus, RU
counts and stats live in the process):

    uvicorn mock_sharepoint.app:app --port 9651

It serves three hosts under path prefixes:

    /login/...               login.microsoftonline.com
    /graph/...               graph.microsoft.com
    /sharepoint/<host>/...   <tenant>.sharepoint.com

Point Onyx at it with patch_onyx.py or ../sitecustomize.py (see README.md).
"""

import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import parse_qsl, unquote

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from .api import ApiRequest, MockMicrosoftApi, Surface, WalkHook
from .auth import Credentials
from .corpus import CorpusError, FileRequest, MockItem, PermissionRequest
from .responses import MockResponse
from .settings import MockSettings, deep_merge, load_settings_from_env


class TouchRequest(BaseModel):
    """Files to mark as modified now: `file_ids`, or `count` random files."""

    count: int = Field(default=10, ge=1)
    file_ids: list[str] | None = None


class MockServer:
    def __init__(self, settings: MockSettings) -> None:
        self.api = MockMicrosoftApi(settings)
        self.credentials = Credentials()


def _server(request: Request) -> MockServer:
    server = request.app.state.server
    if not isinstance(server, MockServer):
        raise RuntimeError("The mock server is not initialized")
    return server


def _to_response(mock: MockResponse) -> Response:
    return Response(content=mock.body, status_code=mock.status, headers=mock.headers)


def _bad_request(error: ValidationError | CorpusError) -> Response:
    if isinstance(error, CorpusError):
        return JSONResponse({"detail": str(error)}, status_code=400)
    detail = error.errors(include_url=False, include_context=False, include_input=False)
    return JSONResponse({"detail": detail}, status_code=400)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.server = MockServer(load_settings_from_env())
    yield


app = FastAPI(title="Mock Microsoft Graph and SharePoint", lifespan=_lifespan)


@app.middleware("http")
async def _track_inflight(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    if request.url.path.startswith("/_mock") or request.url.path == "/health":
        return await call_next(request)
    stats = _server(request).api.stats
    stats.http_started()
    try:
        return await call_next(request)
    finally:
        stats.http_finished()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/_mock/stats")
async def get_stats(request: Request) -> dict[str, Any]:
    api = _server(request).api
    snapshot = api.stats.snapshot(api.quota.usage(time.monotonic()))
    snapshot["unmatched_requests"] = list(api.unmatched)
    return snapshot


@app.post("/_mock/stats/reset")
async def reset_stats(request: Request) -> dict[str, str]:
    """Clears the stats, the RU counts and each pause."""
    api = _server(request).api
    api.stats.reset()
    api.quota.reset()
    api.unmatched.clear()
    return {"status": "reset"}


@app.get("/_mock/config")
async def get_config(request: Request) -> dict[str, Any]:
    return _server(request).api.settings.model_dump(mode="json")


@app.patch("/_mock/config")
async def patch_config(request: Request, patch: dict[str, Any]) -> Response:
    """Changes the quota, latency, auth, paging and fault settings. Use
    POST /_mock/corpus to change the corpus."""
    api = _server(request).api
    if "corpus" in patch:
        return JSONResponse(
            {"detail": "Use POST /_mock/corpus to change the corpus."}, status_code=400
        )
    try:
        settings = MockSettings.model_validate(
            deep_merge(api.settings.model_dump(), patch)
        )
    except ValidationError as e:
        return _bad_request(e)
    api.update_settings(settings)
    return JSONResponse(settings.model_dump(mode="json"))


@app.post("/_mock/corpus")
async def regenerate_corpus(request: Request, patch: dict[str, Any]) -> Response:
    """Generates a new corpus from the current corpus settings merged with the
    body. Resets the stats, the RU counts and the write-during-walk hooks."""
    api = _server(request).api
    merged = deep_merge(api.settings.model_dump(), {"corpus": patch})
    try:
        settings = MockSettings.model_validate(merged)
    except ValidationError as e:
        return _bad_request(e)
    api.regenerate(settings)
    return JSONResponse(api.corpus.summary(include_ids=False))


@app.get("/_mock/corpus/summary")
async def corpus_summary(request: Request, include_ids: bool = False) -> dict[str, Any]:
    return _server(request).api.corpus.summary(include_ids)


def _describe_item(api: MockMicrosoftApi, item: MockItem) -> dict[str, Any]:
    corpus = api.corpus
    drive = corpus.drives[item.drive_id]
    site = corpus.site_of(drive)
    assignments = corpus.item_assignments(item)
    return {
        "file": item.model_dump(mode="json"),
        "site_url": site.web_url,
        "drive_web_url": corpus.drive_web_url(drive),
        "web_url": corpus.item_web_url(item),
        "path": "/".join(corpus.path_names(item)),
        "has_unique_permissions": item.unique_assignments is not None,
        "role_assignments": corpus.describe_assignments(assignments),
        "effective_access": corpus.effective_access(site, assignments).model_dump(),
    }


@app.get("/_mock/corpus/files/{item_id}")
async def describe_file(request: Request, item_id: str) -> Response:
    """A file or folder as the corpus stores it, with the access Onyx's
    permission sync must give it."""
    api = _server(request).api
    item = api.corpus.items.get(item_id)
    if item is None:
        return JSONResponse({"detail": "No such item"}, status_code=404)
    return JSONResponse(_describe_item(api, item))


@app.get("/_mock/corpus/pages/{page_id}")
async def describe_page(request: Request, page_id: str) -> Response:
    """A site page, with the access Onyx's permission sync must give it."""
    corpus = _server(request).api.corpus
    page = corpus.pages.get(page_id)
    if page is None:
        return JSONResponse({"detail": "No such page"}, status_code=404)
    site = corpus.sites[page.site_name]
    assignments = corpus.page_assignments(page)
    return JSONResponse(
        {
            "page": page.model_dump(mode="json"),
            "site_url": site.web_url,
            "web_url": corpus.page_web_url(page),
            "has_unique_permissions": page.unique_assignments is not None,
            "role_assignments": corpus.describe_assignments(assignments),
            "effective_access": corpus.effective_access(site, assignments).model_dump(),
        }
    )


@app.get("/_mock/corpus/sites")
async def describe_sites(request: Request) -> dict[str, Any]:
    """Each site with its libraries, the access of the site and library
    hierarchy nodes, and the groups Onyx's group sync must give."""
    corpus = _server(request).api.corpus
    sites: list[dict[str, Any]] = []
    for site in corpus.sites.values():
        if site.personal:
            continue
        drives = [corpus.drives[drive_id] for drive_id in site.drive_ids]
        sites.append(
            {
                "name": site.name,
                "url": site.web_url,
                "id": corpus.site_graph_id(site),
                "page_ids": site.page_ids,
                "role_assignments": corpus.describe_assignments(site.assignments),
                "effective_access": corpus.effective_access(
                    site, site.assignments
                ).model_dump(),
                "expected_external_groups": corpus.expected_external_groups(site),
                "site_groups": {
                    name: [corpus.principal_login_name(m) for m in group.members]
                    for name, group in site.site_groups.items()
                },
                "drives": [
                    {
                        "id": drive.id,
                        "name": drive.name,
                        "web_url": corpus.drive_web_url(drive),
                        "list_id": drive.list_id,
                        "root_id": drive.root_id,
                        "has_unique_permissions": drive.unique_assignments is not None,
                        "effective_access": corpus.effective_access(
                            site, corpus.drive_assignments(drive)
                        ).model_dump(),
                    }
                    for drive in drives
                ],
            }
        )
    return {
        "sites": sites,
        "entra_groups": [g.model_dump() for g in corpus.entra_groups.values()],
        "users": [
            {**user.model_dump(), "email": user.email} for user in corpus.users.values()
        ],
    }


@app.post("/_mock/corpus/touch")
async def touch_files(request: Request, body: TouchRequest) -> Response:
    """Marks files as modified now, for incremental runs."""
    try:
        return JSONResponse(
            {"file_ids": _server(request).api.touch(body.count, body.file_ids)}
        )
    except CorpusError as e:
        return _bad_request(e)


@app.post("/_mock/corpus/files")
async def add_file(request: Request, body: FileRequest) -> Response:
    """Adds a file, created now."""
    api = _server(request).api
    try:
        item = api.corpus.add_file(body)
    except CorpusError as e:
        return _bad_request(e)
    return JSONResponse(_describe_item(api, item))


@app.delete("/_mock/corpus/files/{item_id}")
async def delete_file(request: Request, item_id: str) -> Response:
    """Deletes a file, or a folder with what is under it."""
    try:
        return JSONResponse(
            {"deleted_ids": _server(request).api.corpus.delete_item(item_id)}
        )
    except CorpusError as e:
        return _bad_request(e)


@app.post("/_mock/corpus/permissions")
async def set_permissions(request: Request, body: PermissionRequest) -> Response:
    """Breaks or restores inheritance on an item, a page or a library."""
    corpus = _server(request).api.corpus
    try:
        assignments = corpus.set_permissions(body)
    except CorpusError as e:
        return _bad_request(e)
    return JSONResponse({"role_assignments": corpus.describe_assignments(assignments)})


@app.post("/_mock/corpus/write-during-walk")
async def arm_walk_hook(request: Request, body: WalkHook) -> Response:
    """Sets a change that the server makes after the Nth children or delta
    call on a drive."""
    try:
        hook = _server(request).api.add_hook(body)
    except CorpusError as e:
        return _bad_request(e)
    return JSONResponse(hook.model_dump(mode="json"))


@app.get("/_mock/corpus/write-during-walk")
async def list_walk_hooks(request: Request) -> dict[str, Any]:
    hooks = _server(request).api.hooks
    return {"hooks": [hook.model_dump(mode="json") for hook in hooks]}


@app.post("/_mock/corpus/expire-delta-tokens")
async def expire_delta_tokens(request: Request) -> dict[str, int]:
    """Makes each delta link and next link issued until now answer 410 Gone."""
    api = _server(request).api
    api.delta_generation += 1
    return {"generation": api.delta_generation}


@app.get("/_mock/credentials")
async def credentials(request: Request) -> dict[str, Any]:
    """The SharePoint credential for `load_credentials`, in both forms:
    `client_secret` and `certificate`."""
    server = _server(request)
    return server.credentials.credential_json(
        server.api.settings.auth, server.api.corpus.tenant_id
    )


async def _microsoft(request: Request, surface: Surface, prefix: str) -> Response:
    # The raw path keeps an encoded slash inside a path segment.
    raw_path: bytes = request.scope.get("raw_path") or request.url.path.encode()
    path = unquote(raw_path.decode().split("?", 1)[0])[len(prefix) :]
    host = ""
    if surface == "sharepoint":
        host, _, path = path.partition("/")
    query = dict(
        parse_qsl(request.scope["query_string"].decode(), keep_blank_values=True)
    )
    mock_request = ApiRequest(
        method=request.method,
        surface=surface,
        host=host.lower(),
        path=path,
        query=query,
        headers={k.lower(): v for k, v in request.headers.items()},
        body=await request.body(),
    )
    return _to_response(await _server(request).api.handle(mock_request))


@app.api_route("/login/{path:path}", methods=["GET", "POST"])
async def login(request: Request, path: str) -> Response:  # noqa: ARG001
    return await _microsoft(request, "login", "/login/")


@app.api_route("/graph/{path:path}", methods=["GET", "POST"])
async def graph(request: Request, path: str) -> Response:  # noqa: ARG001
    return await _microsoft(request, "graph", "/graph/")


@app.api_route("/sharepoint/{path:path}", methods=["GET", "POST"])
async def sharepoint(request: Request, path: str) -> Response:  # noqa: ARG001
    return await _microsoft(request, "sharepoint", "/sharepoint/")
