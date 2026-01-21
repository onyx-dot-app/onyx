"""Database operations for Build Mode sessions."""

from datetime import datetime
from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import desc
from sqlalchemy import exists
from sqlalchemy.orm import Session

from onyx.configs.constants import MessageType
from onyx.db.enums import BuildSessionStatus
from onyx.db.enums import SandboxStatus
from onyx.db.models import Artifact
from onyx.db.models import BuildMessage
from onyx.db.models import BuildSession
from onyx.db.models import Sandbox
from onyx.db.models import Snapshot
from onyx.utils.logger import setup_logger

logger = setup_logger()


def create_build_session(
    user_id: UUID,
    db_session: Session,
    name: str | None = None,
) -> BuildSession:
    """Create a new build session for the given user."""
    session = BuildSession(
        user_id=user_id,
        name=name,
        status=BuildSessionStatus.ACTIVE,
    )
    db_session.add(session)
    db_session.commit()
    db_session.refresh(session)

    logger.info(f"Created build session {session.id} for user {user_id}")
    return session


def get_build_session(
    session_id: UUID,
    user_id: UUID,
    db_session: Session,
) -> BuildSession | None:
    """Get a build session by ID, ensuring it belongs to the user."""
    return (
        db_session.query(BuildSession)
        .filter(
            BuildSession.id == session_id,
            BuildSession.user_id == user_id,
        )
        .one_or_none()
    )


def get_user_build_sessions(
    user_id: UUID,
    db_session: Session,
    limit: int = 100,
) -> list[BuildSession]:
    """Get all build sessions for a user that have at least 1 message.

    Excludes empty (pre-provisioned) sessions from the listing.
    """
    return (
        db_session.query(BuildSession)
        .join(BuildMessage)  # Inner join excludes empty sessions
        .filter(BuildSession.user_id == user_id)
        .group_by(BuildSession.id)
        .order_by(desc(BuildSession.created_at))
        .limit(limit)
        .all()
    )


def get_empty_session_for_user(
    user_id: UUID,
    db_session: Session,
    max_age_minutes: int = 30,
) -> BuildSession | None:
    """Get the user's empty session (0 messages) if one exists and is recent."""
    cutoff = datetime.utcnow() - timedelta(minutes=max_age_minutes)

    return (
        db_session.query(BuildSession)
        .filter(
            BuildSession.user_id == user_id,
            BuildSession.created_at > cutoff,
            ~exists().where(BuildMessage.session_id == BuildSession.id),
        )
        .first()
    )


def update_session_activity(
    session_id: UUID,
    db_session: Session,
) -> None:
    """Update the last activity timestamp for a session."""
    session = (
        db_session.query(BuildSession)
        .filter(BuildSession.id == session_id)
        .one_or_none()
    )
    if session:
        session.last_activity_at = datetime.utcnow()
        db_session.commit()


def update_session_status(
    session_id: UUID,
    status: BuildSessionStatus,
    db_session: Session,
) -> None:
    """Update the status of a build session."""
    session = (
        db_session.query(BuildSession)
        .filter(BuildSession.id == session_id)
        .one_or_none()
    )
    if session:
        session.status = status
        db_session.commit()
        logger.info(f"Updated build session {session_id} status to {status}")


def delete_build_session(
    session_id: UUID,
    user_id: UUID,
    db_session: Session,
) -> bool:
    """Delete a build session and all related data."""
    session = get_build_session(session_id, user_id, db_session)
    if not session:
        return False

    db_session.delete(session)
    db_session.commit()
    logger.info(f"Deleted build session {session_id}")
    return True


# Sandbox operations
def create_sandbox(
    session_id: UUID,
    db_session: Session,
) -> Sandbox:
    """Create a new sandbox for a build session."""
    sandbox = Sandbox(
        session_id=session_id,
        status=SandboxStatus.PROVISIONING,
    )
    db_session.add(sandbox)
    db_session.commit()
    db_session.refresh(sandbox)

    logger.info(f"Created sandbox {sandbox.id} for session {session_id}")
    return sandbox


def get_sandbox_by_session(
    session_id: UUID,
    db_session: Session,
) -> Sandbox | None:
    """Get the sandbox for a given session."""
    return (
        db_session.query(Sandbox).filter(Sandbox.session_id == session_id).one_or_none()
    )


