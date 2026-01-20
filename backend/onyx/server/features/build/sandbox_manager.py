"""Synchronous sandbox lifecycle management."""

from uuid import UUID

from sqlalchemy.orm import Session

from onyx.db.build_session import create_sandbox
from onyx.db.build_session import get_build_session
from onyx.db.build_session import get_latest_snapshot
from onyx.db.build_session import get_sandbox_by_session
from onyx.db.build_session import update_sandbox_status
from onyx.db.enums import SandboxStatus
from onyx.db.models import Sandbox
from onyx.utils.logger import setup_logger

logger = setup_logger()


def provision_sandbox(
    session_id: UUID,
    db_session: Session,
) -> Sandbox:
    """
    Provision a new sandbox container for a build session.

    This is a synchronous operation that:
    1. Creates a sandbox record
    2. Mounts knowledge, outputs, and instructions volumes
    3. Starts the container
    4. Updates status to RUNNING

    Args:
        session_id: UUID of the build session
        db_session: Database session

    Returns:
        The provisioned Sandbox object
    """
    logger.info(f"Provisioning sandbox for session {session_id}")

    # Get the session
    session = db_session.query("BuildSession").filter_by(id=session_id).first()
    if not session:
        raise ValueError(f"Session {session_id} not found")

    # Check if sandbox already exists
    existing_sandbox = get_sandbox_by_session(session_id, db_session)
    if existing_sandbox:
        logger.warning(
            f"Sandbox already exists for session {session_id}, returning existing"
        )
        return existing_sandbox

    # Create sandbox record
    sandbox = create_sandbox(session_id, db_session)

    # TODO: Implement actual sandbox provisioning
    # - Mount knowledge volume (read-only)
    # - Mount/create outputs volume
    # - Generate and mount instructions volume
    # - Start container
    # - Get container ID

    # For now, just update status to RUNNING with a stub container ID
    container_id = f"container-{str(session_id)[:8]}"
    update_sandbox_status(
        sandbox_id=sandbox.id,
        status=SandboxStatus.RUNNING,
        container_id=container_id,
        db_session=db_session,
    )

    logger.info(
        f"Sandbox {sandbox.id} provisioned for session {session_id} with container {container_id}"
    )
    return sandbox


def restore_sandbox(
    session_id: UUID,
    db_session: Session,
) -> Sandbox:
    """
    Restore a terminated sandbox from its latest snapshot.

    This is a synchronous operation that:
    1. Finds the latest snapshot
    2. Extracts snapshot to outputs volume
    3. Mounts volumes
    4. Starts container
    5. Updates status to RUNNING

    Args:
        session_id: UUID of the build session
        db_session: Database session

    Returns:
        The restored Sandbox object
    """
    logger.info(f"Restoring sandbox for session {session_id}")

    # Get the session and sandbox
    session = get_build_session(session_id, None, db_session)
    if not session or not session.sandbox:
        raise ValueError(f"Session or sandbox not found for {session_id}")

    sandbox = session.sandbox

    # Get latest snapshot
    snapshot = get_latest_snapshot(session_id, db_session)
    if not snapshot:
        logger.warning(
            f"No snapshot found for session {session_id}, provisioning fresh sandbox"
        )
        return provision_sandbox(session_id, db_session)

    # Update status to provisioning
    update_sandbox_status(
        sandbox_id=sandbox.id,
        status=SandboxStatus.PROVISIONING,
        db_session=db_session,
    )

    # TODO: Implement actual sandbox restoration
    # - Retrieve snapshot from storage
    # - Extract to outputs volume
    # - Mount all volumes
    # - Start container
    # - Get container ID

    # For now, just update status to RUNNING
    container_id = f"container-restored-{str(session_id)[:8]}"
    update_sandbox_status(
        sandbox_id=sandbox.id,
        status=SandboxStatus.RUNNING,
        container_id=container_id,
        db_session=db_session,
    )

    logger.info(
        f"Sandbox {sandbox.id} restored for session {session_id} from snapshot {snapshot.id}"
    )
    return sandbox


def terminate_sandbox(
    session_id: UUID,
    db_session: Session,
    create_snapshot: bool = False,
) -> None:
    """
    Terminate a running sandbox.

    This is a synchronous operation that:
    1. Optionally creates a snapshot of the outputs volume
    2. Stops the container
    3. Updates status to TERMINATED

    Args:
        session_id: UUID of the build session
        db_session: Database session
        create_snapshot: Whether to snapshot the outputs volume before terminating
    """
    logger.info(f"Terminating sandbox for session {session_id}")

    # Get the session and sandbox
    session = get_build_session(session_id, None, db_session)
    if not session or not session.sandbox:
        logger.warning(f"Session or sandbox not found for {session_id}")
        return

    sandbox = session.sandbox

    # TODO: Implement actual sandbox termination
    # - If create_snapshot: snapshot outputs volume to storage
    # - Stop container
    # - Clean up volumes (or keep for quick restart)

    # For now, just update status to TERMINATED
    update_sandbox_status(
        sandbox_id=sandbox.id,
        status=SandboxStatus.TERMINATED,
        db_session=db_session,
    )

    logger.info(f"Sandbox {sandbox.id} terminated for session {session_id}")
