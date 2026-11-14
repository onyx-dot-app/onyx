"""The mock Google Drive server.

Run it from the mock_google_drive_server directory (one worker: the corpus,
quotas and stats live in the process):

    uvicorn mock_gdrive.app:app --port 9650

Point Onyx at it with GOOGLE_API_ENDPOINT_OVERRIDE=http://localhost:9650/.
"""

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any, Literal
from urllib.parse import parse_qsl

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from .api import ApiRequest, MockGoogleApi
from .auth import ServiceAccountKeys, handle_token_request, oauth_credentials
from .batch import handle_batch
from .responses import MockResponse
from .settings import MockSettings, deep_merge, load_settings_from_env


class TouchRequest(BaseModel):
    count: int = Field(default=10, ge=1)


class MockServer:
    def __init__(self, settings: MockSettings) -> None:
        self.api = MockGoogleApi(settings)
        self.keys = ServiceAccountKeys()


def _server(request: Request) -> MockServer:
    server = request.app.state.server
    if not isinstance(server, MockServer):
        raise RuntimeError("The mock server is not initialized")
    return server


def _to_response(mock: MockResponse) -> Response:
    return Response(content=mock.body, status_code=mock.status, headers=mock.headers)


def _token_uri(request: Request) -> str:
    return f"{str(request.base_url).rstrip('/')}/token"


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.server = MockServer(load_settings_from_env())
    yield


app = FastAPI(title="Mock Google Drive", lifespan=_lifespan)


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
    return api.stats.snapshot(api.quota.usage(time.monotonic()))


@app.post("/_mock/stats/reset")
async def reset_stats(request: Request) -> dict[str, str]:
    api = _server(request).api
    api.stats.reset()
    api.quota.reset()
    return {"status": "reset"}


@app.get("/_mock/config")
async def get_config(request: Request) -> dict[str, Any]:
    return _server(request).api.settings.model_dump()


@app.patch("/_mock/config")
async def patch_config(request: Request, patch: dict[str, Any]) -> Response:
    """Changes the quota, latency and fault settings. Use POST /_mock/corpus to
    change the corpus."""
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
        return JSONResponse(
            {"detail": e.errors(include_url=False, include_context=False)},
            status_code=400,
        )
    api.update_settings(settings)
    return JSONResponse(settings.model_dump())


@app.post("/_mock/corpus")
async def regenerate_corpus(request: Request, patch: dict[str, Any]) -> Response:
    """Generates a new corpus from the current corpus settings merged with the
    body. Resets the stats."""
    api = _server(request).api
    merged = deep_merge(api.settings.model_dump(), {"corpus": patch})
    try:
        settings = MockSettings.model_validate(merged)
    except ValidationError as e:
        return JSONResponse(
            {"detail": e.errors(include_url=False, include_context=False)},
            status_code=400,
        )
    api.regenerate(settings)
    return JSONResponse(api.corpus.summary())


@app.get("/_mock/corpus/summary")
async def corpus_summary(request: Request, include_ids: bool = False) -> dict[str, Any]:
    corpus = _server(request).api.corpus
    summary: dict[str, Any] = dict(corpus.summary())
    summary["user_emails"] = list(corpus.users)
    summary["shared_drive_ids"] = list(corpus.drives)
    if include_ids:
        summary["content_file_ids"] = [f.id for f in corpus.content_files()]
    return summary


@app.get("/_mock/corpus/files/{file_id}")
async def describe_file(request: Request, file_id: str) -> Response:
    """A file as the corpus stores it, with who can read it: to explain a
    document an indexing run missed."""
    corpus = _server(request).api.corpus
    file = corpus.files.get(file_id)
    if file is None:
        return JSONResponse({"detail": "No such file"}, status_code=404)
    return JSONResponse(
        {
            "file": file.model_dump(mode="json"),
            "readers": [e for e in corpus.users if corpus.can_read(e, file)],
            "drive_members": sorted(
                corpus.drive_member_emails.get(file.drive_id or "", set())
            ),
        }
    )


@app.get("/_mock/corpus/folders/{folder_id}/content-ids")
async def folder_content_ids(request: Request, folder_id: str) -> Response:
    """The content files under a folder at any depth: what a folder target
    must index."""
    corpus = _server(request).api.corpus
    folder = corpus.files.get(folder_id)
    if folder is None or not folder.is_folder:
        return JSONResponse({"detail": "No such folder"}, status_code=404)
    return JSONResponse({"file_ids": corpus.subtree_content_ids(folder_id)})


@app.get("/_mock/corpus/users/{email}/content-ids")
async def user_content_ids(
    request: Request,
    email: str,
    scope: Literal["all_drives", "owned", "shared_with_me"] = "all_drives",
) -> Response:
    """The content files a user lists: "all_drives" is what corpora=allDrives
    returns, "owned" and "shared_with_me" split the user corpus by owner.
    These are what an OAuth connector of that user must index."""
    corpus = _server(request).api.corpus
    if email not in corpus.users:
        return JSONResponse({"detail": "No such user"}, status_code=404)
    if scope == "all_drives":
        return JSONResponse({"file_ids": corpus.all_drives_content_ids(email)})
    mine = corpus.user_corpus[email]
    owned = scope == "owned"
    return JSONResponse(
        {
            "file_ids": [
                f.id
                for f in corpus.content_files()
                if f.id in mine and (f.owner == email) == owned
            ]
        }
    )


@app.post("/_mock/corpus/touch")
async def touch_files(request: Request, body: TouchRequest) -> dict[str, list[str]]:
    """Marks random content files as modified now, for incremental runs."""
    return {"file_ids": _server(request).api.touch(body.count)}


@app.get("/_mock/service-account-key")
async def service_account_key(request: Request) -> dict[str, str]:
    """A service account key to upload as the Onyx credential. Use the corpus
    admin (admin@<domain>) as the primary admin email."""
    server = _server(request)
    return server.keys.service_account_key(
        server.api.settings.faults, _token_uri(request)
    )


@app.get("/_mock/oauth-credentials")
async def get_oauth_credentials(request: Request, email: str) -> Response:
    """An OAuth token of one domain user. External accounts get none."""
    if email not in _server(request).api.corpus.users:
        return JSONResponse({"detail": "No such user"}, status_code=404)
    return JSONResponse(oauth_credentials(email, _token_uri(request)))


@app.post("/token")
async def token(request: Request) -> Response:
    api = _server(request).api
    started = time.monotonic()
    form = dict(parse_qsl((await request.body()).decode(), keep_blank_values=True))
    response = handle_token_request(form, api.corpus, api.settings.faults)
    if api.settings.latency.enabled:
        await asyncio.sleep(api.settings.latency.token_ms / 1000)
    api.stats.record(
        op="oauth.token",
        status=response.status,
        units=0,
        nbytes=len(response.body),
        duration_ms=(time.monotonic() - started) * 1000,
        user=None,
        rate_limited=False,
        content_file_id=None,
    )
    return _to_response(response)


@app.post("/batch/drive/v3")
async def batch(request: Request) -> Response:
    api = _server(request).api
    headers = {k.lower(): v for k, v in request.headers.items()}
    response = await handle_batch(
        api, await request.body(), headers.get("content-type", ""), headers
    )
    return _to_response(response)


@app.get("/{path:path}")
async def google_api(request: Request, path: str) -> Response:
    api = _server(request).api
    mock_request = ApiRequest(
        method="GET",
        path=path,
        query=dict(request.query_params),
        headers={k.lower(): v for k, v in request.headers.items()},
    )
    return _to_response(await api.handle(mock_request))
