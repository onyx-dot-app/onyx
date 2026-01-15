from collections.abc import Sequence
from datetime import datetime
from datetime import timedelta
from typing import Tuple
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete
from sqlalchemy import desc
from sqlalchemy import exists
from sqlalchemy import func
from sqlalchemy import nullsfirst
from sqlalchemy import or_
from sqlalchemy import Row
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.exc import MultipleResultsFound
from sqlalchemy.orm import selectinload
from sqlalchemy.orm import Session

from onyx.chat.models import DocumentRelevance
from onyx.configs.chat_configs import HARD_DELETE_CHATS
from onyx.configs.constants import MessageType
from onyx.context.search.models import InferenceSection
from onyx.context.search.models import SavedSearchDoc
from onyx.context.search.models import SearchDoc as ServerSearchDoc
from onyx.db.models import ChatMessage
from onyx.db.models import ChatMessage__SearchDoc
from onyx.db.models import ChatSession
from onyx.db.models import ChatSessionSharedStatus
from onyx.db.models import SearchDoc as DBSearchDoc
from onyx.db.models import ToolCall
from onyx.db.models import User
from onyx.db.persona import get_best_persona_id_for_user
from onyx.file_store.file_store import get_default_file_store
from onyx.file_store.models import FileDescriptor
from onyx.llm.override_models import LLMOverride
from onyx.llm.override_models import PromptOverride
from onyx.server.query_and_chat.models import ChatMessageDetail
from onyx.utils.logger import setup_logger


logger = setup_logger()


# Note: search/streaming packet helpers moved to streaming_utils.py


