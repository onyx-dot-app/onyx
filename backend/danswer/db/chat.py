from uuid import UUID

from sqlalchemy import delete
from sqlalchemy import nullsfirst
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy.exc import MultipleResultsFound
from sqlalchemy.orm import Session

from danswer.auth.schemas import UserRole
from danswer.configs.chat_configs import HARD_DELETE_CHATS
from danswer.configs.constants import MessageType
from danswer.db.models import ChatMessage
from danswer.db.models import ChatSession
from danswer.db.models import ChatSessionSharedStatus
from danswer.db.models import Prompt
from danswer.db.models import SearchDoc
from danswer.db.models import SearchDoc as DBSearchDoc
from danswer.db.models import User
from danswer.file_store.models import FileDescriptor
from danswer.llm.override_models import LLMOverride
from danswer.llm.override_models import PromptOverride
from danswer.search.models import RetrievalDocs
from danswer.search.models import SavedSearchDoc
from danswer.search.models import SearchDoc as ServerSearchDoc
from danswer.server.query_and_chat.models import ChatMessageDetail
from danswer.utils.logger import setup_logger

logger = setup_logger()


def get_chat_session_by_id(
    chat_session_id: int,
    user_id: UUID | None,
    db_session: Session,
    include_deleted: bool = False,
    is_shared: bool = False,
) -> ChatSession:
    stmt = select(ChatSession).where(ChatSession.id == chat_session_id)

    if is_shared:
        stmt = stmt.where(ChatSession.shared_status == ChatSessionSharedStatus.PUBLIC)
    else:
        # if user_id is None, assume this is an admin who should be able
        # to view all chat sessions
        if user_id is not None:
            stmt = stmt.where(
                or_(ChatSession.user_id == user_id, ChatSession.user_id.is_(None))
            )

    result = db_session.execute(stmt)
    chat_session = result.scalar_one_or_none()

    if not chat_session:
        raise ValueError("Invalid Chat Session ID provided")

    if not include_deleted and chat_session.deleted:
        raise ValueError("Chat session has been deleted")

    return chat_session


def get_chat_sessions_by_user(
    user_id: UUID | None,
    deleted: bool | None,
    db_session: Session,
    include_one_shot: bool = False,
) -> list[ChatSession]:
    stmt = select(ChatSession).where(ChatSession.user_id == user_id)

    if not include_one_shot:
        stmt = stmt.where(ChatSession.one_shot.is_(False))

    if deleted is not None:
        stmt = stmt.where(ChatSession.deleted == deleted)

    result = db_session.execute(stmt)
    chat_sessions = result.scalars().all()

    return list(chat_sessions)


def create_chat_session(
    db_session: Session,
    description: str,
    user_id: UUID | None,
    persona_id: int | None = None,
    llm_override: LLMOverride | None = None,
    prompt_override: PromptOverride | None = None,
    one_shot: bool = False,
    danswerbot_flow: bool = False,
) -> ChatSession:
    chat_session = ChatSession(
        user_id=user_id,
        persona_id=persona_id,
        description=description,
        llm_override=llm_override,
        prompt_override=prompt_override,
        one_shot=one_shot,
        danswerbot_flow=danswerbot_flow,
    )

    db_session.add(chat_session)
    db_session.commit()

    return chat_session


def update_chat_session(
    db_session: Session,
    user_id: UUID | None,
    chat_session_id: int,
    description: str | None = None,
    sharing_status: ChatSessionSharedStatus | None = None,
) -> ChatSession:
    chat_session = get_chat_session_by_id(
        chat_session_id=chat_session_id, user_id=user_id, db_session=db_session
    )

    if chat_session.deleted:
        raise ValueError("Trying to rename a deleted chat session")

    if description is not None:
        chat_session.description = description
    if sharing_status is not None:
        chat_session.shared_status = sharing_status

    db_session.commit()

    return chat_session


def delete_chat_session(
    user_id: UUID | None,
    chat_session_id: int,
    db_session: Session,
    hard_delete: bool = HARD_DELETE_CHATS,
) -> None:
    chat_session = get_chat_session_by_id(
        chat_session_id=chat_session_id, user_id=user_id, db_session=db_session
    )

    if hard_delete:
        stmt_messages = delete(ChatMessage).where(
            ChatMessage.chat_session_id == chat_session_id
        )
        db_session.execute(stmt_messages)

        stmt = delete(ChatSession).where(ChatSession.id == chat_session_id)
        db_session.execute(stmt)

    else:
        chat_session.deleted = True

    db_session.commit()


