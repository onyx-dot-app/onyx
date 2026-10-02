"""Chat session policy and conversion of saved history into model input."""

import json
from collections.abc import Callable
from itertools import groupby
from typing import TypedDict

from pydantic import JsonValue
from sqlalchemy.orm import Session

from onyx.agents.execution_records import CompactionCheckpoint, messages_for_model
from onyx.agents.models import messages_from_steps
from onyx.chat.files import build_file_context
from onyx.chat.incognito import (
    incognito_allowed_for_user,
    resolve_incognito_record_mode,
)
from onyx.chat.incognito_context import incognito_context_available
from onyx.chat.models import ChatHistoryMessage, ChatHistoryResult
from onyx.chat.prompt_formatting import PromptMetadata, count_message_tokens
from onyx.configs.constants import DEFAULT_PERSONA_ID, MessageType
from onyx.db.chat import (
    create_chat_session,
)
from onyx.db.chat_response_messages import read_response_steps
from onyx.db.enums import IncognitoRecordMode, record_mode_persists_content
from onyx.db.models import ChatMessage, ChatSession, User
from onyx.db.persona import user_can_access_persona
from onyx.db.projects import check_project_ownership
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
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
from onyx.server.query_and_chat.models import (
    ChatSessionCreationRequest,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

IMAGE_GENERATION_TOOL_NAME = "generate_image"


def create_chat_session_from_request(
    chat_session_request: ChatSessionCreationRequest,
    user: User,
    db_session: Session,
) -> ChatSession:
    """Create a chat session from a ChatSessionCreationRequest.

    Includes project ownership and persona access validation.

    Args:
        chat_session_request: The request containing persona_id, description, and project_id
        user: The user creating the session. Anonymous users are represented as a
            User with is_anonymous=True (never None); the access-check helpers
            handle that case. A real User is required so the persona access check
            always runs — do not introduce a None-tolerant caller.
        db_session: The database session

    Returns:
        The newly created ChatSession

    Raises:
        ValueError: If user lacks access to the specified project or persona
        Exception: If the persona is invalid
    """
    project_id = chat_session_request.project_id
    if project_id:
        if not check_project_ownership(project_id, user.id, db_session):
            raise ValueError("User does not have access to project")

    persona_id = chat_session_request.persona_id
    if persona_id != DEFAULT_PERSONA_ID:
        if not user_can_access_persona(
            db_session=db_session,
            persona_id=persona_id,
            user=user,
            get_editable=False,
        ):
            raise ValueError("User does not have access to persona")

    # Pinned at creation so a later setting change cannot alter a live session.
    # Availability decides server-side, never the client flag. A refusal
    # errors: degrading would silently persist a believed-incognito chat.
    # The capability is checked first so a deployment that cannot hold the
    # context says so, rather than reporting it as a permission the admin
    # could grant.
    incognito_mode: IncognitoRecordMode | None = None
    if chat_session_request.incognito:
        if not incognito_context_available():
            raise OnyxError(
                OnyxErrorCode.DEPLOYMENT_UNSUPPORTED,
                "Incognito chat is not supported on this deployment.",
            )
        if not incognito_allowed_for_user(user, db_session, cached=False):
            raise OnyxError(
                OnyxErrorCode.UNAUTHORIZED,
                "Incognito chat is not enabled for this user.",
            )
        incognito_mode = resolve_incognito_record_mode()

    # A caller-supplied title is conversation-derived, so a content-free
    # session stores none of it.
    description = (
        chat_session_request.description or ""
        if record_mode_persists_content(incognito_mode)
        else ""
    )

    chat_session = create_chat_session(
        db_session=db_session,
        description=description,
        user_id=user.id,
        persona_id=chat_session_request.persona_id,
        project_id=chat_session_request.project_id,
        incognito_record_mode=incognito_mode,
        session_id=(
            chat_session_request.incognito_session_id if incognito_mode else None
        ),
    )
    return chat_session


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
                    messages_from_steps(read_response_steps(message)),
                    copy_messages=False,
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
