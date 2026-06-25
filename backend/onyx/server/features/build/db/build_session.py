"""Database operations for Build Mode sessions."""

from datetime import datetime
from datetime import timezone
from typing import Any
from uuid import UUID

from sqlalchemy import desc
from sqlalchemy import exists
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm import Session

from onyx.auth.schemas import UserRole
from onyx.configs.constants import MessageType
from onyx.db.enums import BuildSessionStatus
from onyx.db.enums import SandboxStatus
from onyx.db.enums import SessionOrigin
from onyx.db.enums import SharingScope
from onyx.db.llm import can_user_access_llm_provider
from onyx.db.llm import fetch_user_group_ids
from onyx.db.models import Artifact
from onyx.db.models import BuildMessage
from onyx.db.models import BuildSession
from onyx.db.models import LLMProvider as LLMProviderModel
from onyx.db.models import Sandbox
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.build.configs import BUILD_MODE_ALLOWED_PROVIDER_TYPES
from onyx.server.features.build.configs import SANDBOX_NEXTJS_PORT_END
from onyx.server.features.build.configs import SANDBOX_NEXTJS_PORT_START
from onyx.server.manage.llm.models import LLMProviderView
from onyx.utils.logger import setup_logger
from onyx.utils.postgres_sanitization import sanitize_json_like

logger = setup_logger()


