"""Database operations for CLI agent sandbox management."""

import datetime
from uuid import UUID

from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.enums import SandboxStatus
from onyx.db.models import Sandbox
from onyx.db.models import SandboxSnapshot


def create_sandbox(
    db_session: Session,
    session_id: UUID,
    tenant_id: str,
    directory_path: str,
) -> Sandbox:
    """Create a new sandbox record."""
    sandbox = Sandbox(
        session_id=session_id,
        tenant_id=tenant_id,
        directory_path=directory_path,
        status=SandboxStatus.PROVISIONING,
    )
    db_session.add(sandbox)
    db_session.commit()
    return sandbox


def get_sandbox_by_session_id(db_session: Session, session_id: UUID) -> Sandbox | None:
    """Get sandbox by session ID."""
    stmt = select(Sandbox).where(Sandbox.session_id == session_id)
    return db_session.execute(stmt).scalar_one_or_none()


def get_sandbox_by_id(db_session: Session, sandbox_id: UUID) -> Sandbox | None:
    """Get sandbox by its ID."""
    stmt = select(Sandbox).where(Sandbox.id == sandbox_id)
    return db_session.execute(stmt).scalar_one_or_none()


def update_sandbox_status(
    db_session: Session, sandbox_id: UUID, status: SandboxStatus
) -> Sandbox:
    """Update sandbox status."""
    sandbox = get_sandbox_by_id(db_session, sandbox_id)
    if not sandbox:
        raise ValueError(f"Sandbox {sandbox_id} not found")

    sandbox.status = status
    if status == SandboxStatus.TERMINATED:
        sandbox.terminated_at = datetime.datetime.now(datetime.timezone.utc)
    db_session.commit()
    return sandbox


def update_sandbox_agent_pid(
    db_session: Session, sandbox_id: UUID, agent_pid: int
) -> Sandbox:
    """Update sandbox agent process PID."""
    sandbox = get_sandbox_by_id(db_session, sandbox_id)
    if not sandbox:
        raise ValueError(f"Sandbox {sandbox_id} not found")

    sandbox.agent_pid = agent_pid
    db_session.commit()
    return sandbox


def update_sandbox_nextjs(
    db_session: Session, sandbox_id: UUID, nextjs_pid: int, nextjs_port: int
) -> Sandbox:
    """Update sandbox Next.js server process info."""
    sandbox = get_sandbox_by_id(db_session, sandbox_id)
    if not sandbox:
        raise ValueError(f"Sandbox {sandbox_id} not found")

    sandbox.nextjs_pid = nextjs_pid
    sandbox.nextjs_port = nextjs_port
    db_session.commit()
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


def get_sandboxes_by_tenant(db_session: Session, tenant_id: str) -> list[Sandbox]:
    """Get all sandboxes for a tenant."""
    stmt = select(Sandbox).where(Sandbox.tenant_id == tenant_id)
    return list(db_session.execute(stmt).scalars().all())


def get_running_sandbox_count_by_tenant(db_session: Session, tenant_id: str) -> int:
    """Get count of running sandboxes for a tenant (for limit enforcement)."""
    stmt = (
        select(func.count(Sandbox.id))
        .where(Sandbox.tenant_id == tenant_id)
        .where(Sandbox.status.in_([SandboxStatus.RUNNING, SandboxStatus.IDLE]))
    )
    result = db_session.execute(stmt).scalar()
    return result or 0


def create_snapshot(
    db_session: Session,
    session_id: UUID,
    tenant_id: str,
    storage_path: str,
    size_bytes: int,
) -> SandboxSnapshot:
    """Create a snapshot record."""
    snapshot = SandboxSnapshot(
        session_id=session_id,
        tenant_id=tenant_id,
        storage_path=storage_path,
        size_bytes=size_bytes,
    )
    db_session.add(snapshot)
    db_session.commit()
    return snapshot


def get_latest_snapshot_for_session(
    db_session: Session, session_id: UUID
) -> SandboxSnapshot | None:
    """Get most recent snapshot for a session."""
    stmt = (
        select(SandboxSnapshot)
        .where(SandboxSnapshot.session_id == session_id)
        .order_by(SandboxSnapshot.created_at.desc())
        .limit(1)
    )
    return db_session.execute(stmt).scalar_one_or_none()


def get_snapshots_for_session(
    db_session: Session, session_id: UUID
) -> list[SandboxSnapshot]:
    """Get all snapshots for a session, ordered by creation time descending."""
    stmt = (
        select(SandboxSnapshot)
        .where(SandboxSnapshot.session_id == session_id)
        .order_by(SandboxSnapshot.created_at.desc())
    )
    return list(db_session.execute(stmt).scalars().all())


def delete_old_snapshots(
    db_session: Session, tenant_id: str, retention_days: int
) -> int:
    """Delete snapshots older than retention period, return count deleted."""
    cutoff_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        days=retention_days
    )

    stmt = select(SandboxSnapshot).where(
        SandboxSnapshot.tenant_id == tenant_id,
        SandboxSnapshot.created_at < cutoff_time,
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
    stmt = select(SandboxSnapshot).where(SandboxSnapshot.id == snapshot_id)
    snapshot = db_session.execute(stmt).scalar_one_or_none()

    if not snapshot:
        return False

    db_session.delete(snapshot)
    db_session.commit()
    return True
