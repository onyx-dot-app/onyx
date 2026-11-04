import asyncio
import secrets
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qsl, urlencode
from uuid import UUID

import httpx
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
    WebSocketException,
)
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi_users.authentication import Strategy
from pydantic import ValidationError
from starlette.websockets import WebSocketState
from websockets.asyncio.client import ClientConnection
from websockets.asyncio.client import connect as websocket_connect
from websockets.exceptions import ConnectionClosed

from onyx.auth.users import (
    auth_backend,
    current_user_from_websocket_cookie,
    is_same_origin,
    optional_user,
)
from onyx.cache.factory import get_cache_backend, get_shared_cache_backend
from onyx.configs.app_configs import WEB_DOMAIN
from onyx.db.engine.async_sql_engine import get_async_session_context_manager
from onyx.db.enums import SharingScope
from onyx.db.models import User
from onyx.db.users import is_user_active_async
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.build.db.build_session import (
    get_webapp_access_async,
    get_webapp_target_async,
)
from onyx.server.features.build.models import WebappViewerGrant
from onyx.server.features.build.sandbox.factory import get_sandbox_manager
from onyx.server.features.build.sandbox.nextjs_dev import webapp_base_path
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import (
    CURRENT_TENANT_ID_CONTEXTVAR,
    get_current_tenant_id,
)

HmrEndpoint = Literal["hmr", "webpack-hmr"]

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


# The sandboxed document has an opaque origin, so the browser sends no Onyx
# cookie with its subresource and websocket requests. A document load that the
# Onyx cookie authenticated issues this SameSite=None cookie, scoped to the one
# webapp path, carrying a capability token the sandboxed script cannot read.
_WEBAPP_VIEWER_COOKIE = "onyx_craft_webapp"
_WEBAPP_VIEWER_TTL = 600


def _webapp_viewer_grant_key(token: str) -> str:
    return f"craft:webapp:viewer:{token}"


def _load_viewer_grant(token: str, session_id: UUID) -> WebappViewerGrant | None:
    """The grant a viewer cookie carries, or None when it is absent, expired, or
    issued for another session. Shared cache: the token selects the tenant."""
    if not token:
        return None
    raw = get_shared_cache_backend().get(_webapp_viewer_grant_key(token))
    if raw is None:
        return None
    try:
        grant = WebappViewerGrant.model_validate_json(raw)
    except ValidationError:
        return None
    return grant if grant.session_id == session_id else None


def _set_viewer_cookie(
    response: Response, session_id: UUID, token: str, grant: WebappViewerGrant
) -> None:
    get_shared_cache_backend().set(
        _webapp_viewer_grant_key(token), grant.model_dump_json(), ex=_WEBAPP_VIEWER_TTL
    )
    # Secure is required with SameSite=None; browsers accept it on localhost.
    response.set_cookie(
        _WEBAPP_VIEWER_COOKIE,
        token,
        max_age=_WEBAPP_VIEWER_TTL,
        path=webapp_base_path(session_id),
        secure=True,
        httponly=True,
        samesite="none",
    )


# Response headers to skip when proxying back from the sandbox: hop-by-hop
# headers, set-cookie (no app cookies on the Onyx domain), and policy headers
# the proxy owns (no root-scoped service worker, no replaced CSP).
EXCLUDED_HEADERS = {
    "content-encoding",
    "content-length",
    "transfer-encoding",
    "connection",
    "set-cookie",
    "content-security-policy",
    "content-security-policy-report-only",
    "service-worker-allowed",
    "x-frame-options",
    "cross-origin-opener-policy",
    "cross-origin-embedder-policy",
    "cross-origin-resource-policy",
}

# Proxied webapps run LLM-generated code on the Onyx origin, so the CSP
# sandboxes every proxied document without allow-same-origin: the page gets an
# opaque origin, so it cannot read Onyx cookies or storage, reach the Craft
# page through window.parent, or register a service worker. The Craft iframe
# attribute carries the same flag set.
_WEBAPP_SECURITY_HEADERS = {
    "content-security-policy": (
        "sandbox allow-scripts allow-forms allow-modals allow-popups "
        "allow-popups-to-escape-sandbox allow-top-navigation-by-user-activation; "
        "frame-ancestors 'self'"
    ),
    "x-content-type-options": "nosniff",
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
    # Browser context. cors-mode fetches send the product Origin even
    # same-origin; Next dev blocks /_next/* requests from unlisted origins.
    # The proxy is the trust boundary (sec-fetch-* is stripped by prefix).
    "origin",
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
    rel_path = path.lstrip("/")
    base_path = webapp_base_path(session_id).lstrip("/")
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
            or lowered.startswith(("x-onyx-", "sec-fetch-"))
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
        response_headers.update(_WEBAPP_SECURITY_HEADERS)

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
    session_id: UUID, base_url: str, query_string: str, endpoint: HmrEndpoint
) -> str:
    scheme = "wss" if base_url.startswith("https://") else "ws"
    host_and_path = base_url.split("://", 1)[1].rstrip("/")
    target_url = (
        f"{scheme}://{host_and_path}/"
        f"{_webapp_next_path(session_id, f'_next/{endpoint}')}"
    )
    hmr_query_string = _webapp_hmr_query_string(query_string)
    if hmr_query_string:
        target_url = f"{target_url}?{hmr_query_string}"
    return target_url


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


