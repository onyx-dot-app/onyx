import json
from collections.abc import Callable

from sqlalchemy.orm import Session

from onyx.chat.files import build_file_context
from onyx.chat.incognito import (
    incognito_allowed_for_user,
    resolve_incognito_record_mode,
)
from onyx.chat.incognito_context import incognito_context_available
from onyx.chat.models import ChatHistoryResult, ChatMessageSimple, ToolCallSimple
from onyx.configs.constants import (
    DEFAULT_PERSONA_ID,
    MessageType,
)
from onyx.db.chat import (
    create_chat_session,
)
from onyx.db.enums import (
    IncognitoRecordMode,
    record_mode_persists_content,
)
from onyx.db.models import ChatMessage, ChatSession, Persona, User
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
from onyx.prompts.chat_prompts import (
    ADDITIONAL_CONTEXT_PROMPT,
    NON_VISION_IMAGE_MARKER,
    TOOL_CALL_RESPONSE_CROSS_MESSAGE,
)
from onyx.prompts.tool_prompts import TOOL_CALL_FAILURE_PROMPT
from onyx.server.query_and_chat.models import ChatSessionCreationRequest
from onyx.tools.models import ToolCallKickoff
from onyx.utils.logger import setup_logger

logger = setup_logger()
IMAGE_GENERATION_TOOL_NAME = "generate_image"


# Used when no token_counter is available to measure the non-vision image
# marker; intentionally generous so budgeting stays conservative.
_NON_VISION_MARKER_TOKEN_FALLBACK = 40


def count_message_replay_tokens(
    msg: ChatMessageSimple,
    *,
    image_files_replayed_as_markers: bool = False,
    token_counter: Callable[[str], int] | None = None,
) -> int:
    if not image_files_replayed_as_markers:
        return msg.token_count
    # Include images whose stored cost is zero, such as project images.
    num_images: int = sum(
        1 for f in msg.image_files or [] if f.file_type == ChatFileType.IMAGE
    )
    if not num_images:
        return msg.token_count
    sample_marker: str = NON_VISION_IMAGE_MARKER.format(file_id="0" * 36)
    marker_tokens: int = (
        token_counter(sample_marker)
        if token_counter
        else _NON_VISION_MARKER_TOKEN_FALLBACK
    )
    return max(0, msg.token_count - msg.image_token_count) + num_images * marker_tokens


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
) -> list[ChatMessageSimple]:
    """Convert ChatMessage history to ChatMessageSimple format with no tool calls or files included.

    Args:
        chat_history: List of ChatMessage objects to convert
        token_counter: Function to count tokens in a message string
        max_individual_message_tokens: If set, messages exceeding this number of tokens are dropped.
            If None, no messages are dropped based on individual token count.
        max_total_tokens: If set, maximum number of tokens allowed for the entire history.
            If None, the history is not trimmed based on total token count.

    Returns:
        List of ChatMessageSimple objects
    """
    # Defensive: treat a non-positive total budget as "no history".
    if max_total_tokens is not None and max_total_tokens <= 0:
        return []

    # Convert only the core USER/ASSISTANT messages; omit files and tool calls.
    converted: list[ChatMessageSimple] = []
    for chat_message in chat_history:
        if chat_message.message_type not in (MessageType.USER, MessageType.ASSISTANT):
            continue

        message = chat_message.message or ""
        token_count = getattr(chat_message, "token_count", None)  # ods: ignore[getattr]
        if token_count is None:
            token_count = token_counter(message)

        # Drop any single message that would dominate the context window.
        if (
            max_individual_message_tokens is not None
            and token_count > max_individual_message_tokens
        ):
            continue

        converted.append(
            ChatMessageSimple(
                message=message,
                token_count=token_count,
                message_type=chat_message.message_type,
                image_files=None,
            )
        )

    if max_total_tokens is None:
        return converted

    # Enforce a max total budget by keeping a contiguous suffix of the conversation.
    trimmed_reversed: list[ChatMessageSimple] = []
    total_tokens = 0
    for msg in reversed(converted):
        if total_tokens + msg.token_count > max_total_tokens:
            break
        trimmed_reversed.append(msg)
        total_tokens += msg.token_count

    return list(reversed(trimmed_reversed))


def _build_tool_call_response_history_message(
    tool_name: str,
    generated_images: list[dict] | None,
    tool_call_response: str | None,
) -> str:
    if tool_name != IMAGE_GENERATION_TOOL_NAME:
        return TOOL_CALL_RESPONSE_CROSS_MESSAGE

    if generated_images:
        llm_image_context: list[dict[str, str]] = []
        for image in generated_images:
            file_id = image.get("file_id")
            revised_prompt = image.get("revised_prompt")
            if not isinstance(file_id, str):
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