def get_chat_message(
    chat_message_id: int,
    user_id: UUID | None,
    db_session: Session,
) -> ChatMessage:
    stmt = select(ChatMessage).where(ChatMessage.id == chat_message_id)

    result = db_session.execute(stmt)
    chat_message = result.scalar_one_or_none()

    if not chat_message:
        raise ValueError("Invalid Chat Message specified")

    chat_user = chat_message.chat_session.user
    expected_user_id = chat_user.id if chat_user is not None else None

    if expected_user_id != user_id:
        logger.error(
            f"User {user_id} tried to fetch a chat message that does not belong to them"
        )
        raise ValueError("Chat message does not belong to user")

    return chat_message


def get_chat_messages_by_session(
    chat_session_id: int,
    user_id: UUID | None,
    db_session: Session,
    skip_permission_check: bool = False,
) -> list[ChatMessage]:
    if not skip_permission_check:
        get_chat_session_by_id(
            chat_session_id=chat_session_id, user_id=user_id, db_session=db_session
        )

    stmt = (
        select(ChatMessage).where(ChatMessage.chat_session_id == chat_session_id)
        # Start with the root message which has no parent
        .order_by(nullsfirst(ChatMessage.parent_message))
    )

    result = db_session.execute(stmt).scalars().all()

    return list(result)


def get_or_create_root_message(
    chat_session_id: int,
    db_session: Session,
) -> ChatMessage:
    try:
        root_message: ChatMessage | None = (
            db_session.query(ChatMessage)
            .filter(
                ChatMessage.chat_session_id == chat_session_id,
                ChatMessage.parent_message.is_(None),
            )
            .one_or_none()
        )
    except MultipleResultsFound:
        raise Exception(
            "Multiple root messages found for chat session. Data inconsistency detected."
        )

    if root_message is not None:
        return root_message
    else:
        new_root_message = ChatMessage(
            chat_session_id=chat_session_id,
            prompt_id=None,
            parent_message=None,
            latest_child_message=None,
            message="",
            token_count=0,
            message_type=MessageType.SYSTEM,
        )
        db_session.add(new_root_message)
        db_session.commit()
        return new_root_message


def create_new_chat_message(
    chat_session_id: int,
    parent_message: ChatMessage,
    message: str,
    prompt_id: int | None,
    token_count: int,
    message_type: MessageType,
    db_session: Session,
    files: list[FileDescriptor] | None = None,
    rephrased_query: str | None = None,
    error: str | None = None,
    reference_docs: list[DBSearchDoc] | None = None,
    # Maps the citation number [n] to the DB SearchDoc
    citations: dict[int, int] | None = None,
    commit: bool = True,
) -> ChatMessage:
    new_chat_message = ChatMessage(
        chat_session_id=chat_session_id,
        parent_message=parent_message.id,
        latest_child_message=None,
        message=message,
        rephrased_query=rephrased_query,
        prompt_id=prompt_id,
        token_count=token_count,
        message_type=message_type,
        citations=citations,
        files=files,
        error=error,
    )

    # SQL Alchemy will propagate this to update the reference_docs' foreign keys
    if reference_docs:
        new_chat_message.search_docs = reference_docs

    db_session.add(new_chat_message)

    # Flush the session to get an ID for the new chat message
    db_session.flush()

    parent_message.latest_child_message = new_chat_message.id
    if commit:
        db_session.commit()

    return new_chat_message


def set_as_latest_chat_message(
    chat_message: ChatMessage,
    user_id: UUID | None,
    db_session: Session,
) -> None:
    parent_message_id = chat_message.parent_message

    if parent_message_id is None:
        raise RuntimeError(
            f"Trying to set a latest message without parent, message id: {chat_message.id}"
        )

    parent_message = get_chat_message(
        chat_message_id=parent_message_id, user_id=user_id, db_session=db_session
    )

    parent_message.latest_child_message = chat_message.id

    db_session.commit()


def attach_files_to_chat_message(
    chat_message: ChatMessage,
    files: list[FileDescriptor],
    db_session: Session,
    commit: bool = True,
) -> None:
    chat_message.files = files
    if commit:
        db_session.commit()


def get_prompt_by_id(
    prompt_id: int,
    user: User | None,
    db_session: Session,
    include_deleted: bool = False,
) -> Prompt:
    stmt = select(Prompt).where(Prompt.id == prompt_id)

    # if user is not specified OR they are an admin, they should
    # have access to all prompts, so this where clause is not needed
    if user and user.role != UserRole.ADMIN:
        stmt = stmt.where(or_(Prompt.user_id == user.id, Prompt.user_id.is_(None)))

    if not include_deleted:
        stmt = stmt.where(Prompt.deleted.is_(False))

    result = db_session.execute(stmt)
    prompt = result.scalar_one_or_none()

    if prompt is None:
        raise ValueError(
            f"Prompt with ID {prompt_id} does not exist or does not belong to user"
        )

    return prompt