async def _proxy_webapp_hmr_websocket(
    session_id: UUID, websocket: WebSocket, endpoint: HmrEndpoint
) -> None:
    base_url = await _get_sandbox_url(session_id)
    upstream_url = _webapp_hmr_websocket_url(
        session_id, base_url, websocket.url.query, endpoint
    )
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


async def _load_webapp_access(session_id: UUID) -> tuple[SharingScope, UUID]:
    async with get_async_session_context_manager() as db_session:
        access = await get_webapp_access_async(db_session, session_id)
    if access is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Session not found")
    return access


async def _check_webapp_access(session_id: UUID, user_id: UUID) -> None:
    """Runs for the Onyx session and for every viewer-grant request alike, so
    a share scope change or a deactivated viewer reaches a preview within the
    short cache TTL."""
    cache = get_cache_backend()
    if cache.get(_webapp_access_cache_key(session_id, user_id)):
        return

    async with get_async_session_context_manager() as db_session:
        access = await get_webapp_access_async(db_session, session_id)
        viewer_active = await is_user_active_async(db_session, user_id)
    if access is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Session not found")
    if not viewer_active:
        raise OnyxError(OnyxErrorCode.UNAUTHORIZED, "Account is not active")
    sharing_scope, owner_id = access
    if sharing_scope == SharingScope.PRIVATE and owner_id != user_id:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Session not found")

    cache.set(
        _webapp_access_cache_key(session_id, user_id), b"1", ex=_WEBAPP_ACCESS_TTL
    )


_OFFLINE_HTML = (_TEMPLATES_DIR / "webapp_offline.html").read_text()


def _offline_html_response() -> Response:
    return Response(
        content=_OFFLINE_HTML,
        status_code=503,
        media_type="text/html",
        headers=_WEBAPP_SECURITY_HEADERS,
    )


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
    if user is None:
        grant = _load_viewer_grant(
            request.cookies.get(_WEBAPP_VIEWER_COOKIE, ""), session_id
        )
        if grant is not None:
            # The grant never renews itself: only a load carrying the Onyx
            # session issues one, so sign-out ends preview access within the TTL.
            tenant_token = CURRENT_TENANT_ID_CONTEXTVAR.set(grant.tenant_id)
            try:
                await _check_webapp_access(session_id, grant.user_id)
                return await _proxy_or_offline(path, request, session_id)
            finally:
                CURRENT_TENANT_ID_CONTEXTVAR.reset(tenant_token)
        # A missing session must still answer 404 before the login redirect.
        await _load_webapp_access(session_id)
        return RedirectResponse(url="/auth/login", status_code=302)
    await _check_webapp_access(session_id, user.id)
    response = await _proxy_or_offline(path, request, session_id)
    grant = WebappViewerGrant(
        tenant_id=get_current_tenant_id(), session_id=session_id, user_id=user.id
    )
    _set_viewer_cookie(response, session_id, secrets.token_urlsafe(32), grant)
    return response


async def _proxy_or_offline(
    path: str, request: Request, session_id: UUID
) -> StreamingResponse | Response:
    try:
        return await _proxy_request(path, request, session_id)
    except HTTPException as e:
        if e.status_code in (502, 503, 504):
            # Cached URL may point at a dead/recreated pod; drop it to force re-resolve.
            get_cache_backend().delete(_sandbox_url_cache_key(session_id))
            return _offline_html_response()
        raise


async def webapp_websocket_viewer(
    session_id: UUID,
    websocket: WebSocket,
    strategy: Strategy[User, UUID] = Depends(auth_backend.get_strategy),
) -> AsyncGenerator[UUID, None]:
    """The user id to check access for: from a viewer cookie issued for this
    session, else from the Onyx session cookie. The sandboxed document sends
    Origin null, which only the viewer cookie path accepts."""
    grant = _load_viewer_grant(
        websocket.cookies.get(_WEBAPP_VIEWER_COOKIE, ""), session_id
    )
    if grant is not None:
        origin = websocket.headers.get("origin")
        if origin != "null" and not (origin and is_same_origin(origin, WEB_DOMAIN)):
            raise WebSocketException(code=1008)
        tenant_token = CURRENT_TENANT_ID_CONTEXTVAR.set(grant.tenant_id)
        try:
            yield grant.user_id
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(tenant_token)
        return
    cookie_user = current_user_from_websocket_cookie(websocket, strategy)
    try:
        yield (await anext(cookie_user)).id
    finally:
        await cookie_user.aclose()


webapp_websocket_viewer._is_websocket_auth_dependency = True  # ty: ignore[unresolved-attribute]


@public_build_router.websocket("/sessions/{session_id}/webapp/_next/{hmr_endpoint}")
async def websocket_webapp_hmr(
    session_id: UUID,
    hmr_endpoint: HmrEndpoint,
    websocket: WebSocket,
    viewer_user_id: UUID = Depends(webapp_websocket_viewer),
) -> None:
    try:
        await _check_webapp_access(session_id, viewer_user_id)
    except OnyxError as e:
        raise WebSocketException(code=1008) from e

    await _proxy_webapp_hmr_websocket(session_id, websocket, hmr_endpoint)
