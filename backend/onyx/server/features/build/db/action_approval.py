"""Database operations for the action_approval table.

`try_record_decision`'s conditional UPDATE is the only race arbiter.
"""

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from onyx.db.enums import (
    POLICY_SEVERITY,
    ApprovalDecidedVia,
    ApprovalDecision,
    EndpointPolicy,
    GatedAppKind,
)
from onyx.db.gated_app import get_gated_app_id, get_or_create_gated_app_id
from onyx.db.models import ActionApproval, BuildSession
from onyx.utils.logger import setup_logger

logger = setup_logger()


def insert_action_approval(
    db_session: Session,
    *,
    session_id: UUID,
    actions: list[dict[str, Any]],
    app_name: str,
    payload: dict[str, Any],
    target: tuple[GatedAppKind, int] | None = None,
    decision: ApprovalDecision | None = None,
    decided_via: ApprovalDecidedVia | None = None,
) -> ActionApproval:
    """Commit an approval row. ``actions`` is the JSONB list of
    ``MatchedAction``-shaped dicts; must be non-empty. Re-sorted
    strictest-policy-first so every reader can rely on ``actions[0]``.
    ``target`` attributes the row to a gated ``(kind, target_id)`` via its
    ``gated_app`` identity row; a target-less row (e.g. a bash gate) leaves
    ``gated_app_id`` NULL.

    Defaults to a pending row (``decision IS NULL``). Passing ``decision``
    inserts it pre-decided — safe to bypass ``try_record_decision``'s
    arbiter because nothing parks on a pre-decided row.
    """
    if not actions:
        raise ValueError("actions must be non-empty")
    sorted_actions = sorted(
        actions,
        key=lambda a: POLICY_SEVERITY[EndpointPolicy(a["policy"])],
        reverse=True,
    )
    gated_app_id = (
        get_or_create_gated_app_id(db_session, *target) if target is not None else None
    )
    row = ActionApproval(
        session_id=session_id,
        actions=sorted_actions,
        app_name=app_name,
        payload=payload,
        gated_app_id=gated_app_id,
        decision=decision,
        decided_at=datetime.now(timezone.utc) if decision is not None else None,
        decided_via=decided_via,
    )
    db_session.add(row)
    db_session.flush()
    return row


def try_record_decision(
    db_session: Session,
    *,
    approval_id: UUID,
    decision: ApprovalDecision,
    decided_via: ApprovalDecidedVia | None = None,
) -> ActionApproval | None:
    """Conditional UPDATE that succeeds only while `decision IS NULL`.

    Returns the updated row, or `None` if a decision was already recorded.
    """
    stmt = (
        update(ActionApproval)
        .where(ActionApproval.approval_id == approval_id)
        .where(ActionApproval.decision.is_(None))
        .values(
            decision=decision,
            decided_at=datetime.now(timezone.utc),
            decided_via=decided_via,
        )
        .returning(ActionApproval)
        .execution_options(synchronize_session=False)
    )
    row = db_session.execute(stmt).scalar_one_or_none()
    db_session.flush()
    if row is not None:
        # synchronize_session=False + expire_on_commit=False: without this
        # refresh the caller sees the stale identity-mapped row (decision=None).
        db_session.refresh(row)
    return row


def get_action_approval(
    db_session: Session, approval_id: UUID
) -> ActionApproval | None:
    return db_session.get(ActionApproval, approval_id)


def get_action_approval_for_user(
    db_session: Session, approval_id: UUID, user_id: UUID
) -> ActionApproval | None:
    """Row only if the caller owns the parent build_session.

    `None` for both missing-row and wrong-owner so existence isn't leaked.
    """
    stmt = (
        select(ActionApproval)
        .join(BuildSession, BuildSession.id == ActionApproval.session_id)
        .where(ActionApproval.approval_id == approval_id)
        .where(BuildSession.user_id == user_id)
    )
    return db_session.scalar(stmt)


def list_session_pending_action_approvals(
    db_session: Session,
    session_id: UUID,
    *,
    created_after: datetime | None = None,
    load_target: bool = False,
) -> list[ActionApproval]:
    """Undecided rows for the session.

    `created_after` excludes rows older than the proxy's wait window
    (likely orphaned by a crashed proxy that couldn't write EXPIRED).

    `load_target` eager-loads each row's ``gated_app`` in one batched SELECT —
    set it when the caller inspects the target per row (else it stays lazy and a
    caller that never touches it pays nothing).
    """
    stmt = (
        select(ActionApproval)
        .where(ActionApproval.session_id == session_id)
        .where(ActionApproval.decision.is_(None))
    )
    if load_target:
        stmt = stmt.options(selectinload(ActionApproval.gated_app))
    if created_after is not None:
        stmt = stmt.where(ActionApproval.created_at >= created_after)
    stmt = stmt.order_by(ActionApproval.created_at.desc())
    return list(db_session.scalars(stmt))


def list_session_grant_action_approvals(
    db_session: Session,
    session_id: UUID,
    *,
    kind: GatedAppKind,
    target_id: int,
) -> list[ActionApproval]:
    """Approved rows covered by a durable session-scope grant for one target."""
    gated_app_id = get_gated_app_id(db_session, kind, target_id)
    if gated_app_id is None:
        return []
    stmt = (
        select(ActionApproval)
        .where(ActionApproval.session_id == session_id)
        .where(ActionApproval.gated_app_id == gated_app_id)
        .where(ActionApproval.decision == ApprovalDecision.APPROVED)
        .where(ActionApproval.decided_via == ApprovalDecidedVia.SESSION_GRANT)
        .order_by(ActionApproval.decided_at.desc())
    )
    return list(db_session.scalars(stmt))
