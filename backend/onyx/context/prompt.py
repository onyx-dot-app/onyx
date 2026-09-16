"""Assemble Onyx instructions and file context for the shared agent runtime."""

import json
from collections.abc import Callable

from pydantic import BaseModel, Field

from onyx.context.messages import (
    PromptMetadata,
    count_message_tokens,
    prepare_model_messages,
    prompt_metadata,
)
from onyx.file_store.models import ExtractedContextFiles, FileToolMetadata
from onyx.llm.interfaces import LLMInfo
from onyx.llm.models import Message, ToolResultMessage, UserMessage
from onyx.prompts.chat_prompts import TOOL_CALL_RESPONSE_CROSS_MESSAGE


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


def prepare_prompt(
    messages: list[Message],
    *,
    system_prompt: Message | None,
    custom_agent_prompt: Message | None,
    reminder_message: Message | None,
    context_files: ExtractedContextFiles | None,
    token_counter: Callable[[str], int],
    all_injected_file_metadata: dict[str, FileToolMetadata] | None = None,
    llm_info: LLMInfo | None = None,
) -> list[Message]:
    """Assemble instructions and file context without discarding execution history."""
    history = [message.model_copy(deep=True) for message in messages]
    for message in history:
        metadata = prompt_metadata(message)
        if isinstance(message, ToolResultMessage) and metadata.omit_tool_result_content:
            # Keep stored evidence intact; later questions use the existing placeholder.
            message.content = TOOL_CALL_RESPONSE_CROSS_MESSAGE
            metadata.token_count = None
        metadata.token_count = count_message_tokens(message, token_counter)
        message.metadata = metadata
    insertion = next(
        (
            index
            for index in range(len(history) - 1, -1, -1)
            if isinstance(history[index], UserMessage)
            and not prompt_metadata(history[index]).is_reminder
        ),
        len(history),
    )
    result: list[Message] = []
    if system_prompt is not None:
        system_prompt = system_prompt.model_copy(deep=True)
        metadata = prompt_metadata(system_prompt)
        metadata.should_cache = True
        system_prompt.metadata = metadata
        result.append(system_prompt)
    result.extend(history[:insertion])
    if custom_agent_prompt is not None:
        result.append(custom_agent_prompt)
    result.extend(_build_project_message(context_files, token_counter))
    present_files = {prompt_metadata(message).file_id for message in history}
    omitted_files = [
        metadata
        for file_id, metadata in (all_injected_file_metadata or {}).items()
        if file_id not in present_files
    ]
    if omitted_files:
        result.append(_create_file_tool_metadata_message(omitted_files, token_counter))
    result.extend(history[insertion:])
    if reminder_message is not None:
        result.append(reminder_message)
    return prepare_model_messages(result, llm_info) if llm_info else result


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
