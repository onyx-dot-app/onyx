from collections.abc import Sequence
from functools import lru_cache
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy import func
from sqlalchemy import not_
from sqlalchemy import nullsfirst
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.exc import MultipleResultsFound
from sqlalchemy.orm import Session

from danswer.auth.schemas import UserRole
from danswer.configs.chat_configs import HARD_DELETE_CHATS
from danswer.configs.constants import MessageType
from danswer.db.constants import SLACK_BOT_PERSONA_PREFIX
from danswer.db.engine import get_sqlalchemy_engine
from danswer.db.models import ChatMessage
from danswer.db.models import ChatSession
from danswer.db.models import ChatSessionSharedStatus
from danswer.db.models import DocumentSet as DBDocumentSet
from danswer.db.models import Persona
from danswer.db.models import Persona__User
from danswer.db.models import Persona__UserGroup
from danswer.db.models import Prompt
from danswer.db.models import SearchDoc
from danswer.db.models import SearchDoc as DBSearchDoc
from danswer.db.models import StarterMessage
from danswer.db.models import User
from danswer.db.models import User__UserGroup
from danswer.file_store.models import FileDescriptor
from danswer.llm.override_models import LLMOverride
from danswer.llm.override_models import PromptOverride
from danswer.search.enums import RecencyBiasSetting
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


@lru_cache()
def get_default_prompt() -> Prompt:
    with Session(get_sqlalchemy_engine()) as db_session:
        stmt = select(Prompt).where(Prompt.id == 0)

        result = db_session.execute(stmt)
        prompt = result.scalar_one_or_none()

        if prompt is None:
            raise RuntimeError("Default Prompt not found")

        return prompt


def get_persona_by_id(
    persona_id: int,
    # if user is `None` assume the user is an admin or auth is disabled
    user: User | None,
    db_session: Session,
    include_deleted: bool = False,
) -> Persona:
    stmt = select(Persona).where(Persona.id == persona_id)

    # if user is an admin, they should have access to all Personas
    if user is not None and user.role != UserRole.ADMIN:
        stmt = stmt.where(or_(Persona.user_id == user.id, Persona.user_id.is_(None)))

    if not include_deleted:
        stmt = stmt.where(Persona.deleted.is_(False))

    result = db_session.execute(stmt)
    persona = result.scalar_one_or_none()

    if persona is None:
        raise ValueError(
            f"Persona with ID {persona_id} does not exist or does not belong to user"
        )

    return persona


def get_prompts_by_ids(prompt_ids: list[int], db_session: Session) -> Sequence[Prompt]:
    """Unsafe, can fetch prompts from all users"""
    if not prompt_ids:
        return []
    prompts = db_session.scalars(select(Prompt).where(Prompt.id.in_(prompt_ids))).all()

    return prompts


def get_personas_by_ids(
    persona_ids: list[int], db_session: Session
) -> Sequence[Persona]:
    """Unsafe, can fetch personas from all users"""
    if not persona_ids:
        return []
    personas = db_session.scalars(
        select(Persona).where(Persona.id.in_(persona_ids))
    ).all()

    return personas


def get_prompt_by_name(
    prompt_name: str, user: User | None, db_session: Session
) -> Prompt | None:
    stmt = select(Prompt).where(Prompt.name == prompt_name)

    # if user is not specified OR they are an admin, they should
    # have access to all prompts, so this where clause is not needed
    if user and user.role != UserRole.ADMIN:
        stmt = stmt.where(Prompt.user_id == user.id)

    result = db_session.execute(stmt).scalar_one_or_none()
    return result


def get_persona_by_name(
    persona_name: str, user: User | None, db_session: Session
) -> Persona | None:
    """Admins can see all, regular users can only fetch their own.
    If user is None, assume the user is an admin or auth is disabled."""
    stmt = select(Persona).where(Persona.name == persona_name)
    if user and user.role != UserRole.ADMIN:
        stmt = stmt.where(Persona.user_id == user.id)
    result = db_session.execute(stmt).scalar_one_or_none()
    return result


