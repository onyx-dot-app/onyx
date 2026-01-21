from collections.abc import Iterator
from uuid import UUID

import httpx
from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Request
from fastapi import Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from onyx.auth.users import current_user
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import User
from onyx.server.features.build.api.messages_api import router as messages_router
from onyx.server.features.build.api.sessions_api import router as sessions_router
from onyx.server.features.build.db.sandbox import get_sandbox_by_session_id
from onyx.utils.logger import setup_logger

logger = setup_logger()

router = APIRouter(prefix="/build")

# Include sub-routers for sessions and messages
router.include_router(sessions_router, tags=["build"])
router.include_router(messages_router, tags=["build"])

# Headers to skip when proxying (hop-by-hop headers)
EXCLUDED_HEADERS = {
    "content-encoding",
    "content-length",
    "transfer-encoding",
    "connection",
}


def _stream_response(response: httpx.Response) -> Iterator[bytes]:
    """Stream the response content in chunks."""
    for chunk in response.iter_bytes(chunk_size=8192):
        yield chunk


def _rewrite_asset_paths(content: bytes, session_id: str) -> bytes:
    """Rewrite Next.js asset paths to go through the proxy."""
    import re

    # Base path includes session_id for routing
    webapp_base_path = f"/api/build/sessions/{session_id}/webapp"

    text = content.decode("utf-8")
    # Rewrite /_next/ paths to go through our proxy
    text = text.replace("/_next/", f"{webapp_base_path}/_next/")
    # Rewrite root-level JSON data file fetch paths (e.g., /data.json, /pr_data.json)
    # Only matches paths like "/filename.json" (no subdirectories)
    text = re.sub(r'"(/[a-zA-Z0-9_-]+\.json)"', f'"{webapp_base_path}\\1"', text)
    text = re.sub(r"'(/[a-zA-Z0-9_-]+\.json)'", f"'{webapp_base_path}\\1'", text)
    # Rewrite favicon
    text = text.replace('"/favicon.ico', f'"{webapp_base_path}/favicon.ico')
    return text.encode("utf-8")


# Content types that may contain asset path references that need rewriting
REWRITABLE_CONTENT_TYPES = {
    "text/html",
    "text/css",
    "application/javascript",
    "text/javascript",
    "application/x-javascript",
}


def _get_sandbox_url(session_id: UUID, db_session: Session) -> str:
    """Get the localhost URL for a sandbox's Next.js server.

    Args:
        session_id: The build session ID
        db_session: Database session

    Returns:
        The localhost URL (e.g., "http://localhost:3010")

    Raises:
        HTTPException: If sandbox not found or port not allocated
    """
    sandbox = get_sandbox_by_session_id(db_session, session_id)
    if not sandbox:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    if sandbox.nextjs_port is None:
        raise HTTPException(status_code=503, detail="Sandbox port not allocated")
    return f"http://localhost:{sandbox.nextjs_port}"


def _proxy_request(
    path: str, request: Request, session_id: UUID, db_session: Session
) -> StreamingResponse | Response:
    """Proxy a request to the sandbox's Next.js server."""
    base_url = _get_sandbox_url(session_id, db_session)

    # Build the target URL
    target_url = f"{base_url}/{path.lstrip('/')}"

    # Include query params if present
    if request.query_params:
        target_url = f"{target_url}?{request.query_params}"

    logger.debug(f"Proxying request to: {target_url}")

    try:
        # Make the request to the target URL
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            response = client.get(
                target_url,
                headers={
                    key: value
                    for key, value in request.headers.items()
                    if key.lower() not in ("host", "content-length")
                },
            )

            # Build response headers, excluding hop-by-hop headers
            response_headers = {
                key: value
                for key, value in response.headers.items()
                if key.lower() not in EXCLUDED_HEADERS
            }

            content_type = response.headers.get("content-type", "")

            # For HTML/CSS/JS responses, rewrite asset paths
            if any(ct in content_type for ct in REWRITABLE_CONTENT_TYPES):
                content = _rewrite_asset_paths(response.content, str(session_id))
                return Response(
                    content=content,
                    status_code=response.status_code,
                    headers=response_headers,
                    media_type=content_type,
                )

            return StreamingResponse(
                content=_stream_response(response),
                status_code=response.status_code,
                headers=response_headers,
                media_type=content_type or None,
            )

    except httpx.TimeoutException:
        logger.error(f"Timeout while proxying request to {target_url}")
        raise HTTPException(status_code=504, detail="Gateway timeout")
    except httpx.RequestError as e:
        logger.error(f"Error proxying request to {target_url}: {e}")
        raise HTTPException(status_code=502, detail="Bad gateway")


@router.get("/sessions/{session_id}/webapp", response_model=None)
def get_webapp_root(
    session_id: UUID,
    request: Request,
    _: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> StreamingResponse | Response:
    """Proxy the root path of the webapp for a specific session."""
    return _proxy_request("", request, session_id, db_session)


@router.get("/sessions/{session_id}/webapp/{path:path}", response_model=None)
def get_webapp_path(
    session_id: UUID,
    path: str,
    request: Request,
    _: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> StreamingResponse | Response:
    """Proxy any subpath of the webapp (static assets, etc.) for a specific session."""
    return _proxy_request(path, request, session_id, db_session)


# Separate router for Next.js static assets at /_next/*
# This is needed because Next.js apps may reference assets with root-relative paths
# that don't get rewritten. The session_id is extracted from the Referer header.
nextjs_assets_router = APIRouter()


def _extract_session_from_referer(request: Request) -> UUID | None:
    """Extract session_id from the Referer header.

    Expects Referer to contain /api/build/sessions/{session_id}/webapp
    """
    import re

    referer = request.headers.get("referer", "")
    match = re.search(r"/api/build/sessions/([a-f0-9-]+)/webapp", referer)
    if match:
        try:
            return UUID(match.group(1))
        except ValueError:
            return None
    return None


@nextjs_assets_router.get("/_next/{path:path}", response_model=None)
def get_nextjs_assets(
    path: str,
    request: Request,
    _: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> StreamingResponse | Response:
    """Proxy Next.js static assets requested at root /_next/ path.

    The session_id is extracted from the Referer header since these requests
    come from within the iframe context.
    """
    session_id = _extract_session_from_referer(request)
    if not session_id:
        raise HTTPException(
            status_code=400,
            detail="Could not determine session from request context",
        )
    return _proxy_request(f"_next/{path}", request, session_id, db_session)
