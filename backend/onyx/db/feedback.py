from datetime import datetime
from datetime import timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import and_
from sqlalchemy import asc
from sqlalchemy import delete
from sqlalchemy import desc
from sqlalchemy import exists
from sqlalchemy import Select
from sqlalchemy import select
from sqlalchemy.orm import aliased
from sqlalchemy.orm import Session

from onyx.configs.app_configs import DISABLE_AUTH
from onyx.configs.constants import MessageType
from onyx.configs.constants import SearchFeedbackType
from onyx.db.chat import get_chat_message
from onyx.db.enums import AccessType
from onyx.db.models import ChatMessageFeedback
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import Document as DbDocument
from onyx.db.models import DocumentByConnectorCredentialPair
from onyx.db.models import DocumentRetrievalFeedback
from onyx.db.models import User
from onyx.db.models import User__UserGroup
from onyx.db.models import UserGroup__ConnectorCredentialPair
from onyx.db.models import UserRole
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _fetch_db_doc_by_id(doc_id: str, db_session: Session) -> DbDocument:
    stmt = select(DbDocument).where(DbDocument.id == doc_id)
    result = db_session.execute(stmt)
    doc = result.scalar_one_or_none()

    if not doc:
        raise ValueError("Invalid Document ID Provided")

    return doc


def _add_user_filters(
    stmt: Select, user: User | None, get_editable: bool = True
) -> Select:
    # If user is None and auth is disabled, assume the user is an admin
    if (user is None and DISABLE_AUTH) or (user and user.role == UserRole.ADMIN):
        return stmt

    stmt = stmt.distinct()
    DocByCC = aliased(DocumentByConnectorCredentialPair)
    CCPair = aliased(ConnectorCredentialPair)
    UG__CCpair = aliased(UserGroup__ConnectorCredentialPair)
    User__UG = aliased(User__UserGroup)

    """
    Here we select documents by relation:
    User -> User__UserGroup -> UserGroup__ConnectorCredentialPair ->
    ConnectorCredentialPair -> DocumentByConnectorCredentialPair -> Document
    """
    stmt = (
        stmt.outerjoin(DocByCC, DocByCC.id == DbDocument.id)
        .outerjoin(
            CCPair,
            and_(
                CCPair.connector_id == DocByCC.connector_id,
                CCPair.credential_id == DocByCC.credential_id,
            ),
        )
        .outerjoin(UG__CCpair, UG__CCpair.cc_pair_id == CCPair.id)
        .outerjoin(User__UG, User__UG.user_group_id == UG__CCpair.user_group_id)
    )

    """
    Filter Documents by:
    - if the user is in the user_group that owns the object
    - if the user is not a global_curator, they must also have a curator relationship
    to the user_group
    - if editing is being done, we also filter out objects that are owned by groups
    that the user isn't a curator for
    - if we are not editing, we show all objects in the groups the user is a curator
    for (as well as public objects as well)
    """

    # If user is None, this is an anonymous user and we should only show public documents
    if user is None:
        where_clause = CCPair.access_type == AccessType.PUBLIC
        return stmt.where(where_clause)

    where_clause = User__UG.user_id == user.id
    if user.role == UserRole.CURATOR and get_editable:
        where_clause &= User__UG.is_curator == True  # noqa: E712
    if get_editable:
        user_groups = select(User__UG.user_group_id).where(User__UG.user_id == user.id)
        where_clause &= (
            ~exists()
            .where(UG__CCpair.cc_pair_id == CCPair.id)
            .where(~UG__CCpair.user_group_id.in_(user_groups))
            .correlate(CCPair)
        )
    else:
        where_clause |= CCPair.access_type == AccessType.PUBLIC

    return stmt.where(where_clause)


def fetch_docs_ranked_by_boost_for_user(
    db_session: Session,
    user: User | None,
    ascending: bool = False,
    limit: int = 100,
) -> list[DbDocument]:
    order_func = asc if ascending else desc
    stmt = select(DbDocument)

    stmt = _add_user_filters(stmt=stmt, user=user, get_editable=False)

    stmt = stmt.order_by(
        order_func(DbDocument.boost), order_func(DbDocument.semantic_id)
    )
    stmt = stmt.limit(limit)
    result = db_session.execute(stmt)
    doc_list = result.scalars().all()

    return list(doc_list)


def update_document_boost_for_user(
    db_session: Session,
    document_id: str,
    boost: int,
    user: User | None,
) -> None:
    stmt = select(DbDocument).where(DbDocument.id == document_id)
    stmt = _add_user_filters(stmt, user, get_editable=True)
    result: DbDocument | None = db_session.execute(stmt).scalar_one_or_none()
    if result is None:
        raise HTTPException(
            status_code=400, detail="Document is not editable by this user"
        )

    result.boost = boost

    # updating last_modified triggers sync
    # TODO: Should this submit to the queue directly so that the UI can update?
    result.last_modified = datetime.now(timezone.utc)
    db_session.commit()


def update_document_hidden_for_user(
    db_session: Session,
    document_id: str,
    hidden: bool,
    user: User | None,
) -> None:
    stmt = select(DbDocument).where(DbDocument.id == document_id)
    stmt = _add_user_filters(stmt, user, get_editable=True)
    result = db_session.execute(stmt).scalar_one_or_none()
    if result is None:
        raise HTTPException(
            status_code=400, detail="Document is not editable by this user"
        )

    result.hidden = hidden

    # updating last_modified triggers sync
    # TODO: Should this submit to the queue directly so that the UI can update?
    result.last_modified = datetime.now(timezone.utc)
    db_session.commit()


def create_doc_retrieval_feedback(
    message_id: int,
    document_id: str,
    document_rank: int,
    db_session: Session,
    clicked: bool = False,
    feedback: SearchFeedbackType | None = None,
) -> None:
    """Creates a new Document feedback row and updates the boost value in Postgres and Vespa"""
    db_doc = _fetch_db_doc_by_id(document_id, db_session)

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
        # updating last_modified triggers sync
        # TODO: Should this submit to the queue directly so that the UI can update?
        db_doc.last_modified = datetime.now(timezone.utc)

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
