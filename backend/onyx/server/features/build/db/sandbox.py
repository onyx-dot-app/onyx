"""Database operations for CLI agent sandbox management."""

import datetime
from uuid import UUID

from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.enums import SandboxStatus
from onyx.db.models import Sandbox
from onyx.db.models import Snapshot
from onyx.server.features.build.configs import SANDBOX_NEXTJS_PORT_END
from onyx.server.features.build.configs import SANDBOX_NEXTJS_PORT_START
from onyx.utils.logger import setup_logger

logger = setup_logger()


def create_sandbox__no_commit(
    db_session: Session,
    user_id: UUID,
    nextjs_port: int | None = None,
) -> Sandbox:
    """Create a new sandbox record for a user.

    NOTE: This function uses flush() instead of commit(). The caller is
    responsible for committing the transaction when ready.
    """
    sandbox = Sandbox(
        user_id=user_id,
        status=SandboxStatus.PROVISIONING,
        nextjs_port=nextjs_port,
    )
    db_session.add(sandbox)
    db_session.flush()
    return sandbox


def get_sandbox_by_user_id(db_session: Session, user_id: UUID) -> Sandbox | None:
    """Get sandbox by user ID (primary lookup method)."""
    stmt = select(Sandbox).where(Sandbox.user_id == user_id)
    return db_session.execute(stmt).scalar_one_or_none()


def get_sandbox_by_session_id(db_session: Session, session_id: UUID) -> Sandbox | None:
    """Get sandbox by session ID (compatibility function).

    This function provides backwards compatibility during the transition to
    user-owned sandboxes. It looks up the session's user_id, then finds the
    user's sandbox.

    NOTE: This will be removed in a future phase when all callers are updated
    to use get_sandbox_by_user_id() directly.
    """
    from onyx.db.models import BuildSession

    stmt = select(BuildSession.user_id).where(BuildSession.id == session_id)
    result = db_session.execute(stmt).scalar_one_or_none()
    if result is None:
        return None

    return get_sandbox_by_user_id(db_session, result)


def get_sandbox_by_id(db_session: Session, sandbox_id: UUID) -> Sandbox | None:
    """Get sandbox by its ID."""
    stmt = select(Sandbox).where(Sandbox.id == sandbox_id)
    return db_session.execute(stmt).scalar_one_or_none()


def update_sandbox_status__no_commit(
    db_session: Session,
    sandbox_id: UUID,
    status: SandboxStatus,
) -> Sandbox:
    """Update sandbox status.

    NOTE: This function uses flush() instead of commit(). The caller is
    responsible for committing the transaction when ready.
    """
    sandbox = get_sandbox_by_id(db_session, sandbox_id)
    if not sandbox:
        raise ValueError(f"Sandbox {sandbox_id} not found")

    sandbox.status = status
    db_session.flush()
    return sandbox


def update_sandbox_heartbeat(db_session: Session, sandbox_id: UUID) -> Sandbox:
    """Update sandbox last_heartbeat to now."""
    sandbox = get_sandbox_by_id(db_session, sandbox_id)
    if not sandbox:
        raise ValueError(f"Sandbox {sandbox_id} not found")

    sandbox.last_heartbeat = datetime.datetime.now(datetime.timezone.utc)
    db_session.commit()
    return sandbox


def get_idle_sandboxes(
    db_session: Session, idle_threshold_seconds: int
) -> list[Sandbox]:
    """Get sandboxes that have been idle longer than threshold."""
    threshold_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        seconds=idle_threshold_seconds
    )

    stmt = select(Sandbox).where(
        Sandbox.status.in_([SandboxStatus.RUNNING, SandboxStatus.IDLE]),
        Sandbox.last_heartbeat < threshold_time,
    )
    return list(db_session.execute(stmt).scalars().all())


def get_running_sandbox_count_by_tenant(db_session: Session, tenant_id: str) -> int:
    """Get count of running sandboxes for a tenant (for limit enforcement).

    Note: tenant_id parameter is kept for API compatibility but is not used
    since Sandbox model no longer has tenant_id. This function returns
    the count of all running sandboxes.
    """
    stmt = select(func.count(Sandbox.id)).where(
        Sandbox.status.in_([SandboxStatus.RUNNING, SandboxStatus.IDLE])
    )
    result = db_session.execute(stmt).scalar()
    return result or 0


def create_snapshot(
    db_session: Session,
    session_id: UUID,
    storage_path: str,
    size_bytes: int,
) -> Snapshot:
    """Create a snapshot record for a session."""
    snapshot = Snapshot(
        session_id=session_id,
        storage_path=storage_path,
        size_bytes=size_bytes,
    )
    db_session.add(snapshot)
    db_session.commit()
    return snapshot


def get_latest_snapshot_for_session(
    db_session: Session, session_id: UUID
) -> Snapshot | None:
    """Get most recent snapshot for a session."""
    stmt = (
        select(Snapshot)
        .where(Snapshot.session_id == session_id)
        .order_by(Snapshot.created_at.desc())
        .limit(1)
    )
    return db_session.execute(stmt).scalar_one_or_none()


def get_snapshots_for_session(db_session: Session, session_id: UUID) -> list[Snapshot]:
    """Get all snapshots for a session, ordered by creation time descending."""
    stmt = (
        select(Snapshot)
        .where(Snapshot.session_id == session_id)
        .order_by(Snapshot.created_at.desc())
    )
    return list(db_session.execute(stmt).scalars().all())


def delete_old_snapshots(
    db_session: Session, tenant_id: str, retention_days: int
) -> int:
    """Delete snapshots older than retention period, return count deleted.

    Note: tenant_id parameter is kept for API compatibility but is not used
    since Snapshot model no longer has tenant_id. This function deletes
    all snapshots older than the retention period.
    """
    cutoff_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        days=retention_days
    )

    stmt = select(Snapshot).where(
        Snapshot.created_at < cutoff_time,
    )
    old_snapshots = db_session.execute(stmt).scalars().all()

    count = 0
    for snapshot in old_snapshots:
        db_session.delete(snapshot)
        count += 1

    if count > 0:
        db_session.commit()

    return count


def delete_snapshot(db_session: Session, snapshot_id: UUID) -> bool:
    """Delete a specific snapshot by ID. Returns True if deleted, False if not found."""
    stmt = select(Snapshot).where(Snapshot.id == snapshot_id)
    snapshot = db_session.execute(stmt).scalar_one_or_none()

    if not snapshot:
        return False

    db_session.delete(snapshot)
    db_session.commit()
    return True


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
    """Allocate an available port for a new sandbox.

    Finds the first available port in the configured range by checking
    both database allocations and system-level port availability.

    Args:
        db_session: Database session for querying allocated ports

    Returns:
        An available port number

    Raises:
        RuntimeError: If no ports are available in the configured range
    """
    # Get all currently allocated ports from the database
    allocated_ports = set(
        db_session.query(Sandbox.nextjs_port)
        .filter(Sandbox.nextjs_port.isnot(None))
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
