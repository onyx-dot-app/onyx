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
from onyx.configs.constants import DocumentSource
from onyx.db.connector_credential_pair import get_connector_credential_pairs_for_user
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.enums import IndexingStatus
from onyx.db.enums import ProcessingMode
from onyx.db.index_attempt import get_latest_index_attempt_for_cc_pair_id
from onyx.db.models import BuildSession
from onyx.db.models import User
from onyx.server.features.build.api.messages_api import router as messages_router
from onyx.server.features.build.api.models import BuildConnectorInfo
from onyx.server.features.build.api.models import BuildConnectorListResponse
from onyx.server.features.build.api.models import BuildConnectorStatus
from onyx.server.features.build.api.models import RateLimitResponse
from onyx.server.features.build.api.rate_limit import get_user_rate_limit_status
from onyx.server.features.build.api.sessions_api import router as sessions_router
from onyx.server.features.build.api.user_library import router as user_library_router
from onyx.server.features.build.db.sandbox import get_sandbox_by_user_id
from onyx.server.features.build.sandbox import get_sandbox_manager
from onyx.server.features.build.session.manager import SessionManager
from onyx.server.features.build.utils import is_onyx_craft_enabled
from onyx.utils.logger import setup_logger

logger = setup_logger()


def require_onyx_craft_enabled(user: User = Depends(current_user)) -> User:
    """
    Dependency that checks if Onyx Craft is enabled for the user.
    Raises HTTP 403 if Onyx Craft is disabled via feature flag.
    """
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


# -----------------------------------------------------------------------------
# Rate Limiting
# -----------------------------------------------------------------------------


