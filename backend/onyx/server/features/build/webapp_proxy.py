import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path
from urllib.parse import parse_qsl
from urllib.parse import urlencode
from uuid import UUID

import httpx
from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Request
from fastapi import Response
from fastapi import WebSocket
from fastapi import WebSocketDisconnect
from fastapi import WebSocketException
from fastapi.responses import RedirectResponse
from fastapi.responses import StreamingResponse
from fastapi_users.authentication.strategy.base import Strategy
from fastapi_users.manager import BaseUserManager
from starlette.websockets import WebSocketState
from websockets.asyncio.client import ClientConnection
from websockets.asyncio.client import connect as websocket_connect
from websockets.exceptions import ConnectionClosed

from onyx.auth.permissions import get_effective_permissions
from onyx.auth.users import auth_backend
from onyx.auth.users import get_user_manager
from onyx.auth.users import optional_user
from onyx.cache.factory import get_cache_backend
from onyx.configs.constants import FASTAPI_USERS_AUTH_COOKIE_NAME
from onyx.db.engine.async_sql_engine import get_async_session_context_manager
from onyx.db.enums import Permission
from onyx.db.enums import SharingScope
from onyx.db.models import User
from onyx.server.features.build.db.build_session import get_webapp_access_async
from onyx.server.features.build.db.build_session import get_webapp_target_async
from onyx.server.features.build.sandbox.factory import get_sandbox_manager
from onyx.utils.logger import setup_logger

logger = setup_logger()

_TEMPLATES_DIR = Path(__file__).parent / "templates"

# Lazy-init so importing this module (e.g. in tests) doesn't leak an open client.
_ASYNC_PROXY_CLIENT: httpx.AsyncClient | None = None


def _get_proxy_client() -> httpx.AsyncClient:
    global _ASYNC_PROXY_CLIENT
    if _ASYNC_PROXY_CLIENT is None:
        _ASYNC_PROXY_CLIENT = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            limits=httpx.Limits(max_keepalive_connections=50, max_connections=200),
        )
    return _ASYNC_PROXY_CLIENT


# Redis-backed so cache entries are shared across pods. Only grants are cached.
_SANDBOX_URL_TTL = 60
_WEBAPP_ACCESS_TTL = 30


def _sandbox_url_cache_key(session_id: UUID) -> str:
    return f"craft:webapp:url:{session_id}"


def _webapp_access_cache_key(session_id: UUID, user_id: UUID) -> str:
    return f"craft:webapp:access:{session_id}:{user_id}"


# Response headers to skip when proxying back from the sandbox.
# Hop-by-hop headers must not be forwarded, and set-cookie is stripped to
# prevent LLM-generated apps from setting cookies on the parent Onyx domain.
EXCLUDED_HEADERS = {
    "content-encoding",
    "content-length",
    "transfer-encoding",
    "connection",
    "set-cookie",
}

# Request headers stripped before forwarding to the sandbox. The sandbox runs
# LLM-generated webapp code and must never receive the viewer's Onyx
# credentials, CSRF tokens, or client-identity headers
#
# Entries must be lowercase — the filter compares against `key.lower()`.
EXCLUDED_REQUEST_HEADERS = {
    # End-to-end but unsafe to forward verbatim.
    "host",
    "content-length",
    # Hop-by-hop (RFC 7230 §6.1).
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    # Credentials.
    "cookie",
    "authorization",
    "x-api-key",
    "x-auth-token",
    # CSRF.
    "x-csrf-token",
    "x-xsrf-token",
    # Client identity (RFC 7239 + common ingress/IDP conventions).
    "forwarded",
    "x-forwarded-for",
    "x-forwarded-host",
    "x-forwarded-port",
    "x-forwarded-proto",
    "x-forwarded-server",
    "x-real-ip",
    "x-client-ip",
    "cf-connecting-ip",
    "true-client-ip",
    # IDP-injected identity (oauth2-proxy / similar).
    "x-forwarded-user",
    "x-forwarded-email",
    "x-forwarded-preferred-username",
}


async def _get_sandbox_url(session_id: UUID) -> str:
    """Resolve a session's Next.js server URL; cache hits open no DB connection."""
    cache = get_cache_backend()
    key = _sandbox_url_cache_key(session_id)
    cached = cache.get(key)
    if cached is not None:
        return cached.decode()

    async with get_async_session_context_manager() as db_session:
        target = await get_webapp_target_async(db_session, session_id)

    if target is None:
        raise HTTPException(status_code=404, detail="Session not found")
    sandbox_id, nextjs_port = target
    if nextjs_port is None:
        raise HTTPException(status_code=503, detail="Session port not allocated")
    if sandbox_id is None:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    url = get_sandbox_manager().get_webapp_url(sandbox_id, nextjs_port)
    cache.set(key, url, ex=_SANDBOX_URL_TTL)
    return url


