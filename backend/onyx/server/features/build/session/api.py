"""API endpoints for Build Mode session management."""

import json
import time
from collections.abc import Generator
from datetime import datetime
from datetime import timezone
from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from fastapi import File
from fastapi import HTTPException
from fastapi import Response
from fastapi import UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import exists
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.db.engine.sql_engine import get_session
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import BuildSessionStatus
from onyx.db.enums import Permission
from onyx.db.enums import SandboxStatus
from onyx.db.enums import ScheduledTaskRunStatus
from onyx.db.models import BuildMessage
from onyx.db.models import User
from onyx.db.scheduled_task import get_scheduled_run_context
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.redis.redis_pool import get_redis_client
from onyx.server.features.build.db.build_session import allocate_nextjs_port
from onyx.server.features.build.db.build_session import get_build_session
from onyx.server.features.build.db.build_session import set_build_session_sharing_scope
from onyx.server.features.build.db.sandbox import ensure_sandbox_pat
from onyx.server.features.build.db.sandbox import get_latest_snapshot_for_session
from onyx.server.features.build.db.sandbox import get_sandbox_by_user_id
from onyx.server.features.build.db.sandbox import update_sandbox_heartbeat
from onyx.server.features.build.db.sandbox import update_sandbox_status__no_commit
from onyx.server.features.build.models import UploadResponse
from onyx.server.features.build.sandbox.factory import get_sandbox_manager
from onyx.server.features.build.sandbox.models import DirectoryListing
from onyx.server.features.build.sandbox.user_library import hydrate_user_library
from onyx.server.features.build.session.errors import UploadLimitExceededError
from onyx.server.features.build.session.manager import SessionManager
from onyx.server.features.build.session.models import ArtifactResponse
from onyx.server.features.build.session.models import DetailedSessionResponse
from onyx.server.features.build.session.models import PptxPreviewResponse
from onyx.server.features.build.session.models import PreProvisionedCheckResponse
from onyx.server.features.build.session.models import SessionCreateRequest
from onyx.server.features.build.session.models import SessionListResponse
from onyx.server.features.build.session.models import SessionNameGenerateResponse
from onyx.server.features.build.session.models import SessionResponse
from onyx.server.features.build.session.models import SessionUpdateRequest
from onyx.server.features.build.session.models import SetSessionSharingRequest
from onyx.server.features.build.session.models import SetSessionSharingResponse
from onyx.server.features.build.session.models import WebappInfo
from onyx.server.features.build.session.sandbox_lifecycle import (
    snapshot_opencode_history_before_recovery,
)
from onyx.server.features.build.session.streaming import SSE_KEEPALIVE
from onyx.server.features.build.utils import sanitize_filename
from onyx.server.features.build.utils import validate_file
from onyx.skills.push import build_user_skills_payload
from onyx.skills.push import hydrate_sandbox_skills
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

router = APIRouter(prefix="/sessions")


# =============================================================================
# Session Management Endpoints
# =============================================================================