@router.get("/limit", response_model=RateLimitResponse)
def get_rate_limit(
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> RateLimitResponse:
    """Get rate limit information for the current user."""
    return get_user_rate_limit_status(user, db_session)


# -----------------------------------------------------------------------------
# Build Connectors
# -----------------------------------------------------------------------------


@router.get("/connectors", response_model=BuildConnectorListResponse)
def get_build_connectors(
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> BuildConnectorListResponse:
    """Get all connectors for the build admin panel.

    Returns connector-credential pairs with simplified status information.
    On the build configure page, all users (including admins) only see connectors
    they own/created. Users can create new connectors if they don't have one of a type.
    """
    # Fetch both FILE_SYSTEM (standard connectors) and RAW_BINARY (User Library) connectors
    file_system_cc_pairs = get_connector_credential_pairs_for_user(
        db_session=db_session,
        user=user,
        get_editable=False,
        eager_load_connector=True,
        eager_load_credential=True,
        processing_mode=ProcessingMode.FILE_SYSTEM,
    )
    raw_binary_cc_pairs = get_connector_credential_pairs_for_user(
        db_session=db_session,
        user=user,
        get_editable=False,
        eager_load_connector=True,
        eager_load_credential=True,
        processing_mode=ProcessingMode.RAW_BINARY,
    )
    cc_pairs = file_system_cc_pairs + raw_binary_cc_pairs

    # Filter to only show connectors created by the current user
    # All users (including admins) must create their own connectors on the build configure page
    if user:
        cc_pairs = [cc_pair for cc_pair in cc_pairs if cc_pair.creator_id == user.id]

    connectors: list[BuildConnectorInfo] = []
    for cc_pair in cc_pairs:
        # Skip ingestion API connectors and default pairs
        if cc_pair.connector.source == DocumentSource.INGESTION_API:
            continue
        if cc_pair.name == "DefaultCCPair":
            continue

        # Determine status
        error_message: str | None = None
        has_ever_succeeded = cc_pair.last_successful_index_time is not None

        if cc_pair.status == ConnectorCredentialPairStatus.DELETING:
            status = BuildConnectorStatus.DELETING
        elif cc_pair.status == ConnectorCredentialPairStatus.INVALID:
            # If connector has succeeded before but credentials are now invalid,
            # show as connected_with_errors so user can still disable demo data
            if has_ever_succeeded:
                status = BuildConnectorStatus.CONNECTED_WITH_ERRORS
                error_message = "Connector credentials are invalid"
            else:
                status = BuildConnectorStatus.ERROR
                error_message = "Connector credentials are invalid"
        else:
            # Check latest index attempt for errors
            latest_attempt = get_latest_index_attempt_for_cc_pair_id(
                db_session=db_session,
                connector_credential_pair_id=cc_pair.id,
                secondary_index=False,
                only_finished=True,
            )

            if latest_attempt and latest_attempt.status == IndexingStatus.FAILED:
                # If connector has succeeded before but latest attempt failed,
                # show as connected_with_errors
                if has_ever_succeeded:
                    status = BuildConnectorStatus.CONNECTED_WITH_ERRORS
                else:
                    status = BuildConnectorStatus.ERROR
                error_message = latest_attempt.error_msg
            elif (
                latest_attempt
                and latest_attempt.status == IndexingStatus.COMPLETED_WITH_ERRORS
            ):
                # Completed with errors - if it has succeeded before, show as connected_with_errors
                if has_ever_succeeded:
                    status = BuildConnectorStatus.CONNECTED_WITH_ERRORS
                else:
                    status = BuildConnectorStatus.ERROR
                error_message = "Indexing completed with errors"
            elif cc_pair.status == ConnectorCredentialPairStatus.PAUSED:
                status = BuildConnectorStatus.CONNECTED
            elif cc_pair.last_successful_index_time is None:
                # Never successfully indexed - check if currently indexing
                # First check cc_pair status for scheduled/initial indexing
                if cc_pair.status in (
                    ConnectorCredentialPairStatus.SCHEDULED,
                    ConnectorCredentialPairStatus.INITIAL_INDEXING,
                ):
                    status = BuildConnectorStatus.INDEXING
                else:
                    in_progress_attempt = get_latest_index_attempt_for_cc_pair_id(
                        db_session=db_session,
                        connector_credential_pair_id=cc_pair.id,
                        secondary_index=False,
                        only_finished=False,
                    )
                    if (
                        in_progress_attempt
                        and in_progress_attempt.status == IndexingStatus.IN_PROGRESS
                    ):
                        status = BuildConnectorStatus.INDEXING
                    elif (
                        in_progress_attempt
                        and in_progress_attempt.status == IndexingStatus.NOT_STARTED
                    ):
                        status = BuildConnectorStatus.INDEXING
                    else:
                        # Has a finished attempt but never succeeded - likely error
                        status = BuildConnectorStatus.ERROR
                        error_message = (
                            latest_attempt.error_msg
                            if latest_attempt
                            else "Initial indexing failed"
                        )
            else:
                status = BuildConnectorStatus.CONNECTED

        connectors.append(
            BuildConnectorInfo(
                cc_pair_id=cc_pair.id,
                connector_id=cc_pair.connector.id,
                credential_id=cc_pair.credential.id,
                source=cc_pair.connector.source.value,
                name=cc_pair.name or cc_pair.connector.name or "Unnamed",
                status=status,
                docs_indexed=0,  # Would need to query for this
                last_indexed=cc_pair.last_successful_index_time,
                error_message=error_message,
            )
        )

    return BuildConnectorListResponse(connectors=connectors)


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
    # Rewrite JSON data file fetch paths (e.g., /data.json, /data/tickets.json)
    # Matches paths like "/filename.json" or "/path/to/file.json"
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
    """Get the internal URL for a session's Next.js server.

    Uses the sandbox manager to get the correct URL for both local and
    Kubernetes environments.

    Args:
        session_id: The build session ID
        db_session: Database session

    Returns:
        The internal URL to proxy requests to

    Raises:
        HTTPException: If session not found, port not allocated, or sandbox not found
    """

    session = db_session.get(BuildSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.nextjs_port is None:
        raise HTTPException(status_code=503, detail="Session port not allocated")
    if session.user_id is None:
        raise HTTPException(status_code=404, detail="User not found")

    # Get the user's sandbox to get the sandbox_id
    sandbox = get_sandbox_by_user_id(db_session, session.user_id)
    if sandbox is None:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    # Use sandbox manager to get the correct internal URL
    sandbox_manager = get_sandbox_manager()
    return sandbox_manager.get_webapp_url(sandbox.id, session.nextjs_port)


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


# =============================================================================
# Sandbox Management Endpoints
# =============================================================================


@router.post("/sandbox/reset", response_model=None)
def reset_sandbox(
    user: User = Depends(current_user),
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
        logger.error(f"Failed to reset sandbox for user {user.id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to reset sandbox: {e}",
        )

    return Response(status_code=204)
