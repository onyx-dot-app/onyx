import json
from collections.abc import Callable, Sequence
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError
from sqlalchemy.orm import Session

from onyx.chat.llm_step import (
    PromptMetadata,
    count_message_tokens,
    prepare_model_messages,
    prompt_metadata,
)
from onyx.context.search.models import SearchDocsResponse
from onyx.db.enums import SUPPORTED_LANGUAGE_ENGLISH_NAMES, SupportedLanguage
from onyx.db.memory import UserMemoryContext
from onyx.db.persona import get_default_behavior_persona
from onyx.db.user_file import calculate_user_files_token_count
from onyx.file_store.models import (
    ExtractedContextFiles,
    FileDescriptor,
    FileToolMetadata,
)
from onyx.llm.interfaces import LLMConfig
from onyx.llm.models import AssistantMessage, Message, ToolResultMessage, UserMessage
from onyx.prompts.chat_prompts import (
    ANSWER_COMPLETENESS_REMINDER,
    ANSWER_COVERAGE_GUIDANCE,
    CITATION_REMINDER,
    DEFAULT_SYSTEM_PROMPT,
    FILE_REMINDER,
    IMAGE_GEN_REMINDER,
    LAST_CYCLE_CITATION_REMINDER,
    OPEN_URL_REMINDER,
    REQUIRE_CITATION_GUIDANCE,
    TOOL_CALL_RESPONSE_CROSS_MESSAGE,
)
from onyx.prompts.prompt_utils import apply_prompt_placeholders, get_company_context
from onyx.prompts.tool_prompts import (
    GENERATE_IMAGE_GUIDANCE,
    INTERNAL_SEARCH_GUIDANCE,
    MEMORY_GUIDANCE,
    OPEN_URLS_GUIDANCE,
    PYTHON_TOOL_GUIDANCE,
    TOOL_DESCRIPTION_SEARCH_GUIDANCE,
    TOOL_SECTION_HEADER,
    WEB_SEARCH_GUIDANCE,
    WEB_SEARCH_SITE_DISABLED_GUIDANCE,
)
from onyx.prompts.user_info import (
    BASIC_INFORMATION_PROMPT,
    ORGANIZATION_PROFILE_PROMPT,
    QUERY_LANGUAGE_PROMPT,
    TEAM_INFORMATION_PROMPT,
    USER_INFORMATION_HEADER,
    USER_LANGUAGE_PROMPT,
    USER_MEMORIES_PROMPT,
    USER_PREFERENCES_PROMPT,
    USER_ROLE_PROMPT,
)
from onyx.tools.constants import FILE_READER_TOOL_NAME
from onyx.tools.interface import Tool
from onyx.tools.tool_implementations.images.image_generation_tool import (
    ImageGenerationTool,
)
from onyx.tools.tool_implementations.memory.memory_tool import MemoryTool
from onyx.tools.tool_implementations.open_url.open_url_tool import OpenURLTool
from onyx.tools.tool_implementations.python.python_tool import PythonTool
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool
from onyx.utils.logger import setup_logger
from onyx.utils.timing import log_function_time

logger = setup_logger()


class _ContextDocument(BaseModel):
    document: int
    title: str | None = None
    contents: str


class _ContextDocuments(BaseModel):
    documents: list[_ContextDocument] = Field(default_factory=list)


class _SearchPassage(BaseModel):
    model_config = ConfigDict(extra="allow")
    __pydantic_extra__: dict[str, JsonValue] = Field(init=False)
    document: int
    content: str


class _SearchPassages(BaseModel):
    model_config = ConfigDict(extra="allow")
    __pydantic_extra__: dict[str, JsonValue] = Field(init=False)
    results: list[_SearchPassage]


def get_default_base_system_prompt(db_session: Session) -> str:
    default_persona = get_default_behavior_persona(db_session)
    return (
        default_persona.system_prompt
        if default_persona and default_persona.system_prompt is not None
        else DEFAULT_SYSTEM_PROMPT
    )


@log_function_time(print_only=True)
def calculate_reserved_tokens(
    db_session: Session,
    persona_system_prompt: str,
    base_system_prompt: str,
    token_counter: Callable[[str], int],
    files: list[FileDescriptor] | None = None,
    user_memory_context: UserMemoryContext | None = None,
) -> int:
    """
    Calculate reserved token count for system prompt and user files.

    This is used for token estimation purposes to reserve space for:
    - The system prompt (base + custom agent prompt + all guidance)
    - User files attached to the message

    Args:
        db_session: Database session
        persona_system_prompt: Custom agent system prompt (can be empty string)
        token_counter: Function that counts tokens in text
        files: List of file descriptors from the chat message (optional)
        user_memory_context: User memory context (optional)

    Returns:
        Total reserved token count
    """
    # This is for token estimation purposes
    fake_system_prompt = build_system_prompt(
        base_system_prompt=base_system_prompt,
        datetime_aware=True,
        user_memory_context=user_memory_context,
        tools=None,
        should_cite_documents=True,
        include_all_guidance=True,
    )

    custom_agent_prompt = persona_system_prompt or ""

    reserved_token_count = token_counter(
        # Annoying that the dict has no attributes now
        custom_agent_prompt + " " + fake_system_prompt
    )

    # Calculate total token count for files in the last message
    file_token_count = 0
    if files:
        # Extract user_file_id from each file descriptor
        user_file_ids: list[UUID] = []
        for file in files:
            uid = file.get("user_file_id")
            if not uid:
                continue
            try:
                user_file_ids.append(UUID(uid))
            except (TypeError, ValueError, AttributeError):
                # Skip invalid user_file_id values
                continue
        if user_file_ids:
            file_token_count = calculate_user_files_token_count(
                user_file_ids, db_session
            )

    reserved_token_count += file_token_count

    return reserved_token_count


