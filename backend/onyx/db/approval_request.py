"""Approval requests of chat actions and the user's decisions.

Times compare with the database clock, so the decision API and the waiter
agree on which requests have expired.
"""

import datetime
from collections.abc import Collection
from uuid import UUID

from sqlalchemy import and_, exists, func, insert, or_, select, update
from sqlalchemy.orm import Session

from onyx.db.enums import ApprovalDecidedVia, ApprovalDecision
from onyx.db.models import ApprovalRequest, ChatSession

# A decided request's decision, how it was made, and its action ID.
type SavedDecision = tuple[ApprovalDecision, ApprovalDecidedVia | None, str]


def lock_session_grants__no_commit(db_session: Session, chat_session_id: UUID) -> None:
    """Serialize session grants with new requests of the chat until commit, so
    a request is not opened for an action that a grant now approves."""
    db_session.execute(
        select(ChatSession.id)
        .where(ChatSession.id == chat_session_id)
        # FOR NO KEY UPDATE: inserts that reference the chat do not wait.
        .with_for_update(key_share=True)
    )


def create_approval_request__no_commit(
    db_session: Session,
    *,
    chat_session_id: UUID,
    chat_message_id: int,
    gated_app_id: int,
    action_id: str,
) -> tuple[UUID, datetime.datetime]:
    """Returns the request's ID and its creation time on the database clock."""
    approval_id, created_at = db_session.execute(
        insert(ApprovalRequest)
        .values(
            chat_session_id=chat_session_id,
            chat_message_id=chat_message_id,
            gated_app_id=gated_app_id,
            action_id=action_id,
        )
        .returning(ApprovalRequest.id, ApprovalRequest.created_at)
    ).one()
    return approval_id, created_at


def has_session_grant(
    db_session: Session, chat_session_id: UUID, gated_app_id: int, action_id: str
) -> bool:
    return bool(
        db_session.scalar(
            select(
                exists().where(
                    ApprovalRequest.chat_session_id == chat_session_id,
                    ApprovalRequest.gated_app_id == gated_app_id,
                    ApprovalRequest.action_id == action_id,
                    ApprovalRequest.decided_via == ApprovalDecidedVia.SESSION_GRANT,
                )
            )
        )
    )


def get_approval_request_for_user(
    db_session: Session, approval_id: UUID, user_id: UUID
) -> ApprovalRequest | None:
    return db_session.scalar(
        select(ApprovalRequest)
        .join(ChatSession, ChatSession.id == ApprovalRequest.chat_session_id)
        .where(
            ApprovalRequest.id == approval_id,
            ChatSession.user_id == user_id,
            ChatSession.deleted.is_(False),
        )
    )


def record_approval_decision__no_commit(
    db_session: Session,
    approval: ApprovalRequest,
    decision: ApprovalDecision,
    decided_via: ApprovalDecidedVia,
    *,
    timeout: datetime.timedelta,
) -> set[int]:
    """Decide a pending request that is younger than `timeout`. A session grant
    also approves the action's other pending requests in the chat, and turns
    the user's earlier approval of this request into a grant. Returns the
    responses whose requests this decided; empty when this request was not
    decided."""
    live = ApprovalRequest.created_at > func.now() - timeout
    decidable = ApprovalRequest.decision.is_(None)
    if decided_via == ApprovalDecidedVia.SESSION_GRANT:
        lock_session_grants__no_commit(db_session, approval.chat_session_id)
        decidable = or_(
            decidable,
            and_(
                ApprovalRequest.decision == ApprovalDecision.APPROVED,
                ApprovalRequest.decided_via == ApprovalDecidedVia.USER,
            ),
        )
    decided = db_session.scalar(
        update(ApprovalRequest)
        .where(ApprovalRequest.id == approval.id, decidable, live)
        .values(decision=decision, decided_via=decided_via, decided_at=func.now())
        .returning(ApprovalRequest.chat_message_id)
    )
    if decided is None:
        return set()
    if decided_via != ApprovalDecidedVia.SESSION_GRANT:
        return {decided}
    return {
        decided,
        *db_session.scalars(
            update(ApprovalRequest)
            .where(
                ApprovalRequest.chat_session_id == approval.chat_session_id,
                ApprovalRequest.gated_app_id == approval.gated_app_id,
                ApprovalRequest.action_id == approval.action_id,
                ApprovalRequest.decision.is_(None),
                live,
            )
            .values(
                decision=ApprovalDecision.APPROVED,
                decided_via=ApprovalDecidedVia.SESSION_GRANT,
                decided_at=func.now(),
            )
            .returning(ApprovalRequest.chat_message_id)
        ),
    }


