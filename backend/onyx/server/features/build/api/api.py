import re
from collections.abc import AsyncGenerator
from pathlib import Path
from uuid import UUID

import httpx
from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Request
from fastapi import Response
from fastapi.responses import RedirectResponse
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.auth.users import optional_user
from onyx.cache.factory import get_cache_backend
from onyx.db.engine.async_sql_engine import get_async_session_context_manager
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.enums import SharingScope
from onyx.db.models import User
from onyx.server.features.build.api.debug_api import router as debug_router
from onyx.server.features.build.api.external_apps_api import (
    router as external_apps_router,
)
from onyx.server.features.build.api.external_apps_oauth_api import (
    router as external_apps_oauth_router,
)
from onyx.server.features.build.api.messages_api import router as messages_router
from onyx.server.features.build.api.models import RateLimitResponse
from onyx.server.features.build.api.rate_limit import get_user_rate_limit_status
from onyx.server.features.build.api.sessions_api import router as sessions_router
from onyx.server.features.build.api.user_library import router as user_library_router
from onyx.server.features.build.approvals.api import router as approvals_router
from onyx.server.features.build.db.build_session import get_webapp_access_async
from onyx.server.features.build.db.build_session import get_webapp_target_async
from onyx.server.features.build.sandbox.base import get_sandbox_manager
from onyx.server.features.build.scheduled_tasks.api import (
    router as scheduled_tasks_router,
)
from onyx.server.features.build.session.manager import SessionManager
from onyx.server.features.build.utils import is_onyx_craft_enabled
from onyx.utils.logger import setup_logger

logger = setup_logger()

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_WEBAPP_HMR_FIXER_TEMPLATE = (_TEMPLATES_DIR / "webapp_hmr_fixer.js").read_text()

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