def build_reminder_message(
    reminder_text: str | None,
    include_citation_reminder: bool,
    include_file_reminder: bool,
    is_last_cycle: bool,
) -> str | None:
    reminder = reminder_text.strip() if reminder_text else ""
    if is_last_cycle:
        reminder += "\n\n" + LAST_CYCLE_CITATION_REMINDER
    if include_citation_reminder:
        reminder += "\n\n" + CITATION_REMINDER
        reminder += "\n\n" + ANSWER_COMPLETENESS_REMINDER
    if include_file_reminder:
        reminder += "\n\n" + FILE_REMINDER
    reminder = reminder.strip()
    return reminder or None


def process_prompt_template(
    prompt_str: str,
    *,
    datetime_aware: bool,
    append_datetime_if_aware: bool,
    should_cite_documents: bool,
) -> str:
    """Apply standard prompt placeholders to any agent or task prompt."""
    processed_prompt, _ = apply_prompt_placeholders(
        prompt_str,
        datetime_aware=datetime_aware,
        append_datetime_if_aware=append_datetime_if_aware,
        should_cite_documents=should_cite_documents,
        append_citation_if_missing=False,
    )
    return processed_prompt


def build_language_section(language: SupportedLanguage | None) -> str:
    """The branch is decided here so the model never has to notice whether a
    language was given. English is the column default and counts as no choice."""
    if language is None or language is SupportedLanguage.EN:
        return QUERY_LANGUAGE_PROMPT
    return USER_LANGUAGE_PROMPT.format(
        language=SUPPORTED_LANGUAGE_ENGLISH_NAMES[language]
    )


def with_language_section(prompt: str, language_section: str) -> str:
    """Deep research builds its own system prompts, so the reply-language line that
    build_system_prompt adds for chat is appended to the user-facing ones here."""
    return f"{prompt}\n\n{language_section}"


def _build_user_information_section(
    user_memory_context: UserMemoryContext | None,
    company_context: str | None,
) -> str:
    """'# User Information' sub-sections, in order: Basic Info → Organization Profile →
    Team Info → Language → Preferences → Memories."""
    sections: list[str] = []

    if user_memory_context:
        ctx = user_memory_context
        has_basic_info = ctx.user_info.name or ctx.user_info.email or ctx.user_info.role

        if has_basic_info:
            role_line = (
                USER_ROLE_PROMPT.format(user_role=ctx.user_info.role).strip()
                if ctx.user_info.role
                else ""
            )
            if role_line:
                role_line = "\n" + role_line
            sections.append(
                BASIC_INFORMATION_PROMPT.format(
                    user_name=ctx.user_info.name or "",
                    user_email=ctx.user_info.email or "",
                    user_role=role_line,
                )
            )

        if ctx.user_info.organization_profile:
            formatted_profile = "\n".join(
                f"- {label}: {value}"
                for label, value in ctx.user_info.organization_profile.items()
            )
            sections.append(
                ORGANIZATION_PROFILE_PROMPT.format(
                    organization_profile=formatted_profile
                )
            )

    if company_context:
        sections.append(
            TEAM_INFORMATION_PROMPT.format(team_information=company_context.strip())
        )

    # Language sits before Preferences so an explicit preference wins over the hint.
    # Every prompt carries one line, so the model never infers whether a language was set.
    sections.append(
        build_language_section(
            user_memory_context.user_info.language if user_memory_context else None
        )
    )

    if user_memory_context:
        ctx = user_memory_context

        if ctx.user_preferences:
            sections.append(
                USER_PREFERENCES_PROMPT.format(user_preferences=ctx.user_preferences)
            )

        if ctx.memories:
            formatted_memories = "\n".join(f"- {memory}" for memory in ctx.memories)
            sections.append(
                USER_MEMORIES_PROMPT.format(user_memories=formatted_memories)
            )

    return USER_INFORMATION_HEADER + "\n".join(sections)