def upsert_prompt(
    user: User | None,
    name: str,
    description: str,
    system_prompt: str,
    task_prompt: str,
    include_citations: bool,
    datetime_aware: bool,
    personas: list[Persona] | None,
    db_session: Session,
    prompt_id: int | None = None,
    default_prompt: bool = True,
    commit: bool = True,
) -> Prompt:
    if prompt_id is not None:
        prompt = db_session.query(Prompt).filter_by(id=prompt_id).first()
    else:
        prompt = get_prompt_by_name(prompt_name=name, user=user, db_session=db_session)

    if prompt:
        if not default_prompt and prompt.default_prompt:
            raise ValueError("Cannot update default prompt with non-default.")

        prompt.name = name
        prompt.description = description
        prompt.system_prompt = system_prompt
        prompt.task_prompt = task_prompt
        prompt.include_citations = include_citations
        prompt.datetime_aware = datetime_aware
        prompt.default_prompt = default_prompt

        if personas is not None:
            prompt.personas.clear()
            prompt.personas = personas

    else:
        prompt = Prompt(
            id=prompt_id,
            user_id=user.id if user else None,
            name=name,
            description=description,
            system_prompt=system_prompt,
            task_prompt=task_prompt,
            include_citations=include_citations,
            datetime_aware=datetime_aware,
            default_prompt=default_prompt,
            personas=personas or [],
        )
        db_session.add(prompt)

    if commit:
        db_session.commit()
    else:
        # Flush the session so that the Prompt has an ID
        db_session.flush()

    return prompt


def upsert_persona(
    user: User | None,
    name: str,
    description: str,
    num_chunks: float,
    llm_relevance_filter: bool,
    llm_filter_extraction: bool,
    recency_bias: RecencyBiasSetting,
    prompts: list[Prompt] | None,
    document_sets: list[DBDocumentSet] | None,
    llm_model_provider_override: str | None,
    llm_model_version_override: str | None,
    starter_messages: list[StarterMessage] | None,
    is_public: bool,
    db_session: Session,
    persona_id: int | None = None,
    default_persona: bool = False,
    commit: bool = True,
) -> Persona:
    if persona_id is not None:
        persona = db_session.query(Persona).filter_by(id=persona_id).first()
    else:
        persona = get_persona_by_name(
            persona_name=name, user=user, db_session=db_session
        )

    if persona:
        if not default_persona and persona.default_persona:
            raise ValueError("Cannot update default persona with non-default.")

        persona.name = name
        persona.description = description
        persona.num_chunks = num_chunks
        persona.llm_relevance_filter = llm_relevance_filter
        persona.llm_filter_extraction = llm_filter_extraction
        persona.recency_bias = recency_bias
        persona.default_persona = default_persona
        persona.llm_model_provider_override = llm_model_provider_override
        persona.llm_model_version_override = llm_model_version_override
        persona.starter_messages = starter_messages
        persona.deleted = False  # Un-delete if previously deleted
        persona.is_public = is_public

        # Do not delete any associations manually added unless
        # a new updated list is provided
        if document_sets is not None:
            persona.document_sets.clear()
            persona.document_sets = document_sets or []

        if prompts is not None:
            persona.prompts.clear()
            persona.prompts = prompts

    else:
        persona = Persona(
            id=persona_id,
            user_id=user.id if user else None,
            is_public=is_public,
            name=name,
            description=description,
            num_chunks=num_chunks,
            llm_relevance_filter=llm_relevance_filter,
            llm_filter_extraction=llm_filter_extraction,
            recency_bias=recency_bias,
            default_persona=default_persona,
            prompts=prompts or [],
            document_sets=document_sets or [],
            llm_model_provider_override=llm_model_provider_override,
            llm_model_version_override=llm_model_version_override,
            starter_messages=starter_messages,
        )
        db_session.add(persona)

    if commit:
        db_session.commit()
    else:
        # flush the session so that the persona has an ID
        db_session.flush()

    return persona


def mark_prompt_as_deleted(
    prompt_id: int,
    user: User | None,
    db_session: Session,
) -> None:
    prompt = get_prompt_by_id(prompt_id=prompt_id, user=user, db_session=db_session)
    prompt.deleted = True
    db_session.commit()


