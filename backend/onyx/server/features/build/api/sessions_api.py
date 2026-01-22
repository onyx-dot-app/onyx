"""API endpoints for Build Mode session management."""

from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from fastapi import File
from fastapi import HTTPException
from fastapi import Response
from fastapi import UploadFile
from sqlalchemy.orm import Session

from onyx.auth.users import current_user
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import User
from onyx.server.features.build.api.models import ArtifactResponse
from onyx.server.features.build.api.models import DirectoryListing
from onyx.server.features.build.api.models import SessionCreateRequest
from onyx.server.features.build.api.models import SessionListResponse
from onyx.server.features.build.api.models import SessionNameGenerateResponse
from onyx.server.features.build.api.models import SessionResponse
from onyx.server.features.build.api.models import SessionUpdateRequest
from onyx.server.features.build.api.models import UploadResponse
from onyx.server.features.build.api.models import WebappInfo
from onyx.server.features.build.session.manager import SessionManager
from onyx.server.features.build.utils import sanitize_filename
from onyx.server.features.build.utils import validate_file
from onyx.utils.logger import setup_logger

logger = setup_logger()

router = APIRouter(prefix="/sessions")


# =============================================================================
# Session Management Endpoints
# =============================================================================


@router.get("", response_model=SessionListResponse)
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


