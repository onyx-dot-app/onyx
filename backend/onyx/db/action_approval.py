"""Database operations for the action_approval table.

`try_record_decision`'s conditional UPDATE is the only race arbiter.
"""

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session, load_only, selectinload

from onyx.db.enums import (
    POLICY_SEVERITY,
    ActionPolicy,
    ApprovalDecidedVia,
    ApprovalDecision,
)
from onyx.db.models import ActionApproval, BuildSession, ChatSession
from onyx.server.features.build.configs import SANDBOX_APPROVAL_WAIT_TIMEOUT_SECONDS
from onyx.utils.logger import setup_logger

logger = setup_logger()


def waiting_cutoff() -> datetime:
    """Pending rows created before this wait on no proxy (the proxy's wait
    timeout)."""
    return datetime.now(timezone.utc) - timedelta(
        seconds=SANDBOX_APPROVAL_WAIT_TIMEOUT_SECONDS
    )


def insert_action_approval(
    db_session: Session,
    *,
    session_id: UUID | None,
    actions: list[dict[str, Any]],
    app_name: str,
    payload: dict[str, Any],
    integration_id: int | None = None,
    decision: ApprovalDecision | None = None,
    decided_via: ApprovalDecidedVia | None = None,
    chat_session_id: UUID | None = None,
    command_id: UUID | None = None,
) -> ActionApproval:
    """Commit an approval row. ``actions`` is the JSONB list of
    ``MatchedAction``-shaped dicts; must be non-empty. Re-sorted
    strictest-policy-first so every reader can rely on ``actions[0]``.
    ``integration_id`` attributes the row to an integration; a row with no
    integration (e.g. a bash gate) leaves it NULL.

    The row belongs to the Craft session ``session_id``, or to the chat VM
    command ``command_id`` of ``chat_session_id``.

    Defaults to a pending row (``decision IS NULL``). Passing ``decision``
    inserts it pre-decided — safe to bypass ``try_record_decision``'s
    arbiter because nothing parks on a pre-decided row.
    """
    if not actions:
        raise ValueError("actions must be non-empty")
    if (session_id is None) == (chat_session_id is None) or (
        chat_session_id is None
    ) != (command_id is None):
        raise ValueError("set session_id, or chat_session_id and command_id")
    sorted_actions = sorted(
        actions,
        key=lambda a: POLICY_SEVERITY[ActionPolicy(a["policy"])],
        reverse=True,
    )
    row = ActionApproval(
        session_id=session_id,
        chat_session_id=chat_session_id,
        command_id=command_id,
        actions=sorted_actions,
        app_name=app_name,
        payload=payload,
        integration_id=integration_id,
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
    created_after: datetime | None = None,
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
    if created_after is not None:
        stmt = stmt.where(ActionApproval.created_at >= created_after)
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
    db_session: Session, approval_id: UUID, user_id: UUID, *, lock_session: bool = False
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
    if lock_session:
        # Serialize grants before either request locks its own approval row.
        stmt = stmt.with_for_update(of=BuildSession)
    return db_session.scalar(stmt)


def list_session_action_approvals(
    db_session: Session,
    session_id: UUID,
    *,
    created_after: datetime,
    status_only: bool = False,
) -> list[ActionApproval]:
    """All live requests and the 50 most recent completed or expired requests."""
    is_live = and_(
        ActionApproval.decision.is_(None),
        ActionApproval.created_at >= created_after,
    )
    recent_outcomes = (
        select(ActionApproval.approval_id)
        .where(ActionApproval.session_id == session_id, ~is_live)
        .order_by(ActionApproval.created_at.desc(), ActionApproval.approval_id.desc())
        .limit(50)
    )
    return list(
        db_session.scalars(
            select(ActionApproval)
            .where(
                ActionApproval.session_id == session_id,
                or_(is_live, ActionApproval.approval_id.in_(recent_outcomes)),
            )
            .options(
                load_only(
                    ActionApproval.approval_id,
                    ActionApproval.created_at,
                    ActionApproval.decision,
                    raiseload=True,
                )
                if status_only
                else selectinload(ActionApproval.integration)
            )
            .order_by(
                ActionApproval.created_at.desc(), ActionApproval.approval_id.desc()
            )
        )
    )


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

    `load_target` eager-loads each row's ``integration`` in one batched SELECT —
    set it when the caller inspects the target per row (else it stays lazy and a
    caller that never touches it pays nothing).
    """
    stmt = (
        select(ActionApproval)
        .where(ActionApproval.session_id == session_id)
        .where(ActionApproval.decision.is_(None))
    )
    if load_target:
        stmt = stmt.options(selectinload(ActionApproval.integration))
    if created_after is not None:
        stmt = stmt.where(ActionApproval.created_at >= created_after)
    stmt = stmt.order_by(ActionApproval.created_at.desc())
    return list(db_session.scalars(stmt))


def list_session_grant_action_approvals(
    db_session: Session,
    session_id: UUID,
    *,
    integration_id: int | None,
) -> list[ActionApproval]:
    """Approved rows covered by a durable session-scope grant for one
    integration. ``None`` (an integration that was deleted) has no grants."""
    if integration_id is None:
        return []
    stmt = (
        select(ActionApproval)
        .where(ActionApproval.session_id == session_id)
        .where(ActionApproval.integration_id == integration_id)
        .where(ActionApproval.decision == ApprovalDecision.APPROVED)
        .where(ActionApproval.decided_via == ApprovalDecidedVia.SESSION_GRANT)
        .order_by(ActionApproval.decided_at.desc())
    )
    return list(db_session.scalars(stmt))


def get_chat_action_approval_for_user(
    db_session: Session, approval_id: UUID, user_id: UUID
) -> ActionApproval | None:
    """A chat command's row, only if the caller owns its chat, which is not
    deleted. `None` for a missing row and for another user's row."""
    return db_session.scalar(
        select(ActionApproval)
        .join(ChatSession, ChatSession.id == ActionApproval.chat_session_id)
        .where(ActionApproval.approval_id == approval_id)
        .where(ChatSession.user_id == user_id)
        .where(ChatSession.deleted.is_(False))
    )


def list_pending_command_action_approvals(
    db_session: Session,
    *,
    chat_session_id: UUID,
    command_id: UUID,
    created_after: datetime | None = None,
) -> list[ActionApproval]:
    """The pending rows of one chat command, oldest first, optionally only
    the rows created at or after `created_after`."""
    stmt = select(ActionApproval).where(
        ActionApproval.chat_session_id == chat_session_id,
        ActionApproval.command_id == command_id,
        ActionApproval.decision.is_(None),
    )
    if created_after is not None:
        stmt = stmt.where(ActionApproval.created_at >= created_after)
    return list(
        db_session.scalars(
            stmt.order_by(ActionApproval.created_at, ActionApproval.approval_id)
        )
    )