def settle_approval_requests__no_commit(
    db_session: Session,
    approval_ids: Collection[UUID],
    *,
    timeout: datetime.timedelta,
) -> dict[UUID, SavedDecision | None]:
    """Expire the pending requests older than `timeout`, then return the
    decisions of the decided ones, how they were made, and their action IDs.
    A request whose row no longer exists maps to None: deleting its tool's
    server, chat, or response deletes it, and nothing can decide it. The
    decision API's conditional update and this one decide whether a decision
    or the expiry wins."""
    db_session.execute(
        update(ApprovalRequest)
        .where(
            ApprovalRequest.id.in_(approval_ids),
            ApprovalRequest.decision.is_(None),
            ApprovalRequest.created_at <= func.now() - timeout,
        )
        .values(decision=ApprovalDecision.EXPIRED, decided_at=func.now())
    )
    saved = {
        approval_id: (decision, decided_via, action_id)
        for approval_id, decision, decided_via, action_id in db_session.execute(
            select(
                ApprovalRequest.id,
                ApprovalRequest.decision,
                ApprovalRequest.decided_via,
                ApprovalRequest.action_id,
            ).where(ApprovalRequest.id.in_(approval_ids))
        ).tuples()
    }
    settled: dict[UUID, SavedDecision | None] = {}
    for approval_id in approval_ids:
        row = saved.get(approval_id)
        if row is None:
            settled[approval_id] = None
            continue
        decision, decided_via, action_id = row
        if decision is not None:
            settled[approval_id] = (decision, decided_via, action_id)
    return settled


def expire_approval_requests__no_commit(
    db_session: Session,
    *,
    approval_ids: Collection[UUID] | None = None,
    chat_message_id: int | None = None,
) -> list[UUID]:
    """Expire the given requests, or a response's requests, that are still
    pending; returns the expired IDs."""
    return list(
        db_session.scalars(
            update(ApprovalRequest)
            .where(
                ApprovalRequest.decision.is_(None),
                ApprovalRequest.id.in_(approval_ids)
                if approval_ids is not None
                else ApprovalRequest.chat_message_id == chat_message_id,
            )
            .values(decision=ApprovalDecision.EXPIRED, decided_at=func.now())
            .returning(ApprovalRequest.id)
        ).all()
    )


def responses_waiting_for_approval(
    db_session: Session,
    chat_session_id: UUID,
    user_id: UUID | None,
    *,
    timeout: datetime.timedelta,
) -> set[int]:
    """The responses of the user's chat with a pending request younger than
    `timeout`."""
    return set(
        db_session.scalars(
            select(ApprovalRequest.chat_message_id)
            .join(ChatSession, ChatSession.id == ApprovalRequest.chat_session_id)
            .where(
                ApprovalRequest.chat_session_id == chat_session_id,
                ChatSession.user_id == user_id,
                ApprovalRequest.decision.is_(None),
                ApprovalRequest.created_at > func.now() - timeout,
            )
            .distinct()
        )
    )


def get_pending_approval_ids(db_session: Session, chat_message_id: int) -> set[UUID]:
    """The requests of a response that wait for a decision."""
    return set(
        db_session.scalars(
            select(ApprovalRequest.id).where(
                ApprovalRequest.chat_message_id == chat_message_id,
                ApprovalRequest.decision.is_(None),
            )
        )
    )
