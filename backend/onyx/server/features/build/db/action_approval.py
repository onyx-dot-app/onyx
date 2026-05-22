"""Database operations for the action_approval table.

A row records one agent-initiated gated action and its eventual
terminal decision (APPROVED / REJECTED / EXPIRED). `decision IS NULL`
is the pending / in-flight state. The conditional UPDATE in
`try_record_decision` is the only race arbiter.
"""

from datetime import datetime
from datetime import timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.orm import Session

from onyx.db.enums import ApprovalDecision
from onyx.db.models import ActionApproval
from onyx.db.models import BuildSession
from onyx.utils.logger import setup_logger

logger = setup_logger()


def insert_action_approval(
    db_session: Session,
    *,
    session_id: UUID,
    action_type: str,
    payload: dict[str, Any],
) -> ActionApproval:
    """Insert a new pending row and return it."""
    row = ActionApproval(
        session_id=session_id,
        action_type=action_type,
        payload=payload,
    )
    db_session.add(row)
    db_session.flush()
    return row


def try_record_decision(
    db_session: Session,
    *,
    approval_id: UUID,
    decision: ApprovalDecision,
) -> ActionApproval | None:
    """Conditional UPDATE: succeeds only while `decision IS NULL`.

    Returns the updated row, or `None` if a decision was already
    recorded (caller decides between idempotent retry and CONFLICT).
    """
    stmt = (
        update(ActionApproval)
        .where(ActionApproval.approval_id == approval_id)
        .where(ActionApproval.decision.is_(None))
        .values(decision=decision, decided_at=datetime.now(timezone.utc))
        .returning(ActionApproval)
        .execution_options(synchronize_session=False)
    )
    row = db_session.execute(stmt).scalar_one_or_none()
    db_session.flush()
    if row is not None:
        # The session is `expire_on_commit=False`, and our UPDATE uses
        # `synchronize_session=False`. Without this refresh the caller
        # would see the pre-UPDATE in-memory state of the identity-mapped
        # row (decision=None) even though Postgres has the new value.
        db_session.refresh(row)
    return row


def get_action_approval(
    db_session: Session, approval_id: UUID
) -> ActionApproval | None:
    return db_session.get(ActionApproval, approval_id)


def get_action_approval_for_user(
    db_session: Session, approval_id: UUID, user_id: UUID
) -> ActionApproval | None:
    """Return the row only if the caller owns the parent build_session.

    Returns `None` for both missing-row and wrong-owner — callers map
    to NOT_FOUND so existence isn't leaked to non-owners.
    """
    stmt = (
        select(ActionApproval)
        .join(BuildSession, BuildSession.id == ActionApproval.session_id)
        .where(ActionApproval.approval_id == approval_id)
        .where(BuildSession.user_id == user_id)
    )
    return db_session.scalar(stmt)


def list_session_action_approvals(
    db_session: Session,
    session_id: UUID,
    *,
    decision: ApprovalDecision | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[ActionApproval]:
    """Audit query for a session. `decision=None` includes pending rows."""
    stmt = select(ActionApproval).where(ActionApproval.session_id == session_id)
    if decision is not None:
        stmt = stmt.where(ActionApproval.decision == decision)
    if since is not None:
        stmt = stmt.where(ActionApproval.created_at >= since)
    if until is not None:
        stmt = stmt.where(ActionApproval.created_at <= until)
    stmt = stmt.order_by(ActionApproval.created_at.desc())
    return list(db_session.scalars(stmt))


def list_session_pending_action_approvals(
    db_session: Session,
    session_id: UUID,
    *,
    created_after: datetime | None = None,
) -> list[ActionApproval]:
    """Return undecided rows for the session, optionally cutting off by age.

    `created_after` lets callers exclude rows older than the proxy's
    wait window (likely orphaned by a crashed proxy that can't write
    EXPIRED itself).
    """
    stmt = (
        select(ActionApproval)
        .where(ActionApproval.session_id == session_id)
        .where(ActionApproval.decision.is_(None))
    )
    if created_after is not None:
        stmt = stmt.where(ActionApproval.created_at >= created_after)
    stmt = stmt.order_by(ActionApproval.created_at.desc())
    return list(db_session.scalars(stmt))
