"""Questions that chat agents ask the user, and the user's answers."""

from collections.abc import Collection
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import func, insert, select, update
from sqlalchemy.orm import Session

from onyx.db.enums import QuestionAnsweredVia, QuestionOutcome
from onyx.db.models import ChatSession, QuestionRequest
from onyx.utils.postgres_sanitization import sanitize_json_like, sanitize_string


def create_question_request__no_commit(
    db_session: Session,
    *,
    question_request_id: UUID,
    chat_session_id: UUID,
    chat_message_id: int,
    tool_call_id: str,
    questions: list[dict[str, JsonValue]],
) -> None:
    db_session.execute(
        insert(QuestionRequest).values(
            id=question_request_id,
            chat_session_id=chat_session_id,
            chat_message_id=chat_message_id,
            tool_call_id=tool_call_id,
            # PostgreSQL stores no NUL or surrogate characters.
            questions=sanitize_json_like(questions),
        )
    )


def get_question_request_for_user(
    db_session: Session, question_request_id: UUID, user_id: UUID
) -> QuestionRequest | None:
    return db_session.scalar(
        select(QuestionRequest)
        .join(ChatSession, ChatSession.id == QuestionRequest.chat_session_id)
        .where(
            QuestionRequest.id == question_request_id,
            ChatSession.user_id == user_id,
            ChatSession.deleted.is_(False),
        )
    )


def resolve_question_requests__no_commit(
    db_session: Session,
    outcome: QuestionOutcome,
    *,
    question_request_ids: Collection[UUID] | None = None,
    chat_message_ids: Collection[int] | None = None,
    answered_via: QuestionAnsweredVia | None = None,
    answers: list[dict[str, JsonValue]] | None = None,
    message: str | None = None,
) -> list[UUID]:
    """End the given requests, or the responses' requests, that still wait:
    answered from the card or by a typed message, or CANCELLED when nothing
    waits for them anymore. Returns the IDs that ended here."""
    return list(
        db_session.scalars(
            update(QuestionRequest)
            .where(
                QuestionRequest.outcome.is_(None),
                QuestionRequest.id.in_(question_request_ids)
                if question_request_ids is not None
                else QuestionRequest.chat_message_id.in_(chat_message_ids or []),
            )
            .values(
                outcome=outcome,
                answered_via=answered_via,
                answers=sanitize_json_like(answers) if answers is not None else None,
                message=sanitize_string(message) if message is not None else None,
                resolved_at=func.now(),
            )
            .returning(QuestionRequest.id)
        ).all()
    )


def get_question_requests(
    db_session: Session, question_request_ids: Collection[UUID]
) -> dict[UUID, QuestionRequest]:
    """The saved requests by ID; deleting their chat or response deletes them."""
    if not question_request_ids:
        return {}
    return {
        row.id: row
        for row in db_session.scalars(
            select(QuestionRequest)
            .where(QuestionRequest.id.in_(question_request_ids))
            .execution_options(populate_existing=True)
        )
    }


def get_response_question_requests(
    db_session: Session, chat_message_ids: Collection[int]
) -> list[QuestionRequest]:
    """The requests of these responses, in the order they were made."""
    return list(
        db_session.scalars(
            select(QuestionRequest)
            .where(QuestionRequest.chat_message_id.in_(chat_message_ids))
            .order_by(QuestionRequest.created_at, QuestionRequest.id)
            .execution_options(populate_existing=True)
        )
    )
