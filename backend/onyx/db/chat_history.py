from uuid import UUID

from sqlalchemy.orm import Session

from onyx.configs.constants import MessageType
from onyx.db.chat import (
    get_chat_messages_by_session,
    get_or_create_root_message,
)
from onyx.db.models import ChatMessage


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


def is_last_assistant_message_clarification(chat_history: list[ChatMessage]) -> bool:
    """Return whether the last assistant response requested clarification."""
    for message in reversed(chat_history):
        if message.message_type == MessageType.ASSISTANT:
            return message.is_clarification
    return False