def require_onyx_craft_enabled(
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> User:
    if not is_onyx_craft_enabled(user):
        raise HTTPException(
            status_code=403,
            detail="Onyx Craft is not available",
        )
    return user


router = APIRouter(prefix="/build", dependencies=[Depends(require_onyx_craft_enabled)])

# Include sub-routers for sessions, messages, and user library
router.include_router(sessions_router, tags=["build"])
router.include_router(messages_router, tags=["build"])
router.include_router(user_library_router, tags=["build"])
router.include_router(scheduled_tasks_router, tags=["build"])
router.include_router(external_apps_router, tags=["build"])
router.include_router(external_apps_oauth_router, tags=["build"])
router.include_router(debug_router, tags=["build-debug"])
router.include_router(approvals_router, tags=["build"])


# -----------------------------------------------------------------------------
# Rate Limiting
# -----------------------------------------------------------------------------


@router.get("/limit", response_model=RateLimitResponse)
def get_rate_limit(
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> RateLimitResponse:
    """Get rate limit information for the current user."""
    return get_user_rate_limit_status(user, db_session)


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


def _inject_hmr_fixer(content: bytes, session_id: str) -> bytes:
    """Inject a script that stubs root-scoped Next HMR websocket connections."""
    base = f"/api/build/sessions/{session_id}/webapp"
    script = f"<script>{_WEBAPP_HMR_FIXER_TEMPLATE.replace('__WEBAPP_BASE__', base)}</script>"
    text = content.decode("utf-8")
    text = re.sub(
        r"(<head\b[^>]*>)",
        lambda m: m.group(0) + script,
        text,
        count=1,
        flags=re.IGNORECASE,
    )
    return text.encode("utf-8")


def _rewrite_asset_paths(content: bytes, session_id: str) -> bytes:
    """Rewrite Next.js asset paths to go through the proxy."""
    webapp_base_path = f"/api/build/sessions/{session_id}/webapp"
    escaped_webapp_base_path = webapp_base_path.replace("/", r"\/")
    hmr_paths = ("/_next/webpack-hmr", "/_next/hmr")

    text = content.decode("utf-8")
    # Anchor on delimiter so already-prefixed URLs (from assetPrefix) aren't double-rewritten.
    for delim in ('"', "'", "("):
        text = text.replace(f"{delim}/_next/", f"{delim}{webapp_base_path}/_next/")
        text = re.sub(
            rf"{re.escape(delim)}https?://[^/\"')]+/_next/",
            f"{delim}{webapp_base_path}/_next/",
            text,
        )
        text = re.sub(
            rf"{re.escape(delim)}wss?://[^/\"')]+/_next/",
            f"{delim}{webapp_base_path}/_next/",
            text,
        )
    text = text.replace(r"\/_next\/", rf"{escaped_webapp_base_path}\/_next\/")
    text = re.sub(
        r"https?:\\\/\\\/[^\"']+?\\\/_next\\\/",
        rf"{escaped_webapp_base_path}\/_next\/",
        text,
    )
    text = re.sub(
        r"wss?:\\\/\\\/[^\"']+?\\\/_next\\\/",
        rf"{escaped_webapp_base_path}\/_next\/",
        text,
    )
    for hmr_path in hmr_paths:
        escaped_hmr_path = hmr_path.replace("/", r"\/")
        text = text.replace(
            f"{webapp_base_path}{hmr_path}",
            hmr_path,
        )
        text = text.replace(
            f"{escaped_webapp_base_path}{escaped_hmr_path}",
            escaped_hmr_path,
        )
    text = re.sub(
        r'"(/(?:[a-zA-Z0-9_-]+/)*[a-zA-Z0-9_-]+\.json)"',
        f'"{webapp_base_path}\\1"',
        text,
    )
    text = re.sub(
        r"'(/(?:[a-zA-Z0-9_-]+/)*[a-zA-Z0-9_-]+\.json)'",
        f"'{webapp_base_path}\\1'",
        text,
    )
    text = text.replace('"/favicon.ico', f'"{webapp_base_path}/favicon.ico')
    return text.encode("utf-8")


def _rewrite_proxy_response_headers(
    headers: dict[str, str], session_id: str
) -> dict[str, str]:
    """Rewrite response headers that can leak root-scoped asset URLs."""
    link = headers.get("link")
    if link:
        webapp_base_path = f"/api/build/sessions/{session_id}/webapp"
        rewritten_link = re.sub(
            r"<https?://[^>]+/_next/",
            f"<{webapp_base_path}/_next/",
            link,
        )
        rewritten_link = rewritten_link.replace(
            "</_next/", f"<{webapp_base_path}/_next/"
        )
        headers["link"] = rewritten_link
    return headers


# Content types that may contain asset path references that need rewriting
REWRITABLE_CONTENT_TYPES = {
    "text/html",
    "text/css",
    "application/javascript",
    "text/javascript",
    "application/x-javascript",
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


async def _proxy_request(
    path: str, request: Request, session_id: UUID
) -> StreamingResponse | Response:
    """Proxy a request to the sandbox's Next.js server."""
    session_str = str(session_id)
    rel_path = path.lstrip("/")
    base_url = await _get_sandbox_url(session_id)

    target_url = f"{base_url}/{rel_path}"
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
        response_headers = _rewrite_proxy_response_headers(
            response_headers, session_str
        )

        # Only /_next/static/media/* is content-hashed (safe forever). Dev chunk/CSS
        # URLs are stable but mutable, so immutable would serve stale code after edits.
        if rel_path.startswith("_next/static/media/"):
            response_headers["cache-control"] = "public, max-age=31536000, immutable"
            response_headers.pop("pragma", None)
            response_headers.pop("expires", None)

        content_type = response.headers.get("content-type", "")

        # Buffer to rewrite /_next/ refs; idempotent for assetPrefix-prefixed URLs.
        if any(ct in content_type for ct in REWRITABLE_CONTENT_TYPES):
            try:
                raw = await response.aread()
            except httpx.RequestError as e:
                # Surface as 502 so the caller falls back to the offline page.
                logger.error("Error reading proxied body from %s: %s", target_url, e)
                raise HTTPException(status_code=502, detail="Bad gateway")
            content = _rewrite_asset_paths(raw, session_str)
            if "text/html" in content_type:
                content = _inject_hmr_fixer(content, session_str)
            return Response(
                content=content,
                status_code=response.status_code,
                headers=response_headers,
                media_type=content_type,
            )

        # Binary assets: stream through; _aiter_and_close now owns the connection.
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


# =============================================================================
# Sandbox Management Endpoints
# =============================================================================


@router.post("/sandbox/reset", response_model=None)
def reset_sandbox(
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> Response:
    """Reset the user's sandbox by terminating it and cleaning up all sessions.

    This endpoint terminates the user's shared sandbox container/pod and
    cleans up all session workspaces. Useful for "start fresh" functionality.

    After calling this endpoint, the next session creation will provision a
    new sandbox.
    """
    session_manager = SessionManager(db_session)

    try:
        success = session_manager.terminate_user_sandbox(user.id)
        if not success:
            raise HTTPException(
                status_code=404,
                detail="No sandbox found for user",
            )
        db_session.commit()
    except HTTPException:
        raise
    except Exception as e:
        db_session.rollback()
        logger.error("Failed to reset sandbox for user %s: %s", user.id, e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to reset sandbox: {e}",
        )

    return Response(status_code=204)
