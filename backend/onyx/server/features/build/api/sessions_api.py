"""API endpoints for Build Mode session management."""

from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Response
from sqlalchemy.orm import Session

from onyx.auth.users import current_user
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import User
from onyx.server.features.build.api.models import ArtifactInfo
from onyx.server.features.build.api.models import DirectoryListing
from onyx.server.features.build.api.models import SessionCreateRequest
from onyx.server.features.build.api.models import SessionListResponse
from onyx.server.features.build.api.models import SessionNameGenerateResponse
from onyx.server.features.build.api.models import SessionResponse
from onyx.server.features.build.api.models import SessionUpdateRequest
from onyx.server.features.build.session.manager import SessionManager
from onyx.utils.logger import setup_logger

logger = setup_logger()

router = APIRouter()


# =============================================================================
# Session Management Endpoints
# =============================================================================


@router.get("/sessions", response_model=SessionListResponse)
def list_sessions(
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> SessionListResponse:
    """List all build sessions for the current user."""
    session_manager = SessionManager(db_session)

    sessions = session_manager.list_sessions(user.id)

    return SessionListResponse(
        sessions=[SessionResponse.from_model(session) for session in sessions]
    )


@router.post("/sessions", response_model=SessionResponse)
def create_session(
    request: SessionCreateRequest,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> SessionResponse:
    """
    Create a new build session.

    Creates a sandbox with the necessary file structure and returns a session ID.
    Uses SessionManager for session and sandbox provisioning.
    """
    session_manager = SessionManager(db_session)

    try:
        build_session = session_manager.create_session(
            user_id=user.id,
            name=request.name,
        )
    except ValueError as e:
        # Max concurrent sandboxes reached
        raise HTTPException(status_code=429, detail=str(e))
    except RuntimeError as e:
        logger.error(f"Failed to provision sandbox: {e}")
        raise HTTPException(status_code=500, detail="Failed to create session")

    return SessionResponse.from_model(build_session)


@router.get("/sessions/{session_id}", response_model=SessionResponse)
def get_session_details(
    session_id: str,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> SessionResponse:
    """
    Get details of a specific build session.

    If the sandbox is terminated, this will restore it synchronously.
    """
    try:
        session_uuid = UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session ID format")

    session_manager = SessionManager(db_session)

    session = session_manager.get_session(session_uuid, user.id)

    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    return SessionResponse.from_model(session)


@router.post(
    "/sessions/{session_id}/generate-name", response_model=SessionNameGenerateResponse
)
def generate_session_name(
    session_id: str,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> SessionNameGenerateResponse:
    """Generate a session name using LLM based on the first user message."""
    try:
        session_uuid = UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session ID format")

    session_manager = SessionManager(db_session)

    generated_name = session_manager.generate_session_name(session_uuid, user.id)

    if generated_name is None:
        raise HTTPException(status_code=404, detail="Session not found")

    return SessionNameGenerateResponse(name=generated_name)


@router.put("/sessions/{session_id}/name", response_model=SessionResponse)
def update_session_name(
    session_id: str,
    request: SessionUpdateRequest,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> SessionResponse:
    """Update the name of a build session."""
    try:
        session_uuid = UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session ID format")

    session_manager = SessionManager(db_session)

    session = session_manager.update_session_name(session_uuid, user.id, request.name)

    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    return SessionResponse.from_model(session)


@router.delete("/sessions/{session_id}", response_model=None)
def delete_session(
    session_id: str,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> Response:
    """Delete a build session and all associated data."""
    try:
        session_uuid = UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session ID format")

    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    session_manager = SessionManager(db_session)

    success = session_manager.delete_session(session_uuid, user.id)

    if not success:
        raise HTTPException(status_code=404, detail="Session not found")

    return Response(status_code=204)


# =============================================================================
# Artifact Endpoints
# =============================================================================


@router.get("/sessions/{session_id}/artifacts", response_model=list[ArtifactInfo])
def list_artifacts(
    session_id: str,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> list[ArtifactInfo]:
    """List artifacts generated in the session."""
    try:
        session_uuid = UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session ID format")

    user_id = user.id if user is not None else None
    session_manager = SessionManager(db_session)

    artifacts = session_manager.list_artifacts(session_uuid, user_id)
    if artifacts is None:
        raise HTTPException(status_code=404, detail="Session not found")

    return artifacts


@router.get("/sessions/{session_id}/files", response_model=DirectoryListing)
def list_directory(
    session_id: str,
    path: str = "",
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> DirectoryListing:
    """
    List files and directories in the sandbox.

    Args:
        session_id: The session ID
        path: Relative path from sandbox root (empty string for root)

    Returns:
        DirectoryListing with sorted entries (directories first, then files)
    """
    try:
        session_uuid = UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session ID format")

    user_id = user.id if user is not None else None
    session_manager = SessionManager(db_session)

    try:
        listing = session_manager.list_directory(session_uuid, user_id, path)
    except ValueError as e:
        error_message = str(e)
        if "path traversal" in error_message.lower():
            raise HTTPException(status_code=403, detail="Access denied")
        elif "not found" in error_message.lower():
            raise HTTPException(status_code=404, detail="Directory not found")
        elif "not a directory" in error_message.lower():
            raise HTTPException(status_code=400, detail="Path is not a directory")
        raise HTTPException(status_code=400, detail=error_message)

    if listing is None:
        raise HTTPException(status_code=404, detail="Session not found")

    return listing


@router.get("/sessions/{session_id}/artifacts/{path:path}")
def download_artifact(
    session_id: str,
    path: str,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> Response:
    """Download a specific artifact file."""
    try:
        session_uuid = UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session ID format")

    user_id = user.id if user is not None else None
    session_manager = SessionManager(db_session)

    try:
        result = session_manager.download_artifact(session_uuid, user_id, path)
    except ValueError as e:
        error_message = str(e)
        if (
            "path traversal" in error_message.lower()
            or "access denied" in error_message.lower()
        ):
            raise HTTPException(status_code=403, detail="Access denied")
        elif "directory" in error_message.lower():
            raise HTTPException(status_code=400, detail="Cannot download directory")
        raise HTTPException(status_code=400, detail=error_message)

    if result is None:
        raise HTTPException(status_code=404, detail="Artifact not found")

    content, mime_type, filename = result

    return Response(
        content=content,
        media_type=mime_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
