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
from onyx.db.enums import SandboxStatus
from onyx.db.models import User
from onyx.redis.redis_pool import get_redis_client
from onyx.server.features.build.api.models import ArtifactResponse
from onyx.server.features.build.api.models import DetailedSessionResponse
from onyx.server.features.build.api.models import DirectoryListing
from onyx.server.features.build.api.models import GenerateSuggestionsRequest
from onyx.server.features.build.api.models import GenerateSuggestionsResponse
from onyx.server.features.build.api.models import SessionCreateRequest
from onyx.server.features.build.api.models import SessionListResponse
from onyx.server.features.build.api.models import SessionNameGenerateResponse
from onyx.server.features.build.api.models import SessionResponse
from onyx.server.features.build.api.models import SessionUpdateRequest
from onyx.server.features.build.api.models import SuggestionBubble
from onyx.server.features.build.api.models import SuggestionTheme
from onyx.server.features.build.api.models import UploadResponse
from onyx.server.features.build.api.models import WebappInfo
from onyx.server.features.build.db.build_session import allocate_nextjs_port
from onyx.server.features.build.db.build_session import get_build_session
from onyx.server.features.build.db.sandbox import get_latest_snapshot_for_session
from onyx.server.features.build.db.sandbox import get_sandbox_by_user_id
from onyx.server.features.build.db.sandbox import update_sandbox_status__no_commit
from onyx.server.features.build.sandbox import get_sandbox_manager
from onyx.server.features.build.session.manager import SessionManager
from onyx.server.features.build.session.manager import UploadLimitExceededError
from onyx.server.features.build.utils import sanitize_filename
from onyx.server.features.build.utils import validate_file
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

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

    # Get the user's sandbox (shared across all sessions)
    sandbox = get_sandbox_by_user_id(db_session, user.id)

    return SessionListResponse(
        sessions=[SessionResponse.from_model(session, sandbox) for session in sessions]
    )


