"""API endpoints for Build Mode session management."""

from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Response
from sqlalchemy.orm import Session

from onyx.auth.users import current_user
from onyx.configs.constants import PUBLIC_API_TAGS
from onyx.db.build_session import create_build_session
from onyx.db.build_session import delete_build_session
from onyx.db.build_session import get_build_session
from onyx.db.build_session import get_user_build_sessions
from onyx.db.build_session import update_session_activity
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import SandboxStatus
from onyx.db.models import User
from onyx.server.features.build.models import SessionCreateRequest
from onyx.server.features.build.models import SessionListResponse
from onyx.server.features.build.models import SessionResponse
from onyx.server.features.build.sandbox_manager import provision_sandbox
from onyx.server.features.build.sandbox_manager import restore_sandbox
from onyx.server.features.build.sandbox_manager import terminate_sandbox
from onyx.utils.logger import setup_logger

logger = setup_logger()


router = APIRouter(prefix="/build/sessions")


@router.get("/", tags=PUBLIC_API_TAGS)
def list_sessions(
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> SessionListResponse:
    """List all build sessions for the current user."""
    user_id = user.id if user is not None else None
    sessions = get_user_build_sessions(user_id, db_session)

    return SessionListResponse(
        sessions=[SessionResponse.from_model(session) for session in sessions]
    )


@router.post("/", tags=PUBLIC_API_TAGS)
def create_session(
    request: SessionCreateRequest,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> SessionResponse:
    """Create a new build session and provision its sandbox."""
    user_id = user.id if user is not None else None

    # Create the session
    session = create_build_session(user_id, db_session)

    # Provision sandbox synchronously
    provision_sandbox(session.id, db_session)

    # Refresh to get the created sandbox
    db_session.refresh(session)

    return SessionResponse.from_model(session)


@router.get("/{session_id}", tags=PUBLIC_API_TAGS)
def get_session_details(
    session_id: UUID,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> SessionResponse:
    """
    Get details of a specific build session.

    If the sandbox is terminated, this will restore it synchronously.
    """
    user_id = user.id if user is not None else None
    session = get_build_session(session_id, user_id, db_session)

    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    # Update last activity timestamp
    update_session_activity(session_id, db_session)

    # If sandbox is terminated, restore it synchronously
    if session.sandbox and session.sandbox.status == SandboxStatus.TERMINATED:
        logger.info(f"Restoring terminated sandbox for session_id={session_id}")
        restore_sandbox(session_id, db_session)

    # Refresh to get updated sandbox status
    db_session.refresh(session)

    return SessionResponse.from_model(session)


@router.delete("/{session_id}", tags=PUBLIC_API_TAGS)
def delete_session(
    session_id: UUID,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> Response:
    """Delete a build session and all associated data."""
    user_id = user.id if user is not None else None

    # Get session to check if it has a running sandbox
    session = get_build_session(session_id, user_id, db_session)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    # If sandbox is running, terminate it synchronously before deletion
    if session.sandbox and session.sandbox.status in [
        SandboxStatus.RUNNING,
        SandboxStatus.PROVISIONING,
    ]:
        logger.info(f"Terminating sandbox before deleting session {session_id}")
        terminate_sandbox(session_id, db_session, create_snapshot=False)

    # Delete the session (cascade will handle sandbox, artifacts, snapshots)
    success = delete_build_session(session_id, user_id, db_session)

    if not success:
        raise HTTPException(status_code=404, detail="Session not found")

    return Response(status_code=204)
