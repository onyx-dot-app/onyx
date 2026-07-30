"""Database operations for CLI agent sandbox management."""

import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from onyx.auth.pat import hash_pat
from onyx.db.enums import BuildSessionStatus, PatType, Permission, SandboxStatus
from onyx.db.models import BuildSession, PersonalAccessToken, Sandbox, Snapshot, User
from onyx.db.pat import create_pat, revoke_pat
from onyx.utils.logger import setup_logger

logger = setup_logger()

_PAT_EXPIRATION_DAYS = 30


def ensure_sandbox_pat(db_session: Session, sandbox: Sandbox, user: User) -> str:
    """Return a valid PAT for this sandbox, minting if needed."""
    now = datetime.datetime.now(datetime.timezone.utc)

    existing_craft_pats = list(
        db_session.scalars(
            select(PersonalAccessToken)
            .where(PersonalAccessToken.user_id == user.id)
            .where(PersonalAccessToken.pat_type == PatType.CRAFT)
            .where(
                (PersonalAccessToken.expires_at.is_(None))
                | (PersonalAccessToken.expires_at > now)
            )
        ).all()
    )

    if sandbox.encrypted_pat and len(existing_craft_pats) == 1:
        raw_token = sandbox.encrypted_pat.get_value(apply_mask=False)
        existing = existing_craft_pats[0]
        # Re-mint if the stored PAT's scopes drifted from the current role scope
        if hash_pat(raw_token) == existing.hashed_token and existing.scopes == [
            Permission.CRAFT_SANDBOX.value
        ]:
            return raw_token

    for pat in existing_craft_pats:
        revoke_pat(db_session, pat.id, user.id)

    _pat_record, raw_token = create_pat(
        db_session=db_session,
        user_id=user.id,
        name=f"craft-{user.id}",
        expiration_days=_PAT_EXPIRATION_DAYS,
        pat_type=PatType.CRAFT,
        scopes=[Permission.CRAFT_SANDBOX],
    )

    sandbox.encrypted_pat = raw_token  # ty: ignore[invalid-assignment]
    db_session.flush()
    return raw_token


def create_sandbox__no_commit(
    db_session: Session,
    user_id: UUID,
) -> Sandbox:
    """Create a new sandbox record for a user.

    Sets last_heartbeat to now so that:
    1. The sandbox has a proper idle timeout baseline from creation
    2. Long-running provisioning doesn't cause the sandbox to appear "old"
       when it transitions to RUNNING

    NOTE: This function uses flush() instead of commit(). The caller is
    responsible for committing the transaction when ready.
    """
    sandbox = Sandbox(
        user_id=user_id,
        status=SandboxStatus.PROVISIONING,
        last_heartbeat=datetime.datetime.now(datetime.timezone.utc),
    )
    db_session.add(sandbox)
    db_session.flush()
    return sandbox


def get_sandbox_by_user_id(db_session: Session, user_id: UUID) -> Sandbox | None:
    """Get sandbox by user ID (primary lookup method)."""
    stmt = select(Sandbox).where(Sandbox.user_id == user_id)
    return db_session.execute(stmt).scalar_one_or_none()


def begin_provisioning_attempt__no_commit(
    db_session: Session,
    sandbox: Sandbox,
) -> int:
    """Authorize a new external provisioning attempt: assign the next attempt
    number and mark the sandbox ``PROVISIONING``. Must run inside the
    per-user reservation transaction (user row locked) so concurrent
    reservers get distinct numbers.

    Returns the new attempt number, which the attempt must present to the
    conditional transitions below.
    """
    sandbox.status = SandboxStatus.PROVISIONING
    sandbox.provisioning_attempt_number += 1
    sandbox.provisioning_started_at = datetime.datetime.now(datetime.timezone.utc)
    db_session.flush()
    return sandbox.provisioning_attempt_number