@router.get("", response_model=SessionListResponse)
def list_sessions(
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
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


# Lock timeout for session creation (should be longer than max provision time)
SESSION_CREATE_LOCK_TIMEOUT_SECONDS = 300


@router.post("", response_model=DetailedSessionResponse)
def create_session(
    request: SessionCreateRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> DetailedSessionResponse:
    """
    Create or get an existing empty build session.

    Creates a sandbox with the necessary file structure and returns a session ID.
    Uses SessionManager for session and sandbox provisioning.

    This endpoint is atomic - if sandbox provisioning fails, no database
    records are created (transaction is rolled back).

    Uses Redis lock to prevent race conditions when multiple requests try to
    create/provision a session for the same user concurrently.
    """
    tenant_id = get_current_tenant_id()
    redis_client = get_redis_client(tenant_id=tenant_id)

    # Lock on user_id to prevent concurrent session creation for the same user
    # This prevents race conditions where two requests both see sandbox as SLEEPING
    # and both try to provision, with one deleting the other's work
    lock_key = f"session_create:{user.id}"
    lock = redis_client.lock(lock_key, timeout=SESSION_CREATE_LOCK_TIMEOUT_SECONDS)

    # blocking=True means wait if another create is in progress
    acquired = lock.acquire(
        blocking=True, blocking_timeout=SESSION_CREATE_LOCK_TIMEOUT_SECONDS
    )
    if not acquired:
        raise HTTPException(
            status_code=503,
            detail="Session creation timed out waiting for lock",
        )

    try:
        session_manager = SessionManager(db_session)
        build_session = session_manager.get_or_create_empty_session(
            user.id,
            llm_provider_type=request.llm_provider_type,
            llm_model_name=request.llm_model_name,
            headless=request.headless,
        )
        db_session.commit()

        sandbox = get_sandbox_by_user_id(db_session, user.id)
        base_response = SessionResponse.from_model(build_session, sandbox)
        return DetailedSessionResponse.from_session_response(
            base_response, session_loaded_in_sandbox=True
        )
    except OnyxError:
        # e.g. no provider exposes a supported model; let the global handler
        # return its own status code instead of collapsing to 429/500.
        db_session.rollback()
        raise
    except ValueError as e:
        logger.exception("Session creation failed")
        db_session.rollback()
        raise HTTPException(status_code=429, detail=str(e))
    except Exception as e:
        db_session.rollback()
        logger.error("Session creation failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Session creation failed: {e}")
    finally:
        if lock.owned():
            lock.release()


@router.get("/{session_id}", response_model=DetailedSessionResponse)
def get_session_details(
    session_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
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


@router.get(
    "/{session_id}/pre-provisioned-check", response_model=PreProvisionedCheckResponse
)
def check_pre_provisioned_session(
    session_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> PreProvisionedCheckResponse:
    """
    Check if a pre-provisioned session is still valid (empty).

    Used by the frontend to poll and detect when another tab has used
    the session. A session is considered valid if it has no messages yet.

    Returns:
        - valid=True, session_id=<id> if the session is still empty
        - valid=False, session_id=None if the session has messages or doesn't exist
    """
    session = get_build_session(session_id, user.id, db_session)

    if session is None:
        return PreProvisionedCheckResponse(valid=False, session_id=None)

    # Check if session is still empty (no messages = pre-provisioned)
    has_messages = db_session.query(
        exists().where(BuildMessage.session_id == session_id)
    ).scalar()

    if not has_messages:
        return PreProvisionedCheckResponse(valid=True, session_id=str(session_id))

    # Session has messages - it's no longer a valid pre-provisioned session
    return PreProvisionedCheckResponse(valid=False, session_id=None)


@router.post("/{session_id}/generate-name", response_model=SessionNameGenerateResponse)
def generate_session_name(
    session_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
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
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
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


@router.patch("/{session_id}/public")
def set_session_public(
    session_id: UUID,
    request: SetSessionSharingRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SetSessionSharingResponse:
    """Set the sharing scope of a build session's webapp."""
    updated = set_build_session_sharing_scope(
        session_id, user.id, request.sharing_scope, db_session
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Session not found")
    return SetSessionSharingResponse(
        session_id=str(session_id),
        sharing_scope=updated.sharing_scope,
    )


@router.delete("/{session_id}", response_model=None)
def delete_session(
    session_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
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
    except OnyxError:
        db_session.rollback()
        raise
    except HTTPException:
        # Re-raise HTTP exceptions (like 404) without rollback
        raise
    except Exception as e:
        # Sandbox termination failed - rollback to preserve session
        db_session.rollback()
        logger.error("Failed to delete session %s: %s", session_id, e)
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
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> DetailedSessionResponse:
    """Restore the sandbox (re-provisioning if asleep) and load the session
    workspace. Serialized per-sandbox via a Redis lock; returns 409 if another
    restore holds it."""
    session = get_build_session(session_id, user.id, db_session)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    sandbox = get_sandbox_by_user_id(db_session, user.id)
    if not sandbox:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    sandbox_manager = get_sandbox_manager()
    tenant_id = get_current_tenant_id()

    redis_client = get_redis_client(tenant_id=tenant_id)
    lock_key = f"sandbox_restore:{sandbox.id}"
    lock = redis_client.lock(lock_key, timeout=RESTORE_LOCK_TIMEOUT_SECONDS)

    # 409 instead of blocking — the frontend retries.
    acquired = lock.acquire(blocking=False)
    if not acquired:
        raise HTTPException(
            status_code=409,
            detail="Restore already in progress",
        )

    try:
        db_session.refresh(sandbox)

        if sandbox.status == SandboxStatus.RUNNING:
            is_healthy = sandbox_manager.health_check(sandbox.id, timeout=10.0)
            if is_healthy and sandbox_manager.session_workspace_exists(
                sandbox.id, session_id
            ):
                session.status = BuildSessionStatus.ACTIVE
                update_sandbox_heartbeat(db_session, sandbox.id)
                base_response = SessionResponse.from_model(session, sandbox)
                return DetailedSessionResponse.from_session_response(
                    base_response, session_loaded_in_sandbox=True
                )

            if not is_healthy:
                logger.warning(
                    "Sandbox %s marked as RUNNING but pod is unhealthy/missing. Entering recovery mode.",
                    sandbox.id,
                )
                snapshot_opencode_history_before_recovery(
                    sandbox_manager, sandbox.id, tenant_id
                )
                sandbox_manager.terminate(sandbox.id)
                update_sandbox_status__no_commit(
                    db_session, sandbox.id, SandboxStatus.TERMINATED
                )
                db_session.commit()
                db_session.refresh(sandbox)

        llm_config, all_llm_configs = SessionManager(db_session).build_llm_configs(user)

        if sandbox.status in (SandboxStatus.SLEEPING, SandboxStatus.TERMINATED):
            # Mint the PAT before flipping to PROVISIONING so a failure is retriable.
            onyx_pat = ensure_sandbox_pat(db_session, sandbox, user)

            update_sandbox_status__no_commit(
                db_session, sandbox.id, SandboxStatus.PROVISIONING
            )
            db_session.commit()

            sandbox_manager.provision(
                sandbox_id=sandbox.id,
                user_id=user.id,
                tenant_id=tenant_id,
                llm_config=llm_config,
                onyx_pat=onyx_pat,
                all_llm_configs=all_llm_configs,
            )

            update_sandbox_status__no_commit(
                db_session, sandbox.id, SandboxStatus.RUNNING
            )
            db_session.commit()

        if sandbox.status == SandboxStatus.RUNNING:
            workspace_exists = sandbox_manager.session_workspace_exists(
                sandbox.id, session_id
            )

            if not workspace_exists:
                if not session.nextjs_port:
                    session.nextjs_port = allocate_nextjs_port(db_session)
                    db_session.commit()

                snapshot = get_latest_snapshot_for_session(db_session, session_id)

                skills_section, skills_files = build_user_skills_payload(
                    user, db_session
                )
                if snapshot:
                    try:
                        sandbox_manager.restore_snapshot(
                            sandbox_id=sandbox.id,
                            session_id=session_id,
                            snapshot_storage_path=snapshot.storage_path,
                            nextjs_port=session.nextjs_port,
                            llm_config=llm_config,
                            skills_section=skills_section,
                        )
                        session.status = BuildSessionStatus.ACTIVE
                        db_session.commit()
                    except Exception as e:
                        logger.error(
                            "Snapshot restore failed for session %s: %s", session_id, e
                        )
                        session.nextjs_port = None
                        db_session.commit()
                        raise
                else:
                    sandbox_manager.setup_session_workspace(
                        sandbox_id=sandbox.id,
                        session_id=session_id,
                        llm_config=llm_config,
                        nextjs_port=session.nextjs_port,
                        skills_section=skills_section,
                    )
                    session.status = BuildSessionStatus.ACTIVE
                    db_session.commit()

                try:
                    hydrate_sandbox_skills(
                        sandbox.id, user, db_session, files=skills_files
                    )
                except Exception:
                    logger.warning(
                        "Failed to push skills to sandbox %s",
                        sandbox.id,
                        exc_info=True,
                    )

                try:
                    hydrate_user_library(sandbox.id, user.id, db_session)
                except Exception:
                    logger.warning(
                        "Failed to push user library to sandbox %s",
                        sandbox.id,
                        exc_info=True,
                    )
        else:
            logger.warning(
                "Sandbox %s status is %s after re-provision, expected RUNNING",
                sandbox.id,
                sandbox.status,
            )

    except Exception as e:
        logger.error("Failed to restore session %s: %s", session_id, e, exc_info=True)
        # Recover so the next attempt isn't blocked by a half-finished state.
        try:
            db_session.rollback()
            stuck = get_sandbox_by_user_id(db_session, user.id)
            if stuck is not None and stuck.status == SandboxStatus.PROVISIONING:
                # provision() failed — back to SLEEPING so it isn't stuck.
                update_sandbox_status__no_commit(
                    db_session, stuck.id, SandboxStatus.SLEEPING
                )
                db_session.commit()
                logger.info(
                    "Rolled sandbox %s back to SLEEPING after failed restore",
                    stuck.id,
                )
            elif stuck is not None and stuck.status == SandboxStatus.RUNNING:
                # Workspace load failed after provision — drop the partial dir
                # so session_workspace_exists() doesn't later report it restored.
                sandbox_manager.cleanup_session_workspace(stuck.id, session_id)
                logger.info(
                    "Cleaned up partial workspace for session %s after failed restore",
                    session_id,
                )
        except Exception as rollback_err:
            logger.warning(
                "Failed to recover sandbox state after restore failure: %s",
                rollback_err,
            )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to restore session: {e}",
        )
    finally:
        if lock.owned():
            lock.release()

    # Update heartbeat to mark sandbox as active after successful restore
    update_sandbox_heartbeat(db_session, sandbox.id)

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
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
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
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
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
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
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
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
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


@router.get("/{session_id}/pptx-preview/{path:path}")
def get_pptx_preview(
    session_id: UUID,
    path: str,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> PptxPreviewResponse:
    """Generate slide image previews for a PPTX file."""
    session_manager = SessionManager(db_session)

    try:
        result = session_manager.get_pptx_preview(session_id, user.id, path)
    except ValueError as e:
        error_message = str(e)
        if (
            "path traversal" in error_message.lower()
            or "access denied" in error_message.lower()
        ):
            raise HTTPException(status_code=403, detail="Access denied")
        raise HTTPException(status_code=400, detail=error_message)

    if result is None:
        raise HTTPException(status_code=404, detail="Session not found")

    return PptxPreviewResponse(**result)


@router.get("/{session_id}/webapp-info", response_model=WebappInfo)
def get_webapp_info(
    session_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
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


@router.get("/{session_id}/webapp-download")
def download_webapp(
    session_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
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


@router.get("/{session_id}/download-directory/{path:path}")
def download_directory(
    session_id: UUID,
    path: str,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> Response:
    """
    Download a directory as a zip file.

    Returns the specified directory as a zip archive.
    """
    user_id: UUID = user.id
    session_manager = SessionManager(db_session)

    try:
        result = session_manager.download_directory(session_id, user_id, path)
    except ValueError as e:
        error_message = str(e)
        if "path traversal" in error_message.lower():
            raise HTTPException(status_code=403, detail="Access denied")
        raise HTTPException(status_code=400, detail=error_message)

    if result is None:
        raise HTTPException(status_code=404, detail="Directory not found")

    zip_bytes, filename = result

    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.post("/{session_id}/upload", response_model=UploadResponse)
def upload_file_endpoint(
    session_id: UUID,
    file: UploadFile = File(...),
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> UploadResponse:
    """Upload a file to the session's sandbox.

    The file will be placed in the sandbox's attachments directory.
    """
    user_id: UUID = user.id
    session_manager = SessionManager(db_session)

    if not file.filename:
        raise HTTPException(status_code=400, detail="File has no filename")

    # Read file content (use sync file interface)
    content = file.file.read()

    # Validate file size (extension/type are intentionally unrestricted)
    is_valid, error = validate_file(len(content))
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
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
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


# =============================================================================
# Scheduled Task — session-view banner
# =============================================================================


class ScheduledRunContextResponse(BaseModel):
    """Context surfaced by the session-view banner when a session came from a
    scheduled run. Returned by ``GET /sessions/{id}/scheduled-run-context``.
    """

    run_id: str
    task_id: str
    task_name: str
    status: ScheduledTaskRunStatus
    started_at: datetime
    finished_at: datetime | None


@router.get("/{session_id}/scheduled-run-context")
def get_session_scheduled_run_context(
    session_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> ScheduledRunContextResponse:
    """Return the scheduled-task context for a session, if any.

    The web UI calls this on every session view; a 200 response means
    "render the banner above the transcript and apply scheduled-run state".
    A 404 means "this is an interactive session, behave normally".
    """
    context = get_scheduled_run_context(
        db_session=db_session,
        session_id=session_id,
        user_id=user.id,
    )
    if context is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Session has no scheduled-run context")
    return ScheduledRunContextResponse(
        run_id=str(context["run_id"]),
        task_id=str(context["task_id"]),
        task_name=context["task_name"],
        status=context["status"],
        started_at=context["started_at"],
        finished_at=context["finished_at"],
    )


LIVE_STREAM_READY_POLL_SECONDS = 1.0
LIVE_STREAM_KEEPALIVE_SECONDS = 15.0


def _scheduled_run_is_running(
    *,
    db_session: Session,
    session_id: UUID,
    user_id: UUID,
) -> bool:
    context = get_scheduled_run_context(
        db_session=db_session,
        session_id=session_id,
        user_id=user_id,
    )
    return context is not None and context["status"] == ScheduledTaskRunStatus.RUNNING


def _format_stream_error(detail: str) -> str:
    payload = {
        "type": "error",
        "message": detail,
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
    }
    return f"event: message\ndata: {json.dumps(payload)}\n\n"


@router.get("/{session_id}/scheduled-run-events")
def get_session_scheduled_run_events(
    session_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> StreamingResponse:
    """Stream live ACP events for a running scheduled-origin Craft session."""
    context = get_scheduled_run_context(
        db_session=db_session,
        session_id=session_id,
        user_id=user.id,
    )
    if context is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Session has no scheduled-run context")
    if context["status"] != ScheduledTaskRunStatus.RUNNING:
        raise OnyxError(OnyxErrorCode.CONFLICT, "Scheduled run is not running")

    user_id = user.id

    def stream_generator() -> Generator[str, None, None]:
        # The executor links ScheduledTaskRun.session_id just before it resolves
        # and persists BuildSession.opencode_session_id. Keep the HTTP stream
        # alive during that short handoff so a fast click from the run table can
        # attach without a visible error.
        while True:
            with get_session_with_current_tenant() as stream_db_session:
                if not _scheduled_run_is_running(
                    db_session=stream_db_session,
                    session_id=session_id,
                    user_id=user_id,
                ):
                    return

                session = get_build_session(session_id, user_id, stream_db_session)
                if session is None:
                    yield _format_stream_error("Session not found")
                    return
                if session.opencode_session_id:
                    break

            yield SSE_KEEPALIVE
            time.sleep(LIVE_STREAM_READY_POLL_SECONDS)

        try:
            with get_session_with_current_tenant() as stream_db_session:
                session_manager = SessionManager(stream_db_session)
                for chunk in session_manager.subscribe_to_existing_session_events(
                    session_id,
                    user_id,
                    keepalive_seconds=LIVE_STREAM_KEEPALIVE_SECONDS,
                ):
                    yield chunk
                    stream_db_session.expire_all()
                    if not _scheduled_run_is_running(
                        db_session=stream_db_session,
                        session_id=session_id,
                        user_id=user_id,
                    ):
                        return
        except GeneratorExit:
            logger.info(
                "Scheduled run live stream disconnected for session %s", session_id
            )
            raise
        except OnyxError as exc:
            yield _format_stream_error(exc.detail)
        except Exception as exc:
            logger.exception(
                "Scheduled run live stream failed for session %s", session_id
            )
            yield _format_stream_error(str(exc))

    return StreamingResponse(
        stream_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
