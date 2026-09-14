"""Fit conversation history and Onyx file context into a generation budget."""

import json
from collections.abc import Callable

from pydantic import BaseModel, Field

from onyx.context.messages import PromptMetadata, count_message_tokens, prompt_metadata
from onyx.file_store.models import ChatFileType, ExtractedContextFiles, FileToolMetadata
from onyx.llm.models import AssistantMessage, Message, ToolResultMessage, UserMessage
from onyx.prompts.chat_prompts import NON_VISION_IMAGE_MARKER
from onyx.utils.logger import setup_logger

logger = setup_logger()


class _ContextDocument(BaseModel):
    document: int
    title: str | None = None
    contents: str


class _ContextDocuments(BaseModel):
    documents: list[_ContextDocument] = Field(default_factory=list)


def _build_project_message(
    context_files: ExtractedContextFiles | None,
    token_counter: Callable[[str], int] | None,
) -> list[Message]:
    """Include file contents and metadata for files available through the reader tool."""
    if not context_files:
        return []

    messages: list[Message] = []
    if context_files.file_texts:
        messages.append(_create_context_files_message(context_files))
    if context_files.file_metadata_for_tool and token_counter:
        messages.append(
            _create_file_tool_metadata_message(
                context_files.file_metadata_for_tool, token_counter
            )
        )
    return messages


def _message_replay_tokens(
    msg: Message,
    image_files_replayed_as_markers: bool,
    marker_tokens: int,
    token_counter: Callable[[str], int],
) -> int:
    if not image_files_replayed_as_markers:
        return count_message_tokens(msg, token_counter)
    # Charge markers for every IMAGE entry, including ones whose stored
    # token contribution is zero (project/context images are never
    # counted) — the marker text is still sent for them.
    num_images = sum(
        1
        for f in prompt_metadata(msg).image_files or []
        if f.file_type == ChatFileType.IMAGE
    )
    if not num_images:
        return count_message_tokens(msg, token_counter)
    return (
        max(
            0,
            count_message_tokens(msg, token_counter)
            - prompt_metadata(msg).image_token_count,
        )
        + num_images * marker_tokens
    )


def prepare_prompt(
    system_prompt: Message | None,
    custom_agent_prompt: Message | None,
    messages: list[Message],
    reminder_message: Message | None,
    context_files: ExtractedContextFiles | None,
    available_tokens: int,
    token_counter: Callable[[str], int],
    last_n_user_messages: int | None = None,
    all_injected_file_metadata: dict[str, FileToolMetadata] | None = None,
    image_files_replayed_as_markers: bool = False,
) -> list[Message]:
    prepared: list[Message] = []
    for message in messages:
        copied = message.model_copy(deep=True)
        metadata = prompt_metadata(copied)
        metadata.token_count = count_message_tokens(copied, token_counter)
        copied.metadata = metadata
        prepared.append(copied)
    messages = prepared
    if system_prompt is not None:
        system_prompt = system_prompt.model_copy(deep=True)
        metadata = prompt_metadata(system_prompt)
        metadata.should_cache = True
        system_prompt.metadata = metadata
    if last_n_user_messages is not None and last_n_user_messages <= 0:
        raise ValueError("last_n_user_messages must be greater than 0")

    # Budget each message at its replay cost: when the model takes no image
    # input, prepare_model_messages sends short text markers instead
    # of the images, so charging the stored image token cost would evict
    # history that actually fits.
    marker_tokens = 0
    if image_files_replayed_as_markers:
        sample_marker = NON_VISION_IMAGE_MARKER.format(file_id="0" * 36)
        marker_tokens = token_counter(sample_marker)

    def _replay_token_count(msg: Message) -> int:
        return _message_replay_tokens(
            msg, image_files_replayed_as_markers, marker_tokens, token_counter
        )

    # Build the project / file-metadata messages up front so we can use their
    # actual token counts for the budget.
    project_messages = _build_project_message(context_files, token_counter)
    project_messages_tokens = sum(
        count_message_tokens(m, token_counter) for m in project_messages
    )

    history_token_budget = available_tokens
    history_token_budget -= (
        count_message_tokens(system_prompt, token_counter) if system_prompt else 0
    )
    history_token_budget -= (
        count_message_tokens(custom_agent_prompt, token_counter)
        if custom_agent_prompt
        else 0
    )
    history_token_budget -= project_messages_tokens
    history_token_budget -= (
        count_message_tokens(reminder_message, token_counter) if reminder_message else 0
    )

    if history_token_budget < 0:
        raise ValueError("Not enough tokens available to construct message history")

    # If no history, build minimal context
    if not messages:
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
            for i, msg in enumerate(messages)
            if isinstance(msg, UserMessage) and not prompt_metadata(msg).is_reminder
        ]

        if not user_msg_indices:
            raise ValueError("No user message found in messages")

        # If we have more than n user messages, keep only the last n
        if len(user_msg_indices) > last_n_user_messages:
            # Find the index of the n-th user message from the end
            # For example, if last_n_user_messages=2, we want the 2nd-to-last user message
            nth_user_msg_index = user_msg_indices[-(last_n_user_messages)]
            # Keep everything from that user message onwards
            messages = messages[nth_user_msg_index:]

    # Find the last USER message in the history
    # The history may contain tool calls and responses after the last user message
    last_user_msg_index = None
    for i in range(len(messages) - 1, -1, -1):
        if (
            isinstance(messages[i], UserMessage)
            and not prompt_metadata(messages[i]).is_reminder
        ):
            last_user_msg_index = i
            break

    if last_user_msg_index is None:
        raise ValueError("No user message found in messages")

    # Split history into three parts:
    # 1. History before the last user message
    # 2. The last user message
    # 3. Messages after the last user message (tool calls, responses, etc.)
    history_before_last_user = messages[:last_user_msg_index]
    last_user_message = messages[last_user_msg_index]
    messages_after_last_user = messages[last_user_msg_index + 1 :]

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

    truncated_history_before, forgotten_files_message = _fit_history_and_file_metadata(
        history_before_last_user,
        messages,
        remaining_budget,
        _replay_token_count,
        all_injected_file_metadata,
        token_counter,
    )

    # Keep request instructions before the latest user message and reminders last.
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