def get_chat_session_by_id(
    chat_session_id: UUID,
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


def get_chat_sessions_by_slack_thread_id(
    slack_thread_id: str,
    user_id: UUID | None,
    db_session: Session,
) -> Sequence[ChatSession]:
    stmt = select(ChatSession).where(ChatSession.slack_thread_id == slack_thread_id)
    if user_id is not None:
        stmt = stmt.where(
            or_(ChatSession.user_id == user_id, ChatSession.user_id.is_(None))
        )
    return db_session.scalars(stmt).all()


def get_valid_messages_from_query_sessions(
    chat_session_ids: list[UUID],
    db_session: Session,
) -> dict[UUID, str]:
    user_message_subquery = (
        select(
            ChatMessage.chat_session_id, func.min(ChatMessage.id).label("user_msg_id")
        )
        .where(
            ChatMessage.chat_session_id.in_(chat_session_ids),
            ChatMessage.message_type == MessageType.USER,
        )
        .group_by(ChatMessage.chat_session_id)
        .subquery()
    )

    assistant_message_subquery = (
        select(
            ChatMessage.chat_session_id,
            func.min(ChatMessage.id).label("assistant_msg_id"),
        )
        .where(
            ChatMessage.chat_session_id.in_(chat_session_ids),
            ChatMessage.message_type == MessageType.ASSISTANT,
        )
        .group_by(ChatMessage.chat_session_id)
        .subquery()
    )

    query = (
        select(ChatMessage.chat_session_id, ChatMessage.message)
        .join(
            user_message_subquery,
            ChatMessage.chat_session_id == user_message_subquery.c.chat_session_id,
        )
        .join(
            assistant_message_subquery,
            ChatMessage.chat_session_id == assistant_message_subquery.c.chat_session_id,
        )
        .join(
            ChatMessage__SearchDoc,
            ChatMessage__SearchDoc.chat_message_id
            == assistant_message_subquery.c.assistant_msg_id,
        )
        .where(ChatMessage.id == user_message_subquery.c.user_msg_id)
    )

    first_messages = db_session.execute(query).all()
    logger.info(f"Retrieved {len(first_messages)} first messages with documents")

    return {row.chat_session_id: row.message for row in first_messages}


# Retrieves chat sessions by user
# Chat sessions do not include onyxbot flows
def get_chat_sessions_by_user(
    user_id: UUID | None,
    deleted: bool | None,
    db_session: Session,
    include_onyxbot_flows: bool = False,
    limit: int = 50,
    project_id: int | None = None,
    only_non_project_chats: bool = False,
    include_failed_chats: bool = False,
) -> list[ChatSession]:
    stmt = select(ChatSession).where(ChatSession.user_id == user_id)

    if not include_onyxbot_flows:
        stmt = stmt.where(ChatSession.onyxbot_flow.is_(False))

    stmt = stmt.order_by(desc(ChatSession.time_updated))

    if deleted is not None:
        stmt = stmt.where(ChatSession.deleted == deleted)

    if limit:
        stmt = stmt.limit(limit)

    if project_id is not None:
        stmt = stmt.where(ChatSession.project_id == project_id)
    elif only_non_project_chats:
        stmt = stmt.where(ChatSession.project_id.is_(None))

    if not include_failed_chats:
        non_system_message_exists_subq = (
            exists()
            .where(ChatMessage.chat_session_id == ChatSession.id)
            .where(ChatMessage.message_type != MessageType.SYSTEM)
            .correlate(ChatSession)
        )

        stmt = stmt.where(non_system_message_exists_subq)

    result = db_session.execute(stmt)
    chat_sessions = result.scalars().all()

    return list(chat_sessions)


def delete_orphaned_search_docs(db_session: Session) -> None:
    orphaned_docs = (
        db_session.query(DBSearchDoc)
        .outerjoin(ChatMessage__SearchDoc)
        .filter(ChatMessage__SearchDoc.chat_message_id.is_(None))
        .all()
    )
    for doc in orphaned_docs:
        db_session.delete(doc)
    db_session.commit()


def delete_messages_and_files_from_chat_session(
    chat_session_id: UUID, db_session: Session
) -> None:
    # Select messages older than cutoff_time with files
    messages_with_files = db_session.execute(
        select(ChatMessage.id, ChatMessage.files).where(
            ChatMessage.chat_session_id == chat_session_id,
        )
    ).fetchall()

    for _, files in messages_with_files:
        file_store = get_default_file_store()
        for file_info in files or []:
            file_store.delete_file(file_id=file_info.get("id"))

    # Delete ChatMessage records - CASCADE constraints will automatically handle:
    # - ChatMessage__StandardAnswer relationship records
    db_session.execute(
        delete(ChatMessage).where(ChatMessage.chat_session_id == chat_session_id)
    )
    db_session.commit()

    delete_orphaned_search_docs(db_session)


def create_chat_session(
    db_session: Session,
    description: str | None,
    user_id: UUID | None,
    persona_id: int | None,  # Can be none if temporary persona is used
    llm_override: LLMOverride | None = None,
    prompt_override: PromptOverride | None = None,
    onyxbot_flow: bool = False,
    slack_thread_id: str | None = None,
    project_id: int | None = None,
) -> ChatSession:
    chat_session = ChatSession(
        user_id=user_id,
        persona_id=persona_id,
        description=description,
        llm_override=llm_override,
        prompt_override=prompt_override,
        onyxbot_flow=onyxbot_flow,
        slack_thread_id=slack_thread_id,
        project_id=project_id,
    )

    db_session.add(chat_session)
    db_session.commit()

    return chat_session


def duplicate_chat_session_for_user_from_slack(
    db_session: Session,
    user: User | None,
    chat_session_id: UUID,
) -> ChatSession:
    """
    This takes a chat session id for a session in Slack and:
    - Creates a new chat session in the DB
    - Tries to copy the persona from the original chat session
        (if it is available to the user clicking the button)
    - Sets the user to the given user (if provided)
    """
    chat_session = get_chat_session_by_id(
        chat_session_id=chat_session_id,
        user_id=None,  # Ignore user permissions for this
        db_session=db_session,
    )
    if not chat_session:
        raise HTTPException(status_code=400, detail="Invalid Chat Session ID provided")

    # This enforces permissions and sets a default
    new_persona_id = get_best_persona_id_for_user(
        db_session=db_session,
        user=user,
        persona_id=chat_session.persona_id,
    )

    return create_chat_session(
        db_session=db_session,
        user_id=user.id if user else None,
        persona_id=new_persona_id,
        # Set this to empty string so the frontend will force a rename
        description="",
        llm_override=chat_session.llm_override,
        prompt_override=chat_session.prompt_override,
        # Chat is in UI now so this is false
        onyxbot_flow=False,
        # Maybe we want this in the future to track if it was created from Slack
        slack_thread_id=None,
    )


def update_chat_session(
    db_session: Session,
    user_id: UUID | None,
    chat_session_id: UUID,
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


def delete_all_chat_sessions_for_user(
    user: User | None, db_session: Session, hard_delete: bool = HARD_DELETE_CHATS
) -> None:
    user_id = user.id if user is not None else None

    chat_sessions = (
        db_session.query(ChatSession)
        .filter(ChatSession.user_id == user_id, ChatSession.onyxbot_flow.is_(False))
        .all()
    )

    if hard_delete:
        for chat_session in chat_sessions:
            delete_messages_and_files_from_chat_session(chat_session.id, db_session)
        db_session.execute(
            delete(ChatSession).where(
                ChatSession.user_id == user_id, ChatSession.onyxbot_flow.is_(False)
            )
        )
    else:
        db_session.execute(
            update(ChatSession)
            .where(ChatSession.user_id == user_id, ChatSession.onyxbot_flow.is_(False))
            .values(deleted=True)
        )

    db_session.commit()


def delete_chat_session(
    user_id: UUID | None,
    chat_session_id: UUID,
    db_session: Session,
    include_deleted: bool = False,
    hard_delete: bool = HARD_DELETE_CHATS,
) -> None:
    chat_session = get_chat_session_by_id(
        chat_session_id=chat_session_id,
        user_id=user_id,
        db_session=db_session,
        include_deleted=include_deleted,
    )

    if chat_session.deleted and not include_deleted:
        raise ValueError("Cannot delete an already deleted chat session")

    if hard_delete:
        delete_messages_and_files_from_chat_session(chat_session_id, db_session)
        db_session.execute(delete(ChatSession).where(ChatSession.id == chat_session_id))
    else:
        chat_session = get_chat_session_by_id(
            chat_session_id=chat_session_id, user_id=user_id, db_session=db_session
        )
        chat_session.deleted = True

    db_session.commit()


def get_chat_sessions_older_than(
    days_old: int, db_session: Session
) -> list[tuple[UUID | None, UUID]]:
    """
    Retrieves chat sessions older than a specified number of days.

    Args:
        days_old: The number of days to consider as "old".
        db_session: The database session.

    Returns:
        A list of tuples, where each tuple contains the user_id (can be None) and the chat_session_id of an old chat session.
    """

    cutoff_time = datetime.utcnow() - timedelta(days=days_old)
    old_sessions: Sequence[Row[Tuple[UUID | None, UUID]]] = db_session.execute(
        select(ChatSession.user_id, ChatSession.id).where(
            ChatSession.time_created < cutoff_time
        )
    ).fetchall()

    # convert old_sessions to a conventional list of tuples
    returned_sessions: list[tuple[UUID | None, UUID]] = [
        (user_id, session_id) for user_id, session_id in old_sessions
    ]

    return returned_sessions


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


def get_chat_session_by_message_id(
    db_session: Session,
    message_id: int,
) -> ChatSession:
    """
    Should only be used for Slack
    Get the chat session associated with a specific message ID
    Note: this ignores permission checks.
    """
    stmt = select(ChatMessage).where(ChatMessage.id == message_id)

    result = db_session.execute(stmt)
    chat_message = result.scalar_one_or_none()

    if chat_message is None:
        raise ValueError(
            f"Unable to find chat session associated with message ID: {message_id}"
        )

    return chat_message.chat_session


def get_chat_messages_by_sessions(
    chat_session_ids: list[UUID],
    user_id: UUID | None,
    db_session: Session,
    skip_permission_check: bool = False,
) -> Sequence[ChatMessage]:
    if not skip_permission_check:
        for chat_session_id in chat_session_ids:
            get_chat_session_by_id(
                chat_session_id=chat_session_id, user_id=user_id, db_session=db_session
            )
    stmt = (
        select(ChatMessage)
        .where(ChatMessage.chat_session_id.in_(chat_session_ids))
        .order_by(nullsfirst(ChatMessage.parent_message_id))
    )
    return db_session.execute(stmt).scalars().all()


def add_chats_to_session_from_slack_thread(
    db_session: Session,
    slack_chat_session_id: UUID,
    new_chat_session_id: UUID,
) -> None:
    new_root_message = get_or_create_root_message(
        chat_session_id=new_chat_session_id,
        db_session=db_session,
    )

    for chat_message in get_chat_messages_by_sessions(
        chat_session_ids=[slack_chat_session_id],
        user_id=None,  # Ignore user permissions for this
        db_session=db_session,
        skip_permission_check=True,
    ):
        if chat_message.message_type == MessageType.SYSTEM:
            continue
        # Duplicate the message
        new_root_message = create_new_chat_message(
            db_session=db_session,
            chat_session_id=new_chat_session_id,
            parent_message=new_root_message,
            message=chat_message.message,
            files=chat_message.files,
            error=chat_message.error,
            token_count=chat_message.token_count,
            message_type=chat_message.message_type,
            reasoning_tokens=chat_message.reasoning_tokens,
        )


def get_search_docs_for_chat_message(
    chat_message_id: int, db_session: Session
) -> list[DBSearchDoc]:
    stmt = (
        select(DBSearchDoc)
        .join(
            ChatMessage__SearchDoc,
            ChatMessage__SearchDoc.search_doc_id == DBSearchDoc.id,
        )
        .where(ChatMessage__SearchDoc.chat_message_id == chat_message_id)
    )

    return list(db_session.scalars(stmt).all())


def add_search_docs_to_chat_message(
    chat_message_id: int, search_doc_ids: list[int], db_session: Session
) -> None:
    """
    Link SearchDocs to a ChatMessage by creating entries in the chat_message__search_doc junction table.

    Args:
        chat_message_id: The ID of the chat message
        search_doc_ids: List of search document IDs to link
        db_session: The database session
    """
    for search_doc_id in search_doc_ids:
        chat_message_search_doc = ChatMessage__SearchDoc(
            chat_message_id=chat_message_id, search_doc_id=search_doc_id
        )
        db_session.add(chat_message_search_doc)


def add_search_docs_to_tool_call(
    tool_call_id: int, search_doc_ids: list[int], db_session: Session
) -> None:
    """
    Link SearchDocs to a ToolCall by creating entries in the tool_call__search_doc junction table.

    Args:
        tool_call_id: The ID of the tool call
        search_doc_ids: List of search document IDs to link
        db_session: The database session
    """
    from onyx.db.models import ToolCall__SearchDoc

    for search_doc_id in search_doc_ids:
        tool_call_search_doc = ToolCall__SearchDoc(
            tool_call_id=tool_call_id, search_doc_id=search_doc_id
        )
        db_session.add(tool_call_search_doc)


def get_chat_messages_by_session(
    chat_session_id: UUID,
    user_id: UUID | None,
    db_session: Session,
    skip_permission_check: bool = False,
    prefetch_top_two_level_tool_calls: bool = True,
) -> list[ChatMessage]:
    if not skip_permission_check:
        # bug if we ever call this expecting the permission check to not be skipped
        get_chat_session_by_id(
            chat_session_id=chat_session_id, user_id=user_id, db_session=db_session
        )

    stmt = (
        select(ChatMessage)
        .where(ChatMessage.chat_session_id == chat_session_id)
        .order_by(nullsfirst(ChatMessage.parent_message_id))
    )

    # This should handle both the top level tool calls and deep research
    # If there are future nested agents, this can be extended.
    if prefetch_top_two_level_tool_calls:
        # Load tool_calls and their direct children (one level deep)
        stmt = stmt.options(
            selectinload(ChatMessage.tool_calls).selectinload(
                ToolCall.tool_call_children
            )
        )
        result = db_session.scalars(stmt).unique().all()
    else:
        result = db_session.scalars(stmt).all()

    return list(result)


def get_or_create_root_message(
    chat_session_id: UUID,
    db_session: Session,
) -> ChatMessage:
    try:
        root_message: ChatMessage | None = (
            db_session.query(ChatMessage)
            .filter(
                ChatMessage.chat_session_id == chat_session_id,
                ChatMessage.parent_message_id.is_(None),
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
            parent_message_id=None,
            latest_child_message_id=None,
            message="",
            token_count=0,
            message_type=MessageType.SYSTEM,
        )
        db_session.add(new_root_message)
        db_session.commit()
        return new_root_message


def reserve_message_id(
    db_session: Session,
    chat_session_id: UUID,
    parent_message: int,
    message_type: MessageType = MessageType.ASSISTANT,
) -> ChatMessage:
    # Create an temporary holding chat message to the updated and saved at the end
    empty_message = ChatMessage(
        chat_session_id=chat_session_id,
        parent_message_id=parent_message,
        latest_child_message_id=None,
        message="Response was terminated prior to completion, try regenerating.",
        token_count=15,
        message_type=message_type,
    )

    # Add the empty message to the session
    db_session.add(empty_message)
    db_session.flush()

    # Get the parent message and set its child pointer to the current message
    parent_chat_message = (
        db_session.query(ChatMessage).filter(ChatMessage.id == parent_message).first()
    )
    if parent_chat_message:
        parent_chat_message.latest_child_message_id = empty_message.id

    # Committing because it's ok to recover this state. More clear to the user than it is now.
    # Ideally there's a special UI for a case like this with a regenerate button but not needed for now.
    db_session.commit()

    return empty_message


def create_new_chat_message(
    chat_session_id: UUID,
    parent_message: ChatMessage,
    message: str,
    token_count: int,
    message_type: MessageType,
    db_session: Session,
    files: list[FileDescriptor] | None = None,
    error: str | None = None,
    commit: bool = True,
    reserved_message_id: int | None = None,
    reasoning_tokens: str | None = None,
) -> ChatMessage:
    if reserved_message_id is not None:
        # Edit existing message
        existing_message = db_session.query(ChatMessage).get(reserved_message_id)
        if existing_message is None:
            raise ValueError(f"No message found with id {reserved_message_id}")

        existing_message.chat_session_id = chat_session_id
        existing_message.parent_message_id = parent_message.id
        existing_message.message = message
        existing_message.token_count = token_count
        existing_message.message_type = message_type
        existing_message.files = files
        existing_message.error = error
        existing_message.reasoning_tokens = reasoning_tokens
        new_chat_message = existing_message
    else:
        # Create new message
        new_chat_message = ChatMessage(
            chat_session_id=chat_session_id,
            parent_message_id=parent_message.id,
            latest_child_message_id=None,
            message=message,
            token_count=token_count,
            message_type=message_type,
            files=files,
            error=error,
            reasoning_tokens=reasoning_tokens,
        )
        db_session.add(new_chat_message)

    # Flush the session to get an ID for the new chat message
    db_session.flush()

    parent_message.latest_child_message_id = new_chat_message.id
    if commit:
        db_session.commit()

    return new_chat_message


def set_as_latest_chat_message(
    chat_message: ChatMessage,
    user_id: UUID | None,
    db_session: Session,
) -> None:
    parent_message_id = chat_message.parent_message_id

    if parent_message_id is None:
        raise RuntimeError(
            f"Trying to set a latest message without parent, message id: {chat_message.id}"
        )

    parent_message = get_chat_message(
        chat_message_id=parent_message_id, user_id=user_id, db_session=db_session
    )

    parent_message.latest_child_message_id = chat_message.id

    db_session.commit()


def update_search_docs_table_with_relevance(
    db_session: Session,
    reference_db_search_docs: list[DBSearchDoc],
    relevance_summary: DocumentRelevance,
) -> None:
    for search_doc in reference_db_search_docs:
        relevance_data = relevance_summary.relevance_summaries.get(
            search_doc.document_id
        )
        if relevance_data is not None:
            db_session.execute(
                update(DBSearchDoc)
                .where(DBSearchDoc.id == search_doc.id)
                .values(
                    is_relevant=relevance_data.relevant,
                    relevance_explanation=relevance_data.content,
                )
            )
    db_session.commit()


def _sanitize_for_postgres(value: str) -> str:
    """Remove NUL (0x00) characters from strings as PostgreSQL doesn't allow them."""
    sanitized = value.replace("\x00", "")
    if value and not sanitized:
        logger.warning("Sanitization removed all characters from string")
    return sanitized


def _sanitize_list_for_postgres(values: list[str]) -> list[str]:
    """Remove NUL (0x00) characters from all strings in a list."""
    return [_sanitize_for_postgres(v) for v in values]


def create_db_search_doc(
    server_search_doc: ServerSearchDoc,
    db_session: Session,
    commit: bool = True,
) -> DBSearchDoc:
    # Sanitize string fields to remove NUL characters (PostgreSQL doesn't allow them)
    db_search_doc = DBSearchDoc(
        document_id=_sanitize_for_postgres(server_search_doc.document_id),
        chunk_ind=server_search_doc.chunk_ind,
        semantic_id=_sanitize_for_postgres(server_search_doc.semantic_identifier),
        link=(
            _sanitize_for_postgres(server_search_doc.link)
            if server_search_doc.link is not None
            else None
        ),
        blurb=_sanitize_for_postgres(server_search_doc.blurb),
        source_type=server_search_doc.source_type,
        boost=server_search_doc.boost,
        hidden=server_search_doc.hidden,
        doc_metadata=server_search_doc.metadata,
        is_relevant=server_search_doc.is_relevant,
        relevance_explanation=(
            _sanitize_for_postgres(server_search_doc.relevance_explanation)
            if server_search_doc.relevance_explanation is not None
            else None
        ),
        # For docs further down that aren't reranked, we can't use the retrieval score
        score=server_search_doc.score or 0.0,
        match_highlights=_sanitize_list_for_postgres(
            server_search_doc.match_highlights
        ),
        updated_at=server_search_doc.updated_at,
        primary_owners=(
            _sanitize_list_for_postgres(server_search_doc.primary_owners)
            if server_search_doc.primary_owners is not None
            else None
        ),
        secondary_owners=(
            _sanitize_list_for_postgres(server_search_doc.secondary_owners)
            if server_search_doc.secondary_owners is not None
            else None
        ),
        is_internet=server_search_doc.is_internet,
    )

    db_session.add(db_search_doc)
    if commit:
        db_session.commit()
    else:
        db_session.flush()
    return db_search_doc


def get_db_search_doc_by_id(doc_id: int, db_session: Session) -> DBSearchDoc | None:
    """There are no safety checks here like user permission etc., use with caution"""
    search_doc = db_session.query(DBSearchDoc).filter(DBSearchDoc.id == doc_id).first()
    return search_doc


def get_db_search_doc_by_document_id(
    document_id: str, db_session: Session
) -> DBSearchDoc | None:
    """Get SearchDoc by document_id field. There are no safety checks here like user permission etc., use with caution"""
    search_doc = (
        db_session.query(DBSearchDoc)
        .filter(DBSearchDoc.document_id == document_id)
        .first()
    )
    return search_doc


def translate_db_search_doc_to_saved_search_doc(
    db_search_doc: DBSearchDoc,
    remove_doc_content: bool = False,
) -> SavedSearchDoc:
    return SavedSearchDoc(
        db_doc_id=db_search_doc.id,
        score=db_search_doc.score,
        document_id=db_search_doc.document_id,
        chunk_ind=db_search_doc.chunk_ind,
        semantic_identifier=db_search_doc.semantic_id,
        link=db_search_doc.link,
        blurb=db_search_doc.blurb if not remove_doc_content else "",
        source_type=db_search_doc.source_type,
        boost=db_search_doc.boost,
        hidden=db_search_doc.hidden,
        metadata=db_search_doc.doc_metadata if not remove_doc_content else {},
        match_highlights=(
            db_search_doc.match_highlights if not remove_doc_content else []
        ),
        relevance_explanation=db_search_doc.relevance_explanation,
        is_relevant=db_search_doc.is_relevant,
        updated_at=db_search_doc.updated_at if not remove_doc_content else None,
        primary_owners=db_search_doc.primary_owners if not remove_doc_content else [],
        secondary_owners=(
            db_search_doc.secondary_owners if not remove_doc_content else []
        ),
        is_internet=db_search_doc.is_internet,
    )


def translate_db_message_to_chat_message_detail(
    chat_message: ChatMessage,
    remove_doc_content: bool = False,
) -> ChatMessageDetail:
    # Get current feedback if any
    current_feedback = None
    if chat_message.chat_message_feedbacks:
        latest_feedback = chat_message.chat_message_feedbacks[-1]
        if latest_feedback.is_positive is not None:
            current_feedback = "like" if latest_feedback.is_positive else "dislike"

    # Convert citations from {citation_num: db_doc_id} to {citation_num: document_id}
    converted_citations = None
    if chat_message.citations and chat_message.search_docs:
        # Build lookup map: db_doc_id -> document_id
        db_doc_id_to_document_id = {
            doc.id: doc.document_id for doc in chat_message.search_docs
        }

        converted_citations = {}
        for citation_num, db_doc_id in chat_message.citations.items():
            document_id = db_doc_id_to_document_id.get(db_doc_id)
            if document_id:
                converted_citations[citation_num] = document_id

    top_documents = [
        translate_db_search_doc_to_saved_search_doc(
            db_doc, remove_doc_content=remove_doc_content
        )
        for db_doc in chat_message.search_docs
    ]
    top_documents = sorted(
        top_documents, key=lambda doc: (doc.score or 0.0), reverse=True
    )
    chat_msg_detail = ChatMessageDetail(
        chat_session_id=chat_message.chat_session_id,
        message_id=chat_message.id,
        parent_message=chat_message.parent_message_id,
        latest_child_message=chat_message.latest_child_message_id,
        message=chat_message.message,
        reasoning_tokens=chat_message.reasoning_tokens,
        message_type=chat_message.message_type,
        context_docs=top_documents,
        citations=converted_citations,
        time_sent=chat_message.time_sent,
        files=chat_message.files or [],
        error=chat_message.error,
        current_feedback=current_feedback,
    )

    return chat_msg_detail


def update_chat_session_updated_at_timestamp(
    chat_session_id: UUID, db_session: Session
) -> None:
    """
    Explicitly update the timestamp on a chat session without modifying other fields.
    This is useful when adding messages to a chat session to reflect recent activity.
    """

    # Direct SQL update to avoid loading the entire object if it's not already loaded
    db_session.execute(
        update(ChatSession)
        .where(ChatSession.id == chat_session_id)
        .values(time_updated=func.now())
    )
    # No commit - the caller is responsible for committing the transaction


def create_search_doc_from_inference_section(
    inference_section: InferenceSection,
    is_internet: bool,
    db_session: Session,
    score: float = 0.0,
    is_relevant: bool | None = None,
    relevance_explanation: str | None = None,
    commit: bool = False,
) -> DBSearchDoc:
    """Create a SearchDoc in the database from an InferenceSection."""

    db_search_doc = DBSearchDoc(
        document_id=inference_section.center_chunk.document_id,
        chunk_ind=inference_section.center_chunk.chunk_id,
        semantic_id=inference_section.center_chunk.semantic_identifier,
        link=(
            inference_section.center_chunk.source_links.get(0)
            if inference_section.center_chunk.source_links
            else None
        ),
        blurb=inference_section.center_chunk.blurb,
        source_type=inference_section.center_chunk.source_type,
        boost=inference_section.center_chunk.boost,
        hidden=inference_section.center_chunk.hidden,
        doc_metadata=inference_section.center_chunk.metadata,
        score=score,
        is_relevant=is_relevant,
        relevance_explanation=relevance_explanation,
        match_highlights=inference_section.center_chunk.match_highlights,
        updated_at=inference_section.center_chunk.updated_at,
        primary_owners=inference_section.center_chunk.primary_owners or [],
        secondary_owners=inference_section.center_chunk.secondary_owners or [],
        is_internet=is_internet,
    )

    db_session.add(db_search_doc)
    if commit:
        db_session.commit()
    else:
        db_session.flush()

    return db_search_doc


def create_search_doc_from_saved_search_doc(
    saved_search_doc: SavedSearchDoc,
) -> DBSearchDoc:
    """Convert SavedSearchDoc (server model) into DB SearchDoc with correct field mapping."""
    return DBSearchDoc(
        document_id=saved_search_doc.document_id,
        chunk_ind=saved_search_doc.chunk_ind,
        # Map Pydantic semantic_identifier -> DB semantic_id; ensure non-null
        semantic_id=saved_search_doc.semantic_identifier or "Unknown",
        link=saved_search_doc.link,
        blurb=saved_search_doc.blurb,
        source_type=saved_search_doc.source_type,
        boost=saved_search_doc.boost,
        hidden=saved_search_doc.hidden,
        # Map metadata -> doc_metadata (DB column name)
        doc_metadata=saved_search_doc.metadata,
        # SavedSearchDoc.score exists and defaults to 0.0
        score=saved_search_doc.score or 0.0,
        match_highlights=saved_search_doc.match_highlights,
        updated_at=saved_search_doc.updated_at,
        primary_owners=saved_search_doc.primary_owners,
        secondary_owners=saved_search_doc.secondary_owners,
        is_internet=saved_search_doc.is_internet,
        is_relevant=saved_search_doc.is_relevant,
        relevance_explanation=saved_search_doc.relevance_explanation,
    )


def update_db_session_with_messages(
    db_session: Session,
    chat_message_id: int,
    chat_session_id: UUID,
    message: str | None = None,
    message_type: str | None = None,
    token_count: int | None = None,
    error: str | None = None,
    update_parent_message: bool = True,
    files: list[FileDescriptor] | None = None,
    reasoning_tokens: str | None = None,
    commit: bool = False,
) -> ChatMessage:
    chat_message = (
        db_session.query(ChatMessage)
        .filter(
            ChatMessage.id == chat_message_id,
            ChatMessage.chat_session_id == chat_session_id,
        )
        .first()
    )
    if not chat_message:
        raise ValueError("Chat message with id not found")  # should never happen

    if message:
        chat_message.message = message
    if message_type:
        chat_message.message_type = MessageType(message_type)
    if token_count:
        chat_message.token_count = token_count
    if error:
        chat_message.error = error
    if files is not None:
        chat_message.files = files
    if reasoning_tokens is not None:
        chat_message.reasoning_tokens = reasoning_tokens

    if update_parent_message:
        parent_chat_message = (
            db_session.query(ChatMessage)
            .filter(ChatMessage.id == chat_message.parent_message_id)
            .first()
        )
        if parent_chat_message:
            parent_chat_message.latest_child_message_id = chat_message.id

    if commit:
        db_session.commit()
    else:
        db_session.flush()

    return chat_message