async def _aiter_and_close(response: httpx.Response) -> AsyncGenerator[bytes, None]:
    # Runs on client disconnect (GeneratorExit) too, so the connection can't leak.
    try:
        async for chunk in response.aiter_bytes(chunk_size=8192):
            yield chunk
    finally:
        await response.aclose()


def _webapp_next_path(session_id: UUID, path: str = "") -> str:
    session_str = str(session_id)
    rel_path = path.lstrip("/")
    base_path = f"api/build/sessions/{session_str}/webapp"
    return f"{base_path}/{rel_path}" if rel_path else base_path


async def _proxy_request(
    path: str, request: Request, session_id: UUID
) -> StreamingResponse | Response:
    """Proxy a request to the sandbox's Next.js server."""
    rel_path = path.lstrip("/")
    base_url = await _get_sandbox_url(session_id)
    upstream_path = _webapp_next_path(session_id, rel_path)

    target_url = f"{base_url}/{upstream_path}"
    if request.query_params:
        target_url = f"{target_url}?{request.query_params}"

    logger.debug("Proxying request to: %s", target_url)

    forwarded_headers = {
        key: value
        for key, value in request.headers.items()
        if not (
            (lowered := key.lower()) in EXCLUDED_REQUEST_HEADERS
            or lowered.startswith("x-onyx-")
        )
    }

    client = _get_proxy_client()
    req = client.build_request("GET", target_url, headers=forwarded_headers)
    try:
        response = await client.send(req, stream=True)
    except httpx.TimeoutException:
        logger.error("Timeout while proxying request to %s", target_url)
        raise HTTPException(status_code=504, detail="Gateway timeout")
    except httpx.RequestError as e:
        logger.error("Error proxying request to %s: %s", target_url, e)
        raise HTTPException(status_code=502, detail="Bad gateway")

    # aclose() is idempotent: one guarded finally covers every exit except a
    # successful StreamingResponse handoff, which passes ownership to _aiter_and_close.
    handed_off = False
    try:
        response_headers = {
            key: value
            for key, value in response.headers.items()
            if key.lower() not in EXCLUDED_HEADERS
        }

        # Only /_next/static/media/* is content-hashed (safe forever). Dev chunk/CSS
        # URLs are stable but mutable, so immutable would serve stale code after edits.
        if rel_path.startswith("_next/static/media/"):
            response_headers["cache-control"] = "public, max-age=31536000, immutable"
            response_headers.pop("pragma", None)
            response_headers.pop("expires", None)

        content_type = response.headers.get("content-type", "")

        # Next is configured with the proxy base path, so responses pass through
        # without URL rewriting or HMR script injection.
        stream = _aiter_and_close(response)
        handed_off = True
        return StreamingResponse(
            stream,
            status_code=response.status_code,
            headers=response_headers,
            media_type=content_type or None,
        )
    finally:
        if not handed_off:
            await response.aclose()


def _webapp_hmr_query_string(query_string: str) -> str:
    return urlencode(
        [
            (key, value)
            for key, value in parse_qsl(query_string, keep_blank_values=True)
            if key == "id"
        ]
    )


def _webapp_hmr_websocket_url(
    session_id: UUID, base_url: str, query_string: str
) -> str:
    scheme = "wss" if base_url.startswith("https://") else "ws"
    host_and_path = base_url.split("://", 1)[1].rstrip("/")
    target_url = (
        f"{scheme}://{host_and_path}/"
        f"{_webapp_next_path(session_id, '_next/webpack-hmr')}"
    )
    hmr_query_string = _webapp_hmr_query_string(query_string)
    if hmr_query_string:
        target_url = f"{target_url}?{hmr_query_string}"
    return target_url


async def _current_webapp_websocket_user(
    websocket: WebSocket,
    user_manager: BaseUserManager[User, UUID] = Depends(get_user_manager),
    strategy: Strategy[User, UUID] = Depends(auth_backend.get_strategy),
) -> User:
    token = websocket.cookies.get(FASTAPI_USERS_AUTH_COOKIE_NAME)
    user = await strategy.read_token(token, user_manager)
    if user is None or not user.is_active:
        raise WebSocketException(code=1008)
    if Permission.BASIC_ACCESS not in get_effective_permissions(user):
        raise WebSocketException(code=1008)
    return user