def _fit_history_and_file_metadata(
    history_before_last_user: list[Message],
    messages: list[Message],
    remaining_budget: int,
    replay_token_count: Callable[[Message], int],
    all_injected_file_metadata: dict[str, FileToolMetadata] | None,
    token_counter: Callable[[str], int] | None,
) -> tuple[list[Message], Message | None]:
    """Keep recent history and describe files removed from context."""
    # Truncate history_before_last_user from the top to fit in remaining budget.
    # Track dropped file messages so we can provide their metadata to the
    # FileReaderTool instead.
    truncated_history_before: list[Message] = []
    current_token_count = 0

    for msg in reversed(history_before_last_user):
        msg_tokens = replay_token_count(msg)
        if current_token_count + msg_tokens <= remaining_budget:
            prompt_metadata(msg).should_cache = True
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
        file_id
        for msg in history_before_last_user[: len(history_before_last_user) - num_kept]
        if (file_id := prompt_metadata(msg).file_id) is not None
    ]

    # Also treat "orphaned" metadata entries as dropped -- these are files
    # from messages removed by summary truncation (before convert_chat_history
    # ran), so no Message was ever tagged with their file_id.
    if all_injected_file_metadata:
        surviving_file_ids = {
            prompt_metadata(msg).file_id
            for msg in messages
            if prompt_metadata(msg).file_id is not None
        }
        for fid in all_injected_file_metadata:
            if fid not in surviving_file_ids and fid not in dropped_file_ids:
                dropped_file_ids.append(fid)

    # Build a forgotten-files metadata message if any file messages were
    # dropped AND we have metadata for them (meaning the FileReaderTool is
    # available). Reserve tokens for this message in the budget.
    forgotten_files_message: Message | None = None
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
            remaining_budget -= count_message_tokens(
                forgotten_files_message, token_counter
            )
            while truncated_history_before and current_token_count > remaining_budget:
                evicted = truncated_history_before.pop(0)
                current_token_count -= replay_token_count(evicted)
                # If the evicted message is itself a file, add it to the
                # forgotten metadata (it's now dropped too).
                if (
                    (file_id := prompt_metadata(evicted).file_id) is not None
                    and file_id in all_injected_file_metadata
                    and file_id not in {m.file_id for m in forgotten_meta}
                ):
                    forgotten_meta.append(all_injected_file_metadata[file_id])
                    # Rebuild the message with the new entry
                    forgotten_files_message = _create_file_tool_metadata_message(
                        forgotten_meta, token_counter
                    )

    return truncated_history_before, forgotten_files_message


def _drop_orphaned_tool_call_responses(
    messages: list[Message],
) -> list[Message]:
    """Drop tool response messages whose tool_call_id is not in prior assistant tool calls.

    This can happen when history truncation drops an ASSISTANT tool-call message but
    leaves a later TOOL_CALL_RESPONSE message in context. Some providers (e.g. Ollama)
    reject such history with an "unexpected tool call id" error.
    """
    known_tool_call_ids: set[str] = set()
    sanitized: list[Message] = []

    for msg in messages:
        if isinstance(msg, AssistantMessage) and msg.tool_calls:
            for tool_call in msg.tool_calls:
                known_tool_call_ids.add(tool_call.id)
            sanitized.append(msg)
            continue

        if isinstance(msg, ToolResultMessage):
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
) -> Message:
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
    return UserMessage(
        content=message_content,
        metadata=PromptMetadata(token_count=token_counter(message_content)),
    )


def _create_context_files_message(
    context_files: ExtractedContextFiles,
) -> Message:
    """Build a user message with numbered document text and titles."""
    documents: list[_ContextDocument] = []
    for idx, file_text in enumerate(context_files.file_texts, start=1):
        title = (
            context_files.file_metadata[idx - 1].filename
            if idx - 1 < len(context_files.file_metadata)
            else None
        )
        documents.append(
            _ContextDocument(document=idx, title=title or None, contents=file_text)
        )

    documents_json = json.dumps(
        _ContextDocuments(documents=documents).model_dump(exclude_none=True), indent=2
    )
    message_content = f"Here are some documents provided for context, they may not all be relevant:\n{documents_json}"

    # Use pre-calculated token count from context_files
    return UserMessage(
        content=message_content,
        metadata=PromptMetadata(token_count=context_files.total_token_count),
    )
