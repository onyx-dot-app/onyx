from collections.abc import Collection, Sequence
from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import NoReturn, Tuple
from uuid import UUID, uuid4

from pydantic import TypeAdapter
from sqlalchemy import (
    Integer,
    Row,
    String,
    Text,
    any_,
    bindparam,
    case,
    cast,
    delete,
    desc,
    event,
    exists,
    func,
    literal,
    nullsfirst,
    or_,
    select,
    true,
    update,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import MultipleResultsFound
from sqlalchemy.orm import Session, aliased, joinedload, load_only, selectinload
from sqlalchemy.sql.expression import ColumnElement
from sqlalchemy.sql.selectable import CTE, Select

from onyx.agents.models import (
    CompactionCheckpoint,
    InputSource,
    MessageDelivery,
    RunFailureKind,
    RunStatus,
)
from onyx.chat.errors import chat_error
from onyx.chat.mention_models import PickedSkillMessage, RecordedMention
from onyx.chat.models import (
    ChatBranch,
    HistoryLink,
    MessageRendering,
    PresentationMode,
    ResponseAncestry,
    SessionAncestor,
    read_message_rendering,
)
from onyx.configs.chat_configs import HARD_DELETE_CHATS
from onyx.configs.constants import (
    ANONYMOUS_USER_UUID,
    FileOrigin,
    MessageType,
)
from onyx.context.search.models import InferenceSection, SavedSearchDoc
from onyx.context.search.models import SearchDoc as ServerSearchDoc
from onyx.db.document_set import require_document_set_access
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import (
    IncognitoRecordMode,
    record_mode_persists_content,
)
from onyx.db.models import (
    ChatArtifact,
    ChatArtifactVersion,
    ChatInput,
    ChatMessage,
    ChatMessage__SearchDoc,
    ChatSession,
    ChatSessionSharedStatus,
    FileRecord,
    Persona,
    ScheduledTaskRun,
    ToolCall,
    User,
    UserFile,
)
from onyx.db.models import SearchDoc as DBSearchDoc
from onyx.db.persona import get_best_persona_id_for_user
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.constants import AGENT_CHECKPOINT_FILE_PREFIX
from onyx.file_store.file_store import (
    FILE_SIZE_MISSING_SENTINEL,
    get_default_file_store,
)
from onyx.file_store.models import FileDescriptor
from onyx.file_store.staging import delete_files_best_effort
from onyx.llm.models import GenerationRequestParams, TextContent, ThinkingContent
from onyx.llm.override_models import LLMOverride, PromptOverride
from onyx.server.query_and_chat.models import (
    AUTO_PLACE_AFTER_LATEST_MESSAGE,
    ChatMessageDetail,
)
from onyx.server.query_and_chat.streaming_models import StreamingError
from onyx.tools.models import IntegrationEntry, ToolOptions
from onyx.tools.tool_implementations.sandbox.models import (
    PublishedFile,
    PublishedFileView,
)
from onyx.utils.logger import setup_logger
from onyx.utils.postgres_sanitization import sanitize_string

logger = setup_logger()

FILE_CLEANUP_BATCH_SIZE = 500
MAX_AGENT_HISTORY_RUNS = 512
MAX_AGENT_DEPTH = 8
MAX_CONVERSATION_MESSAGES = 8192
CHAT_RESPONSE_STATEMENT_TIMEOUT_MS = 30_000
CHAT_RESPONSE_LOCK_TIMEOUT_MS = 5_000


def visible_chat_messages_filter() -> ColumnElement[bool]:
    """Exclude context summaries from public chat history."""
    return ChatMessage.message_type != MessageType.SUMMARY


def session_descendants(root_id: UUID | None = None) -> CTE:
    """Map conversations to their policy-owning root for lifecycle queries."""
    roots = select(
        ChatSession.id, ChatSession.id.label("root_id"), ChatSession.time_created
    ).where(ChatSession.spawned_by_message_id.is_(None))
    if root_id is not None:
        roots = roots.where(ChatSession.id == root_id)
    descendants = roots.cte("session_descendants", recursive=True)
    # UNION stops traversal if corrupt ancestry repeats a row.
    return descendants.union(
        select(ChatSession.id, descendants.c.root_id, ChatSession.time_created)
        .select_from(ChatSession)
        .join(ChatMessage, ChatMessage.id == ChatSession.spawned_by_message_id)
        .join(descendants, ChatMessage.chat_session_id == descendants.c.id)
    )


def get_chat_session_by_id(
    chat_session_id: UUID,
    user_id: UUID | None,
    db_session: Session,
    include_deleted: bool = False,
    is_shared: bool = False,
    eager_load_persona: bool = False,
) -> ChatSession:
    stmt = select(ChatSession).where(
        ChatSession.id == chat_session_id, ChatSession.spawned_by_message_id.is_(None)
    )

    if eager_load_persona:
        stmt = stmt.options(
            joinedload(ChatSession.persona).options(
                selectinload(Persona.tools),
                selectinload(Persona.user_files),
                selectinload(Persona.document_sets),
                selectinload(Persona.attached_documents),
                selectinload(Persona.hierarchy_nodes),
            ),
            joinedload(ChatSession.project),
        )

    if is_shared:
        # Deleting does not unshare, so a shared reader must never see a tombstone.
        # `include_deleted` is for the owner/admin path only.
        stmt = stmt.where(
            ChatSession.shared_status == ChatSessionSharedStatus.PUBLIC,
            ChatSession.deleted.is_(False),
        )
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


def get_owned_chat_session(
    chat_session_id: UUID | str, user_id: UUID, db_session: Session
) -> ChatSession | None:
    """Read a root session with this exact owner, including deleted sessions."""
    return db_session.scalar(
        select(ChatSession).where(
            ChatSession.id == chat_session_id,
            ChatSession.user_id == user_id,
            ChatSession.spawned_by_message_id.is_(None),
        )
    )


def get_chat_sessions_by_slack_thread_id(
    slack_thread_id: str,
    user_id: UUID | None,
    db_session: Session,
) -> Sequence[ChatSession]:
    stmt = select(ChatSession).where(
        ChatSession.slack_thread_id == slack_thread_id,
        ChatSession.spawned_by_message_id.is_(None),
    )
    if user_id is not None:
        stmt = stmt.where(
            or_(ChatSession.user_id == user_id, ChatSession.user_id.is_(None))
        )
    return db_session.scalars(stmt).all()


def get_incognito_session_ids_for_user(
    user_id: UUID, db_session: Session
) -> list[UUID]:
    return list(
        db_session.scalars(
            select(ChatSession.id).where(
                ChatSession.user_id == user_id,
                ChatSession.spawned_by_message_id.is_(None),
                ChatSession.incognito_record_mode.is_not(None),
            )
        )
    )


def content_persisting_sessions_filter() -> ColumnElement[bool]:
    """Ordinary chats plus incognito modes that persist content. Content-free
    sessions have no message content to show on any history surface."""
    persisting = [m for m in IncognitoRecordMode if m.persists_content]
    return ChatSession.incognito_record_mode.is_(
        None
    ) | ChatSession.incognito_record_mode.in_(persisting)


# Retrieves chat sessions by user
# Chat sessions do not include onyxbot flows
def not_a_scheduled_run_chat() -> ColumnElement[bool]:
    """Excludes the hidden chat that a scheduled task run made. The history
    list, chat search and delete-all leave those chats out."""
    return ~exists().where(ScheduledTaskRun.chat_session_id == ChatSession.id)


def get_chat_sessions_by_user(
    user_id: UUID | None,
    deleted: bool | None,
    db_session: Session,
    limit: int = 50,
    before: datetime | None = None,
    project_id: int | None = None,
    only_non_project_chats: bool = False,
    include_failed_chats: bool = False,
    exclude_incognito: bool = False,
    exclude_content_free: bool = False,
) -> list[ChatSession]:
    stmt = (
        select(ChatSession)
        .where(ChatSession.user_id == user_id)
        .where(ChatSession.spawned_by_message_id.is_(None))
        .where(ChatSession.onyxbot_flow.is_(False))
        .where(not_a_scheduled_run_chat())
        .order_by(desc(ChatSession.time_updated))
    )

    # The two exclusions are independent because the surfaces differ: the owner
    # sees none of their incognito sessions, while a workspace surface keeps the
    # full-history ones and drops only those with no content to show.
    if exclude_incognito:
        stmt = stmt.where(ChatSession.incognito_record_mode.is_(None))

    if exclude_content_free:
        stmt = stmt.where(content_persisting_sessions_filter())

    if deleted is not None:
        stmt = stmt.where(ChatSession.deleted == deleted)

    if before is not None:
        stmt = stmt.where(ChatSession.time_updated < before)

    if project_id is not None:
        stmt = stmt.where(ChatSession.project_id == project_id)
    elif only_non_project_chats:
        stmt = stmt.where(ChatSession.project_id.is_(None))

    # When filtering out failed chats, we apply the limit in Python after
    # filtering rather than in SQL, since the post-filter may remove rows.
    if limit and include_failed_chats:
        stmt = stmt.limit(limit)

    result = db_session.execute(stmt)
    chat_sessions = list(result.scalars().all())

    if not include_failed_chats and chat_sessions:
        # Filter out "failed" sessions (those with only SYSTEM messages)
        # using a separate efficient query instead of a correlated EXISTS
        # subquery, which causes full sequential scans of chat_message.
        leeway = datetime.now(timezone.utc) - timedelta(minutes=5)
        session_ids = [cs.id for cs in chat_sessions if cs.time_created < leeway]

        if session_ids:
            valid_session_ids_stmt = (
                select(ChatMessage.chat_session_id)
                .where(ChatMessage.chat_session_id.in_(session_ids))
                .where(ChatMessage.message_type != MessageType.SYSTEM)
                .distinct()
            )
            valid_session_ids = set(
                db_session.execute(valid_session_ids_stmt).scalars().all()
            )

            chat_sessions = [
                cs
                for cs in chat_sessions
                if cs.time_created >= leeway or cs.id in valid_session_ids
            ]

        if limit:
            chat_sessions = chat_sessions[:limit]

    return chat_sessions


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


def delete_chat_artifact_files(versions: Sequence[tuple[str, str | None]]) -> None:
    """Delete the file and the thumbnail of each artifact version, the
    thumbnail first: the file's delete cascades to its version, which links
    the thumbnail. A failed thumbnail delete keeps its file and version, so a
    later hard chat delete retries both. Raises the first failure after it
    tries every version."""
    file_store = get_default_file_store()
    failures: list[Exception] = []
    for file_id, thumbnail_file_id in versions:
        try:
            if thumbnail_file_id is not None:
                file_store.delete_file(
                    file_id=thumbnail_file_id, error_on_missing=False
                )
            file_store.delete_file(file_id=file_id, error_on_missing=False)
        except Exception as e:
            logger.warning(
                "Could not delete published file %s or its thumbnail %s",
                file_id,
                thumbnail_file_id,
                exc_info=True,
            )
            failures.append(e)
    if failures:
        raise failures[0]


def delete_messages_and_files_from_chat_session(
    chat_session_id: UUID, db_session: Session
) -> None:
    # The chat's published files and thumbnails go before the message files:
    # a saved message lists a published file, whose delete would drop the
    # link to its thumbnail. A failure stops the delete, so the next hard
    # delete finds what is left.
    delete_chat_artifact_files(
        db_session.execute(
            select(ChatArtifactVersion.file_id, ChatArtifactVersion.thumbnail_file_id)
            .join(ChatArtifact, ChatArtifact.id == ChatArtifactVersion.artifact_id)
            .where(ChatArtifact.chat_session_id == chat_session_id)
        )
        .tuples()
        .all()
    )

    descendants = session_descendants(chat_session_id)
    messages_with_files = (
        db_session.execute(
            select(ChatMessage.id, ChatMessage.files).where(
                ChatMessage.chat_session_id.in_(select(descendants.c.id)),
            )
        )
        .tuples()
        .yield_per(FILE_CLEANUP_BATCH_SIZE)
    )

    file_store = get_default_file_store()
    for _, files in messages_with_files:
        for file_info in files or []:
            if file_info.get("user_file_id"):
                # user files are managed by the user file lifecycle
                continue
            file_store.delete_file(file_id=file_info["id"], error_on_missing=False)

    checkpoint_files = db_session.scalars(
        select(FileRecord.file_id)
        .where(
            FileRecord.file_id.startswith(
                f"{AGENT_CHECKPOINT_FILE_PREFIX}{chat_session_id}/"
            )
        )
        .execution_options(yield_per=FILE_CLEANUP_BATCH_SIZE)
    )
    for file_id in checkpoint_files:
        file_store.delete_file(file_id=file_id, error_on_missing=False)

    # Delete ChatMessage records - CASCADE constraints will automatically handle:
    # - ChatMessage__StandardAnswer relationship records
    db_session.execute(
        delete(ChatMessage).where(
            ChatMessage.chat_session_id.in_(select(descendants.c.id))
        )
    )
    db_session.commit()

    delete_orphaned_search_docs(db_session)


def create_chat_session__no_commit(
    db_session: Session,
    description: str | None,
    user_id: UUID | None,
    persona_id: int | None,  # Can be none if temporary persona is used
    llm_override: LLMOverride | None = None,
    prompt_override: PromptOverride | None = None,
    onyxbot_flow: bool = False,
    slack_thread_id: str | None = None,
    project_id: int | None = None,
    incognito_record_mode: IncognitoRecordMode | None = None,
    session_id: UUID | None = None,
) -> ChatSession:
    """A chat session flushed into the caller's transaction."""
    chat_session = ChatSession(
        # Caller-supplied only for incognito, where uploads name the session
        # before it exists so the server can verify them.
        **({"id": session_id} if session_id is not None else {}),
        user_id=user_id,
        persona_id=persona_id,
        description=description,
        llm_override=llm_override,
        prompt_override=prompt_override,
        onyxbot_flow=onyxbot_flow,
        slack_thread_id=slack_thread_id,
        project_id=project_id,
        incognito_record_mode=incognito_record_mode,
    )
    db_session.add(chat_session)
    db_session.flush()
    return chat_session


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
    incognito_record_mode: IncognitoRecordMode | None = None,
    session_id: UUID | None = None,
) -> ChatSession:
    chat_session = create_chat_session__no_commit(
        db_session,
        description,
        user_id,
        persona_id,
        llm_override=llm_override,
        prompt_override=prompt_override,
        onyxbot_flow=onyxbot_flow,
        slack_thread_id=slack_thread_id,
        project_id=project_id,
        incognito_record_mode=incognito_record_mode,
        session_id=session_id,
    )
    db_session.commit()
    return chat_session


