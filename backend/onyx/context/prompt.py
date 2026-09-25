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
from onyx.llm.interfaces import LLMConfig
from onyx.llm.models import Message, ToolResultMessage, UserMessage
from onyx.prompts.chat_prompts import TOOL_CALL_RESPONSE_CROSS_MESSAGE
from onyx.tools.constants import FILE_READER_TOOL_NAME
from onyx.tools.tool_implementations.python.python_tool import PythonTool
from onyx.tools.tool_implementations.search.search_tool import SearchTool


class _ContextDocument(BaseModel):
    document: int
    title: str | None = None
    contents: str


class _ContextDocuments(BaseModel):
    documents: list[_ContextDocument] = Field(default_factory=list)


def _build_project_message(
    context_files: ExtractedContextFiles | None,
    token_counter: Callable[[str], int] | None,
    available_tool_names: set[str] | None = None,
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
                context_files.file_metadata_for_tool,
                token_counter,
                available_tool_names,
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
    llm_config: LLMConfig | None = None,
    available_tool_names: set[str] | None = None,
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
    result.extend(
        _build_project_message(context_files, token_counter, available_tool_names)
    )
    present_files = {prompt_metadata(message).file_id for message in history}
    omitted_files = [
        metadata
        for file_id, metadata in (all_injected_file_metadata or {}).items()
        if file_id not in present_files
    ]
    if omitted_files:
        result.append(
            _create_file_tool_metadata_message(
                omitted_files, token_counter, available_tool_names
            )
        )
    result.extend(history[insertion:])
    if reminder_message is not None:
        result.append(reminder_message)
    return prepare_model_messages(result, llm_config) if llm_config else result


def _create_file_tool_metadata_message(
    file_metadata: list[FileToolMetadata],
    token_counter: Callable[[str], int],
    available_tool_names: set[str] | None = None,
) -> Message:
    """Build a lightweight metadata-only message listing files not held in context.

    Name only a tool this step actually received. FileReaderTool is attached
    only when the vector DB is disabled, and internal search can be absent even
    when it is enabled (persona, ``allowed_tool_ids``, or a disabled search
    usage setting). Naming a tool the model was never given makes it invent
    workarounds — it searches the web for the document or guesses the contents.

    Preference order is read_file, then internal search, then the python tool.
    read_file pages through a file directly; search retrieves from the indexed
    copy; the python tool is handed the files themselves, so prompt truncation
    does not take them away from it.

    The python tier applies only when every listed file actually reached
    ``chat_files_for_tools`` (see ``FileToolMetadata.staged_for_tools``) —
    summary-truncated files are listed for the LLM but never staged, so naming
    python for them would send the model after bytes it does not have. The
    notice also stops short of promising a path, because PythonTool normalizes
    and de-duplicates filenames at staging time and applies its own count and
    byte caps.

    An unreported tool set names no tool. Steps that offer none are common (a
    deep-research final report runs with no tools), and under-promising is the
    safe direction to fail in.
    """
    offered: set[str] = available_tool_names or set()
    if FILE_READER_TOOL_NAME in offered:
        lines: list[str] = [
            "You have access to the following files. Use the read_file tool to "
            "read sections of any file. You MUST pass the file_id UUID (not the "
            "filename) to read_file:"
        ]
        # The UUID is only meaningful to read_file, so it is listed only here.
        lines.extend(
            f'- file_id="{meta.file_id}" filename="{meta.filename}" (~{meta.approx_char_count:,} chars)'
            for meta in file_metadata
        )
        return _finalize_file_metadata_message(lines, token_counter)

    if SearchTool.NAME in offered:
        lines = [
            "These files are attached but too large to include in full. Their "
            "contents are indexed — use internal search to find the relevant "
            "passages. Do not guess them or search the web for them:"
        ]
    elif PythonTool.NAME in offered and all(
        meta.staged_for_tools for meta in file_metadata
    ):
        lines = [
            "These files are attached but too large to include in full. The "
            "python tool receives them — read them there, listing the working "
            "directory if a name does not resolve. Do not guess their contents "
            "or search the web for them:"
        ]
    else:
        lines = [
            "These files are attached but too large to include in full, and no "
            "tool here can read them. Do not guess their contents or search the "
            "web for them — say they are too large to read in this conversation:"
        ]
    lines.extend(
        f'- filename="{meta.filename}" (~{meta.approx_char_count:,} chars)'
        for meta in file_metadata
    )
    return _finalize_file_metadata_message(lines, token_counter)


def _finalize_file_metadata_message(
    lines: list[str],
    token_counter: Callable[[str], int],
) -> Message:
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
