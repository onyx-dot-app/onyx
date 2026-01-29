"""Database operations for Build Mode sessions."""

from datetime import datetime
from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import desc
from sqlalchemy import exists
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.orm import Session

from onyx.configs.constants import MessageType
from onyx.db.enums import BuildSessionStatus
from onyx.db.enums import SandboxStatus
from onyx.db.models import Artifact
from onyx.db.models import BuildMessage
from onyx.db.models import BuildSession
from onyx.db.models import LLMProvider as LLMProviderModel
from onyx.db.models import Sandbox
from onyx.db.models import Snapshot
from onyx.server.features.build.configs import SANDBOX_NEXTJS_PORT_END
from onyx.server.features.build.configs import SANDBOX_NEXTJS_PORT_START
from onyx.server.manage.llm.models import LLMProviderView
from onyx.utils.logger import setup_logger

logger = setup_logger()


def create_build_session__no_commit(
    user_id: UUID,
    db_session: Session,
    name: str | None = None,
    demo_data_enabled: bool = True,
) -> BuildSession:
    """Create a new build session for the given user.

    NOTE: This function uses flush() instead of commit(). The caller is
    responsible for committing the transaction when ready.

    Args:
        user_id: The user ID
        db_session: Database session
        name: Optional session name
        demo_data_enabled: Whether this session uses demo data (default True)
    """
    session = BuildSession(
        user_id=user_id,
        name=name,
        status=BuildSessionStatus.ACTIVE,
        demo_data_enabled=demo_data_enabled,
    )
    db_session.add(session)
    db_session.flush()

    logger.info(
        f"Created build session {session.id} for user {user_id} (demo_data={demo_data_enabled})"
    )
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
    demo_data_enabled: bool | None = None,
) -> BuildSession | None:
    """Get the user's empty session (0 messages) if one exists and is recent.

    Args:
        user_id: The user ID
        db_session: Database session
        max_age_minutes: Maximum age of session to consider (default 30)
        demo_data_enabled: Match sessions with this demo_data setting.
                          This ensures pre-provisioned sessions match the user's current
                          preferences. If None, matches any session regardless of setting.
                          Note: None is only used internally for operations that need to
                          match any session (e.g., deletion).
    """
    cutoff = datetime.utcnow() - timedelta(minutes=max_age_minutes)

    query = db_session.query(BuildSession).filter(
        BuildSession.user_id == user_id,
        BuildSession.created_at > cutoff,
        ~exists().where(BuildMessage.session_id == BuildSession.id),
    )

    if demo_data_enabled is not None:
        query = query.filter(BuildSession.demo_data_enabled == demo_data_enabled)

    return query.first()


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


def delete_build_session__no_commit(
    session_id: UUID,
    user_id: UUID,
    db_session: Session,
) -> bool:
    """Delete a build session and all related data.

    NOTE: This function uses flush() instead of commit(). The caller is
    responsible for committing the transaction when ready.
    """
    session = get_build_session(session_id, user_id, db_session)
    if not session:
        return False

    db_session.delete(session)
    db_session.flush()
    logger.info(f"Deleted build session {session_id}")
    return True


# Sandbox operations
# NOTE: Most sandbox operations have moved to sandbox.py
# These remain here for convenience in session-related workflows


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


# Message operations
def create_message(
    session_id: UUID,
    message_type: MessageType,
    turn_index: int,
    message_metadata: dict[str, Any],
    db_session: Session,
) -> BuildMessage:
    """Create a new message in a build session.

    All message data is stored in message_metadata as JSON.

    Args:
        session_id: Session UUID
        message_type: Type of message (USER, ASSISTANT, SYSTEM)
        turn_index: 0-indexed user message number this message belongs to
        message_metadata: Required structured data (the raw ACP packet JSON)
        db_session: Database session
    """
    message = BuildMessage(
        session_id=session_id,
        turn_index=turn_index,
        type=message_type,
        message_metadata=message_metadata,
    )
    db_session.add(message)
    db_session.commit()
    db_session.refresh(message)

    logger.info(
        f"Created {message_type.value} message {message.id} for session {session_id} "
        f"turn={turn_index} type={message_metadata.get('type')}"
    )
    return message


def update_message(
    message_id: UUID,
    message_metadata: dict[str, Any],
    db_session: Session,
) -> BuildMessage | None:
    """Update an existing message's metadata.

    Used for upserting agent_plan_update messages.

    Args:
        message_id: The message UUID to update
        message_metadata: New metadata to set
        db_session: Database session

    Returns:
        Updated BuildMessage or None if not found
    """
    message = (
        db_session.query(BuildMessage).filter(BuildMessage.id == message_id).first()
    )
    if message is None:
        return None

    message.message_metadata = message_metadata
    db_session.commit()
    db_session.refresh(message)

    logger.info(
        f"Updated message {message_id} metadata type={message_metadata.get('type')}"
    )
    return message