def get_doc_query_identifiers_from_model(
    search_doc_ids: list[int],
    chat_session: ChatSession,
    user_id: UUID | None,
    db_session: Session,
) -> list[tuple[str, int]]:
    """Given a list of search_doc_ids"""
    search_docs = (
        db_session.query(SearchDoc).filter(SearchDoc.id.in_(search_doc_ids)).all()
    )

    if user_id != chat_session.user_id:
        logger.error(
            f"Docs referenced are from a chat session not belonging to user {user_id}"
        )
        raise ValueError("Docs references do not belong to user")

    if any(
        [doc.chat_messages[0].chat_session_id != chat_session.id for doc in search_docs]
    ):
        raise ValueError("Invalid reference doc, not from this chat session.")

    doc_query_identifiers = [(doc.document_id, doc.chunk_ind) for doc in search_docs]

    return doc_query_identifiers


def create_db_search_doc(
    server_search_doc: ServerSearchDoc,
    db_session: Session,
) -> SearchDoc:
    db_search_doc = SearchDoc(
        document_id=server_search_doc.document_id,
        chunk_ind=server_search_doc.chunk_ind,
        semantic_id=server_search_doc.semantic_identifier,
        link=server_search_doc.link,
        blurb=server_search_doc.blurb,
        source_type=server_search_doc.source_type,
        boost=server_search_doc.boost,
        hidden=server_search_doc.hidden,
        doc_metadata=server_search_doc.metadata,
        # For docs further down that aren't reranked, we can't use the retrieval score
        score=server_search_doc.score or 0.0,
        match_highlights=server_search_doc.match_highlights,
        updated_at=server_search_doc.updated_at,
        primary_owners=server_search_doc.primary_owners,
        secondary_owners=server_search_doc.secondary_owners,
    )

    db_session.add(db_search_doc)
    db_session.commit()

    return db_search_doc


def get_db_search_doc_by_id(doc_id: int, db_session: Session) -> DBSearchDoc | None:
    """There are no safety checks here like user permission etc., use with caution"""
    search_doc = db_session.query(SearchDoc).filter(SearchDoc.id == doc_id).first()
    return search_doc


def translate_db_search_doc_to_server_search_doc(
    db_search_doc: SearchDoc,
    remove_doc_content: bool = False,
) -> SavedSearchDoc:
    return SavedSearchDoc(
        db_doc_id=db_search_doc.id,
        document_id=db_search_doc.document_id,
        chunk_ind=db_search_doc.chunk_ind,
        semantic_identifier=db_search_doc.semantic_id,
        link=db_search_doc.link,
        blurb=db_search_doc.blurb if not remove_doc_content else "",
        source_type=db_search_doc.source_type,
        boost=db_search_doc.boost,
        hidden=db_search_doc.hidden,
        metadata=db_search_doc.doc_metadata if not remove_doc_content else {},
        score=db_search_doc.score,
        match_highlights=db_search_doc.match_highlights
        if not remove_doc_content
        else [],
        updated_at=db_search_doc.updated_at if not remove_doc_content else None,
        primary_owners=db_search_doc.primary_owners if not remove_doc_content else [],
        secondary_owners=db_search_doc.secondary_owners
        if not remove_doc_content
        else [],
    )


def get_retrieval_docs_from_chat_message(
    chat_message: ChatMessage, remove_doc_content: bool = False
) -> RetrievalDocs:
    top_documents = [
        translate_db_search_doc_to_server_search_doc(
            db_doc, remove_doc_content=remove_doc_content
        )
        for db_doc in chat_message.search_docs
    ]
    top_documents = sorted(top_documents, key=lambda doc: doc.score, reverse=True)  # type: ignore
    return RetrievalDocs(top_documents=top_documents)


def translate_db_message_to_chat_message_detail(
    chat_message: ChatMessage, remove_doc_content: bool = False
) -> ChatMessageDetail:
    chat_msg_detail = ChatMessageDetail(
        message_id=chat_message.id,
        parent_message=chat_message.parent_message,
        latest_child_message=chat_message.latest_child_message,
        message=chat_message.message,
        rephrased_query=chat_message.rephrased_query,
        context_docs=get_retrieval_docs_from_chat_message(
            chat_message, remove_doc_content=remove_doc_content
        ),
        message_type=chat_message.message_type,
        time_sent=chat_message.time_sent,
        citations=chat_message.citations,
        files=chat_message.files or [],
    )

    return chat_msg_detail