def convert_chat_history(
    chat_history: list[ChatMessage],
    files: list[ChatLoadedFile],
    context_image_files: list[ChatLoadedFile],
    additional_context: str | None,
    token_counter: Callable[[str], int],
    tool_id_to_name_map: dict[int, str],
) -> ChatHistoryResult:
    """Convert ChatMessage history to ChatMessageSimple format.

    For user messages: includes attached files (images attached to message, text files as separate messages)
    For assistant messages with tool calls: creates ONE ASSISTANT message with tool_calls array,
        followed by N TOOL_CALL_RESPONSE messages (OpenAI parallel tool calling format)
    For assistant messages without tool calls: creates a simple ASSISTANT message

    Every injected text-file message is tagged with ``file_id`` and its
    metadata is collected in ``ChatHistoryResult.all_injected_file_metadata``.
    After context-window truncation, callers compare surviving ``file_id`` tags
    against this map to discover "forgotten" files and provide their metadata
    to the FileReaderTool.
    """
    simple_messages: list[ChatMessageSimple] = []
    all_injected_file_metadata: dict[str, FileToolMetadata] = {}

    # Create a mapping of file IDs to loaded files for quick lookup
    file_map = {str(f.file_id): f for f in files}

    # Find the index of the last USER message
    last_user_message_idx = None
    for i in range(len(chat_history) - 1, -1, -1):
        if chat_history[i].message_type == MessageType.USER:
            last_user_message_idx = i
            break

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
                simple_messages.append(ctx.message)
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
                    simple_messages.append(
                        ChatMessageSimple(
                            message=ADDITIONAL_CONTEXT_PROMPT.format(
                                additional_context=additional_context
                            ),
                            token_count=token_counter(additional_context),
                            message_type=MessageType.USER,
                            image_files=None,
                        )
                    )

            simple_messages.append(
                ChatMessageSimple(
                    message=chat_message.message,
                    token_count=chat_message.token_count + image_token_count,
                    message_type=MessageType.USER,
                    image_files=image_files or None,
                    image_token_count=image_token_count,
                )
            )

        elif chat_message.message_type == MessageType.ASSISTANT:
            # Handle tool calls if present using OpenAI parallel tool calling format:
            # 1. Group tool calls by turn_number
            # 2. For each turn: ONE ASSISTANT message with tool_calls array
            # 3. Followed by N TOOL_CALL_RESPONSE messages (one per tool call)
            if chat_message.tool_calls:
                # Group tool calls by turn number
                tool_calls_by_turn: dict[int, list] = {}
                for tool_call in chat_message.tool_calls:
                    if tool_call.turn_number not in tool_calls_by_turn:
                        tool_calls_by_turn[tool_call.turn_number] = []
                    tool_calls_by_turn[tool_call.turn_number].append(tool_call)

                # Sort turns and process each turn
                for turn_number in sorted(tool_calls_by_turn.keys()):
                    turn_tool_calls = tool_calls_by_turn[turn_number]
                    # Sort by tool_id within the turn for consistent ordering
                    turn_tool_calls.sort(key=lambda tc: tc.tool_id)

                    # Build ToolCallSimple list for this turn
                    tool_calls_simple: list[ToolCallSimple] = []
                    for tool_call in turn_tool_calls:
                        tool_name = tool_id_to_name_map.get(
                            tool_call.tool_id, "unknown"
                        )
                        tool_calls_simple.append(
                            ToolCallSimple(
                                tool_call_id=tool_call.tool_call_id,
                                tool_name=tool_name,
                                tool_arguments=tool_call.tool_call_arguments or {},
                                token_count=tool_call.tool_call_tokens,
                            )
                        )

                    # Create ONE ASSISTANT message with all tool calls for this turn
                    total_tool_call_tokens = sum(
                        tc.token_count for tc in tool_calls_simple
                    )
                    simple_messages.append(
                        ChatMessageSimple(
                            message="",  # No text content when making tool calls
                            token_count=total_tool_call_tokens,
                            message_type=MessageType.ASSISTANT,
                            tool_calls=tool_calls_simple,
                            image_files=None,
                        )
                    )

                    # Add TOOL_CALL_RESPONSE messages for each tool call in this turn
                    for tool_call in turn_tool_calls:
                        tool_name = tool_id_to_name_map.get(
                            tool_call.tool_id, "unknown"
                        )
                        tool_response_message = (
                            _build_tool_call_response_history_message(
                                tool_name=tool_name,
                                generated_images=tool_call.generated_images,
                                tool_call_response=tool_call.tool_call_response,
                            )
                        )
                        simple_messages.append(
                            ChatMessageSimple(
                                message=tool_response_message,
                                token_count=token_counter(tool_response_message),
                                message_type=MessageType.TOOL_CALL_RESPONSE,
                                tool_call_id=tool_call.tool_call_id,
                                image_files=None,
                            )
                        )

            # Add the assistant message itself (the final answer)
            simple_messages.append(
                ChatMessageSimple(
                    message=chat_message.message,
                    token_count=chat_message.token_count,
                    message_type=MessageType.ASSISTANT,
                    image_files=None,
                )
            )
        else:
            raise ValueError(
                f"Invalid message type when constructing simple history: {chat_message.message_type}"
            )

    return ChatHistoryResult(
        simple_messages=simple_messages,
        all_injected_file_metadata=all_injected_file_metadata,
    )