def mark_persona_as_deleted(
    persona_id: int,
    user: User | None,
    db_session: Session,
) -> None:
    persona = get_persona_by_id(persona_id=persona_id, user=user, db_session=db_session)
    persona.deleted = True
    db_session.commit()


def mark_delete_persona_by_name(
    persona_name: str, db_session: Session, is_default: bool = True
) -> None:
    stmt = (
        update(Persona)
        .where(Persona.name == persona_name, Persona.default_persona == is_default)
        .values(deleted=True)
    )

    db_session.execute(stmt)
    db_session.commit()


def delete_old_default_personas(
    db_session: Session,
) -> None:
    """Note, this locks out the Summarize and Paraphrase personas for now
    Need a more graceful fix later or those need to never have IDs"""
    stmt = (
        update(Persona)
        .where(Persona.default_persona, Persona.id > 0)
        .values(deleted=True, name=func.concat(Persona.name, "_old"))
    )

    db_session.execute(stmt)
    db_session.commit()


def update_persona_visibility(
    persona_id: int,
    is_visible: bool,
    db_session: Session,
) -> None:
    persona = get_persona_by_id(persona_id=persona_id, user=None, db_session=db_session)
    persona.is_visible = is_visible
    db_session.commit()


def update_all_personas_display_priority(
    display_priority_map: dict[int, int],
    db_session: Session,
) -> None:
    """Updates the display priority of all lives Personas"""
    personas = get_personas(user_id=None, db_session=db_session)
    available_persona_ids = {persona.id for persona in personas}
    if available_persona_ids != set(display_priority_map.keys()):
        raise ValueError("Invalid persona IDs provided")

    for persona in personas:
        persona.display_priority = display_priority_map[persona.id]

    db_session.commit()


def get_prompts(
    user_id: UUID | None,
    db_session: Session,
    include_default: bool = True,
    include_deleted: bool = False,
) -> Sequence[Prompt]:
    stmt = select(Prompt).where(
        or_(Prompt.user_id == user_id, Prompt.user_id.is_(None))
    )

    if not include_default:
        stmt = stmt.where(Prompt.default_prompt.is_(False))
    if not include_deleted:
        stmt = stmt.where(Prompt.deleted.is_(False))

    return db_session.scalars(stmt).all()


def get_personas(
    # if user_id is `None` assume the user is an admin or auth is disabled
    user_id: UUID | None,
    db_session: Session,
    include_default: bool = True,
    include_slack_bot_personas: bool = False,
    include_deleted: bool = False,
) -> Sequence[Persona]:
    stmt = select(Persona).distinct()
    if user_id is not None:
        # Subquery to find all groups the user belongs to
        user_groups_subquery = (
            select(User__UserGroup.user_group_id)
            .where(User__UserGroup.user_id == user_id)
            .subquery()
        )

        # Include personas where the user is directly related or part of a user group that has access
        access_conditions = or_(
            Persona.is_public == True,  # noqa: E712
            Persona.id.in_(  # User has access through list of users with access
                select(Persona__User.persona_id).where(Persona__User.user_id == user_id)
            ),
            Persona.id.in_(  # User is part of a group that has access
                select(Persona__UserGroup.persona_id).where(
                    Persona__UserGroup.user_group_id.in_(user_groups_subquery)  # type: ignore
                )
            ),
        )
        stmt = stmt.where(access_conditions)

    if not include_default:
        stmt = stmt.where(Persona.default_persona.is_(False))
    if not include_slack_bot_personas:
        stmt = stmt.where(not_(Persona.name.startswith(SLACK_BOT_PERSONA_PREFIX)))
    if not include_deleted:
        stmt = stmt.where(Persona.deleted.is_(False))

    return db_session.scalars(stmt).all()


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


def delete_persona_by_name(
    persona_name: str, db_session: Session, is_default: bool = True
) -> None:
    stmt = delete(Persona).where(
        Persona.name == persona_name, Persona.default_persona == is_default
    )

    db_session.execute(stmt)

    db_session.commit()
