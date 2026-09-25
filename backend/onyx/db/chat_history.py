import json
from collections.abc import Callable
from itertools import groupby
from typing import TypedDict
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import case, select
from sqlalchemy.orm import Session, load_only, selectinload

from onyx.agents.items import messages_from_items
from onyx.agents.transcript import CompactionCheckpoint, messages_for_model
from onyx.chat.files import build_file_context
from onyx.chat.llm_step import PromptMetadata, count_message_tokens
from onyx.chat.models import ChatHistoryMessage, ChatHistoryResult
from onyx.configs.constants import MessageType
from onyx.db.chat import (
    get_chat_messages_by_session,
    get_or_create_root_message,
)
from onyx.db.chat_response_items import read_response_items
from onyx.db.enums import record_mode_persists_content
from onyx.db.models import ChatMessage
from onyx.file_store.models import (
    ChatFileType,
    ChatLoadedFile,
    FileDescriptor,
    FileToolMetadata,
)
from onyx.llm.models import (
    AssistantMessage,
    Message,
    TextContent,
    ToolResultMessage,
    UserMessage,
)
from onyx.llm.models import ToolCall as AgentToolCall
from onyx.prompts.chat_prompts import (
    ADDITIONAL_CONTEXT_PROMPT,
    TOOL_CALL_RESPONSE_CROSS_MESSAGE,
)
from onyx.server.query_and_chat.models import AUTO_PLACE_AFTER_LATEST_MESSAGE
from onyx.utils.logger import setup_logger

logger = setup_logger()


IMAGE_GENERATION_TOOL_NAME = "generate_image"


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


def convert_chat_history_basic(
    chat_history: list[ChatMessage],
    token_counter: Callable[[str], int],
    max_individual_message_tokens: int | None = None,
    max_total_tokens: int | None = None,
) -> list[Message]:
    """Read user and assistant text, keeping the latest messages within the token budget."""
    # Defensive: treat a non-positive total budget as "no history".
    if max_total_tokens is not None and max_total_tokens <= 0:
        return []

    # Convert only the core USER/ASSISTANT messages; omit files and tool calls.
    converted: list[Message] = []
    for chat_message in chat_history:
        if chat_message.message_type not in (MessageType.USER, MessageType.ASSISTANT):
            continue

        message = chat_message.message
        token_count = chat_message.token_count
        if token_count is None:
            token_count = token_counter(message)

        # Drop any single message that would dominate the context window.
        if (
            max_individual_message_tokens is not None
            and token_count > max_individual_message_tokens
        ):
            continue

        converted.append(
            UserMessage(
                content=message, metadata=PromptMetadata(token_count=token_count)
            )
            if chat_message.message_type == MessageType.USER
            else AssistantMessage(
                content=[TextContent(text=message)],
                metadata=PromptMetadata(token_count=token_count),
            )
        )

    if max_total_tokens is None:
        return converted

    # Enforce a max total budget by keeping a contiguous suffix of the conversation.
    trimmed_reversed: list[Message] = []
    total_tokens = 0
    for msg in reversed(converted):
        if total_tokens + count_message_tokens(msg, token_counter) > max_total_tokens:
            break
        trimmed_reversed.append(msg)
        total_tokens += count_message_tokens(msg, token_counter)

    return list(reversed(trimmed_reversed))


class _ImageReplay(TypedDict):
    file_id: str
    revised_prompt: str


def _build_tool_call_response_history_message(
    tool_name: str,
    generated_images: list[dict[str, JsonValue]] | None,
    tool_call_response: str | None,
) -> str:
    if tool_name != IMAGE_GENERATION_TOOL_NAME:
        return TOOL_CALL_RESPONSE_CROSS_MESSAGE

    if generated_images:
        llm_image_context: list[_ImageReplay] = []
        for image in generated_images:
            file_id = image.get("file_id")
            revised_prompt = image.get("revised_prompt")
            if not isinstance(file_id, str):
                logger.warning("Skipping stored generated image without a file ID")
                continue

            llm_image_context.append(
                {
                    "file_id": file_id,
                    "revised_prompt": (
                        revised_prompt if isinstance(revised_prompt, str) else ""
                    ),
                }
            )

        if llm_image_context:
            return json.dumps(llm_image_context)

    if tool_call_response:
        return tool_call_response

    return TOOL_CALL_RESPONSE_CROSS_MESSAGE


def _legacy_tool_messages(
    message: ChatMessage,
    tool_names: dict[int, str],
    token_counter: Callable[[str], int],
) -> list[Message]:
    """Reconstruct tool steps for responses saved without response items."""
    messages: list[Message] = []
    calls = sorted(
        message.tool_calls or [], key=lambda call: (call.turn_number, call.tool_id)
    )
    for _, turn in groupby(calls, key=lambda call: call.turn_number):
        records = list(turn)
        tool_calls = [
            AgentToolCall(
                id=call.tool_call_id,
                name=tool_names.get(call.tool_id, "unknown"),
                arguments=call.tool_call_arguments or {},
            )
            for call in records
        ]
        messages.append(
            AssistantMessage(
                content=[TextContent(text=""), *tool_calls],
                metadata=PromptMetadata(
                    token_count=sum(
                        token_counter(json.dumps(call.arguments)) for call in tool_calls
                    )
                ),
            )
        )
        for call in records:
            text = _build_tool_call_response_history_message(
                tool_name=tool_names.get(call.tool_id, "unknown"),
                generated_images=call.generated_images,
                tool_call_response=call.tool_call_response,
            )
            messages.append(
                ToolResultMessage(
                    content=text,
                    tool_call_id=call.tool_call_id,
                    tool_name="",
                    metadata=PromptMetadata(token_count=token_counter(text)),
                )
            )
    return messages