def create_build_session__no_commit(
    user_id: UUID,
    db_session: Session,
    name: str | None = None,
    origin: SessionOrigin = SessionOrigin.INTERACTIVE,
    agent_provider: str | None = None,
    agent_model: str | None = None,
) -> BuildSession:
    """``flush()`` only — caller commits.

    ``agent_provider`` / ``agent_model`` are nullable for legacy rows;
    the send-message path then falls back to opencode's startup default.
    """
    session = BuildSession(
        user_id=user_id,
        name=name,
        status=BuildSessionStatus.ACTIVE,
        origin=origin,
        agent_provider=agent_provider,
        agent_model=agent_model,
    )
    db_session.add(session)
    db_session.flush()

    logger.info(
        "Created build session %s for user %s (origin=%s)",
        session.id,
        user_id,
        origin.value,
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


async def get_webapp_access_async(
    db_session: AsyncSession,
    session_id: UUID,
) -> tuple[SharingScope, UUID] | None:
    """(sharing_scope, owner_user_id) for the proxy access check; None if absent."""
    row = (
        await db_session.execute(
            select(BuildSession.sharing_scope, BuildSession.user_id).where(
                BuildSession.id == session_id
            )
        )
    ).first()
    return (row[0], row[1]) if row is not None else None


async def get_webapp_target_async(
    db_session: AsyncSession,
    session_id: UUID,
) -> tuple[UUID | None, int | None] | None:
    """(sandbox_id, nextjs_port) in one round-trip; None if the session is absent."""
    row = (
        await db_session.execute(
            select(Sandbox.id, BuildSession.nextjs_port)
            .select_from(BuildSession)
            .outerjoin(Sandbox, Sandbox.user_id == BuildSession.user_id)
            .where(BuildSession.id == session_id)
        )
    ).first()
    return (row[0], row[1]) if row is not None else None


def get_user_build_sessions(
    user_id: UUID,
    db_session: Session,
    limit: int = 100,
) -> list[BuildSession]:
    """Get a user's interactive build sessions that have at least one message.

    Sessions created by non-interactive callers (e.g. the scheduled-tasks
    executor) are intentionally excluded from this listing so they don't
    leak into the Craft sidebar. The covering composite index
    ``ix_build_session_user_origin_created`` is built for this exact query
    shape: ``(user_id, origin, created_at DESC)``.
    """
    # Subquery to check if session has any messages
    has_messages = exists().where(BuildMessage.session_id == BuildSession.id)

    return (
        db_session.query(BuildSession)
        .filter(
            BuildSession.user_id == user_id,
            BuildSession.origin == SessionOrigin.INTERACTIVE,
            has_messages,  # Only sessions with messages
        )
        .order_by(desc(BuildSession.created_at))
        .limit(limit)
        .all()
    )


def get_empty_session_for_user(
    user_id: UUID,
    db_session: Session,
) -> BuildSession | None:
    """Get an empty (pre-provisioned) session for the user if one exists.

    Returns a session with no messages, or None if all sessions have messages.
    """
    has_messages = exists().where(BuildMessage.session_id == BuildSession.id)

    return (
        db_session.query(BuildSession)
        .filter(
            BuildSession.user_id == user_id,
            ~has_messages,
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
        session.last_activity_at = datetime.now(tz=timezone.utc)
        db_session.commit()


def set_build_session_sharing_scope(
    session_id: UUID,
    user_id: UUID,
    sharing_scope: SharingScope,
    db_session: Session,
) -> BuildSession | None:
    """Set the sharing scope of a build session.

    Only the session owner can change this setting.
    Returns the updated session, or None if not found/unauthorized.
    """
    session = get_build_session(session_id, user_id, db_session)
    if not session:
        return None
    session.sharing_scope = sharing_scope
    db_session.commit()
    logger.info("Set build session %s sharing_scope=%s", session_id, sharing_scope)
    return session


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
    logger.info("Deleted build session %s", session_id)
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
        sandbox.last_heartbeat = datetime.now(tz=timezone.utc)
        db_session.commit()
        logger.info("Updated sandbox %s status to %s", sandbox_id, status)


def update_sandbox_heartbeat(
    sandbox_id: UUID,
    db_session: Session,
) -> None:
    """Update the heartbeat timestamp for a sandbox."""
    sandbox = db_session.query(Sandbox).filter(Sandbox.id == sandbox_id).one_or_none()
    if sandbox:
        sandbox.last_heartbeat = datetime.now(tz=timezone.utc)
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

    logger.info("Created artifact %s for session %s", artifact.id, session_id)
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
        artifact.updated_at = datetime.now(tz=timezone.utc)
        db_session.commit()
        logger.info("Updated artifact %s", artifact_id)


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
        message_metadata: Required structured data (the raw sandbox event packet JSON)
        db_session: Database session
    """
    sanitized_metadata = sanitize_json_like(message_metadata)
    message = BuildMessage(
        session_id=session_id,
        turn_index=turn_index,
        type=message_type,
        message_metadata=sanitized_metadata,
    )
    db_session.add(message)
    db_session.commit()
    db_session.refresh(message)

    logger.info(
        "Created %s message %s for session %s turn=%s type=%s",
        message_type.value,
        message.id,
        session_id,
        turn_index,
        sanitized_metadata.get("type"),
    )
    return message


def count_user_messages(session_id: UUID, db_session: Session) -> int:
    """Count persisted user messages in a build session."""
    return (
        db_session.query(BuildMessage)
        .filter(
            BuildMessage.session_id == session_id,
            BuildMessage.type == MessageType.USER,
        )
        .count()
    )


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

    sanitized_metadata = sanitize_json_like(message_metadata)
    message.message_metadata = sanitized_metadata
    db_session.commit()
    db_session.refresh(message)

    logger.info(
        "Updated message %s metadata type=%s",
        message_id,
        sanitized_metadata.get("type"),
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
        sanitized_metadata = sanitize_json_like(plan_metadata)
        existing_plan.message_metadata = sanitized_metadata
        db_session.commit()
        db_session.refresh(existing_plan)
        logger.info(
            "Updated agent_plan_update message %s for session %s",
            existing_plan.id,
            session_id,
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

    logger.debug("Checking if port %s is available", port)

    # Check IPv4 wildcard (0.0.0.0) - this will detect any IPv4 listener
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("0.0.0.0", port))  # noqa: S104 — port availability probe; binds wildcard to detect any listener
            logger.debug("Port %s IPv4 wildcard bind successful", port)
    except OSError as e:
        logger.debug("Port %s IPv4 wildcard not available: %s", port, e)
        return False

    # Check IPv6 wildcard (::) - this will detect any IPv6 listener
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            # IPV6_V6ONLY must be False to allow dual-stack behavior
            sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
            sock.bind(("::", port))
            logger.debug("Port %s IPv6 wildcard bind successful", port)
    except OSError as e:
        logger.debug("Port %s IPv6 wildcard not available: %s", port, e)
        return False

    logger.debug("Port %s is available", port)
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
        OnyxError: If no ports are available in the configured range
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

    raise OnyxError(
        OnyxErrorCode.SERVICE_UNAVAILABLE,
        f"No available ports in range [{SANDBOX_NEXTJS_PORT_START}, {SANDBOX_NEXTJS_PORT_END})",
    )


def mark_user_sessions_idle__no_commit(db_session: Session, user_id: UUID) -> int:
    """Mark all ACTIVE sessions for a user as IDLE.

    Called when a sandbox goes to sleep so the frontend knows these sessions
    need restoration before they can be used again.

    Args:
        db_session: Database session
        user_id: The user whose sessions should be marked idle

    Returns:
        Number of sessions updated
    """
    result = (
        db_session.query(BuildSession)
        .filter(
            BuildSession.user_id == user_id,
            BuildSession.status == BuildSessionStatus.ACTIVE,
        )
        .update({BuildSession.status: BuildSessionStatus.IDLE})
    )
    db_session.flush()
    logger.info("Marked %s sessions as IDLE for user %s", result, user_id)
    return result


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
    logger.info("Cleared %s nextjs_port allocations for user %s", result, user_id)
    return result


def fetch_all_supported_build_llm_providers(
    db_session: Session, user: User
) -> list[LLMProviderView]:
    """Every provider of a Craft-supported type (anthropic, openai, openrouter)
    that the ``user`` can access. Respects is_public / group restrictions so a
    user never gets a sandbox keyed with a provider they can't use."""
    provider_models = db_session.scalars(
        select(LLMProviderModel)
        .where(LLMProviderModel.provider.in_(BUILD_MODE_ALLOWED_PROVIDER_TYPES))
        .options(
            selectinload(LLMProviderModel.model_configurations),
            selectinload(LLMProviderModel.groups),
            selectinload(LLMProviderModel.personas),
        )
    )
    user_group_ids = fetch_user_group_ids(db_session, user)
    is_admin = user.role == UserRole.ADMIN
    # persona=None: Craft has no persona context, so a provider restricted to
    # specific personas is intentionally excluded even when otherwise public.
    return [
        LLMProviderView.from_model(p)
        for p in provider_models
        if can_user_access_llm_provider(
            p, user_group_ids, persona=None, is_admin=is_admin
        )
    ]