def begin_recovery_attempt__no_commit(
    db_session: Session,
    sandbox_id: UUID,
    expected_attempt_number: int,
) -> int | None:
    """Take over an unhealthy ``RUNNING`` sandbox for a new provisioning
    attempt — applied only if the row is still RUNNING under
    ``expected_attempt_number`` (recovery happens outside the reservation lock).
    Returns the new attempt number, or None when the row already moved on."""
    result = db_session.execute(
        update(Sandbox)
        .where(
            Sandbox.id == sandbox_id,
            Sandbox.provisioning_attempt_number == expected_attempt_number,
            Sandbox.status == SandboxStatus.RUNNING,
        )
        .values(
            status=SandboxStatus.PROVISIONING,
            provisioning_attempt_number=expected_attempt_number + 1,
            provisioning_started_at=datetime.datetime.now(datetime.timezone.utc),
        )
    )
    if result.rowcount != 1:  # ty: ignore[unresolved-attribute]
        return None
    return expected_attempt_number + 1


def finalize_provisioning_attempt__no_commit(
    db_session: Session,
    sandbox_id: UUID,
    attempt_number: int,
    to_status: Literal[SandboxStatus.RUNNING, SandboxStatus.FAILED],
) -> bool:
    """Record the attempt's outcome — applied only if the row is still
    ``PROVISIONING`` under this attempt's number. Returns False when a newer
    attempt has taken over: the caller's external work must not be recorded
    as the current runtime. ``RUNNING`` also stamps the heartbeat so the
    fresh pod gets a proper idle-timeout baseline."""
    values: dict[str, object] = {"status": to_status}
    if to_status == SandboxStatus.RUNNING:
        values["last_heartbeat"] = datetime.datetime.now(datetime.timezone.utc)
    result = db_session.execute(
        update(Sandbox)
        .where(
            Sandbox.id == sandbox_id,
            Sandbox.provisioning_attempt_number == attempt_number,
            Sandbox.status == SandboxStatus.PROVISIONING,
        )
        .values(**values)
    )
    return result.rowcount == 1  # ty: ignore[unresolved-attribute]


def sleep_running_sandbox__no_commit(
    db_session: Session,
    sandbox_id: UUID,
    attempt_number: int,
) -> bool:
    """``RUNNING`` → ``SLEEPING`` for the idle reaper — applied only if the
    sandbox still belongs to attempt ``attempt_number``. Returns False when the
    row moved on (a concurrent recovery or create started a newer attempt /
    left RUNNING), so the reaper must not clobber that decision."""
    result = db_session.execute(
        update(Sandbox)
        .where(
            Sandbox.id == sandbox_id,
            Sandbox.provisioning_attempt_number == attempt_number,
            Sandbox.status == SandboxStatus.RUNNING,
        )
        .values(status=SandboxStatus.SLEEPING)
    )
    return result.rowcount == 1  # ty: ignore[unresolved-attribute]


def get_sandbox_by_id(db_session: Session, sandbox_id: UUID) -> Sandbox | None:
    """Get sandbox by its ID."""
    stmt = select(Sandbox).where(Sandbox.id == sandbox_id)
    return db_session.execute(stmt).scalar_one_or_none()


def set_sandbox_skills_hashes__no_commit(
    db_session: Session,
    skills_hashes: dict[UUID, str],
) -> None:
    """Record the skill runtime state successfully synchronized to each sandbox."""
    if not skills_hashes:
        return
    sandboxes = db_session.scalars(
        select(Sandbox).where(Sandbox.id.in_(skills_hashes))
    ).all()
    for sandbox in sandboxes:
        sandbox.skills_hash = skills_hashes[sandbox.id]
    db_session.flush()


def set_sandbox_mcp_config_hashes__no_commit(
    db_session: Session,
    mcp_config_hashes: dict[UUID, str],
) -> None:
    """Record each sandbox's current craft MCP fingerprint. Tracked separately
    from ``skills_hash`` so an MCP change doesn't ride the skill-file push."""
    if not mcp_config_hashes:
        return
    sandboxes = db_session.scalars(
        select(Sandbox).where(Sandbox.id.in_(mcp_config_hashes))
    ).all()
    for sandbox in sandboxes:
        sandbox.mcp_config_hash = mcp_config_hashes[sandbox.id]
    db_session.flush()