@router.post("", response_model=DetailedSessionResponse)
def create_session(
    request: SessionCreateRequest,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> DetailedSessionResponse:
    """
    Create or get an existing empty build session.

    Creates a sandbox with the necessary file structure and returns a session ID.
    Uses SessionManager for session and sandbox provisioning.

    This endpoint is atomic - if sandbox provisioning fails, no database
    records are created (transaction is rolled back).
    """
    session_manager = SessionManager(db_session)

    try:
        # Only pass user_work_area and user_level if demo data is enabled
        # This prevents org_info directory creation when demo data is disabled
        build_session = session_manager.get_or_create_empty_session(
            user.id,
            user_work_area=(
                request.user_work_area if request.demo_data_enabled else None
            ),
            user_level=request.user_level if request.demo_data_enabled else None,
            llm_provider_type=request.llm_provider_type,
            llm_model_name=request.llm_model_name,
        )
        db_session.commit()
    except ValueError as e:
        # Max concurrent sandboxes reached or other validation error
        logger.exception("Sandbox provisioning failed")
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

    # Get the user's sandbox to include in response
    sandbox = get_sandbox_by_user_id(db_session, user.id)
    base_response = SessionResponse.from_model(build_session, sandbox)
    # Session was just created, so it's loaded in the sandbox
    return DetailedSessionResponse.from_session_response(
        base_response, session_loaded_in_sandbox=True
    )


@router.get("/{session_id}", response_model=DetailedSessionResponse)
def get_session_details(
    session_id: UUID,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> DetailedSessionResponse:
    """
    Get details of a specific build session.

    Returns session_loaded_in_sandbox to indicate if the session workspace
    exists in the running sandbox.
    """
    session_manager = SessionManager(db_session)

    session = session_manager.get_session(session_id, user.id)

    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    # Get the user's sandbox to include in response
    sandbox = get_sandbox_by_user_id(db_session, user.id)

    # Check if session workspace exists in the sandbox
    session_loaded = False
    if sandbox and sandbox.status == SandboxStatus.RUNNING:
        sandbox_manager = get_sandbox_manager()
        session_loaded = sandbox_manager.session_workspace_exists(
            sandbox.id, session_id
        )

    base_response = SessionResponse.from_model(session, sandbox)
    return DetailedSessionResponse.from_session_response(
        base_response, session_loaded_in_sandbox=session_loaded
    )


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


@router.post(
    "/{session_id}/generate-suggestions", response_model=GenerateSuggestionsResponse
)
def generate_suggestions(
    session_id: UUID,
    request: GenerateSuggestionsRequest,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> GenerateSuggestionsResponse:
    """Generate follow-up suggestions based on the first exchange in a session."""
    session_manager = SessionManager(db_session)

    # Verify session exists and belongs to user
    session = session_manager.get_session(session_id, user.id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    # Generate suggestions
    suggestions_data = session_manager.generate_followup_suggestions(
        user_message=request.user_message,
        assistant_message=request.assistant_message,
    )

    # Convert to response model
    suggestions = [
        SuggestionBubble(
            theme=SuggestionTheme(item["theme"]),
            text=item["text"],
        )
        for item in suggestions_data
    ]

    return GenerateSuggestionsResponse(suggestions=suggestions)


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

    # Get the user's sandbox to include in response
    sandbox = get_sandbox_by_user_id(db_session, user.id)
    return SessionResponse.from_model(session, sandbox)


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


# Lock timeout should be longer than max restore time (5 minutes)
RESTORE_LOCK_TIMEOUT_SECONDS = 300


@router.post("/{session_id}/restore", response_model=DetailedSessionResponse)
def restore_session(
    session_id: UUID,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> DetailedSessionResponse:
    """Restore sandbox and load session snapshot. Blocks until complete.

    Uses Redis lock to ensure only one restore runs per sandbox at a time.
    If another restore is in progress, waits for it to complete.

    Handles two cases:
    1. Sandbox is SLEEPING: Re-provision pod, then load session snapshot
    2. Sandbox is RUNNING but session not loaded: Just load session snapshot

    Returns immediately if session workspace already exists in pod.
    Always returns session_loaded_in_sandbox=True on success.
    """
    session = get_build_session(session_id, user.id, db_session)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    sandbox = get_sandbox_by_user_id(db_session, user.id)
    if not sandbox:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    # If sandbox is already running, check if session workspace exists
    sandbox_manager = get_sandbox_manager()
    tenant_id = get_current_tenant_id()

    # Need to do some work - acquire Redis lock
    redis_client = get_redis_client(tenant_id=tenant_id)
    lock_key = f"sandbox_restore:{sandbox.id}"
    lock = redis_client.lock(lock_key, timeout=RESTORE_LOCK_TIMEOUT_SECONDS)

    # blocking=True means wait if another restore is in progress
    acquired = lock.acquire(
        blocking=True, blocking_timeout=RESTORE_LOCK_TIMEOUT_SECONDS
    )
    if not acquired:
        raise HTTPException(
            status_code=503,
            detail="Restore operation timed out waiting for lock",
        )

    try:
        # Re-fetch sandbox status (may have changed while waiting for lock)
        db_session.refresh(sandbox)

        # Also re-check if session workspace exists (another request may have
        # restored it while we were waiting)
        if sandbox.status == SandboxStatus.RUNNING:
            # Verify pod is healthy before proceeding
            is_healthy = sandbox_manager.health_check(sandbox.id, timeout=10.0)
            if is_healthy and sandbox_manager.session_workspace_exists(
                sandbox.id, session_id
            ):
                logger.info(
                    f"Session {session_id} workspace was restored by another request"
                )
                base_response = SessionResponse.from_model(session, sandbox)
                return DetailedSessionResponse.from_session_response(
                    base_response, session_loaded_in_sandbox=True
                )

            if not is_healthy:
                logger.warning(
                    f"Sandbox {sandbox.id} marked as RUNNING but pod is "
                    f"unhealthy/missing. Entering recovery mode."
                )
                # Terminate to clean up any lingering K8s resources
                sandbox_manager.terminate(sandbox.id)

                update_sandbox_status__no_commit(
                    db_session, sandbox.id, SandboxStatus.TERMINATED
                )
                db_session.commit()
                db_session.refresh(sandbox)
                # Fall through to TERMINATED handling below

        session_manager = SessionManager(db_session)

        if sandbox.status in (SandboxStatus.SLEEPING, SandboxStatus.TERMINATED):
            # 1. Re-provision the pod
            logger.info(f"Re-provisioning {sandbox.status.value} sandbox {sandbox.id}")
            llm_config = session_manager._get_llm_config(None, None)
            sandbox_manager.provision(
                sandbox_id=sandbox.id,
                user_id=user.id,
                tenant_id=tenant_id,
                llm_config=llm_config,
            )
            update_sandbox_status__no_commit(
                db_session, sandbox.id, SandboxStatus.RUNNING
            )
            db_session.commit()
            db_session.refresh(sandbox)

        # 2. Check if session workspace needs to be loaded
        if sandbox.status == SandboxStatus.RUNNING:
            if not sandbox_manager.session_workspace_exists(sandbox.id, session_id):
                # Get latest snapshot and restore it
                snapshot = get_latest_snapshot_for_session(db_session, session_id)
                if snapshot:
                    # Allocate a new port for the restored session
                    new_port = allocate_nextjs_port(db_session)
                    session.nextjs_port = new_port
                    db_session.commit()

                    logger.info(
                        f"Restoring snapshot for session {session_id} "
                        f"from {snapshot.storage_path} with port {new_port}"
                    )

                    try:
                        sandbox_manager.restore_snapshot(
                            sandbox_id=sandbox.id,
                            session_id=session_id,
                            snapshot_storage_path=snapshot.storage_path,
                            tenant_id=tenant_id,
                            nextjs_port=new_port,
                        )
                    except Exception as e:
                        # Clear the port allocation on failure so it can be reused
                        logger.error(
                            f"Failed to restore session {session_id}, "
                            f"clearing port {new_port}: {e}"
                        )
                        session.nextjs_port = None
                        db_session.commit()
                        raise
                else:
                    # No snapshot - set up fresh workspace
                    logger.info(
                        f"No snapshot found for session {session_id}, "
                        f"setting up fresh workspace"
                    )
                    llm_config = session_manager._get_llm_config(None, None)
                    sandbox_manager.setup_session_workspace(
                        sandbox_id=sandbox.id,
                        session_id=session_id,
                        llm_config=llm_config,
                        nextjs_port=session.nextjs_port or 3010,
                    )

    except Exception as e:
        logger.error(f"Failed to restore session {session_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to restore session: {e}",
        )
    finally:
        if lock.owned():
            lock.release()

    base_response = SessionResponse.from_model(session, sandbox)
    return DetailedSessionResponse.from_session_response(
        base_response, session_loaded_in_sandbox=True
    )


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

    # Handle Unicode filenames in Content-Disposition header
    # HTTP headers require Latin-1 encoding, so we use RFC 5987 for Unicode
    try:
        # Try Latin-1 encoding first (ASCII-compatible filenames)
        filename.encode("latin-1")
        content_disposition = f'attachment; filename="{filename}"'
    except UnicodeEncodeError:
        # Use RFC 5987 encoding for Unicode filenames
        from urllib.parse import quote

        encoded_filename = quote(filename, safe="")
        content_disposition = f"attachment; filename*=UTF-8''{encoded_filename}"

    return Response(
        content=content,
        media_type=mime_type,
        headers={
            "Content-Disposition": content_disposition,
        },
    )


@router.get("/{session_id}/export-docx/{path:path}")
def export_docx(
    session_id: UUID,
    path: str,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> Response:
    """Export a markdown file as DOCX."""
    session_manager = SessionManager(db_session)

    try:
        result = session_manager.export_docx(session_id, user.id, path)
    except ValueError as e:
        error_message = str(e)
        if (
            "path traversal" in error_message.lower()
            or "access denied" in error_message.lower()
        ):
            raise HTTPException(status_code=403, detail="Access denied")
        raise HTTPException(status_code=400, detail=error_message)

    if result is None:
        raise HTTPException(status_code=404, detail="File not found")

    docx_bytes, filename = result

    try:
        filename.encode("latin-1")
        content_disposition = f'attachment; filename="{filename}"'
    except UnicodeEncodeError:
        from urllib.parse import quote

        encoded_filename = quote(filename, safe="")
        content_disposition = f"attachment; filename*=UTF-8''{encoded_filename}"

    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": content_disposition},
    )


@router.get("/{session_id}/webapp-info", response_model=WebappInfo)
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

    The file will be placed in the sandbox's attachments directory.
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
    except UploadLimitExceededError as e:
        # Return 429 for limit exceeded errors
        raise HTTPException(status_code=429, detail=str(e))
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
        path: Relative path to the file (e.g., "attachments/doc.pdf")
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