def update_sandbox_status(
    sandbox_id: UUID,
    status: SandboxStatus,
    db_session: Session,
    container_id: str | None = None,
) -> None:
    """Update the status of a sandbox."""
    sandbox = db_session.query(Sandbox).filter(Sandbox.id == sandbox_id).one_or_none()
    if sandbox:
        sandbox.status = status
        if container_id is not None:
            sandbox.container_id = container_id
        sandbox.last_heartbeat = datetime.utcnow()
        db_session.commit()
        logger.info(f"Updated sandbox {sandbox_id} status to {status}")


def update_sandbox_heartbeat(
    sandbox_id: UUID,
    db_session: Session,
) -> None:
    """Update the heartbeat timestamp for a sandbox."""
    sandbox = db_session.query(Sandbox).filter(Sandbox.id == sandbox_id).one_or_none()
    if sandbox:
        sandbox.last_heartbeat = datetime.utcnow()
        db_session.commit()


# Artifact operations
def create_artifact(
    session_id: UUID,
    artifact_type: str,
    path: str,
    name: str,
    db_session: Session,
) -> Artifact:
    """Create a new artifact record."""
    artifact = Artifact(
        session_id=session_id,
        type=artifact_type,
        path=path,
        name=name,
    )
    db_session.add(artifact)
    db_session.commit()
    db_session.refresh(artifact)

    logger.info(f"Created artifact {artifact.id} for session {session_id}")
    return artifact


def get_session_artifacts(
    session_id: UUID,
    db_session: Session,
) -> list[Artifact]:
    """Get all artifacts for a session."""
    return (
        db_session.query(Artifact)
        .filter(Artifact.session_id == session_id)
        .order_by(desc(Artifact.created_at))
        .all()
    )


def update_artifact(
    artifact_id: UUID,
    db_session: Session,
    path: str | None = None,
    name: str | None = None,
) -> None:
    """Update artifact metadata."""
    artifact = (
        db_session.query(Artifact).filter(Artifact.id == artifact_id).one_or_none()
    )
    if artifact:
        if path is not None:
            artifact.path = path
        if name is not None:
            artifact.name = name
        artifact.updated_at = datetime.utcnow()
        db_session.commit()
        logger.info(f"Updated artifact {artifact_id}")


# Snapshot operations
def create_snapshot(
    session_id: UUID,
    storage_path: str,
    size_bytes: int,
    db_session: Session,
) -> Snapshot:
    """Create a new snapshot record."""
    snapshot = Snapshot(
        session_id=session_id,
        storage_path=storage_path,
        size_bytes=size_bytes,
    )
    db_session.add(snapshot)
    db_session.commit()
    db_session.refresh(snapshot)

    logger.info(f"Created snapshot {snapshot.id} for session {session_id}")
    return snapshot


def get_latest_snapshot(
    session_id: UUID,
    db_session: Session,
) -> Snapshot | None:
    """Get the most recent snapshot for a session."""
    return (
        db_session.query(Snapshot)
        .filter(Snapshot.session_id == session_id)
        .order_by(desc(Snapshot.created_at))
        .first()
    )


def get_session_snapshots(
    session_id: UUID,
    db_session: Session,
) -> list[Snapshot]:
    """Get all snapshots for a session."""
    return (
        db_session.query(Snapshot)
        .filter(Snapshot.session_id == session_id)
        .order_by(desc(Snapshot.created_at))
        .all()
    )


# Message operations
def create_message(
    session_id: UUID,
    message_type: MessageType,
    content: str,
    db_session: Session,
    message_metadata: dict[str, Any] | None = None,
) -> BuildMessage:
    """Create a new message in a build session.

    Args:
        session_id: Session UUID
        message_type: Type of message (USER, ASSISTANT, SYSTEM)
        content: Text content (empty string for structured events)
        db_session: Database session
        message_metadata: Optional structured ACP event data (tool calls, thinking, plans, etc.)
    """
    message = BuildMessage(
        session_id=session_id,
        type=message_type,
        content=content,
        message_metadata=message_metadata,
    )
    db_session.add(message)
    db_session.commit()
    db_session.refresh(message)

    logger.info(
        f"Created {message_type.value} message {message.id} for session {session_id}"
        + (
            f" with metadata type={message_metadata.get('type')}"
            if message_metadata
            else ""
        )
    )
    return message


def get_session_messages(
    session_id: UUID,
    db_session: Session,
) -> list[BuildMessage]:
    """Get all messages for a session, ordered by creation time."""
    return (
        db_session.query(BuildMessage)
        .filter(BuildMessage.session_id == session_id)
        .order_by(BuildMessage.created_at)
        .all()
    )