_current_webapp_websocket_user._is_websocket_auth_dependency = True  # ty: ignore[unresolved-attribute]


async def _pump_webapp_to_upstream(
    websocket: WebSocket, upstream: ClientConnection
) -> None:
    while True:
        message = await websocket.receive()
        message_type = message["type"]
        if message_type == "websocket.disconnect":
            await upstream.close()
            return
        if "text" in message:
            await upstream.send(message["text"])
        elif "bytes" in message:
            await upstream.send(message["bytes"])


async def _pump_upstream_to_webapp(
    websocket: WebSocket, upstream: ClientConnection
) -> None:
    async for message in upstream:
        if isinstance(message, str):
            await websocket.send_text(message)
        else:
            await websocket.send_bytes(message)


async def _proxy_webapp_hmr_websocket(session_id: UUID, websocket: WebSocket) -> None:
    base_url = await _get_sandbox_url(session_id)
    upstream_url = _webapp_hmr_websocket_url(session_id, base_url, websocket.url.query)
    logger.debug("Proxying websocket to: %s", upstream_url)

    try:
        async with websocket_connect(
            upstream_url,
            additional_headers=None,
            compression=None,
            extensions=None,
            origin=None,
            proxy=None,
            subprotocols=None,
            user_agent_header=None,
        ) as upstream:
            await websocket.accept()
            webapp_task = asyncio.create_task(
                _pump_webapp_to_upstream(websocket, upstream)
            )
            upstream_task = asyncio.create_task(
                _pump_upstream_to_webapp(websocket, upstream)
            )
            done, pending = await asyncio.wait(
                {webapp_task, upstream_task}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                task.result()
    except (ConnectionClosed, WebSocketDisconnect):
        return
    except Exception as e:
        logger.warning("Error proxying webapp HMR websocket: %s", e)
        if websocket.application_state == WebSocketState.CONNECTED:
            await websocket.close(code=1011)


async def _check_webapp_access(session_id: UUID, user: User | None) -> None:
    # Only grants are cached — a 404 (missing session) must still beat 401 (unauth).
    cache = get_cache_backend()
    if user is not None and cache.get(_webapp_access_cache_key(session_id, user.id)):
        return

    async with get_async_session_context_manager() as db_session:
        access = await get_webapp_access_async(db_session, session_id)

    if access is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    sharing_scope, owner_id = access
    if sharing_scope == SharingScope.PRIVATE and owner_id != user.id:
        raise HTTPException(status_code=404, detail="Session not found")

    cache.set(
        _webapp_access_cache_key(session_id, user.id), b"1", ex=_WEBAPP_ACCESS_TTL
    )


_OFFLINE_HTML = (_TEMPLATES_DIR / "webapp_offline.html").read_text()


def _offline_html_response() -> Response:
    return Response(content=_OFFLINE_HTML, status_code=503, media_type="text/html")


# Router for the webapp proxy. The route is exempted from the global auth
# middleware (see PUBLIC_ENDPOINT_SPECS in auth_check.py) so the handler can
# return a friendly redirect to /auth/login for unauthenticated browsers
# instead of a bare 401. Auth is enforced inside the handler via
# _check_webapp_access; never wire a handler here that doesn't enforce it.
public_build_router = APIRouter(prefix="/build")


@public_build_router.get("/sessions/{session_id}/webapp", response_model=None)
@public_build_router.get(
    "/sessions/{session_id}/webapp/{path:path}", response_model=None
)
async def get_webapp(
    session_id: UUID,
    request: Request,
    path: str = "",
    user: User | None = Depends(optional_user),
) -> StreamingResponse | Response:
    try:
        await _check_webapp_access(session_id, user)
    except HTTPException as e:
        if e.status_code == 401:
            return RedirectResponse(url="/auth/login", status_code=302)
        raise
    try:
        return await _proxy_request(path, request, session_id)
    except HTTPException as e:
        if e.status_code in (502, 503, 504):
            # Cached URL may point at a dead/recreated pod; drop it to force re-resolve.
            get_cache_backend().delete(_sandbox_url_cache_key(session_id))
            return _offline_html_response()
        raise


@public_build_router.websocket("/sessions/{session_id}/webapp/_next/webpack-hmr")
async def websocket_webapp_hmr(
    session_id: UUID,
    websocket: WebSocket,
    user: User = Depends(_current_webapp_websocket_user),
) -> None:
    try:
        await _check_webapp_access(session_id, user)
    except HTTPException:
        raise WebSocketException(code=1008)

    await _proxy_webapp_hmr_websocket(session_id, websocket)
