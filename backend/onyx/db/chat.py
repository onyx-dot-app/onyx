from collections.abc import Sequence
from datetime import datetime
from datetime import timedelta
from typing import Any
from typing import cast
from typing import Tuple
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete
from sqlalchemy import desc
from sqlalchemy import func
from sqlalchemy import nullsfirst
from sqlalchemy import or_
from sqlalchemy import Row
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.exc import MultipleResultsFound
from sqlalchemy.orm import joinedload
from sqlalchemy.orm import Session

from onyx.agents.agent_search.dr.enums import ResearchAnswerPurpose
from onyx.agents.agent_search.dr.enums import ResearchType
from onyx.agents.agent_search.shared_graph_utils.models import CombinedAgentMetrics
from onyx.agents.agent_search.shared_graph_utils.models import (
    SubQuestionAnswerResults,
)
from onyx.agents.agent_search.utils import create_citation_format_list
from onyx.chat.models import DocumentRelevance
from onyx.configs.chat_configs import HARD_DELETE_CHATS
from onyx.configs.constants import MessageType
from onyx.context.search.models import InferenceSection
from onyx.context.search.models import RetrievalDocs
from onyx.context.search.models import SavedSearchDoc
from onyx.context.search.models import SearchDoc as ServerSearchDoc
from onyx.db.models import AgentSearchMetrics
from onyx.db.models import AgentSubQuery
from onyx.db.models import AgentSubQuestion
from onyx.db.models import ChatMessage
from onyx.db.models import ChatMessage__SearchDoc
from onyx.db.models import ChatSession
from onyx.db.models import ChatSessionSharedStatus
from onyx.db.models import ResearchAgentIteration
from onyx.db.models import SearchDoc
from onyx.db.models import SearchDoc as DBSearchDoc
from onyx.db.models import ToolCall
from onyx.db.models import User
from onyx.db.persona import get_best_persona_id_for_user
from onyx.file_store.file_store import get_default_file_store
from onyx.file_store.models import FileDescriptor
from onyx.llm.override_models import LLMOverride
from onyx.llm.override_models import PromptOverride
from onyx.server.query_and_chat.models import ChatMessageDetail
from onyx.server.query_and_chat.models import SubQueryDetail
from onyx.server.query_and_chat.models import SubQuestionDetail
from onyx.tools.models import ToolCallFinalResult
from onyx.utils.logger import setup_logger
from onyx.utils.special_types import JSON_ro


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

    result = db_session.execute(stmt)
    chat_sessions = result.scalars().all()

    return list(chat_sessions)


def delete_search_doc_message_relationship(
    message_id: int, db_session: Session
) -> None:
    db_session.query(ChatMessage__SearchDoc).filter(
        ChatMessage__SearchDoc.chat_message_id == message_id
    ).delete(synchronize_session=False)

    db_session.commit()


def delete_tool_call_for_message_id(message_id: int, db_session: Session) -> None:
    stmt = delete(ToolCall).where(ToolCall.message_id == message_id)
    db_session.execute(stmt)
    db_session.commit()


def delete_orphaned_search_docs(db_session: Session) -> None:
    orphaned_docs = (
        db_session.query(SearchDoc)
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

    for id, files in messages_with_files:
        delete_tool_call_for_message_id(message_id=id, db_session=db_session)
        delete_search_doc_message_relationship(message_id=id, db_session=db_session)

        file_store = get_default_file_store()
        for file_info in files or []:
            file_store.delete_file(file_id=file_info.get("id"))

    # Delete ChatMessage records - CASCADE constraints will automatically handle:
    # - AgentSubQuery records (via AgentSubQuestion)
    # - AgentSubQuestion records
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

    query = db_session.query(ChatSession).filter(
        ChatSession.user_id == user_id, ChatSession.onyxbot_flow.is_(False)
    )

    if hard_delete:
        query.delete(synchronize_session=False)
    else:
        query.update({ChatSession.deleted: True}, synchronize_session=False)

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
        .order_by(nullsfirst(ChatMessage.parent_message))
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
            rephrased_query=chat_message.rephrased_query,
            error=chat_message.error,
            citations=chat_message.citations,
            reference_docs=chat_message.search_docs,
            tool_call=chat_message.tool_call,
            token_count=chat_message.token_count,
            message_type=chat_message.message_type,
            alternate_assistant_id=chat_message.alternate_assistant_id,
            overridden_model=chat_message.overridden_model,
        )