def capture_chat_history(
    messages: list[ChatMessage],
    tool_names: dict[int, str],
    token_counter: Callable[[str], int],
    checkpoint: CompactionCheckpoint | None = None,
) -> list[ChatHistoryMessage]:
    """Copy replay data while ORM relationships are available; the caller owns the session."""
    history: list[ChatHistoryMessage] = []
    for message in messages:
        response_messages: list[Message] = []
        agent_run_id = None
        if message.message_type == MessageType.ASSISTANT:
            if message.response_status is not None and record_mode_persists_content(
                message.chat_session.incognito_record_mode
            ):
                response_messages = messages_for_model(
                    messages_from_items(read_response_items(message))
                )
                for response_message in response_messages:
                    if isinstance(response_message, ToolResultMessage):
                        response_message.metadata = PromptMetadata(
                            omit_tool_result_content=response_message.tool_name
                            != IMAGE_GENERATION_TOOL_NAME
                        )
                agent_run_id = str(message.id)
            else:
                response_messages = _legacy_tool_messages(
                    message, tool_names, token_counter
                )
                response_messages.append(
                    AssistantMessage(
                        content=[TextContent(text=message.message)],
                        metadata=PromptMetadata(token_count=message.token_count),
                    )
                )
        history.append(
            ChatHistoryMessage(
                id=message.id,
                message_type=message.message_type,
                message=message.message,
                token_count=message.token_count,
                files=message.files or [],
                is_clarification=message.is_clarification,
                response_messages=response_messages,
                agent_run_id=agent_run_id,
            )
        )
    if checkpoint is not None:
        for message in reversed(history):
            if message.message_type == MessageType.ASSISTANT:
                message.checkpoint = checkpoint
                break
    return history


def convert_chat_history(
    chat_history: list[ChatHistoryMessage],
    files: list[ChatLoadedFile],
    context_image_files: list[ChatLoadedFile],
    additional_context: str | None,
    token_counter: Callable[[str], int],
) -> ChatHistoryResult:
    """Load canonical assistant output and attach user files to message history."""
    messages: list[Message] = []
    all_injected_file_metadata: dict[str, FileToolMetadata] = {}

    # Create a mapping of file IDs to loaded files for quick lookup
    file_map = {str(f.file_id): f for f in files}

    # Find the index of the last USER message
    last_user_message_idx = next(
        (
            index
            for index in range(len(chat_history) - 1, -1, -1)
            if chat_history[index].message_type == MessageType.USER
        ),
        None,
    )

    for idx, chat_message in enumerate(chat_history):
        if chat_message.message_type == MessageType.USER:
            # Process files attached to this message
            text_files: list[tuple[ChatLoadedFile, FileDescriptor]] = []
            image_files: list[ChatLoadedFile] = []

            if chat_message.files:
                for file_descriptor in chat_message.files:
                    file_id = file_descriptor["id"]
                    loaded_file = file_map.get(file_id)
                    if loaded_file:
                        if loaded_file.file_type == ChatFileType.IMAGE:
                            image_files.append(loaded_file)
                        else:
                            # Text files (DOC, PLAIN_TEXT, TABULAR) are added as separate messages
                            text_files.append((loaded_file, file_descriptor))

            # Add text files as separate messages before the user message.
            # Each message is tagged with ``file_id`` so that forgotten files
            # can be detected after context-window truncation.
            for text_file, fd in text_files:
                # Use user_file_id as the FileReaderTool accepts that.
                # Fall back to the file-store path id.
                tool_id = fd.get("user_file_id") or text_file.file_id
                filename = text_file.filename or "unknown"
                ctx = build_file_context(
                    tool_file_id=tool_id,
                    filename=filename,
                    file_type=text_file.file_type,
                    content_text=text_file.content_text,
                    token_count=text_file.token_count,
                    content_pending=text_file.content_pending,
                )
                messages.append(ctx.message)
                all_injected_file_metadata[tool_id] = ctx.tool_metadata

            # Sum token counts from image files (excluding project image files)
            image_token_count = (
                sum(img.token_count for img in image_files) if image_files else 0
            )

            # Add the user message with image files attached
            # If this is the last USER message, also include context_image_files
            # Note: context image file tokens are NOT counted in the token count
            if idx == last_user_message_idx:
                if context_image_files:
                    image_files.extend(context_image_files)

                if additional_context:
                    messages.append(
                        UserMessage(
                            content=ADDITIONAL_CONTEXT_PROMPT.format(
                                additional_context=additional_context
                            ),
                            metadata=PromptMetadata(
                                token_count=token_counter(additional_context),
                                image_files=None,
                            ),
                        )
                    )

            messages.append(
                UserMessage(
                    content=chat_message.message,
                    metadata=PromptMetadata(
                        token_count=chat_message.token_count + image_token_count,
                        image_files=image_files or None,
                        image_token_count=image_token_count,
                    ),
                )
            )

        elif chat_message.message_type == MessageType.ASSISTANT:
            messages.extend(chat_message.response_messages)
        else:
            raise ValueError(
                f"Invalid message type when constructing simple history: {chat_message.message_type}"
            )

    return ChatHistoryResult(
        messages=messages,
        all_injected_file_metadata=all_injected_file_metadata,
    )


def is_last_assistant_message_clarification(chat_history: list[ChatMessage]) -> bool:
    """Return whether the last assistant response requested clarification."""
    for message in reversed(chat_history):
        if message.message_type == MessageType.ASSISTANT:
            return message.is_clarification
    return False


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
                selectinload(ChatMessage.response_items),
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