@router.post("", response_model=SessionResponse)
def create_session(
    request: SessionCreateRequest,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> SessionResponse:
    """
    Create or get an existing empty build session.

    Creates a sandbox with the necessary file structure and returns a session ID.
    Uses SessionManager for session and sandbox provisioning.

    This endpoint is atomic - if sandbox provisioning fails, no database
    records are created (transaction is rolled back).
    """
    session_manager = SessionManager(db_session)

    try:
        build_session = session_manager.get_or_create_empty_session(user.id)
        db_session.commit()
    except ValueError as e:
        # Max concurrent sandboxes reached or other validation error
        db_session.rollback()
        raise HTTPException(status_code=429, detail=str(e))
    except Exception as e:
        # Sandbox provisioning failed - rollback to remove any uncommitted records
        db_session.rollback()
        logger.error(f"Sandbox provisioning failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Sandbox provisioning failed: {e}",
        )

    return SessionResponse.from_model(build_session)


@router.get("/{session_id}", response_model=SessionResponse)
def get_session_details(
    session_id: UUID,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> SessionResponse:
    """
    Get details of a specific build session.

    If the sandbox is terminated, this will restore it synchronously.
    """
    session_manager = SessionManager(db_session)

    session = session_manager.get_session(session_id, user.id)

    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    return SessionResponse.from_model(session)


@router.post("/{session_id}/generate-name", response_model=SessionNameGenerateResponse)
def generate_session_name(
    session_id: UUID,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> SessionNameGenerateResponse:
    """Generate a session name using LLM based on the first user message."""
    session_manager = SessionManager(db_session)

    generated_name = session_manager.generate_session_name(session_id, user.id)

    if generated_name is None:
        raise HTTPException(status_code=404, detail="Session not found")

    return SessionNameGenerateResponse(name=generated_name)


@router.put("/{session_id}/name", response_model=SessionResponse)
def update_session_name(
    session_id: UUID,
    request: SessionUpdateRequest,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> SessionResponse:
    """Update the name of a build session."""
    session_manager = SessionManager(db_session)

    session = session_manager.update_session_name(session_id, user.id, request.name)

    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    return SessionResponse.from_model(session)


@router.delete("/{session_id}", response_model=None)
def delete_session(
    session_id: UUID,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> Response:
    """Delete a build session and all associated data.

    This endpoint is atomic - if sandbox termination fails, the session
    is NOT deleted (transaction is rolled back).
    """
    session_manager = SessionManager(db_session)

    try:
        success = session_manager.delete_session(session_id, user.id)
        if not success:
            raise HTTPException(status_code=404, detail="Session not found")
        db_session.commit()
    except HTTPException:
        # Re-raise HTTP exceptions (like 404) without rollback
        raise
    except Exception as e:
        # Sandbox termination failed - rollback to preserve session
        db_session.rollback()
        logger.error(f"Failed to delete session {session_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete session: {e}",
        )

    return Response(status_code=204)


# =============================================================================
# Artifact Endpoints
# =============================================================================


@router.get(
    "/{session_id}/artifacts",
    response_model=list[ArtifactResponse],
)
def list_artifacts(
    session_id: UUID,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> list[dict]:
    """List artifacts generated in the session."""
    user_id: UUID = user.id
    session_manager = SessionManager(db_session)

    artifacts = session_manager.list_artifacts(session_id, user_id)
    if artifacts is None:
        raise HTTPException(status_code=404, detail="Session not found")

    return artifacts


@router.get("/{session_id}/files", response_model=DirectoryListing)
def list_directory(
    session_id: UUID,
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
    user_id: UUID = user.id
    session_manager = SessionManager(db_session)

    try:
        listing = session_manager.list_directory(session_id, user_id, path)
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


@router.get("/{session_id}/artifacts/{path:path}")
def download_artifact(
    session_id: UUID,
    path: str,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> Response:
    """Download a specific artifact file."""
    user_id: UUID = user.id
    session_manager = SessionManager(db_session)

    try:
        result = session_manager.download_artifact(session_id, user_id, path)
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


@router.get("/{session_id}/webapp", response_model=WebappInfo)
def get_webapp_info(
    session_id: UUID,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> WebappInfo:
    """
    Get webapp information for a session.

    Returns whether a webapp exists, its URL, and the sandbox status.
    """
    user_id: UUID = user.id
    session_manager = SessionManager(db_session)

    webapp_info = session_manager.get_webapp_info(session_id, user_id)

    if webapp_info is None:
        raise HTTPException(status_code=404, detail="Session not found")

    return WebappInfo(**webapp_info)


@router.get("/{session_id}/webapp/download")
def download_webapp(
    session_id: UUID,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> Response:
    """
    Download the webapp directory as a zip file.

    Returns the entire outputs/web directory as a zip archive.
    """
    user_id: UUID = user.id
    session_manager = SessionManager(db_session)

    result = session_manager.download_webapp_zip(session_id, user_id)

    if result is None:
        raise HTTPException(status_code=404, detail="Webapp not found")

    zip_bytes, filename = result

    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.post("/{session_id}/upload", response_model=UploadResponse)
async def upload_file_endpoint(
    session_id: UUID,
    file: UploadFile = File(...),
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> UploadResponse:
    """Upload a file to the session's sandbox.

    The file will be placed in the sandbox's user_uploaded_files directory.
    """
    user_id: UUID = user.id
    session_manager = SessionManager(db_session)

    if not file.filename:
        raise HTTPException(status_code=400, detail="File has no filename")

    # Read file content
    content = await file.read()

    # Validate file (extension, mime type, size)
    is_valid, error = validate_file(file.filename, file.content_type, len(content))
    if not is_valid:
        raise HTTPException(status_code=400, detail=error)

    # Sanitize filename
    safe_filename = sanitize_filename(file.filename)

    try:
        relative_path, _ = session_manager.upload_file(
            session_id=session_id,
            user_id=user_id,
            filename=safe_filename,
            content=content,
        )
    except ValueError as e:
        error_message = str(e)
        if "not found" in error_message.lower():
            raise HTTPException(status_code=404, detail=error_message)
        raise HTTPException(status_code=400, detail=error_message)

    return UploadResponse(
        filename=safe_filename,
        path=relative_path,
        size_bytes=len(content),
    )


@router.delete("/{session_id}/files/{path:path}", response_model=None)
def delete_file_endpoint(
    session_id: UUID,
    path: str,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> Response:
    """Delete a file from the session's sandbox.

    Args:
        session_id: The session ID
        path: Relative path to the file (e.g., "user_uploaded_files/doc.pdf")
    """
    user_id: UUID = user.id
    session_manager = SessionManager(db_session)

    try:
        deleted = session_manager.delete_file(session_id, user_id, path)
    except ValueError as e:
        error_message = str(e)
        if "path traversal" in error_message.lower():
            raise HTTPException(status_code=403, detail="Access denied")
        elif "not found" in error_message.lower():
            raise HTTPException(status_code=404, detail=error_message)
        elif "directory" in error_message.lower():
            raise HTTPException(status_code=400, detail="Cannot delete directory")
        raise HTTPException(status_code=400, detail=error_message)

    if not deleted:
        raise HTTPException(status_code=404, detail="File not found")

    return Response(status_code=204)