def get_custom_agent_prompt(persona: Persona, chat_session: ChatSession) -> str | None:
    """Combine project and agent instructions without repeating a replacement prompt."""
    project_instructions: str | None = (
        chat_session.project.instructions if chat_session.project else None
    )
    agent_instructions: str | None = (
        persona.system_prompt if persona.id != DEFAULT_PERSONA_ID else None
    )
    if persona.replace_base_system_prompt:
        # The agent instructions already appear in the system message.
        return project_instructions or None
    if project_instructions and agent_instructions:
        return (
            f"Project instructions:\n{project_instructions}\n\n"
            f"Agent instructions:\n{agent_instructions}\n\n"
            "If these instructions conflict, follow the agent instructions."
        )
    return agent_instructions or project_instructions or None


def is_last_assistant_message_clarification(chat_history: list[ChatMessage]) -> bool:
    """Check if the last assistant message in chat history was a clarification question.

    This is used in the deep research flow to determine whether to skip the
    clarification step when the user has already responded to a clarification.

    Args:
        chat_history: List of ChatMessage objects in chronological order

    Returns:
        True if the last assistant message has is_clarification=True, False otherwise
    """
    for message in reversed(chat_history):
        if message.message_type == MessageType.ASSISTANT:
            return message.is_clarification
    return False


def create_tool_call_failure_messages(
    tool_calls: list[ToolCallKickoff], token_counter: Callable[[str], int]
) -> list[ChatMessageSimple]:
    """Create ChatMessageSimple objects for failed tool calls.

    Creates messages using OpenAI parallel tool calling format:
    1. An ASSISTANT message with tool_calls field containing all failed tool calls
    2. A TOOL_CALL_RESPONSE failure message for each tool call

    Args:
        tool_calls: List of ToolCallKickoff objects representing the failed tool calls
        token_counter: Function to count tokens in a message string

    Returns:
        List containing ChatMessageSimple objects: one assistant message with all tool calls
        followed by a failure response for each tool call
    """
    if not tool_calls:
        return []

    # Create ToolCallSimple for each failed tool call
    tool_calls_simple: list[ToolCallSimple] = []
    for tool_call in tool_calls:
        tool_call_token_count = token_counter(tool_call.to_msg_str())
        tool_calls_simple.append(
            ToolCallSimple(
                tool_call_id=tool_call.tool_call_id,
                tool_name=tool_call.tool_name,
                tool_arguments=tool_call.tool_args,
                token_count=tool_call_token_count,
            )
        )

    total_token_count = sum(tc.token_count for tc in tool_calls_simple)

    # Create ONE ASSISTANT message with all tool_calls (OpenAI format)
    assistant_msg = ChatMessageSimple(
        message="",  # No text content when making tool calls
        token_count=total_token_count,
        message_type=MessageType.ASSISTANT,
        tool_calls=tool_calls_simple,
        image_files=None,
    )

    messages: list[ChatMessageSimple] = [assistant_msg]

    messages.extend(
        create_tool_call_failure_response(tool_call.tool_call_id)
        for tool_call in tool_calls
    )

    return messages


def create_tool_call_failure_response(tool_call_id: str) -> ChatMessageSimple:
    return ChatMessageSimple(
        message=TOOL_CALL_FAILURE_PROMPT,
        token_count=50,  # Tiny overestimate
        message_type=MessageType.TOOL_CALL_RESPONSE,
        tool_call_id=tool_call_id,
        image_files=None,
    )