def lock_sandbox_skills_hashes(
    db_session: Session,
    sandbox_ids: set[UUID],
) -> dict[UUID, str | None]:
    """Lock sandboxes while their managed skill files and hashes are updated."""
    if not sandbox_ids:
        return {}
    rows = db_session.execute(
        select(Sandbox.id, Sandbox.skills_hash)
        .where(Sandbox.id.in_(sandbox_ids))
        .order_by(Sandbox.id)
        .with_for_update()
    )
    return {sandbox_id: skills_hash for sandbox_id, skills_hash in rows}


def update_sandbox_heartbeat(db_session: Session, sandbox_id: UUID) -> Sandbox:
    """Update the heartbeat without committing the caller's transaction."""
    sandbox = get_sandbox_by_id(db_session, sandbox_id)
    if not sandbox:
        raise ValueError(f"Sandbox {sandbox_id} not found")

    sandbox.last_heartbeat = datetime.datetime.now(datetime.timezone.utc)
    db_session.flush()
    return sandbox


def get_running_sandboxes(db_session: Session) -> list[Sandbox]:
    """Get all RUNNING sandboxes (the sweep task's working set)."""
    stmt = select(Sandbox).where(Sandbox.status == SandboxStatus.RUNNING)
    return list(db_session.execute(stmt).scalars().all())


def user_has_stale_active_session(
    db_session: Session,
    user_id: UUID,
    snapshot_cutoff: datetime.datetime,
) -> bool:
    """True when any of the user's ACTIVE sessions lacks a snapshot fresher
    than ``snapshot_cutoff`` — lets the sweep skip the pod round-trip when
    every session is already covered."""
    latest_snapshot_at = (
        select(func.max(Snapshot.created_at))
        .where(Snapshot.session_id == BuildSession.id)
        .scalar_subquery()
    )
    stmt = (
        select(BuildSession.id)
        .where(
            BuildSession.user_id == user_id,
            BuildSession.status == BuildSessionStatus.ACTIVE,
            or_(
                latest_snapshot_at.is_(None),
                latest_snapshot_at < snapshot_cutoff,
            ),
        )
        .limit(1)
    )
    return db_session.execute(stmt).first() is not None


def create_snapshot__no_commit(
    db_session: Session,
    session_id: UUID,
    storage_path: str,
    size_bytes: int,
) -> Snapshot:
    """Create a snapshot record for a session.

    NOTE: Uses flush() instead of commit(). The caller (cleanup task) is
    responsible for committing after all snapshots + status updates are done,
    so the entire operation is atomic.
    """
    snapshot = Snapshot(
        session_id=session_id,
        storage_path=storage_path,
        size_bytes=size_bytes,
    )
    db_session.add(snapshot)
    db_session.flush()
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


def delete_snapshot__no_commit(db_session: Session, snapshot: Snapshot) -> None:
    """Delete a snapshot row. Caller owns the transaction boundary."""
    db_session.delete(snapshot)


def delete_snapshot(db_session: Session, snapshot_id: UUID) -> bool:
    """Delete a specific snapshot by ID. Returns True if deleted, False if not found."""
    stmt = select(Snapshot).where(Snapshot.id == snapshot_id)
    snapshot = db_session.execute(stmt).scalar_one_or_none()

    if not snapshot:
        return False

    db_session.delete(snapshot)
    db_session.commit()
    return True


def get_sandbox_user_map(user_ids: list[UUID], db_session: Session) -> dict[UUID, User]:
    """Return ``{sandbox_id: user}`` for active sandboxes owned by *user_ids*.

    Only sandboxes with ``status == RUNNING`` are included — sleeping or
    terminated pods can't receive pushes.
    """
    if not user_ids:
        return {}

    stmt = (
        select(Sandbox, User)
        .join(User, User.id == Sandbox.user_id)  # ty: ignore[invalid-argument-type]
        .where(Sandbox.user_id.in_(user_ids))
        .where(Sandbox.status == SandboxStatus.RUNNING)
    )
    return {row.Sandbox.id: row.User for row in db_session.execute(stmt).unique()}
