"""Approval requests of chat actions and the user's decisions."""

from collections.abc import Collection
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import and_, func, insert, or_, select, update
from sqlalchemy.orm import Session

from onyx.db.enums import ApprovalDecidedVia, ApprovalDecision
from onyx.db.models import ApprovalRequest, ChatSession, GatedApp, Integration
from onyx.utils.postgres_sanitization import sanitize_json_like, sanitize_string


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
    integration_id: int,
    gated_app_id: int | None,
    action_id: str,
    tool_call_id: str,
    tool_name: str,
    display_name: str,
    arguments: dict[str, JsonValue],
) -> UUID:
    return db_session.execute(
        insert(ApprovalRequest)
        .values(
            chat_session_id=chat_session_id,
            chat_message_id=chat_message_id,
            integration_id=integration_id,
            gated_app_id=gated_app_id,
            action_id=action_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            # The card's copy of the call; PostgreSQL stores no NUL or
            # surrogate characters.
            display_name=sanitize_string(display_name),
            arguments=sanitize_json_like(arguments),
        )
        .returning(ApprovalRequest.id)
    ).scalar_one()


def get_legacy_gated_app_id(db_session: Session, integration_id: int) -> int | None:
    """The ``gated_app`` row that the upgrade kept for the integration: same
    id, and the same MCP server or external app. None for an integration made
    after the upgrade and for an OpenAPI tool."""
    return db_session.scalar(
        select(GatedApp.id)
        .join(Integration, Integration.id == GatedApp.id)
        .where(
            GatedApp.id == integration_id,
            or_(
                Integration.mcp_server_id == GatedApp.mcp_server_id,
                Integration.external_app_id == GatedApp.external_app_id,
            ),
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
) -> None:
    """Decide a pending request. A session grant also approves the action's
    other pending requests in the chat, and turns the user's earlier approval
    of this request into a grant. A request that is no longer pending stays
    as it is."""
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
        .where(ApprovalRequest.id == approval.id, decidable)
        .values(decision=decision, decided_via=decided_via, decided_at=func.now())
        .returning(ApprovalRequest.id)
    )
    if (
        decided is None
        or decided_via != ApprovalDecidedVia.SESSION_GRANT
        or approval.integration_id is None
    ):
        return
    db_session.execute(
        update(ApprovalRequest)
        .where(
            ApprovalRequest.chat_session_id == approval.chat_session_id,
            ApprovalRequest.integration_id == approval.integration_id,
            ApprovalRequest.action_id == approval.action_id,
            ApprovalRequest.decision.is_(None),
        )
        .values(
            decision=ApprovalDecision.APPROVED,
            decided_via=ApprovalDecidedVia.SESSION_GRANT,
            decided_at=func.now(),
        )
    )


def get_approval_requests(
    db_session: Session, approval_ids: Collection[UUID]
) -> dict[UUID, ApprovalRequest]:
    """The saved requests by ID; a deleted request is absent. Deleting its
    chat or response deletes a request."""
    return {
        row.id: row
        for row in db_session.scalars(
            select(ApprovalRequest)
            .where(ApprovalRequest.id.in_(approval_ids))
            .execution_options(populate_existing=True)
        )
    }


def close_pending_approval_requests__no_commit(
    db_session: Session,
    decision: ApprovalDecision,
    decided_via: ApprovalDecidedVia | None,
    *,
    approval_ids: Collection[UUID] | None = None,
    chat_message_ids: Collection[int] | None = None,
) -> list[UUID]:
    """Decide the given requests, or the responses' requests, that are still
    pending: EXPIRED when nothing waits for them anymore, or the user's
    rejection when the user stops the responses. Returns the decided IDs."""
    return list(
        db_session.scalars(
            update(ApprovalRequest)
            .where(
                ApprovalRequest.decision.is_(None),
                ApprovalRequest.id.in_(approval_ids)
                if approval_ids is not None
                else ApprovalRequest.chat_message_id.in_(chat_message_ids or []),
            )
            .values(decision=decision, decided_via=decided_via, decided_at=func.now())
            .returning(ApprovalRequest.id)
        ).all()
    )


def get_response_approval_requests(
    db_session: Session, chat_message_ids: Collection[int]
) -> list[ApprovalRequest]:
    """The requests of these responses, in the order they were made."""
    return list(
        db_session.scalars(
            select(ApprovalRequest)
            .where(ApprovalRequest.chat_message_id.in_(chat_message_ids))
            .order_by(ApprovalRequest.created_at, ApprovalRequest.id)
        )
    )


def approvals_version(db_session: Session, chat_session_id: UUID) -> str:
    """A marker that changes when a request of the chat opens, is decided or is
    deleted, for clients that show the requests of a saved chat. It is empty
    while the chat has no request, so a client that loaded nothing takes the
    empty marker as its baseline."""
    marker = db_session.execute(
        select(
            func.count(),
            func.count(ApprovalRequest.decision),
            func.max(ApprovalRequest.created_at),
            func.max(ApprovalRequest.decided_at),
        ).where(ApprovalRequest.chat_session_id == chat_session_id)
    ).one()
    return "/".join(str(value) for value in marker) if marker[0] else ""