def get_search_docs_for_chat_message(
    chat_message_id: int, db_session: Session
) -> list[SearchDoc]:
    stmt = (
        select(SearchDoc)
        .join(
            ChatMessage__SearchDoc, ChatMessage__SearchDoc.search_doc_id == SearchDoc.id
        )
        .where(ChatMessage__SearchDoc.chat_message_id == chat_message_id)
    )

    return list(db_session.scalars(stmt).all())


def get_chat_messages_by_session(
    chat_session_id: UUID,
    user_id: UUID | None,
    db_session: Session,
    skip_permission_check: bool = False,
    prefetch_tool_calls: bool = False,
) -> list[ChatMessage]:
    if not skip_permission_check:
        # bug if we ever call this expecting the permission check to not be skipped
        get_chat_session_by_id(
            chat_session_id=chat_session_id, user_id=user_id, db_session=db_session
        )

    stmt = (
        select(ChatMessage)
        .where(ChatMessage.chat_session_id == chat_session_id)
        .order_by(nullsfirst(ChatMessage.parent_message))
    )

    if prefetch_tool_calls:
        # stmt = stmt.options(
        #     joinedload(ChatMessage.tool_call),
        #     joinedload(ChatMessage.sub_questions).joinedload(
        #         AgentSubQuestion.sub_queries
        #     ),
        # )
        # result = db_session.scalars(stmt).unique().all()

        stmt = (
            select(ChatMessage)
            .where(ChatMessage.chat_session_id == chat_session_id)
            .order_by(nullsfirst(ChatMessage.parent_message))
        )
        stmt = stmt.options(
            joinedload(ChatMessage.research_iterations).joinedload(
                ResearchAgentIteration.sub_steps
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
            parent_message=None,
            latest_child_message=None,
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
    message_type: MessageType,
) -> int:
    # Create an empty chat message
    empty_message = ChatMessage(
        chat_session_id=chat_session_id,
        parent_message=parent_message,
        latest_child_message=None,
        message="",
        token_count=0,
        message_type=message_type,
    )

    # Add the empty message to the session
    db_session.add(empty_message)

    # Flush the session to get an ID for the new chat message
    db_session.flush()

    # Get the ID of the newly created message
    new_id = empty_message.id

    return new_id


def create_new_chat_message(
    chat_session_id: UUID,
    parent_message: ChatMessage,
    message: str,
    token_count: int,
    message_type: MessageType,
    db_session: Session,
    files: list[FileDescriptor] | None = None,
    rephrased_query: str | None = None,
    error: str | None = None,
    reference_docs: list[DBSearchDoc] | None = None,
    alternate_assistant_id: int | None = None,
    # Maps the citation number [n] to the DB SearchDoc
    citations: dict[int, int] | None = None,
    tool_call: ToolCall | None = None,
    commit: bool = True,
    reserved_message_id: int | None = None,
    overridden_model: str | None = None,
    is_agentic: bool = False,
    research_type: ResearchType | None = None,
    research_plan: dict[str, Any] | None = None,
) -> ChatMessage:
    if reserved_message_id is not None:
        # Edit existing message
        existing_message = db_session.query(ChatMessage).get(reserved_message_id)
        if existing_message is None:
            raise ValueError(f"No message found with id {reserved_message_id}")

        existing_message.chat_session_id = chat_session_id
        existing_message.parent_message = parent_message.id
        existing_message.message = message
        existing_message.rephrased_query = rephrased_query
        existing_message.token_count = token_count
        existing_message.message_type = message_type
        existing_message.citations = citations
        existing_message.files = files
        existing_message.tool_call = tool_call
        existing_message.error = error
        existing_message.alternate_assistant_id = alternate_assistant_id
        existing_message.overridden_model = overridden_model
        existing_message.is_agentic = is_agentic
        existing_message.research_type = research_type
        existing_message.research_plan = research_plan
        new_chat_message = existing_message
    else:
        # Create new message
        new_chat_message = ChatMessage(
            chat_session_id=chat_session_id,
            parent_message=parent_message.id,
            latest_child_message=None,
            message=message,
            rephrased_query=rephrased_query,
            token_count=token_count,
            message_type=message_type,
            citations=citations,
            files=files,
            tool_call=tool_call,
            error=error,
            alternate_assistant_id=alternate_assistant_id,
            overridden_model=overridden_model,
            is_agentic=is_agentic,
            research_type=research_type,
            research_plan=research_plan,
        )
        db_session.add(new_chat_message)

    # SQL Alchemy will propagate this to update the reference_docs' foreign keys
    if reference_docs:
        new_chat_message.search_docs = reference_docs

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


def get_doc_query_identifiers_from_model(
    search_doc_ids: list[int],
    chat_session: ChatSession,
    user_id: UUID | None,
    db_session: Session,
    enforce_chat_session_id_for_search_docs: bool,
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

    try:
        if any(
            [
                doc.chat_messages[0].chat_session_id != chat_session.id
                for doc in search_docs
            ]
        ):
            if enforce_chat_session_id_for_search_docs:
                raise ValueError("Invalid reference doc, not from this chat session.")
    except IndexError:
        # This happens when the doc has no chat_messages associated with it.
        # which happens as an edge case where the chat message failed to save
        # This usually happens when the LLM fails either immediately or partially through.
        raise RuntimeError("Chat session failed, please start a new session.")

    doc_query_identifiers = [(doc.document_id, doc.chunk_ind) for doc in search_docs]

    return doc_query_identifiers


def update_search_docs_table_with_relevance(
    db_session: Session,
    reference_db_search_docs: list[SearchDoc],
    relevance_summary: DocumentRelevance,
) -> None:
    for search_doc in reference_db_search_docs:
        relevance_data = relevance_summary.relevance_summaries.get(
            search_doc.document_id
        )
        if relevance_data is not None:
            db_session.execute(
                update(SearchDoc)
                .where(SearchDoc.id == search_doc.id)
                .values(
                    is_relevant=relevance_data.relevant,
                    relevance_explanation=relevance_data.content,
                )
            )
    db_session.commit()


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
        is_relevant=server_search_doc.is_relevant,
        relevance_explanation=server_search_doc.relevance_explanation,
        # For docs further down that aren't reranked, we can't use the retrieval score
        score=server_search_doc.score or 0.0,
        match_highlights=server_search_doc.match_highlights,
        updated_at=server_search_doc.updated_at,
        primary_owners=server_search_doc.primary_owners,
        secondary_owners=server_search_doc.secondary_owners,
        is_internet=server_search_doc.is_internet,
    )

    db_session.add(db_search_doc)
    db_session.commit()
    return db_search_doc


def get_db_search_doc_by_id(doc_id: int, db_session: Session) -> DBSearchDoc | None:
    """There are no safety checks here like user permission etc., use with caution"""
    search_doc = db_session.query(SearchDoc).filter(SearchDoc.id == doc_id).first()
    return search_doc


def get_db_search_doc_by_document_id(
    document_id: str, db_session: Session
) -> DBSearchDoc | None:
    """Get SearchDoc by document_id field. There are no safety checks here like user permission etc., use with caution"""
    search_doc = (
        db_session.query(SearchDoc).filter(SearchDoc.document_id == document_id).first()
    )
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


def translate_db_sub_questions_to_server_objects(
    db_sub_questions: list[AgentSubQuestion],
) -> list[SubQuestionDetail]:
    sub_questions = []
    for sub_question in db_sub_questions:
        sub_queries = []
        docs: dict[str, SearchDoc] = {}
        doc_results = cast(
            list[dict[str, JSON_ro]], sub_question.sub_question_doc_results
        )
        verified_doc_ids = [x["document_id"] for x in doc_results]
        for sub_query in sub_question.sub_queries:
            doc_ids = [doc.id for doc in sub_query.search_docs]
            sub_queries.append(
                SubQueryDetail(
                    query=sub_query.sub_query,
                    query_id=sub_query.id,
                    doc_ids=doc_ids,
                )
            )
            for doc in sub_query.search_docs:
                docs[doc.document_id] = doc

        verified_docs = [
            docs[cast(str, doc_id)] for doc_id in verified_doc_ids if doc_id in docs
        ]

        sub_questions.append(
            SubQuestionDetail(
                level=sub_question.level,
                level_question_num=sub_question.level_question_num,
                question=sub_question.sub_question,
                answer=sub_question.sub_answer,
                sub_queries=sub_queries,
                context_docs=get_retrieval_docs_from_search_docs(
                    verified_docs, sort_by_score=False
                ),
            )
        )
    return sub_questions


def get_retrieval_docs_from_search_docs(
    search_docs: list[SearchDoc],
    remove_doc_content: bool = False,
    sort_by_score: bool = True,
) -> RetrievalDocs:
    top_documents = [
        translate_db_search_doc_to_server_search_doc(
            db_doc, remove_doc_content=remove_doc_content
        )
        for db_doc in search_docs
    ]
    if sort_by_score:
        top_documents = sorted(top_documents, key=lambda doc: doc.score, reverse=True)  # type: ignore
    return RetrievalDocs(top_documents=top_documents)


# Note: translate_db_message_to_packets moved to onyx.server.query_and_chat.streaming_utils


def translate_db_message_to_chat_message_detail(
    chat_message: ChatMessage,
    remove_doc_content: bool = False,
) -> ChatMessageDetail:
    chat_msg_detail = ChatMessageDetail(
        chat_session_id=chat_message.chat_session_id,
        message_id=chat_message.id,
        parent_message=chat_message.parent_message,
        latest_child_message=chat_message.latest_child_message,
        message=chat_message.message,
        rephrased_query=chat_message.rephrased_query,
        context_docs=get_retrieval_docs_from_search_docs(
            chat_message.search_docs, remove_doc_content=remove_doc_content
        ),
        message_type=chat_message.message_type,
        research_type=chat_message.research_type,
        time_sent=chat_message.time_sent,
        citations=chat_message.citations,
        files=chat_message.files or [],
        tool_call=(
            ToolCallFinalResult(
                tool_name=chat_message.tool_call.tool_name,
                tool_args=chat_message.tool_call.tool_arguments,
                tool_result=chat_message.tool_call.tool_result,
            )
            if chat_message.tool_call
            else None
        ),
        alternate_assistant_id=chat_message.alternate_assistant_id,
        overridden_model=chat_message.overridden_model,
        error=chat_message.error,
    )

    return chat_msg_detail


def log_agent_metrics(
    db_session: Session,
    user_id: UUID | None,
    persona_id: int | None,  # Can be none if temporary persona is used
    agent_type: str,
    start_time: datetime | None,
    agent_metrics: CombinedAgentMetrics,
) -> AgentSearchMetrics:
    agent_timings = agent_metrics.timings
    agent_base_metrics = agent_metrics.base_metrics
    agent_refined_metrics = agent_metrics.refined_metrics
    agent_additional_metrics = agent_metrics.additional_metrics

    agent_metric_tracking = AgentSearchMetrics(
        user_id=user_id,
        persona_id=persona_id,
        agent_type=agent_type,
        start_time=start_time,
        base_duration_s=agent_timings.base_duration_s,
        full_duration_s=agent_timings.full_duration_s,
        base_metrics=vars(agent_base_metrics) if agent_base_metrics else None,
        refined_metrics=vars(agent_refined_metrics) if agent_refined_metrics else None,
        all_metrics=(
            vars(agent_additional_metrics) if agent_additional_metrics else None
        ),
    )

    db_session.add(agent_metric_tracking)
    db_session.flush()

    return agent_metric_tracking


def log_agent_sub_question_results(
    db_session: Session,
    chat_session_id: UUID | None,
    primary_message_id: int | None,
    sub_question_answer_results: list[SubQuestionAnswerResults],
) -> None:

    now = datetime.now()

    for sub_question_answer_result in sub_question_answer_results:
        level, level_question_num = [
            int(x) for x in sub_question_answer_result.question_id.split("_")
        ]
        sub_question = sub_question_answer_result.question
        sub_answer = sub_question_answer_result.answer
        sub_document_results = create_citation_format_list(
            sub_question_answer_result.context_documents
        )

        sub_question_object = AgentSubQuestion(
            chat_session_id=chat_session_id,
            primary_question_id=primary_message_id,
            level=level,
            level_question_num=level_question_num,
            sub_question=sub_question,
            sub_answer=sub_answer,
            sub_question_doc_results=sub_document_results,
        )

        db_session.add(sub_question_object)
        db_session.commit()

        sub_question_id = sub_question_object.id

        for sub_query in sub_question_answer_result.sub_query_retrieval_results:
            sub_query_object = AgentSubQuery(
                parent_question_id=sub_question_id,
                chat_session_id=chat_session_id,
                sub_query=sub_query.query,
                time_created=now,
            )

            db_session.add(sub_query_object)
            db_session.commit()

            search_docs = ServerSearchDoc.from_chunks_or_sections(
                sub_query.retrieved_documents
            )
            for doc in search_docs:
                db_doc = create_db_search_doc(doc, db_session)
                db_session.add(db_doc)
                sub_query_object.search_docs.append(db_doc)
            db_session.commit()

    return None


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
) -> SearchDoc:
    """Create a SearchDoc in the database from an InferenceSection."""

    db_search_doc = SearchDoc(
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
) -> SearchDoc:
    """Convert SavedSearchDoc (server model) into DB SearchDoc with correct field mapping."""
    return SearchDoc(
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
    is_agentic: bool | None,
    message: str | None = None,
    message_type: str | None = None,
    token_count: int | None = None,
    rephrased_query: str | None = None,
    citations: dict[int, int] | None = None,
    error: str | None = None,
    alternate_assistant_id: int | None = None,
    overridden_model: str | None = None,
    research_type: str | None = None,
    research_plan: dict[str, str] | None = None,
    final_documents: list[SearchDoc] | None = None,
    update_parent_message: bool = True,
    research_answer_purpose: ResearchAnswerPurpose | None = None,
    files: list[FileDescriptor] | None = None,
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
    if rephrased_query:
        chat_message.rephrased_query = rephrased_query
    if citations:
        # Convert string keys to integers to match database field type
        chat_message.citations = {int(k): v for k, v in citations.items()}
    if error:
        chat_message.error = error
    if alternate_assistant_id:
        chat_message.alternate_assistant_id = alternate_assistant_id
    if overridden_model:
        chat_message.overridden_model = overridden_model
    if research_type:
        chat_message.research_type = ResearchType(research_type)
    if research_plan:
        chat_message.research_plan = research_plan
    if final_documents:
        chat_message.search_docs = final_documents
    if is_agentic is not None:
        chat_message.is_agentic = is_agentic

    if research_answer_purpose:
        chat_message.research_answer_purpose = research_answer_purpose

    if files is not None:
        chat_message.files = files

    if update_parent_message:
        parent_chat_message = (
            db_session.query(ChatMessage)
            .filter(ChatMessage.id == chat_message.parent_message)
            .first()
        )
        if parent_chat_message:
            parent_chat_message.latest_child_message = chat_message.id

    if commit:
        db_session.commit()
    else:
        db_session.flush()

    return chat_message
