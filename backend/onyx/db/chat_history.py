from uuid import UUID

from sqlalchemy import case, select
from sqlalchemy.orm import Session, load_only, selectinload

from onyx.agents.execution_records import CompactionCheckpoint
from onyx.configs.constants import MessageType
from onyx.db.chat import (
    get_chat_messages_by_session,
    get_or_create_root_message,
)
from onyx.db.models import ChatMessage
from onyx.server.query_and_chat.models import AUTO_PLACE_AFTER_LATEST_MESSAGE


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


def load_message_branch(
    chat_session_id: UUID,
    parent_id: int | None,
    db_session: Session,
) -> tuple[list[ChatMessage], ChatMessage]:
    """Select the requested branch before adding a user message."""
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
        if parent_index is None:
            raise ValueError(
                "The new message sent is not on the latest mainline of messages"
            )
        history = history[: parent_index + 1]
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
                selectinload(ChatMessage.response_messages),
                selectinload(ChatMessage.tool_calls),
            )
        ).all()
    return history, parent


def find_summary_for_ancestry(
    db_session: Session,
    session_id: UUID,
    message_ids: list[int],
    *,
    legacy_only: bool = False,
) -> ChatMessage | None:
    """Find a summary on selected ancestry; IDs must run from newest to oldest."""
    if not message_ids:
        return None
    query = select(ChatMessage).where(
        ChatMessage.chat_session_id == session_id,
        ChatMessage.parent_message_id.in_(message_ids),
        ChatMessage.message_type == MessageType.SUMMARY,
    )
    if legacy_only:
        query = query.where(ChatMessage.last_summarized_message_id.is_not(None))
    return db_session.scalar(
        query.order_by(
            case(
                {message_id: index for index, message_id in enumerate(message_ids)},
                value=ChatMessage.parent_message_id,
            ),
            ChatMessage.id.desc(),
        ).limit(1)
    )


def checkpoint_from_summary(message: ChatMessage | None) -> CompactionCheckpoint | None:
    if message is None:
        return None
    if message.summary_covered_count is None and message.summary_covered_digest is None:
        return None
    if message.summary_covered_count is None or message.summary_covered_digest is None:
        raise ValueError("Summary coverage is missing")
    return CompactionCheckpoint(
        summary=message.message,
        covered_count=message.summary_covered_count,
        covered_digest=message.summary_covered_digest,
    )


def find_summary_for_branch(
    db_session: Session,
    chat_history: list[ChatMessage],
    *,
    legacy_only: bool = False,
) -> ChatMessage | None:
    """Find the summary on the nearest selected ancestor, regardless of save time."""
    if not chat_history:
        return None
    return find_summary_for_ancestry(
        db_session,
        chat_history[0].chat_session_id,
        [message.id for message in reversed(chat_history)],
        legacy_only=legacy_only,
    )
