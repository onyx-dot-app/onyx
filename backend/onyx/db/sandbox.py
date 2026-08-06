"""Database operations for sandbox cleanup."""

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from onyx.db.enums import SandboxStatus
from onyx.db.models import Sandbox


def get_sweepable_sandboxes(db_session: Session) -> list[Sandbox]:
    """Get sandboxes whose runtime may need snapshotting or cleanup."""
    stmt = select(Sandbox).where(
        Sandbox.status.in_([SandboxStatus.RUNNING, SandboxStatus.FAILED])
    )
    return list(db_session.execute(stmt).scalars().all())


def sleep_sweepable_sandbox__no_commit(
    db_session: Session,
    sandbox_id: UUID,
    attempt_number: int,
) -> bool:
    """Move ``RUNNING``/``FAILED`` to ``SLEEPING`` if the attempt still owns it."""
    result = db_session.execute(
        update(Sandbox)
        .where(
            Sandbox.id == sandbox_id,
            Sandbox.provisioning_attempt_number == attempt_number,
            Sandbox.status.in_([SandboxStatus.RUNNING, SandboxStatus.FAILED]),
        )
        .values(status=SandboxStatus.SLEEPING)
    )
    return result.rowcount == 1  # ty: ignore[unresolved-attribute]
