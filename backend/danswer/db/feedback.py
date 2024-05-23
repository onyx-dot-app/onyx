from uuid import UUID

from sqlalchemy import asc
from sqlalchemy import delete
from sqlalchemy import desc
from sqlalchemy import select
from sqlalchemy.orm import Session

from danswer.configs.constants import MessageType
from danswer.configs.constants import SearchFeedbackType
from danswer.db.chat import get_chat_message
from danswer.db.models import ChatMessageFeedback
from danswer.db.models import Document as DbDocument
from danswer.db.models import DocumentRetrievalFeedback
from danswer.document_index.interfaces import DocumentIndex
from danswer.document_index.interfaces import UpdateRequest


def fetch_db_doc_by_id(doc_id: str, db_session: Session) -> DbDocument:
    stmt = select(DbDocument).where(DbDocument.id == doc_id)
    result = db_session.execute(stmt)
    doc = result.scalar_one_or_none()

    if not doc:
        raise ValueError("Invalid Document ID Provided")

    return doc


def fetch_docs_ranked_by_boost(
    db_session: Session, ascending: bool = False, limit: int = 100
) -> list[DbDocument]:
    order_func = asc if ascending else desc
    stmt = (
        select(DbDocument)
        .order_by(order_func(DbDocument.boost), order_func(DbDocument.semantic_id))
        .limit(limit)
    )
    result = db_session.execute(stmt)
    doc_list = result.scalars().all()

    return list(doc_list)


def update_document_boost(
    db_session: Session, document_id: str, boost: int, document_index: DocumentIndex
) -> None:
    stmt = select(DbDocument).where(DbDocument.id == document_id)
    result = db_session.execute(stmt).scalar_one_or_none()
    if result is None:
        raise ValueError(f"No document found with ID: '{document_id}'")

    result.boost = boost

    update = UpdateRequest(
        document_ids=[document_id],
        boost=boost,
    )

    document_index.update(update_requests=[update])

    db_session.commit()


def update_document_hidden(
    db_session: Session, document_id: str, hidden: bool, document_index: DocumentIndex
) -> None:
    stmt = select(DbDocument).where(DbDocument.id == document_id)
    result = db_session.execute(stmt).scalar_one_or_none()
    if result is None:
        raise ValueError(f"No document found with ID: '{document_id}'")

    result.hidden = hidden

    update = UpdateRequest(
        document_ids=[document_id],
        hidden=hidden,
    )

    document_index.update(update_requests=[update])

    db_session.commit()


def create_doc_retrieval_feedback(
    message_id: int,
    document_id: str,
    document_rank: int,
    document_index: DocumentIndex,
    db_session: Session,
    clicked: bool = False,
    feedback: SearchFeedbackType | None = None,
) -> None:
    """Creates a new Document feedback row and updates the boost value in Postgres and Vespa"""
    db_doc = fetch_db_doc_by_id(document_id, db_session)

    retrieval_feedback = DocumentRetrievalFeedback(
        chat_message_id=message_id,
        document_id=document_id,
        document_rank=document_rank,
        clicked=clicked,
        feedback=feedback,
    )

    if feedback is not None:
        if feedback == SearchFeedbackType.ENDORSE:
            db_doc.boost += 1
        elif feedback == SearchFeedbackType.REJECT:
            db_doc.boost -= 1
        elif feedback == SearchFeedbackType.HIDE:
            db_doc.hidden = True
        elif feedback == SearchFeedbackType.UNHIDE:
            db_doc.hidden = False
        else:
            raise ValueError("Unhandled document feedback type")

    if feedback in [
        SearchFeedbackType.ENDORSE,
        SearchFeedbackType.REJECT,
        SearchFeedbackType.HIDE,
    ]:
        update = UpdateRequest(
            document_ids=[document_id], boost=db_doc.boost, hidden=db_doc.hidden
        )
        # Updates are generally batched for efficiency, this case only 1 doc/value is updated
        document_index.update(update_requests=[update])

    db_session.add(retrieval_feedback)
    db_session.commit()


def delete_document_feedback_for_documents__no_commit(
    document_ids: list[str], db_session: Session
) -> None:
    """NOTE: does not commit transaction so that this can be used as part of a
    larger transaction block."""
    stmt = delete(DocumentRetrievalFeedback).where(
        DocumentRetrievalFeedback.document_id.in_(document_ids)
    )
    db_session.execute(stmt)


def create_chat_message_feedback(
    is_positive: bool | None,
    feedback_text: str | None,
    chat_message_id: int,
    user_id: UUID | None,
    db_session: Session,
    # Slack user requested help from human
    required_followup: bool | None = None,
    predefined_feedback: str | None = None,  # Added predefined_feedback parameter
) -> None:
    if (
        is_positive is None
        and feedback_text is None
        and required_followup is None
        and predefined_feedback is None
    ):
        raise ValueError("No feedback provided")

    chat_message = get_chat_message(
        chat_message_id=chat_message_id, user_id=user_id, db_session=db_session
    )

    if chat_message.message_type != MessageType.ASSISTANT:
        raise ValueError("Can only provide feedback on LLM Outputs")

    message_feedback = ChatMessageFeedback(
        chat_message_id=chat_message_id,
        is_positive=is_positive,
        feedback_text=feedback_text,
        required_followup=required_followup,
        predefined_feedback=predefined_feedback,
    )

    db_session.add(message_feedback)
    db_session.commit()