def build_system_prompt(
    base_system_prompt: str,
    datetime_aware: bool = False,
    user_memory_context: UserMemoryContext | None = None,
    tools: Sequence[Tool] | None = None,
    should_cite_documents: bool = False,
    include_all_guidance: bool = False,
) -> str:
    """Should only be called with the default behavior system prompt.
    If the user has replaced the default behavior prompt with their custom agent prompt, do not call this function.
    """
    system_prompt, should_append_citation_guidance = apply_prompt_placeholders(
        base_system_prompt,
        datetime_aware=datetime_aware,
        append_datetime_if_aware=True,
        should_cite_documents=should_cite_documents,
        include_all_guidance=include_all_guidance,
        append_citation_if_missing=True,
    )

    company_context = get_company_context()
    user_info_section = _build_user_information_section(
        user_memory_context, company_context
    )
    system_prompt += user_info_section

    # Append citation guidance after company context if placeholder was not present
    if should_append_citation_guidance:
        system_prompt += REQUIRE_CITATION_GUIDANCE
        system_prompt += ANSWER_COVERAGE_GUIDANCE

    if include_all_guidance:
        tool_sections = [
            TOOL_DESCRIPTION_SEARCH_GUIDANCE,
            INTERNAL_SEARCH_GUIDANCE,
            WEB_SEARCH_GUIDANCE.format(
                site_colon_disabled=WEB_SEARCH_SITE_DISABLED_GUIDANCE
            ),
            OPEN_URLS_GUIDANCE,
            PYTHON_TOOL_GUIDANCE,
            GENERATE_IMAGE_GUIDANCE,
            MEMORY_GUIDANCE,
        ]
        system_prompt += TOOL_SECTION_HEADER + "\n".join(tool_sections)
        return system_prompt

    if tools:
        has_web_search = any(isinstance(tool, WebSearchTool) for tool in tools)
        has_internal_search = any(isinstance(tool, SearchTool) for tool in tools)
        has_open_urls = any(isinstance(tool, OpenURLTool) for tool in tools)
        has_python = any(isinstance(tool, PythonTool) for tool in tools)
        has_generate_image = any(
            isinstance(tool, ImageGenerationTool) for tool in tools
        )
        has_memory = any(isinstance(tool, MemoryTool) for tool in tools)

        tool_guidance_sections: list[str] = []

        if has_web_search or has_internal_search or include_all_guidance:
            tool_guidance_sections.append(TOOL_DESCRIPTION_SEARCH_GUIDANCE)

        # These are not included at the Tool level because the ordering may matter.
        if has_internal_search or include_all_guidance:
            tool_guidance_sections.append(INTERNAL_SEARCH_GUIDANCE)

        if has_web_search or include_all_guidance:
            site_disabled_guidance = ""
            if has_web_search:
                web_search_tool = next(
                    (t for t in tools if isinstance(t, WebSearchTool)), None
                )
                if web_search_tool and not web_search_tool.supports_site_filter:
                    site_disabled_guidance = WEB_SEARCH_SITE_DISABLED_GUIDANCE
            tool_guidance_sections.append(
                WEB_SEARCH_GUIDANCE.format(site_colon_disabled=site_disabled_guidance)
            )

        if has_open_urls or include_all_guidance:
            tool_guidance_sections.append(OPEN_URLS_GUIDANCE)

        if has_python or include_all_guidance:
            tool_guidance_sections.append(PYTHON_TOOL_GUIDANCE)

        if has_generate_image or include_all_guidance:
            tool_guidance_sections.append(GENERATE_IMAGE_GUIDANCE)

        if has_memory or include_all_guidance:
            tool_guidance_sections.append(MEMORY_GUIDANCE)

        if tool_guidance_sections:
            system_prompt += TOOL_SECTION_HEADER + "\n".join(tool_guidance_sections)

    return system_prompt


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


def _deduplicate_search_passages(messages: list[Message]) -> None:
    """Shorten exact repeats within a step in caller-owned prompt messages."""
    seen: dict[tuple[str, str], str] = {}
    for message in messages:
        if isinstance(message, (AssistantMessage, UserMessage)):
            seen.clear()
            continue
        if not isinstance(message, ToolResultMessage):
            continue
        if (
            message.is_error
            or not isinstance(message.content, str)
            or prompt_metadata(message).omit_tool_result_content
            or not isinstance(message.details, SearchDocsResponse)
            or not message.details.citation_mapping
        ):
            continue
        try:
            passages = _SearchPassages.model_validate_json(message.text)
        except ValidationError:
            # Search metadata can accompany unstructured or historical tool output.
            logger.debug(
                "Search result has no structured passages: %s", message.tool_call_id
            )
            continue
        changed = False
        for passage in passages.results:
            document_id = message.details.citation_mapping[passage.document]
            key = (document_id, passage.content)
            reference = seen.get(key)
            if reference is not None:
                if len(reference) < len(passage.content):
                    passage.content = reference
                    changed = True
                continue
            seen[key] = (
                f"Same passage as document {passage.document} in tool result "
                f"{message.tool_call_id}; use that result's content."
            )
        if changed:
            message.content = passages.model_dump_json()


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
    _deduplicate_search_passages(history)
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