def duplicate_chat_session_for_user_from_slack(
    db_session: Session,
    user: User,
    chat_session_id: UUID,
) -> ChatSession:
    """
    This takes a chat session id for a session in Slack and:
    - Creates a new chat session in the DB
    - Tries to copy the persona from the original chat session
        (if it is available to the user clicking the button)
    - Sets the user to the given user (if provided)
    """
    try:
        chat_session = get_chat_session_by_id(
            chat_session_id=chat_session_id,
            user_id=None,
            db_session=db_session,
        )
    except ValueError:
        chat_session = None
    # Slack answers are owned by the mapped user (DMs, ephemeral replies) or by
    # the anonymous user (public channel replies). Any other owner is private.
    if chat_session is None or chat_session.user_id not in (
        None,
        user.id,
        UUID(ANONYMOUS_USER_UUID),
    ):
        raise OnyxError(
            OnyxErrorCode.SESSION_NOT_FOUND, "Invalid Chat Session ID provided"
        )
    if chat_session.incognito_record_mode is not None:
        raise ValueError("Incognito chat sessions cannot be duplicated")

    # This enforces permissions and sets a default
    new_persona_id = get_best_persona_id_for_user(
        db_session=db_session,
        user=user,
        persona_id=chat_session.persona_id,
    )

    return create_chat_session(
        db_session=db_session,
        user_id=user.id,
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

    # A title is conversation-derived, so a content-free session never stores
    # one. Enforced here rather than at each caller: auto-naming, manual
    # rename, and the patch endpoint all write through this.
    if description is not None and record_mode_persists_content(
        chat_session.incognito_record_mode
    ):
        chat_session.description = description
    if sharing_status is not None:
        chat_session.shared_status = sharing_status

    db_session.commit()

    return chat_session


def save_chat_session_name_if_unnamed(
    db_session: Session,
    user_id: UUID | None,
    chat_session_id: UUID,
    name: str,
) -> bool:
    """Save an auto-generated name only while the chat has none, so a rename
    made during generation wins. Returns whether the name was saved."""
    statement = (
        update(ChatSession)
        .where(
            ChatSession.id == chat_session_id,
            ChatSession.deleted.is_(False),
            or_(ChatSession.description.is_(None), ChatSession.description == ""),
        )
        .values(description=name)
        .returning(ChatSession.id)
    )
    if user_id is not None:
        statement = statement.where(ChatSession.user_id == user_id)
    saved_id = db_session.execute(statement).scalar_one_or_none()
    db_session.commit()
    return saved_id is not None


def delete_all_chat_sessions_for_user(
    user: User, db_session: Session, hard_delete: bool = HARD_DELETE_CHATS
) -> list[UUID]:
    """Returns the ids of the chat sessions that were not deleted before."""
    user_id = user.id

    chat_sessions = (
        db_session.query(ChatSession)
        .filter(
            ChatSession.user_id == user_id,
            ChatSession.onyxbot_flow.is_(False),
            not_a_scheduled_run_chat(),
            ChatSession.spawned_by_message_id.is_(None),
        )
        .all()
    )
    chat_session_ids = [chat_session.id for chat_session in chat_sessions]
    newly_deleted_ids = [
        chat_session.id for chat_session in chat_sessions if not chat_session.deleted
    ]

    # Only the sessions read above: one that a concurrent request creates now
    # stays, instead of going without its cleanup.
    if hard_delete:
        for chat_session_id in chat_session_ids:
            delete_messages_and_files_from_chat_session(chat_session_id, db_session)
        db_session.execute(
            delete(ChatSession).where(ChatSession.id.in_(chat_session_ids))
        )
    else:
        db_session.execute(
            update(ChatSession)
            .where(ChatSession.id.in_(chat_session_ids))
            .values(deleted=True)
        )

    db_session.commit()
    return newly_deleted_ids


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
    days_old: float, db_session: Session, limit: int | None = None
) -> list[tuple[UUID | None, UUID]]:
    """
    Retrieves chat sessions whose last activity is older than a specified number of days.

    "Last activity" is the time of the most recent message in the session, so an
    old session that is still being used is retained. Sessions without any messages
    fall back to their creation time.

    Args:
        days_old: The number of days to consider as "old".
        db_session: The database session.
        limit: Optional cap on the number of sessions returned. When set, the
            oldest sessions are returned first so callers can drain the backlog
            in bounded batches without loading every matching row at once.

    Returns:
        A list of tuples, where each tuple contains the user_id (can be None) and the chat_session_id of an old chat session.
    """

    cutoff_time = datetime.now(tz=timezone.utc) - timedelta(days=days_old)
    descendants = session_descendants()
    last_activity = func.greatest(
        func.max(ChatMessage.time_sent), func.max(descendants.c.time_created)
    )
    stmt = (
        select(ChatSession.user_id, ChatSession.id)
        .join(descendants, descendants.c.root_id == ChatSession.id)
        .outerjoin(ChatMessage, ChatMessage.chat_session_id == descendants.c.id)
        .where(ChatSession.spawned_by_message_id.is_(None))
        .group_by(ChatSession.id, ChatSession.user_id)
        .having(last_activity < cutoff_time)
    )
    if limit is not None:
        stmt = stmt.order_by(last_activity.asc()).limit(limit)
    old_sessions: Sequence[Row[Tuple[UUID | None, UUID]]] = db_session.execute(
        stmt
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
    stmt = (
        select(ChatMessage)
        .join(ChatSession, ChatSession.id == ChatMessage.chat_session_id)
        .where(
            ChatMessage.id == chat_message_id,
            ChatSession.spawned_by_message_id.is_(None),
            visible_chat_messages_filter(),
        )
    )

    result = db_session.execute(stmt)
    chat_message = result.scalar_one_or_none()

    if not chat_message:
        raise ValueError("Invalid Chat Message specified")

    chat_user = chat_message.chat_session.user
    expected_user_id = chat_user.id if chat_user is not None else None

    if expected_user_id != user_id:
        logger.error(
            "User %s tried to fetch a chat message that does not belong to them",
            user_id,
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
    stmt = (
        select(ChatMessage)
        .join(ChatSession, ChatSession.id == ChatMessage.chat_session_id)
        .where(
            ChatMessage.id == message_id,
            ChatSession.spawned_by_message_id.is_(None),
            visible_chat_messages_filter(),
        )
    )

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
    prefetch_response_items: bool = False,
) -> Sequence[ChatMessage]:
    if not skip_permission_check:
        for chat_session_id in chat_session_ids:
            get_chat_session_by_id(
                chat_session_id=chat_session_id, user_id=user_id, db_session=db_session
            )
    stmt = (
        select(ChatMessage)
        .options(
            selectinload(ChatMessage.search_docs),
        )
        .join(ChatSession, ChatSession.id == ChatMessage.chat_session_id)
        .where(
            ChatSession.spawned_by_message_id.is_(None), visible_chat_messages_filter()
        )
        .where(ChatMessage.chat_session_id.in_(chat_session_ids))
        .order_by(nullsfirst(ChatMessage.parent_message_id))
    )
    if prefetch_response_items:
        stmt = stmt.options(selectinload(ChatMessage.response_items))
    return db_session.execute(stmt).scalars().all()


def add_chats_to_session_from_slack_thread(
    db_session: Session,
    slack_chat_session_id: UUID,
    new_chat_session_id: UUID,
) -> None:
    """Copy displayed conversation content and commit the new message tree."""
    source_session = db_session.get(ChatSession, slack_chat_session_id)
    if source_session and source_session.incognito_record_mode is not None:
        raise ValueError("Incognito chat sessions cannot be duplicated")
    new_root_message = get_or_create_root_message(
        chat_session_id=new_chat_session_id,
        db_session=db_session,
    )

    for chat_message in get_chat_messages_by_sessions(
        chat_session_ids=[slack_chat_session_id],
        user_id=None,  # Ignore user permissions for this
        db_session=db_session,
        skip_permission_check=True,
        prefetch_response_items=True,
    ):
        if chat_message.message_type == MessageType.SYSTEM:
            continue
        reasoning = get_chat_message_reasoning(chat_message)
        new_root_message = create_new_chat_message(
            db_session=db_session,
            chat_session_id=new_chat_session_id,
            parent_message=new_root_message,
            message=chat_message.message,
            files=chat_message.files,
            error=chat_message.error,
            token_count=chat_message.token_count,
            message_type=chat_message.message_type,
            reasoning_tokens=reasoning,
            commit=False,
        )
    db_session.commit()


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
        search_doc_ids: Search document IDs to link, in the order the tool
            returned them (stored as each link's position)
        db_session: The database session
    """
    from onyx.db.models import ToolCall__SearchDoc

    for position, search_doc_id in enumerate(search_doc_ids):
        tool_call_search_doc = ToolCall__SearchDoc(
            tool_call_id=tool_call_id,
            search_doc_id=search_doc_id,
            position=position,
        )
        db_session.add(tool_call_search_doc)


def get_chat_messages_by_session(
    chat_session_id: UUID,
    user_id: UUID | None,
    db_session: Session,
    skip_permission_check: bool = False,
    prefetch_top_two_level_tool_calls: bool = True,
    prefetch_message_details: bool = False,
    # Only the session replay reads tool call search docs; building chat
    # history for a new message does not, so it skips this load.
    prefetch_tool_call_search_docs: bool = False,
    # Load only these messages (one page of the session); None loads all.
    message_ids: Collection[int] | None = None,
) -> list[ChatMessage]:
    if not skip_permission_check:
        # bug if we ever call this expecting the permission check to not be skipped
        get_chat_session_by_id(
            chat_session_id=chat_session_id, user_id=user_id, db_session=db_session
        )

    stmt = (
        select(ChatMessage)
        .join(ChatSession, ChatSession.id == ChatMessage.chat_session_id)
        .where(
            ChatSession.spawned_by_message_id.is_(None), visible_chat_messages_filter()
        )
        .where(ChatMessage.chat_session_id == chat_session_id)
        .order_by(nullsfirst(ChatMessage.parent_message_id))
    )
    if message_ids is not None:
        stmt = stmt.where(ChatMessage.id.in_(message_ids))

    if prefetch_message_details:
        stmt = stmt.options(
            selectinload(ChatMessage.response_items),
            selectinload(ChatMessage.chat_message_feedbacks),
            selectinload(ChatMessage.search_docs),
        )

    # This should handle both the top level tool calls and deep research
    # If there are future nested agents, this can be extended.
    if prefetch_top_two_level_tool_calls:
        # Load tool_calls and their direct children (one level deep), and on
        # request their search docs
        tool_call_loads = [selectinload(ToolCall.tool_call_children)]
        if prefetch_tool_call_search_docs:
            tool_call_loads.append(selectinload(ToolCall.search_docs))
        stmt = stmt.options(
            selectinload(ChatMessage.tool_calls).options(*tool_call_loads)
        )
        result = db_session.scalars(stmt).unique().all()
    else:
        result = db_session.scalars(stmt).all()

    return list(result)


def get_chat_message_page_ids(
    chat_session_id: UUID,
    db_session: Session,
    limit: int,
    before_message_id: int | None = None,
    waiting_reply_ids: Collection[int] = (),
) -> tuple[set[int], bool]:
    """One page of a session's current branch, for paged loading.

    The page holds the last `limit` messages of the current branch (the chain
    of `latest_child_message_id` from the root), or of the part of it before
    `before_message_id`. It also holds every child of those messages, so a
    branch switcher and multi-model replies have their siblings, including the
    siblings of the first message of the next, newer page.

    The latest page also reaches back to the question of each of
    `waiting_reply_ids` that is on the branch, or a reply to it.

    Returns the message ids and whether the branch has older messages. A
    `before_message_id` that is not on the current branch gives an empty page.
    """
    rows = db_session.execute(
        select(
            ChatMessage.id,
            ChatMessage.parent_message_id,
            ChatMessage.latest_child_message_id,
        )
        .where(ChatMessage.chat_session_id == chat_session_id)
        .where(visible_chat_messages_filter())
    ).all()

    latest_child_by_id: dict[int, int | None] = {}
    parent_by_id: dict[int, int | None] = {}
    children_by_parent: dict[int, list[int]] = {}
    root_id: int | None = None
    for message_id, parent_id, latest_child_id in rows:
        latest_child_by_id[message_id] = latest_child_id
        parent_by_id[message_id] = parent_id
        if parent_id is None:
            root_id = message_id
        else:
            children_by_parent.setdefault(parent_id, []).append(message_id)

    branch: list[int] = []
    next_id = root_id
    while next_id is not None and next_id in latest_child_by_id:
        branch.append(next_id)
        next_id = latest_child_by_id[next_id]

    if before_message_id is not None:
        # The branch changed since the client loaded this message.
        if before_message_id not in branch:
            return set(), False
        branch = branch[: branch.index(before_message_id)]

    start = max(len(branch) - limit, 0)
    if before_message_id is None and waiting_reply_ids:
        positions = {message_id: index for index, message_id in enumerate(branch)}
        start = min(
            [start]
            + [
                positions[message_id]
                for reply_id in waiting_reply_ids
                for message_id in (parent_by_id.get(reply_id), reply_id)
                if message_id in positions
            ]
        )
    page = branch[start:]
    page_ids = set(page)
    for message_id in page:
        page_ids.update(children_by_parent.get(message_id, []))
    return page_ids, start > 0


def save_chat_artifact(
    content: bytes,
    *,
    name: str,
    mime_type: str,
    chat_session_id: UUID,
    path: str,
    title: str | None,
    thumbnail: bytes | None,
) -> PublishedFile:
    """Save a file that the model published in the root chat
    `chat_session_id` as the next version of the chat's artifact at `path`,
    with `thumbnail`, a JPEG of its first page, if set. The file and its
    thumbnail get the chat's access, the chat's file list, and its hard
    delete. A thumbnail that fails to save is left out."""
    file_store = get_default_file_store()
    file_id = str(uuid4())
    thumbnail_file_id: str | None = None
    if thumbnail is not None:
        try:
            thumbnail_file_id = file_store.save_file(
                content=BytesIO(thumbnail),
                display_name=f"{name} thumbnail",
                file_origin=FileOrigin.CHAT_ARTIFACT_THUMBNAIL,
                file_type="image/jpeg",
            )
        except Exception:
            logger.warning(
                "Could not save the thumbnail of published file %s",
                file_id,
                exc_info=True,
            )
    saved: list[tuple[UUID, int]] = []

    def add_version(db_session: Session) -> None:
        # The upsert locks the artifact's row until the commit, so concurrent
        # publishes of one path take turns, and the next statement reads
        # the versions they committed.
        artifact_id = db_session.execute(
            postgresql.insert(ChatArtifact)
            .values(chat_session_id=chat_session_id, path=path)
            .on_conflict_do_update(
                index_elements=[ChatArtifact.chat_session_id, ChatArtifact.path],
                set_={"updated_at": func.now()},
            )
            .returning(ChatArtifact.id)
        ).scalar_one()
        version = db_session.execute(
            postgresql.insert(ChatArtifactVersion)
            .from_select(
                ["artifact_id", "version", "file_id", "title", "thumbnail_file_id"],
                select(
                    literal(artifact_id),
                    func.coalesce(func.max(ChatArtifactVersion.version), 0) + 1,
                    literal(file_id),
                    literal(title, Text()),
                    literal(thumbnail_file_id, String()),
                ).where(ChatArtifactVersion.artifact_id == artifact_id),
            )
            .returning(ChatArtifactVersion.version)
        ).scalar_one()
        saved.append((artifact_id, version))

    try:
        with get_session_with_current_tenant() as db_session:
            # save_file commits the session once, after it writes the file
            # record. The rows go in that transaction after the record, so
            # the upload holds no lock.
            event.listen(db_session, "before_commit", add_version, once=True)
            file_store.save_file(
                content=BytesIO(content),
                display_name=name,
                file_origin=FileOrigin.CHAT_ARTIFACT,
                file_type=mime_type,
                file_id=file_id,
                db_session=db_session,
            )
        if not saved:
            raise RuntimeError(
                f"save_file did not commit the session for published file {file_id}"
            )
    except BaseException:
        if thumbnail_file_id is not None:
            delete_files_best_effort([thumbnail_file_id], "unpublished thumbnail")
        raise
    [(artifact_id, version)] = saved
    return PublishedFile(
        file_id=file_id,
        artifact_id=artifact_id,
        version=version,
        name=name,
        title=title,
        path=path,
        size=len(content),
        mime_type=mime_type,
        thumbnail_file_id=thumbnail_file_id,
    )


def delete_unpublished_chat_artifacts(published: Sequence[PublishedFile]) -> None:
    """Delete the files and thumbnails of a publish that failed
    (delete_chat_artifact_files), then the artifacts that they leave without a
    version, so a failed publish sets no artifact's first publish or version
    numbers."""
    try:
        delete_chat_artifact_files(
            [(file.file_id, file.thumbnail_file_id) for file in published]
        )
    except Exception:
        # A kept file keeps its version, so its artifact stays below and a
        # hard chat delete retries it.
        logger.warning(
            "Kept unpublished files whose delete failed: %s",
            [file.file_id for file in published],
        )
    artifact_ids = sorted({file.artifact_id for file in published if file.artifact_id})
    if not artifact_ids:
        return
    with get_session_with_current_tenant() as db_session:
        # The lock waits for a concurrent publish of the path to commit, and
        # the delete's new snapshot then sees its version.
        db_session.execute(
            select(ChatArtifact.id)
            .where(ChatArtifact.id.in_(artifact_ids))
            .order_by(ChatArtifact.id)
            .with_for_update()
        )
        db_session.execute(
            delete(ChatArtifact).where(
                ChatArtifact.id.in_(artifact_ids),
                ~select(ChatArtifactVersion.artifact_id)
                .where(ChatArtifactVersion.artifact_id == ChatArtifact.id)
                .exists(),
            )
        )
        db_session.commit()


def get_chat_published_files(
    chat_session_id: UUID, db_session: Session
) -> list[PublishedFileView]:
    """The files that the model published in a chat, its subagents' files
    included: the latest version of each artifact, by the artifact's first
    publish. Versions whose object is missing are left out."""
    latest = (
        select(
            ChatArtifact.id.label("artifact_id"),
            ChatArtifact.path,
            ChatArtifact.created_at,
            ChatArtifactVersion.version,
            ChatArtifactVersion.file_id,
            ChatArtifactVersion.title,
            ChatArtifactVersion.thumbnail_file_id,
            FileRecord.display_name,
            FileRecord.file_type,
            FileRecord.file_size,
        )
        .join(ChatArtifactVersion, ChatArtifactVersion.artifact_id == ChatArtifact.id)
        .join(FileRecord, FileRecord.file_id == ChatArtifactVersion.file_id)
        .where(
            ChatArtifact.chat_session_id == chat_session_id,
            FileRecord.file_size.is_distinct_from(FILE_SIZE_MISSING_SENTINEL),
        )
        .distinct(ChatArtifact.id)
        .order_by(ChatArtifact.id, ChatArtifactVersion.version.desc())
        .subquery()
    )
    rows = db_session.execute(
        select(latest).order_by(latest.c.created_at, latest.c.artifact_id)
    ).all()
    return [
        PublishedFileView(
            file_id=row.file_id,
            artifact_id=row.artifact_id,
            version=row.version,
            name=row.display_name or row.file_id,
            title=row.title,
            path=row.path,
            # A file without a recorded size shows as 0.
            size=row.file_size or 0,
            mime_type=row.file_type,
            thumbnail_file_id=row.thumbnail_file_id,
        )
        for row in rows
    ]


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


def configure_response_transaction__no_commit(session: Session) -> None:
    """Bound database waits while a response holds its execution lease."""
    session.execute(
        select(
            func.set_config(
                "statement_timeout",
                str(CHAT_RESPONSE_STATEMENT_TIMEOUT_MS),
                True,
            )
        )
    )
    session.execute(
        select(
            func.set_config(
                "lock_timeout",
                str(CHAT_RESPONSE_LOCK_TIMEOUT_MS),
                True,
            )
        )
    )


def reserve_chat_response_ids(
    db_session: Session,
    chat_session_id: UUID,
    parent_message_id: int,
    model_display_names: list[str],
) -> list[int]:
    """Reserve assistant responses and select the last response as the active branch.

    Pending sends without a target were submitted while this turn prepared.
    """
    if not model_display_names:
        raise ValueError("At least one response model is required")
    configure_response_transaction__no_commit(db_session)
    # Queue submission and response reservation share the session-first lock order.
    db_session.execute(
        select(ChatSession.id)
        .where(ChatSession.id == chat_session_id)
        .with_for_update(key_share=True)
    )
    # A new turn resumes a queue that Stop paused.
    db_session.execute(
        update(ChatSession)
        .where(
            ChatSession.id == chat_session_id,
            ChatSession.queue_paused_at.is_not(None),
        )
        .values(queue_paused_at=None)
    )
    reserved: list[ChatMessage] = []
    for display_name in model_display_names:
        msg = ChatMessage(
            chat_session_id=chat_session_id,
            parent_message_id=parent_message_id,
            latest_child_message_id=None,
            message="Response was terminated prior to completion, try regenerating.",
            token_count=15,
            message_type=MessageType.ASSISTANT,
            model_display_name=display_name,
        )
        db_session.add(msg)
        reserved.append(msg)

    # Flush to assign IDs without committing yet
    db_session.flush()

    # Point parent's latest_child to the last reserved message
    parent = (
        db_session.query(ChatMessage)
        .filter(ChatMessage.id == parent_message_id)
        .first()
    )
    if parent:
        parent.latest_child_message_id = reserved[-1].id

    # Sends that arrived while this turn prepared go to its selected response.
    db_session.execute(
        update(ChatInput)
        .where(
            ChatInput.recipient_session_id == chat_session_id,
            ChatInput.source == InputSource.HUMAN,
            ChatInput.delivery == MessageDelivery.SEND,
            ChatInput.target_response_id.is_(None),
        )
        .values(target_response_id=reserved[-1].id)
    )

    db_session.commit()
    return [message.id for message in reserved]


def set_response_model_names__no_commit(
    db_session: Session, model_display_names: dict[int, str]
) -> None:
    """Name the models of responses reserved before their models were selected."""
    for response_id, display_name in model_display_names.items():
        db_session.execute(
            update(ChatMessage)
            .where(ChatMessage.id == response_id)
            .values(model_display_name=display_name)
        )


# Tool options are user input stored on the chat and loaded with it, so their
# size is bounded before anything reads or stores them.
MAX_TOOL_OPTIONS_ITEMS = 1000
MAX_TOOL_OPTIONS_BYTES = 64 * 1024


def _raise_tool_options_too_large() -> NoReturn:
    raise OnyxError(
        OnyxErrorCode.PAYLOAD_TOO_LARGE,
        "The tool options are too large to save",
    )


def set_chat_session_tool_options__no_commit(
    db_session: Session,
    chat_session_id: UUID,
    tool_options: ToolOptions,
    user: User,
) -> ToolOptions | None:
    """Save the fields set on `tool_options`; unset fields keep their saved values.

    A chat that keeps no content stores no options, because search filters
    carry user choices such as tag values. Returns the stored options, or
    None when the chat stores none.
    """
    chat_session = db_session.get(ChatSession, chat_session_id)
    if chat_session is None or not record_mode_persists_content(
        chat_session.incognito_record_mode
    ):
        return None
    filters = tool_options.internal_search_filters
    item_lists = [
        tool_options.allowed,
        *(
            entry.actions
            for entry in tool_options.allowed or []
            if isinstance(entry, IntegrationEntry)
        ),
        filters.source_type if filters else None,
        filters.document_set if filters else None,
        filters.tags if filters else None,
    ]
    if any(len(items) > MAX_TOOL_OPTIONS_ITEMS for items in item_lists if items):
        _raise_tool_options_too_large()
    require_document_set_access(
        db_session, filters.document_set if filters else None, user
    )
    changes = tool_options.model_dump(include=tool_options.model_fields_set)
    saved = chat_session.tool_options
    if (
        saved is not None
        and ToolOptions.model_validate(saved.model_dump() | changes) == saved
    ):
        return saved
    # Merge under the row lock, so a concurrent save keeps the fields it set.
    db_session.refresh(chat_session, with_for_update=True)
    current = chat_session.tool_options or ToolOptions()
    merged = ToolOptions.model_validate(current.model_dump() | changes)
    if len(merged.model_dump_json().encode()) > MAX_TOOL_OPTIONS_BYTES:
        _raise_tool_options_too_large()
    chat_session.tool_options = merged
    return chat_session.tool_options


def set_preferred_response(
    db_session: Session,
    user_message_id: int,
    preferred_assistant_message_id: int,
) -> None:
    """Mark one assistant response as the user's preferred choice in a multi-model turn.

    Also advances ``latest_child_message_id`` so the preferred response becomes
    the active branch for any subsequent messages in the conversation.

    Args:
        db_session: Active database session.
        user_message_id: Primary key of the ``USER``-type ``ChatMessage`` whose
            preferred response is being set.
        preferred_assistant_message_id: Primary key of the ``ASSISTANT``-type
            ``ChatMessage`` to prefer. Must be a direct child of ``user_message_id``
            in the same chat session.

    Raises:
        ValueError: If either message is not found, if ``user_message_id`` does not
            refer to a USER message, or if the preferred response is not an
            ASSISTANT child in the same chat session.
    """
    user_msg = db_session.get(ChatMessage, user_message_id)
    if user_msg is None:
        raise ValueError(f"User message {user_message_id} not found")
    if (
        user_msg.message_type != MessageType.USER
        or user_msg.chat_session.spawned_by_message_id is not None
    ):
        raise ValueError(f"Message {user_message_id} is not a user message")

    assistant_msg = db_session.get(ChatMessage, preferred_assistant_message_id)
    if assistant_msg is None:
        raise ValueError(
            f"Assistant message {preferred_assistant_message_id} not found"
        )
    if assistant_msg.message_type != MessageType.ASSISTANT:
        raise ValueError(
            f"Message {preferred_assistant_message_id} is not an assistant message"
        )
    if assistant_msg.chat_session_id != user_msg.chat_session_id:
        raise ValueError(
            f"Assistant message {preferred_assistant_message_id} is not in the same chat session as user message {user_message_id}"
        )
    if assistant_msg.parent_message_id != user_message_id:
        raise ValueError(
            f"Assistant message {preferred_assistant_message_id} is not a child of user message {user_message_id}"
        )

    user_msg.preferred_response_id = preferred_assistant_message_id
    user_msg.latest_child_message_id = preferred_assistant_message_id
    db_session.commit()


def create_new_chat_message(
    chat_session_id: UUID,
    parent_message: ChatMessage,
    message: str,
    token_count: int,
    message_type: MessageType,
    db_session: Session,
    files: list[FileDescriptor] | None = None,
    mentions: list[RecordedMention] | None = None,
    skill_messages: list[PickedSkillMessage] | None = None,
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
        existing_message.mentions = mentions or []
        existing_message.skill_messages = skill_messages or []
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
            mentions=mentions or [],
            skill_messages=skill_messages or [],
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


_UUID_PATTERN = "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"


def get_chat_session_user_files(
    chat_session_id: UUID, db_session: Session
) -> list[UserFile]:
    """The user files that the chat's user messages attached, on every
    branch, in the order of their first message. Only file descriptors whose
    `user_file_id` is the UUID of an existing user file count."""
    descriptor = (
        func.jsonb_array_elements(
            case(
                (func.jsonb_typeof(ChatMessage.files) == "array", ChatMessage.files),
                else_=cast(literal("[]"), postgresql.JSONB),
            )
        )
        .table_valued("value")
        .lateral("descriptor")
    )
    raw_id = descriptor.c.value.op("->>", return_type=String)("user_file_id")
    user_file_id = case(
        (raw_id.op("~*")(_UUID_PATTERN), cast(raw_id, postgresql.UUID(as_uuid=True)))
    )
    first_messages = (
        select(
            user_file_id.label("user_file_id"),
            func.min(ChatMessage.id).label("message_id"),
        )
        .select_from(ChatMessage)
        .join(descriptor, true())
        .where(
            ChatMessage.chat_session_id == chat_session_id,
            ChatMessage.message_type == MessageType.USER,
        )
        .group_by(user_file_id)
        .subquery()
    )
    return list(
        db_session.scalars(
            select(UserFile)
            .join(first_messages, first_messages.c.user_file_id == UserFile.id)
            .order_by(first_messages.c.message_id, UserFile.id)
        )
    )


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


def create_db_search_doc(
    server_search_doc: ServerSearchDoc,
    db_session: Session,
    commit: bool = True,
) -> DBSearchDoc:
    db_search_doc = DBSearchDoc(
        document_id=sanitize_string(server_search_doc.document_id),
        chunk_ind=server_search_doc.chunk_ind,
        semantic_id=sanitize_string(server_search_doc.semantic_identifier),
        link=(
            sanitize_string(server_search_doc.link)
            if server_search_doc.link is not None
            else None
        ),
        blurb=sanitize_string(server_search_doc.blurb),
        source_type=server_search_doc.source_type,
        boost=server_search_doc.boost,
        hidden=server_search_doc.hidden,
        doc_metadata=server_search_doc.metadata,
        is_relevant=server_search_doc.is_relevant,
        relevance_explanation=(
            sanitize_string(server_search_doc.relevance_explanation)
            if server_search_doc.relevance_explanation is not None
            else None
        ),
        score=server_search_doc.score or 0.0,
        match_highlights=[
            sanitize_string(h) for h in server_search_doc.match_highlights
        ],
        updated_at=server_search_doc.updated_at,
        primary_owners=(
            [sanitize_string(o) for o in server_search_doc.primary_owners]
            if server_search_doc.primary_owners is not None
            else None
        ),
        secondary_owners=(
            [sanitize_string(o) for o in server_search_doc.secondary_owners]
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


def get_chat_message_reasoning(chat_message: ChatMessage) -> str | None:
    """Read displayed thinking from the accepted answer or latest partial output."""
    # Legacy responses have no recorded SDK steps.
    if chat_message.response_status is None:
        return chat_message.reasoning_tokens
    for item in sorted(
        chat_message.response_items,
        key=lambda item: item.step_index,
        reverse=True,
    ):
        if chat_message.response_status == RunStatus.COMPLETE and not item.is_answer:
            continue
        rendering = (
            read_message_rendering(item.rendering)
            if item.rendering is not None
            else MessageRendering()
        )
        if rendering.mode not in (PresentationMode.ANSWER, PresentationMode.RESEARCH):
            continue
        message = item.message
        if rendering.mode == PresentationMode.RESEARCH:
            return "".join(
                block.text
                for block in message.content
                if isinstance(block, (TextContent, ThinkingContent))
            )
        return message.thinking
    return None


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
        top_documents, key=lambda doc: doc.score or 0.0, reverse=True
    )
    request_params = (
        GenerationRequestParams.model_validate(
            chat_message.request_params, extra="ignore"
        )
        if chat_message.request_params is not None
        else None
    )
    deadline_cancelled = (
        chat_message.response_status == RunStatus.CANCELLED
        and chat_message.response_failure is not None
        and chat_message.response_failure.kind == RunFailureKind.DEADLINE
    )
    error_info = (
        None
        if deadline_cancelled
        else chat_error(chat_message.response_failure)
        if chat_message.response_failure is not None
        else StreamingError(error=chat_message.error)
        if chat_message.error is not None
        else None
    )
    if error_info is not None and request_params is not None:
        error_info.details = {
            **(error_info.details or {}),
            "model": request_params.model_name,
            "provider": request_params.model_provider,
        }
    chat_msg_detail = ChatMessageDetail(
        chat_session_id=chat_message.chat_session_id,
        message_id=chat_message.id,
        parent_message=chat_message.parent_message_id,
        latest_child_message=chat_message.latest_child_message_id,
        message=chat_message.message,
        reasoning_tokens=get_chat_message_reasoning(chat_message),
        request_params=request_params,
        message_type=chat_message.message_type,
        context_docs=top_documents,
        citations=converted_citations,
        time_sent=chat_message.time_sent,
        files=chat_message.files or [],
        mentions=chat_message.mentions,
        error=error_info.error if error_info is not None else None,
        error_info=error_info,
        response_status=chat_message.response_status,
        current_feedback=current_feedback,
        processing_duration_seconds=chat_message.processing_duration_seconds,
        preferred_response_id=chat_message.preferred_response_id,
        model_display_name=chat_message.model_display_name,
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


# =============================================================================
# CHAT HISTORY
# Reads the linear message chain of a chat session.
# =============================================================================


def create_chat_history_chain(
    chat_session_id: UUID,
    db_session: Session,
    prefetch_top_two_level_tool_calls: bool = True,
    prefetch_message_details: bool = False,
    # Optional id at which we finish processing
    stop_at_message_id: int | None = None,
) -> list[ChatMessage]:
    """Build the linear chain of messages without including the root message"""
    mainline_messages: list[ChatMessage] = []

    all_chat_messages = get_chat_messages_by_session(
        chat_session_id=chat_session_id,
        user_id=None,
        db_session=db_session,
        skip_permission_check=True,
        prefetch_top_two_level_tool_calls=prefetch_top_two_level_tool_calls,
        prefetch_message_details=prefetch_message_details,
    )

    if not all_chat_messages:
        root_message = get_or_create_root_message(
            chat_session_id=chat_session_id, db_session=db_session
        )
    else:
        root_message = all_chat_messages[0]
        if root_message.parent_message is not None:
            raise RuntimeError(
                "Invalid root message, unable to fetch valid chat message sequence"
            )

    current_message: ChatMessage | None = root_message
    previous_message: ChatMessage | None = None
    while current_message is not None:
        child_msg = current_message.latest_child_message

        # Break if at the end of the chain
        # or have reached the `final_id` of the submitted message
        if not child_msg or (
            stop_at_message_id and current_message.id == stop_at_message_id
        ):
            break
        current_message = child_msg

        if (
            current_message.message_type == MessageType.ASSISTANT
            and previous_message is not None
            and previous_message.message_type == MessageType.ASSISTANT
            and mainline_messages
        ):
            # Note that 2 user messages in a row is fine since this is often used for
            # adding custom prompts and reminders
            raise RuntimeError(
                "Invalid message chain, cannot have two assistant messages in a row"
            )
        else:
            mainline_messages.append(current_message)

        previous_message = current_message

    return mainline_messages


def reserve_stream_id(db_session: Session) -> int:
    """A new stream ID for a stream without a new message, such as one that
    continues a suspended response. It comes from the message ID sequence, so
    it never equals another stream's ID, which is a message ID."""
    stream_id = db_session.scalar(
        select(
            func.nextval(func.pg_get_serial_sequence(ChatMessage.__tablename__, "id"))
        )
    )
    if stream_id is None:
        raise RuntimeError("The message ID sequence returned no value")
    return stream_id


def load_message_branch(
    chat_session_id: UUID,
    parent_id: int | None,
    db_session: Session,
    *,
    any_branch: bool = False,
) -> tuple[list[ChatMessage], ChatMessage]:
    """Select the requested branch before adding a user message.

    The parent must be on the selected branch, unless `any_branch`: then a
    parent off it, such as the suspended response of another model of a
    multi-model turn, brings its own ancestry."""
    history = create_chat_history_chain(
        chat_session_id, db_session, prefetch_top_two_level_tool_calls=False
    )
    root = get_or_create_root_message(chat_session_id, db_session)
    if parent_id == AUTO_PLACE_AFTER_LATEST_MESSAGE:
        parent = history[-1] if history else root
    elif parent_id is None or parent_id == root.id:
        return [], root
    else:
        parent_index = next(
            (index for index, message in enumerate(history) if message.id == parent_id),
            None,
        )
        if parent_index is not None:
            history = history[: parent_index + 1]
        else:
            parent_message = db_session.get(ChatMessage, parent_id)
            if (
                not any_branch
                or parent_message is None
                or parent_message.chat_session_id != chat_session_id
            ):
                raise ValueError(
                    "The new message sent is not on the latest mainline of messages"
                )
            ancestry = visible_message_ids(db_session, parent_message)[::-1]
            by_id = {
                message.id: message
                for message in db_session.scalars(
                    select(ChatMessage).where(
                        ChatMessage.id.in_(ancestry), ChatMessage.id != root.id
                    )
                )
            }
            history = [
                by_id[message_id] for message_id in ancestry if message_id in by_id
            ]
        parent = history[-1]

    response_ids = [
        message.id
        for message in history
        if message.message_type == MessageType.ASSISTANT
    ]
    if response_ids:
        db_session.scalars(
            select(ChatMessage)
            .where(ChatMessage.id.in_(response_ids))
            .options(
                load_only(ChatMessage.id),
                selectinload(ChatMessage.response_items),
                selectinload(ChatMessage.search_docs),
                selectinload(ChatMessage.tool_calls),
            )
        ).all()
    # History gives the model the skill messages of picked skills, which
    # other reads of a chat leave unloaded.
    picking_ids = [message.id for message in history if message.mentions]
    if picking_ids:
        db_session.scalars(
            select(ChatMessage)
            .where(ChatMessage.id.in_(picking_ids))
            .options(load_only(ChatMessage.id, ChatMessage.skill_messages))
        ).all()
    return history, parent


def find_summary_for_ancestry(
    db_session: Session,
    session_id: UUID,
    message_ids: list[int],
) -> ChatMessage | None:
    """Find a summary on selected ancestry; IDs must run from newest to oldest."""
    if not message_ids:
        return None
    # One array parameter keeps the query the same size however long the history is.
    ancestry = bindparam("ancestry", message_ids, type_=postgresql.ARRAY(Integer))
    return db_session.scalar(
        select(ChatMessage)
        .where(
            ChatMessage.chat_session_id == session_id,
            ChatMessage.message_type == MessageType.SUMMARY,
            ChatMessage.parent_message_id == any_(ancestry),
        )
        # Nearest ancestor first, then the newest summary on that ancestor.
        .order_by(
            func.array_position(ancestry, ChatMessage.parent_message_id),
            ChatMessage.id.desc(),
        )
        .limit(1)
    )


def checkpoint_from_summary(message: ChatMessage | None) -> CompactionCheckpoint | None:
    if message is None:
        return None
    if message.last_summarized_message_id is None:
        return None
    return CompactionCheckpoint(
        summary=message.message,
        covered_through_message_id=message.last_summarized_message_id,
    )


def find_summary_for_branch(
    db_session: Session,
    chat_history: list[ChatMessage],
) -> ChatMessage | None:
    """Find the summary on the nearest selected ancestor, regardless of save time."""
    if not chat_history:
        return None
    return find_summary_for_ancestry(
        db_session,
        chat_history[0].chat_session_id,
        [message.id for message in reversed(chat_history)],
    )


def get_selected_branch(
    session: Session, chat_session_id: UUID
) -> tuple[ChatMessage | None, ChatBranch]:
    """Return the selected latest response and the message IDs on its branch."""
    branch = (
        select(
            ChatMessage.id,
            ChatMessage.latest_child_message_id,
            literal(0).label("depth"),
        )
        .where(
            ChatMessage.chat_session_id == chat_session_id,
            ChatMessage.parent_message_id.is_(None),
        )
        .cte("selected_branch", recursive=True)
    )
    branch = branch.union_all(
        select(
            ChatMessage.id,
            ChatMessage.latest_child_message_id,
            branch.c.depth + 1,
        )
        .join(branch, ChatMessage.id == branch.c.latest_child_message_id)
        .where(
            ChatMessage.chat_session_id == chat_session_id,
            branch.c.depth < MAX_CONVERSATION_MESSAGES,
        )
    )
    message_ids = list(
        session.scalars(select(branch.c.id).order_by(branch.c.depth.desc()))
    )
    # Follow only IDs; queue checks do not need response content or tool results.
    selected = (
        session.scalar(
            select(ChatMessage)
            .where(
                ChatMessage.id == message_ids[0],
                ChatMessage.message_type == MessageType.ASSISTANT,
            )
            .options(
                load_only(
                    ChatMessage.id,
                    ChatMessage.chat_session_id,
                    ChatMessage.parent_message_id,
                    ChatMessage.response_status,
                )
            )
        )
        if message_ids
        else None
    )
    return selected, ChatBranch(
        chat_session_id=chat_session_id, message_ids=message_ids
    )


def visible_message_ids(db_session: Session, message: ChatMessage) -> list[int]:
    """Return the selected ancestry, including the current response."""
    ancestry = (
        select(
            ChatMessage.id,
            ChatMessage.parent_message_id,
            ChatMessage.chat_session_id,
            literal(0).label("depth"),
        )
        .where(ChatMessage.id == message.id)
        .cte("agent_ancestry", recursive=True)
    )
    ancestry = ancestry.union_all(
        select(
            ChatMessage.id,
            ChatMessage.parent_message_id,
            ChatMessage.chat_session_id,
            ancestry.c.depth + 1,
        )
        .join(ancestry, ChatMessage.id == ancestry.c.parent_message_id)
        .where(ancestry.c.depth < MAX_CONVERSATION_MESSAGES)
    )
    rows = TypeAdapter(list[HistoryLink]).validate_python(
        db_session.execute(select(ancestry)).mappings().all()
    )
    if any(row.chat_session_id != message.chat_session_id for row in rows):
        raise ValueError("Chat history crosses sessions")
    parents = {row.id: row.parent_message_id for row in rows}
    ids: list[int] = []
    visited: set[int] = set()
    current: int | None = message.id
    while current is not None:
        if current in visited:
            raise ValueError("Chat history contains a cycle")
        ids.append(current)
        visited.add(current)
        if current not in parents:
            raise ValueError(
                "Chat history exceeds its traversal limit or has a missing ancestor"
            )
        current = parents[current]
    return ids


def session_ancestors(
    db_session: Session, agent_ids: list[UUID]
) -> dict[UUID, SessionAncestor]:
    ancestors = (
        select(
            ChatSession.id,
            ChatSession.agent_name,
            ChatMessage.chat_session_id.label("parent_id"),
            literal(0).label("depth"),
        )
        .outerjoin(ChatMessage, ChatMessage.id == ChatSession.spawned_by_message_id)
        .where(ChatSession.id.in_(agent_ids))
        .cte("session_ancestors", recursive=True)
    )
    ancestors = ancestors.union_all(
        select(
            ChatSession.id,
            ChatSession.agent_name,
            ChatMessage.chat_session_id,
            ancestors.c.depth + 1,
        )
        .join(ancestors, ChatSession.id == ancestors.c.parent_id)
        .outerjoin(ChatMessage, ChatMessage.id == ChatSession.spawned_by_message_id)
        .where(ancestors.c.depth < MAX_AGENT_DEPTH)
    )
    rows = TypeAdapter(list[SessionAncestor]).validate_python(
        db_session.execute(select(ancestors).order_by(ancestors.c.depth.desc()))
        .mappings()
        .all()
    )
    return {row.id: row for row in rows}


def agent_ancestor_chain(
    agent_id: UUID, ancestors: dict[UUID, SessionAncestor]
) -> list[SessionAncestor]:
    """Return this agent and its parents, with a complete and acyclic ancestry."""
    chain: list[SessionAncestor] = []
    visited: set[UUID] = set()
    current: UUID | None = agent_id
    while current is not None:
        if current in visited or len(visited) > MAX_AGENT_DEPTH:
            raise ValueError("Agent hierarchy contains a cycle or exceeds its limit")
        visited.add(current)
        ancestor = ancestors.get(current)
        if ancestor is None:
            raise ValueError("Agent parent is unavailable")
        chain.append(ancestor)
        current = ancestor.parent_id
    return chain


def agent_path_from_ancestors(
    agent_id: UUID, ancestors: dict[UUID, SessionAncestor]
) -> str:
    segments = [
        ancestor.agent_name or "root"
        for ancestor in agent_ancestor_chain(agent_id, ancestors)
    ]
    return "/" + "/".join(reversed(segments))


def agent_session_path(db_session: Session, agent: ChatSession) -> str:
    if agent.spawned_by_message_id is None:
        return f"/{agent.agent_name or 'root'}"
    return agent_path_from_ancestors(
        agent.id, session_ancestors(db_session, [agent.id])
    )


def response_invocation(response: ChatMessage) -> ToolCall | None:
    """The tool call that started a child response; its question records it."""
    question = response.parent_message
    return question.invoking_tool_call if question is not None else None


def _response_ancestry_select() -> Select:
    question = aliased(ChatMessage)
    spawning_response = aliased(ChatMessage)
    return (
        select(
            ChatMessage.id.label("message_id"),
            ChatMessage.chat_session_id.label("session_id"),
            ChatMessage.response_status.label("status"),
            ChatSession.spawned_by_message_id,
            spawning_response.chat_session_id.label("parent_session_id"),
            ToolCall.parent_chat_message_id.label("parent_response_id"),
            question.parent_message_id.label("previous_response_id"),
        )
        .join(ChatSession, ChatSession.id == ChatMessage.chat_session_id)
        .outerjoin(question, question.id == ChatMessage.parent_message_id)
        .outerjoin(ToolCall, ToolCall.id == question.invoking_tool_call_id)
        .outerjoin(
            spawning_response,
            spawning_response.id == ChatSession.spawned_by_message_id,
        )
    )


def response_invocation_chain(
    db_session: Session, response_id: int
) -> list[ResponseAncestry]:
    """The response, then each response whose tool call started the one before it.

    The chain ends at the root response. Agents can message each other, so it
    can be longer than the spawn depth. Each step goes to an older response, so
    the walk ends without a length limit. Empty when the response is missing.
    """
    chain = (
        _response_ancestry_select()
        .where(ChatMessage.id == response_id)
        .cte("response_invocation_chain", recursive=True)
    )
    chain = chain.union_all(
        _response_ancestry_select()
        .join(chain, ChatMessage.id == chain.c.parent_response_id)
        .where(
            chain.c.spawned_by_message_id.is_not(None),
            ChatMessage.id < chain.c.message_id,
        )
    )
    rows = TypeAdapter(list[ResponseAncestry]).validate_python(
        db_session.execute(select(chain).order_by(chain.c.message_id.desc()))
        .mappings()
        .all()
    )
    if rows and rows[-1].spawned_by_message_id is not None:
        raise ValueError("Child response is missing its invocation")
    return rows


def ownership_root_id(db_session: Session, response_id: int) -> int | None:
    """The newest turn root that the response's run depends on.

    A child run depends on the turn whose tool call started it and on the turns
    of its previous runs. Another turn can continue an agent, so a previous run
    can belong to a later turn than the invocation. All of these roots are on
    one branch, so the newest is the latest. None when the response is missing.
    """
    question = aliased(ChatMessage)
    nodes = (
        select(
            ChatMessage.id.label("message_id"),
            ChatSession.spawned_by_message_id,
            ToolCall.parent_chat_message_id.label("invoker_id"),
            question.parent_message_id.label("previous_id"),
        )
        .join(ChatSession, ChatSession.id == ChatMessage.chat_session_id)
        .outerjoin(question, question.id == ChatMessage.parent_message_id)
        .outerjoin(ToolCall, ToolCall.id == question.invoking_tool_call_id)
    )
    walk = nodes.where(ChatMessage.id == response_id).cte(
        "ownership_root_walk", recursive=True
    )
    # Each step goes to an older response, so the walk ends.
    walk = walk.union(
        nodes.join(
            walk,
            or_(
                ChatMessage.id == walk.c.invoker_id,
                ChatMessage.id == walk.c.previous_id,
            ),
        ).where(
            walk.c.spawned_by_message_id.is_not(None),
            ChatMessage.id < walk.c.message_id,
        )
    )
    return db_session.scalar(
        select(func.max(walk.c.message_id)).where(
            walk.c.spawned_by_message_id.is_(None)
        )
    )


def root_response_id(db_session: Session, response: ChatMessage) -> int:
    """The newest turn root of the response's run; see `ownership_root_id`."""
    root_id = ownership_root_id(db_session, response.id)
    if root_id is None:
        raise ValueError("Response is unavailable")
    return root_id


def response_on_branch(
    db_session: Session, response: ChatMessage, branch_ids: Collection[int]
) -> bool:
    """Whether the turns that the response's run depends on are on the branch.

    A child run belongs to every later turn of the branch that started it.
    """
    return root_response_id(db_session, response) in branch_ids


def parent_session_id(db_session: Session, session: ChatSession) -> UUID | None:
    if session.spawned_by_message_id is None:
        return None
    parent_id = db_session.scalar(
        select(ChatMessage.chat_session_id).where(
            ChatMessage.id == session.spawned_by_message_id
        )
    )
    if parent_id is None:
        raise ValueError("Agent creation message is unavailable")
    return parent_id


def add_chat_session__no_commit(db_session: Session, row: ChatSession) -> None:
    db_session.add(row)
