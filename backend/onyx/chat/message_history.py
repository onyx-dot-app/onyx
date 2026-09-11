import json
from collections.abc import Callable
from typing import Any

from onyx.chat.citation_processor import (
    CitationMapping,
)
from onyx.chat.models import (
    ChatMessageSimple,
    ContextFileMetadata,
    ExtractedContextFiles,
    FileToolMetadata,
)
from onyx.chat.prompt_utils import (
    build_reminder_message,
)
from onyx.configs.constants import DocumentSource, MessageType
from onyx.context.search.models import SearchDoc
from onyx.file_store.models import ChatFileType
from onyx.prompts.chat_prompts import (
    IMAGE_GEN_REMINDER,
    NON_VISION_IMAGE_MARKER,
    OPEN_URL_REMINDER,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Used when no token_counter is available to measure the non-vision image
# marker; intentionally generous so budgeting stays conservative.
_NON_VISION_MARKER_TOKEN_FALLBACK = 40


def build_context_file_citation_mapping(
    file_metadata: list[ContextFileMetadata],
    starting_citation_num: int = 1,
) -> CitationMapping:
    """Build citation mapping for context files.

    Converts context file metadata into SearchDoc objects that can be cited.
    Citation numbers start from the provided starting number.

    Args:
        file_metadata: List of context file metadata
        starting_citation_num: Starting citation number (default: 1)

    Returns:
        Dictionary mapping citation numbers to SearchDoc objects
    """
    citation_mapping: CitationMapping = {}

    for idx, file_meta in enumerate(file_metadata, start=starting_citation_num):
        search_doc = SearchDoc(
            document_id=file_meta.file_id,
            chunk_ind=0,
            semantic_identifier=file_meta.filename,
            link=None,
            blurb=file_meta.file_content,
            source_type=DocumentSource.FILE,
            boost=1,
            hidden=False,
            metadata={},
            score=0.0,
            match_highlights=[file_meta.file_content],
        )
        citation_mapping[idx] = search_doc

    return citation_mapping


def _build_project_message(
    context_files: ExtractedContextFiles | None,
    token_counter: Callable[[str], int] | None,
) -> list[ChatMessageSimple]:
    """Build messages for context-injected / tool-backed files.

    Returns up to two messages:
    1. The full-text files message (if file_texts is populated).
    2. A lightweight metadata message for files the LLM should access via the
       FileReaderTool (e.g. oversized files that don't fit in context).
    """
    if not context_files:
        return []

    messages: list[ChatMessageSimple] = []
    if context_files.file_texts:
        messages.append(
            _create_context_files_message(context_files, token_counter=None)
        )
    if context_files.file_metadata_for_tool and token_counter:
        messages.append(
            _create_file_tool_metadata_message(
                context_files.file_metadata_for_tool, token_counter
            )
        )
    return messages


def construct_message_history(
    system_prompt: ChatMessageSimple | None,
    custom_agent_prompt: ChatMessageSimple | None,
    simple_chat_history: list[ChatMessageSimple],
    reminder_message: ChatMessageSimple | None,
    context_files: ExtractedContextFiles | None,
    available_tokens: int,
    last_n_user_messages: int | None = None,
    token_counter: Callable[[str], int] | None = None,
    all_injected_file_metadata: dict[str, FileToolMetadata] | None = None,
    image_files_replayed_as_markers: bool = False,
) -> list[ChatMessageSimple]:
    if last_n_user_messages is not None:
        if last_n_user_messages <= 0:
            raise ValueError(
                "filtering chat history by last N user messages must be a value greater than 0"
            )

    # Budget each message at its replay cost: when the model takes no image
    # input, translate_history_to_llm_format sends short text markers instead
    # of the images, so charging the stored image token cost would evict
    # history that actually fits.
    marker_tokens = 0
    if image_files_replayed_as_markers:
        sample_marker = NON_VISION_IMAGE_MARKER.format(file_id="0" * 36)
        marker_tokens = (
            token_counter(sample_marker)
            if token_counter
            else _NON_VISION_MARKER_TOKEN_FALLBACK
        )

    def _replay_token_count(msg: ChatMessageSimple) -> int:
        if not image_files_replayed_as_markers:
            return msg.token_count
        # Charge markers for every IMAGE entry, including ones whose stored
        # token contribution is zero (project/context images are never
        # counted) — the marker text is still sent for them.
        num_images = sum(
            1 for f in msg.image_files or [] if f.file_type == ChatFileType.IMAGE
        )
        if not num_images:
            return msg.token_count
        return (
            max(0, msg.token_count - msg.image_token_count) + num_images * marker_tokens
        )

    # Build the project / file-metadata messages up front so we can use their
    # actual token counts for the budget.
    project_messages = _build_project_message(context_files, token_counter)
    project_messages_tokens = sum(m.token_count for m in project_messages)

    history_token_budget = available_tokens
    history_token_budget -= system_prompt.token_count if system_prompt else 0
    history_token_budget -= (
        custom_agent_prompt.token_count if custom_agent_prompt else 0
    )
    history_token_budget -= project_messages_tokens
    history_token_budget -= reminder_message.token_count if reminder_message else 0

    if history_token_budget < 0:
        raise ValueError("Not enough tokens available to construct message history")

    if system_prompt:
        system_prompt.should_cache = True

    # If no history, build minimal context
    if not simple_chat_history:
        result = [system_prompt] if system_prompt else []
        if custom_agent_prompt:
            result.append(custom_agent_prompt)
        result.extend(project_messages)
        if reminder_message:
            result.append(reminder_message)
        return result

    # If last_n_user_messages is set, filter history to only include the last n user messages
    if last_n_user_messages is not None:
        # Find all user message indices
        user_msg_indices = [
            i
            for i, msg in enumerate(simple_chat_history)
            if msg.message_type == MessageType.USER
        ]

        if not user_msg_indices:
            raise ValueError("No user message found in simple_chat_history")

        # If we have more than n user messages, keep only the last n
        if len(user_msg_indices) > last_n_user_messages:
            # Find the index of the n-th user message from the end
            # For example, if last_n_user_messages=2, we want the 2nd-to-last user message
            nth_user_msg_index = user_msg_indices[-(last_n_user_messages)]
            # Keep everything from that user message onwards
            simple_chat_history = simple_chat_history[nth_user_msg_index:]

    # Find the last USER message in the history
    # The history may contain tool calls and responses after the last user message
    last_user_msg_index = None
    for i in range(len(simple_chat_history) - 1, -1, -1):
        if simple_chat_history[i].message_type == MessageType.USER:
            last_user_msg_index = i
            break

    if last_user_msg_index is None:
        raise ValueError("No user message found in simple_chat_history")

    # Split history into three parts:
    # 1. History before the last user message
    # 2. The last user message
    # 3. Messages after the last user message (tool calls, responses, etc.)
    history_before_last_user = simple_chat_history[:last_user_msg_index]
    last_user_message = simple_chat_history[last_user_msg_index]
    messages_after_last_user = simple_chat_history[last_user_msg_index + 1 :]

    # Calculate tokens needed for the last user message and everything after it
    last_user_tokens = _replay_token_count(last_user_message)
    after_user_tokens = sum(
        _replay_token_count(msg) for msg in messages_after_last_user
    )

    # Check if we can fit at least the last user message and messages after it
    required_tokens = last_user_tokens + after_user_tokens
    if required_tokens > history_token_budget:
        raise ValueError(
            f"Not enough tokens to include the last user message and subsequent messages. "
            f"Required: {required_tokens}, Available: {history_token_budget}"
        )

    # Calculate remaining budget for history before the last user message
    remaining_budget = history_token_budget - required_tokens

    # Truncate history_before_last_user from the top to fit in remaining budget.
    # Track dropped file messages so we can provide their metadata to the
    # FileReaderTool instead.
    truncated_history_before: list[ChatMessageSimple] = []
    current_token_count = 0

    for msg in reversed(history_before_last_user):
        msg_tokens = _replay_token_count(msg)
        if current_token_count + msg_tokens <= remaining_budget:
            msg.should_cache = True
            truncated_history_before.insert(0, msg)
            current_token_count += msg_tokens
        else:
            # Can't fit this message, stop truncating.
            # This message and everything older is dropped.
            break

    # Collect file_ids from ALL dropped messages (those not in
    # truncated_history_before). The truncation loop above keeps the most
    # recent messages, so the dropped ones are at the start of the original
    # list up to (len(history) - len(kept)).
    num_kept = len(truncated_history_before)
    dropped_file_ids: list[str] = [
        msg.file_id
        for msg in history_before_last_user[: len(history_before_last_user) - num_kept]
        if msg.file_id is not None
    ]

    # Also treat "orphaned" metadata entries as dropped -- these are files
    # from messages removed by summary truncation (before convert_chat_history
    # ran), so no ChatMessageSimple was ever tagged with their file_id.
    if all_injected_file_metadata:
        surviving_file_ids = {
            msg.file_id for msg in simple_chat_history if msg.file_id is not None
        }
        for fid in all_injected_file_metadata:
            if fid not in surviving_file_ids and fid not in dropped_file_ids:
                dropped_file_ids.append(fid)

    # Build a forgotten-files metadata message if any file messages were
    # dropped AND we have metadata for them (meaning the FileReaderTool is
    # available). Reserve tokens for this message in the budget.
    forgotten_files_message: ChatMessageSimple | None = None
    if dropped_file_ids and all_injected_file_metadata and token_counter:
        forgotten_meta = [
            all_injected_file_metadata[fid]
            for fid in dropped_file_ids
            if fid in all_injected_file_metadata
        ]
        if forgotten_meta:
            logger.debug(
                "FileReader: building forgotten-files message for %s",
                [(m.file_id, m.filename) for m in forgotten_meta],
            )
            forgotten_files_message = _create_file_tool_metadata_message(
                forgotten_meta, token_counter
            )
            # Shrink the remaining budget. If the metadata message doesn't
            # fit we may need to drop more history messages.
            remaining_budget -= forgotten_files_message.token_count
            while truncated_history_before and current_token_count > remaining_budget:
                evicted = truncated_history_before.pop(0)
                current_token_count -= _replay_token_count(evicted)
                # If the evicted message is itself a file, add it to the
                # forgotten metadata (it's now dropped too).
                if (
                    evicted.file_id is not None
                    and evicted.file_id in all_injected_file_metadata
                    and evicted.file_id not in {m.file_id for m in forgotten_meta}
                ):
                    forgotten_meta.append(all_injected_file_metadata[evicted.file_id])
                    # Rebuild the message with the new entry
                    forgotten_files_message = _create_file_tool_metadata_message(
                        forgotten_meta, token_counter
                    )

    # Build the final message list according to README ordering:
    # [system], [history_before_last_user], [custom_agent], [context_files],
    # [forgotten_files], [last_user_message], [messages_after_last_user], [reminder]
    result = [system_prompt] if system_prompt else []

    # 1. Add truncated history before last user message
    result.extend(truncated_history_before)

    # 2. Add custom agent prompt (inserted before last user message)
    if custom_agent_prompt:
        result.append(custom_agent_prompt)

    # 3. Add context files / file-metadata messages (inserted before last user message)
    result.extend(project_messages)

    # 4. Add forgotten-files metadata (right before the user's question)
    if forgotten_files_message:
        result.append(forgotten_files_message)

    # 5. Add last user message (with context images attached)
    result.append(last_user_message)

    # 6. Add messages after last user message (tool calls, responses, etc.)
    result.extend(messages_after_last_user)

    # 7. Add reminder message at the very end
    if reminder_message:
        result.append(reminder_message)

    return _drop_orphaned_tool_call_responses(result)


def _drop_orphaned_tool_call_responses(
    messages: list[ChatMessageSimple],
) -> list[ChatMessageSimple]:
    """Drop tool response messages whose tool_call_id is not in prior assistant tool calls.

    This can happen when history truncation drops an ASSISTANT tool-call message but
    leaves a later TOOL_CALL_RESPONSE message in context. Some providers (e.g. Ollama)
    reject such history with an "unexpected tool call id" error.
    """
    known_tool_call_ids: set[str] = set()
    sanitized: list[ChatMessageSimple] = []

    for msg in messages:
        if msg.message_type == MessageType.ASSISTANT and msg.tool_calls:
            for tool_call in msg.tool_calls:
                known_tool_call_ids.add(tool_call.tool_call_id)
            sanitized.append(msg)
            continue

        if msg.message_type == MessageType.TOOL_CALL_RESPONSE:
            if msg.tool_call_id and msg.tool_call_id in known_tool_call_ids:
                sanitized.append(msg)
            else:
                logger.debug(
                    "Dropping orphaned tool response with tool_call_id=%s while constructing message history",
                    msg.tool_call_id,
                )
            continue

        sanitized.append(msg)

    return sanitized


def _create_file_tool_metadata_message(
    file_metadata: list[FileToolMetadata],
    token_counter: Callable[[str], int],
) -> ChatMessageSimple:
    """Build a lightweight metadata-only message listing files available via FileReaderTool.

    Used when files are too large to fit in context and the vector DB is
    disabled, so the LLM must use ``read_file`` to inspect them.
    """
    lines = [
        "You have access to the following files. Use the read_file tool to "
        "read sections of any file. You MUST pass the file_id UUID (not the "
        "filename) to read_file:"
    ]
    lines.extend(
        f'- file_id="{meta.file_id}" filename="{meta.filename}" (~{meta.approx_char_count:,} chars)'
        for meta in file_metadata
    )

    message_content = "\n".join(lines)
    return ChatMessageSimple(
        message=message_content,
        token_count=token_counter(message_content),
        message_type=MessageType.USER,
    )


def _create_context_files_message(
    context_files: ExtractedContextFiles,
    token_counter: Callable[[str], int] | None,  # noqa: ARG001
) -> ChatMessageSimple:
    """Convert context files to a ChatMessageSimple message.

    Format follows the README specification for document representation.
    """

    # Format as documents JSON as described in README
    documents_list = []
    for idx, file_text in enumerate(context_files.file_texts, start=1):
        title = (
            context_files.file_metadata[idx - 1].filename
            if idx - 1 < len(context_files.file_metadata)
            else None
        )
        entry: dict[str, Any] = {"document": idx}
        if title:
            entry["title"] = title
        entry["contents"] = file_text
        documents_list.append(entry)

    documents_json = json.dumps({"documents": documents_list}, indent=2)
    message_content = f"Here are some documents provided for context, they may not all be relevant:\n{documents_json}"

    # Use pre-calculated token count from context_files
    return ChatMessageSimple(
        message=message_content,
        token_count=context_files.total_token_count,
        message_type=MessageType.USER,
    )


def select_reminder_text(
    *,
    ran_image_gen: bool,
    just_ran_web_search: bool,
    has_open_url_tool: bool,
    out_of_cycles: bool,
    persona_task_prompt: str | None,
    include_citation_reminder: bool,
    include_file_reminder: bool,
) -> str | None:
    """Choose the reminder appended after a tool cycle.

    The open_url nudge is gated on the tool actually being available; otherwise
    the model is told to call a tool it doesn't have and leaks confusing
    "open_url is not available" replies.
    """
    if ran_image_gen:
        return IMAGE_GEN_REMINDER
    if just_ran_web_search and has_open_url_tool and not out_of_cycles:
        return OPEN_URL_REMINDER
    return build_reminder_message(
        reminder_text=persona_task_prompt,
        include_citation_reminder=include_citation_reminder,
        include_file_reminder=include_file_reminder,
        is_last_cycle=out_of_cycles,
    )