def upsert_agent_plan(
    session_id: UUID,
    turn_index: int,
    plan_metadata: dict[str, Any],
    db_session: Session,
    existing_plan_id: UUID | None = None,
) -> BuildMessage:
    """Upsert an agent plan - update if exists, create if not.

    Each session/turn should only have one agent_plan_update message.
    This function updates the existing plan message or creates a new one.

    Args:
        session_id: Session UUID
        turn_index: Current turn index
        plan_metadata: The agent_plan_update packet data
        db_session: Database session
        existing_plan_id: ID of existing plan message to update (if known)

    Returns:
        The created or updated BuildMessage
    """
    if existing_plan_id:
        # Fast path: we know the plan ID
        updated = update_message(existing_plan_id, plan_metadata, db_session)
        if updated:
            return updated

    # Check if a plan already exists for this session/turn
    existing_plan = (
        db_session.query(BuildMessage)
        .filter(
            BuildMessage.session_id == session_id,
            BuildMessage.turn_index == turn_index,
            BuildMessage.message_metadata["type"].astext == "agent_plan_update",
        )
        .first()
    )

    if existing_plan:
        existing_plan.message_metadata = plan_metadata
        db_session.commit()
        db_session.refresh(existing_plan)
        logger.info(
            f"Updated agent_plan_update message {existing_plan.id} for session {session_id}"
        )
        return existing_plan

    # Create new plan message
    return create_message(
        session_id=session_id,
        message_type=MessageType.ASSISTANT,
        turn_index=turn_index,
        message_metadata=plan_metadata,
        db_session=db_session,
    )


def get_session_messages(
    session_id: UUID,
    db_session: Session,
) -> list[BuildMessage]:
    """Get all messages for a session, ordered by turn index and creation time."""
    return (
        db_session.query(BuildMessage)
        .filter(BuildMessage.session_id == session_id)
        .order_by(BuildMessage.turn_index, BuildMessage.created_at)
        .all()
    )


def _is_port_available(port: int) -> bool:
    """Check if a port is available by attempting to bind to it.

    Checks both IPv4 and IPv6 wildcard addresses to properly detect
    if anything is listening on the port, regardless of address family.
    """
    import socket

    logger.debug(f"Checking if port {port} is available")

    # Check IPv4 wildcard (0.0.0.0) - this will detect any IPv4 listener
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("0.0.0.0", port))
            logger.debug(f"Port {port} IPv4 wildcard bind successful")
    except OSError as e:
        logger.debug(f"Port {port} IPv4 wildcard not available: {e}")
        return False

    # Check IPv6 wildcard (::) - this will detect any IPv6 listener
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            # IPV6_V6ONLY must be False to allow dual-stack behavior
            sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
            sock.bind(("::", port))
            logger.debug(f"Port {port} IPv6 wildcard bind successful")
    except OSError as e:
        logger.debug(f"Port {port} IPv6 wildcard not available: {e}")
        return False

    logger.debug(f"Port {port} is available")
    return True


def allocate_nextjs_port(db_session: Session) -> int:
    """Allocate an available port for a new session.

    Finds the first available port in the configured range by checking
    both database allocations and system-level port availability.

    Args:
        db_session: Database session for querying allocated ports

    Returns:
        An available port number

    Raises:
        RuntimeError: If no ports are available in the configured range
    """
    from onyx.db.models import BuildSession

    # Get all currently allocated ports from active sessions
    allocated_ports = set(
        db_session.query(BuildSession.nextjs_port)
        .filter(BuildSession.nextjs_port.isnot(None))
        .all()
    )
    allocated_ports = {port[0] for port in allocated_ports if port[0] is not None}

    # Find first port that's not in DB and not currently bound
    for port in range(SANDBOX_NEXTJS_PORT_START, SANDBOX_NEXTJS_PORT_END):
        if port not in allocated_ports and _is_port_available(port):
            return port

    raise RuntimeError(
        f"No available ports in range [{SANDBOX_NEXTJS_PORT_START}, {SANDBOX_NEXTJS_PORT_END})"
    )


def clear_nextjs_ports_for_user(db_session: Session, user_id: UUID) -> int:
    """Clear nextjs_port for all sessions belonging to a user.

    Called when sandbox goes to sleep to release port allocations.

    Args:
        db_session: Database session
        user_id: The user whose sessions should have ports cleared

    Returns:
        Number of sessions updated
    """
    result = (
        db_session.query(BuildSession)
        .filter(
            BuildSession.user_id == user_id,
            BuildSession.nextjs_port.isnot(None),
        )
        .update({BuildSession.nextjs_port: None})
    )
    db_session.flush()
    logger.info(f"Cleared {result} nextjs_port allocations for user {user_id}")
    return result


def fetch_llm_provider_by_type_for_build_mode(
    db_session: Session, provider_type: str
) -> LLMProviderView | None:
    """Fetch an LLM provider by its provider type (e.g., "anthropic", "openai").

    Resolution priority:
    1. First try to find a provider named "build-mode-{type}" (e.g., "build-mode-anthropic")
    2. If not found, fall back to any provider that matches the type

    Args:
        db_session: Database session
        provider_type: The provider type (e.g., "anthropic", "openai", "openrouter")

    Returns:
        LLMProviderView if found, None otherwise
    """
    from onyx.db.llm import fetch_existing_llm_provider

    # First try to find a "build-mode-{type}" provider
    build_mode_name = f"build-mode-{provider_type}"
    provider_model = fetch_existing_llm_provider(
        name=build_mode_name, db_session=db_session
    )

    # If not found, fall back to any provider that matches the type
    if not provider_model:
        provider_model = db_session.scalar(
            select(LLMProviderModel)
            .where(LLMProviderModel.provider == provider_type)
            .options(
                selectinload(LLMProviderModel.model_configurations),
                selectinload(LLMProviderModel.groups),
                selectinload(LLMProviderModel.personas),
            )
        )

    if not provider_model:
        return None
    return LLMProviderView.from_model(provider_model)
