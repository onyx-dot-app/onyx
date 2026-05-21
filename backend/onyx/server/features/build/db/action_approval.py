"""Database operations for the action_approval table.

A row records one agent-initiated gated action and its eventual
terminal decision (APPROVED / REJECTED / EXPIRED). `decision IS NULL`
is the pending / in-flight state.

These functions follow the build-feature convention: they flush so the
caller can read auto-generated columns back, but the caller still owns
transaction commit. Cache (Redis) operations belong in
`sandbox_proxy/approval_cache.py`, not here.
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
    """Insert a new pending action_approval row.

    The row starts with ``decision IS NULL``; the primary key is
    auto-generated via the ORM's ``default=uuid4``. Flushes so the
    caller can read ``row.approval_id`` back.
    """
    row = ActionApproval(
        session_id=session_id,
        action_type=action_type,
        payload=payload,
    )
    db_session.add(row)
    db_session.flush()
    return row


def record_decision(
    db_session: Session,
    *,
    approval_id: UUID,
    decision: ApprovalDecision,
) -> ActionApproval | None:
    """Race-safe terminal write: only succeeds while ``decision IS NULL``.

    Returns the updated row, or ``None`` if a decision was already
    recorded. Callers handle the ``None`` case (idempotent retry vs
    genuine CONFLICT).
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
    return row


def get_action_approval(
    db_session: Session, approval_id: UUID
) -> ActionApproval | None:
    return db_session.get(ActionApproval, approval_id)


def get_action_approval_for_user(
    db_session: Session, approval_id: UUID, user_id: UUID
) -> ActionApproval | None:
    """Return the row only if the caller owns the parent build_session.

    Returns ``None`` for both missing-row and wrong-owner — callers map
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
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
) -> list[ActionApproval]:
    """User-scoped audit query.

    ``decision=None`` returns every row including ``decision IS NULL``
    (orphan attempts left by a hard proxy crash). Callers that want to
    filter to a specific terminal state pass that enum value.
    """
    stmt = select(ActionApproval).where(ActionApproval.session_id == session_id)
    if decision is not None:
        stmt = stmt.where(ActionApproval.decision == decision)
    if from_dt is not None:
        stmt = stmt.where(ActionApproval.created_at >= from_dt)
    if to_dt is not None:
        stmt = stmt.where(ActionApproval.created_at <= to_dt)
    stmt = stmt.order_by(ActionApproval.created_at.desc())
    return list(db_session.scalars(stmt))


def list_session_pending_action_approvals(
    db_session: Session, session_id: UUID
) -> list[ActionApproval]:
    """Return every row for the session that has not yet been decided.

    The decision API filters this further by checking each row's
    Redis liveness key — rows that are pending but whose liveness has
    lapsed (orphans from a hard proxy crash) are not actionable.
    """
    stmt = (
        select(ActionApproval)
        .where(ActionApproval.session_id == session_id)
        .where(ActionApproval.decision.is_(None))
        .order_by(ActionApproval.created_at.desc())
    )
    return list(db_session.scalars(stmt))
