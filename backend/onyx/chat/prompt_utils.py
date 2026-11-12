"""Build chat instructions, reminders, and prompts from conversation history."""

import json
from collections.abc import Callable, Mapping, Sequence
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.orm import Session

from onyx.chat.citation_utils import result_cites_documents
from onyx.chat.models import (
    ChatPrompt,
    ChatReminderContext,
    ContextDocument,
    ContextDocuments,
    PersonaPromptConfig,
    PromptMetadata,
    SearchPassages,
)
from onyx.chat.prompt_formatting import (
    count_message_tokens,
    prepare_model_messages,
    prompt_metadata,
)
from onyx.chat.tool_results import tool_result_parts
from onyx.context.models import UserMemoryContext
from onyx.context.search.models import SearchDocsResponse
from onyx.db.enums import SUPPORTED_LANGUAGE_ENGLISH_NAMES, SupportedLanguage
from onyx.db.persona import get_default_behavior_persona
from onyx.db.user_file import calculate_user_files_token_count
from onyx.file_store.models import (
    ExtractedContextFiles,
    FileDescriptor,
    FileToolMetadata,
)
from onyx.llm.interfaces import LLMConfig
from onyx.llm.models import (
    AssistantMessage,
    Message,
    SystemMessage,
    ToolResultMessage,
    UserMessage,
)
from onyx.prompts.chat_prompts import (
    ANSWER_COMPLETENESS_REMINDER,
    ANSWER_COVERAGE_GUIDANCE,
    DEFAULT_SYSTEM_PROMPT,
    FILE_REMINDER,
    IMAGE_GEN_REMINDER,
    LAST_CYCLE_CITATION_REMINDER,
    OPEN_URL_REMINDER,
    REQUIRE_CITATION_GUIDANCE,
    TOOL_PREFERENCE_GUIDANCE,
    TOOL_PREFERENCE_LAST_STEP_GUIDANCE,
    TOOL_PREFERENCE_REMINDER,
)
from onyx.prompts.prompt_utils import (
    apply_prompt_placeholders,
    get_company_context,
    substitute_user_placeholders,
)
from onyx.prompts.tool_prompts import (
    CODE_MODE_GUIDANCE,
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
    USER_INFORMATION_FRAMING,
    USER_INFORMATION_HEADER,
    USER_LANGUAGE_PROMPT,
    USER_MEMORIES_PROMPT,
    USER_PREFERENCES_PROMPT,
    USER_ROLE_PROMPT,
)
from onyx.tools.constants import CODE_MODE_TOOL_NAME, FILE_READER_TOOL_NAME
from onyx.tools.interface import Tool
from onyx.tools.models import LlmPythonExecutionResult
from onyx.tools.tool_implementations.images.image_generation_tool import (
    ImageGenerationTool,
)
from onyx.tools.tool_implementations.images.models import FinalImageGenerationResponse
from onyx.tools.tool_implementations.memory.memory_tool import MemoryTool
from onyx.tools.tool_implementations.open_url.open_url_tool import OpenURLTool
from onyx.tools.tool_implementations.python.python_tool import PythonTool
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool
from onyx.utils.logger import setup_logger
from onyx.utils.timing import log_function_time

logger = setup_logger()


def callable_tools(tools: Sequence[Tool]) -> list[Tool]:
    """The offered tools, then the tools that run inside their calls."""
    return [*tools, *(inner for tool in tools for inner in tool.inner_tools)]


def build_chat_reminder(
    context: ChatReminderContext,
    results: Sequence[ToolResultMessage],
    previous_results: Sequence[ToolResultMessage],
    *,
    enabled: bool,
    has_history_citations: bool = False,
) -> str | None:
    """`results` are this turn's tool results; `previous_results` the last step's."""
    if not enabled:
        return context.persona_task_prompt
    reminder_text = context.persona_task_prompt
    parts = [part for result in results for part in tool_result_parts(result)]
    # Only suggest opening URLs when this agent has the tool.
    if (
        not any(part.tool_name == ImageGenerationTool.NAME for part in parts)
        and context.has_open_url_tool
        and not context.out_of_cycles
        and any(
            part.tool_name == WebSearchTool.NAME
            and isinstance(part.details, SearchDocsResponse)
            and part.details.search_docs
            for result in previous_results
            for part in tool_result_parts(result)
        )
    ):
        reminder_text = OPEN_URL_REMINDER
    return build_reminder_message(
        reminder_text=reminder_text,
        include_citation_reminder=any(
            result_cites_documents(result) for result in results
        )
        or context.has_context_documents
        or has_history_citations,
        include_file_reminder=any(
            part.tool_name == PythonTool.NAME
            and isinstance(part.details, LlmPythonExecutionResult)
            and part.details.generated_files
            for part in parts
        ),
        include_image_reminder=any(
            isinstance(part.details, FinalImageGenerationResponse)
            and part.details.generated_images
            for part in parts
        ),
        is_last_cycle=context.out_of_cycles,
    )


def build_chat_prompt(
    *,
    tools: list[Tool],
    persona: PersonaPromptConfig | None,
    custom_prompt: str | None,
    base_prompt: str,
    files: ExtractedContextFiles,
    memory: UserMemoryContext | None,
    inject_memories: bool,
    reminders_enabled: bool,
    results: Sequence[ToolResultMessage],
    previous_results: Sequence[ToolResultMessage],
    is_last_step: bool,
    has_history_citations: bool = False,
    preferred_tool_id: int | None = None,
) -> ChatPrompt:
    """Select instructions and reminders before assembling conversation history."""
    values = memory.user_info.placeholder_values if memory else {}

    def substitute(text: str | None) -> str | None:
        return substitute_user_placeholders(text, values) if text else None

    custom_prompt = substitute(custom_prompt)
    persona_system = substitute(persona.system_prompt if persona else None)
    persona_task = substitute(persona.task_prompt if persona else None)
    context_documents = bool(files.use_as_search_filter or files.file_texts)
    cite = (
        reminders_enabled
        and (
            has_history_citations
            or any(result_cites_documents(result) for result in results)
        )
    ) or context_documents
    datetime_aware = persona.datetime_aware if persona else True

    def render(
        text: str | None, append_datetime: bool = False, *, citations: bool = False
    ) -> str | None:
        if not text:
            return None
        rendered, _ = apply_prompt_placeholders(
            text,
            datetime_aware=datetime_aware,
            append_datetime_if_aware=append_datetime,
            should_cite_documents=citations,
            append_citation_if_missing=False,
        )
        return rendered

    custom = render(custom_prompt)
    user_info = None
    if persona and persona.replace_base_system_prompt:
        system = render(persona_system, True)
    elif base_prompt:
        memory = (
            memory if inject_memories else memory.without_memories() if memory else None
        )
        system = build_system_prompt(
            base_system_prompt=base_prompt,
            datetime_aware=datetime_aware,
            tools=tools,
            include_user_info=False,
        )
        user_info = build_user_information_prompt(memory).strip()
    else:
        system = render(custom_prompt, True)
        custom = None
    reminder = build_chat_reminder(
        ChatReminderContext(
            has_open_url_tool=any(
                isinstance(tool, OpenURLTool) for tool in callable_tools(tools)
            ),
            out_of_cycles=is_last_step,
            persona_task_prompt=render(persona_task, citations=cite),
            has_context_documents=context_documents,
        ),
        results,
        previous_results,
        enabled=reminders_enabled,
        has_history_citations=has_history_citations,
    )
    if preferred_tool_id is not None:
        preferred_names = [
            name for tool in tools for name in tool.operation_names(preferred_tool_id)
        ]
        if not preferred_names:
            raise ValueError(f"Preferred tool {preferred_tool_id} is not available")
        preference = TOOL_PREFERENCE_REMINDER.format(
            operations=", ".join(preferred_names),
            guidance=TOOL_PREFERENCE_LAST_STEP_GUIDANCE
            if is_last_step
            else TOOL_PREFERENCE_GUIDANCE,
        )
        reminder = "\n\n".join(part for part in (reminder, preference) if part)
    return ChatPrompt(
        system_prompt=SystemMessage(content=system) if system else None,
        user_info_prompt=SystemMessage(content=user_info) if user_info else None,
        custom_prompt=UserMessage(content=custom) if custom else None,
        reminder=UserMessage(
            content=reminder, metadata=PromptMetadata(is_reminder=True)
        )
        if reminder
        else None,
    )


def get_default_base_system_prompt(db_session: Session) -> str:
    default_persona = get_default_behavior_persona(db_session)
    return (
        default_persona.system_prompt
        if default_persona and default_persona.system_prompt is not None
        else DEFAULT_SYSTEM_PROMPT
    )


@log_function_time()
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

    reserved_token_count = token_counter(custom_agent_prompt + " " + fake_system_prompt)

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
    include_image_reminder: bool,
    is_last_cycle: bool,
) -> str | None:
    reminder = reminder_text.strip() if reminder_text else ""
    if is_last_cycle:
        reminder += "\n\n" + LAST_CYCLE_CITATION_REMINDER
    if include_citation_reminder:
        # Keep citation guidance here so the system prompt stays stable across steps.
        # reminder_text may already carry the guidance when the task prompt
        # authored a {{CITATION_GUIDANCE}} tag — don't emit it twice. The tag
        # only injects REQUIRE_CITATION_GUIDANCE, so COVERAGE is appended
        # unconditionally.
        if REQUIRE_CITATION_GUIDANCE.strip() not in reminder:
            reminder += "\n\n" + REQUIRE_CITATION_GUIDANCE
        reminder += "\n\n" + ANSWER_COVERAGE_GUIDANCE
        reminder += "\n\n" + ANSWER_COMPLETENESS_REMINDER
    if include_file_reminder:
        reminder += "\n\n" + FILE_REMINDER
    if include_image_reminder:
        reminder += "\n\n" + IMAGE_GEN_REMINDER
    reminder = reminder.strip()
    return reminder or None


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


def _build_shared_user_information_section(company_context: str | None) -> str:
    """Org-wide part of '# User Information': the framing for the per-user block
    and the company context. Identical for every user, so it lives in the system
    prompt and shares its cache entry."""
    section = USER_INFORMATION_HEADER + USER_INFORMATION_FRAMING
    if company_context:
        section += "\n" + TEAM_INFORMATION_PROMPT.format(
            team_information=company_context.strip()
        )
    return section


def build_user_information_prompt(user_memory_context: UserMemoryContext | None) -> str:
    """Per-user sub-sections, in order: Basic Info → Organization Profile →
    Language → Preferences → Memories."""
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

    return "\n".join(sections)


def build_system_prompt(
    base_system_prompt: str,
    datetime_aware: bool = False,
    user_memory_context: UserMemoryContext | None = None,
    tools: Sequence[Tool] | None = None,
    should_cite_documents: bool = False,
    include_all_guidance: bool = False,
    include_user_info: bool = True,
) -> str:
    """Should only be called with the default behavior system prompt.
    If the user has replaced the default behavior prompt with their custom agent prompt, do not call this function.

    `tools` are the offered tools. Tools that run inside their calls, such as code
    mode functions, get their guidance too, and the prompt names them as functions.

    With include_user_info=False the per-user block is left out so the result is
    byte-identical across users; emit it separately via build_user_information_prompt.
    The org-wide framing (and company context) for that block stays here.
    """
    system_prompt, should_append_citation_guidance = apply_prompt_placeholders(
        base_system_prompt,
        datetime_aware=datetime_aware,
        append_datetime_if_aware=True,
        should_cite_documents=should_cite_documents,
        include_all_guidance=include_all_guidance,
        append_citation_if_missing=True,
    )

    system_prompt += _build_shared_user_information_section(get_company_context())
    if include_user_info:
        system_prompt += "\n" + build_user_information_prompt(user_memory_context)

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
            CODE_MODE_GUIDANCE,
        ]
        system_prompt += TOOL_SECTION_HEADER + "\n".join(tool_sections)
        return system_prompt

    if tools:
        code_mode = any(tool.name == CODE_MODE_TOOL_NAME for tool in tools)
        # Inner tools are functions of a code mode program, not direct tools.
        tools = callable_tools(tools)
        tool_guidance_sections: list[str] = [CODE_MODE_GUIDANCE] if code_mode else []
        has_web_search = any(isinstance(tool, WebSearchTool) for tool in tools)
        has_internal_search = any(isinstance(tool, SearchTool) for tool in tools)
        has_open_urls = any(isinstance(tool, OpenURLTool) for tool in tools)
        has_python = any(isinstance(tool, PythonTool) for tool in tools)
        has_generate_image = any(
            isinstance(tool, ImageGenerationTool) for tool in tools
        )
        has_memory = any(isinstance(tool, MemoryTool) for tool in tools)

        if has_web_search or has_internal_search:
            tool_guidance_sections.append(TOOL_DESCRIPTION_SEARCH_GUIDANCE)

        # These are not included at the Tool level because the ordering may matter.
        if has_internal_search:
            tool_guidance_sections.append(INTERNAL_SEARCH_GUIDANCE)

        if has_web_search:
            web_search_tool = next(t for t in tools if isinstance(t, WebSearchTool))
            site_disabled_guidance = (
                ""
                if web_search_tool.supports_site_filter
                else WEB_SEARCH_SITE_DISABLED_GUIDANCE
            )
            tool_guidance_sections.append(
                WEB_SEARCH_GUIDANCE.format(site_colon_disabled=site_disabled_guidance)
            )

        if has_open_urls:
            tool_guidance_sections.append(OPEN_URLS_GUIDANCE)

        if has_python:
            tool_guidance_sections.append(PYTHON_TOOL_GUIDANCE)

        if has_generate_image:
            tool_guidance_sections.append(GENERATE_IMAGE_GUIDANCE)

        if has_memory:
            tool_guidance_sections.append(MEMORY_GUIDANCE)

        if tool_guidance_sections:
            system_prompt += TOOL_SECTION_HEADER + "\n".join(tool_guidance_sections)

    return system_prompt


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
            or not isinstance(message.details, SearchDocsResponse)
            or not message.details.citation_mapping
        ):
            continue
        try:
            passages = SearchPassages.model_validate_json(message.text)
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


def prepare_prompt(
    messages: Sequence[Message],
    *,
    system_prompt: Message | None,
    custom_agent_prompt: Message | None,
    reminder_message: Message | None,
    context_files: ExtractedContextFiles | None,
    token_counter: Callable[[str], int],
    user_info_prompt: Message | None = None,
    request_context_message: Message | None = None,
    all_injected_file_metadata: dict[str, FileToolMetadata] | None = None,
    llm_config: LLMConfig | None = None,
    available_tool_names: set[str] | None = None,
    context_file_citations: Mapping[str, int] | None = None,
) -> list[Message]:
    """Assemble detached prompt messages without modifying borrowed inputs."""
    # Nested payloads stay read-only until output formatting detaches them.
    history = [message.model_copy() for message in messages]
    _deduplicate_search_passages(history)
    for message in history:
        metadata = prompt_metadata(message).model_copy()
        message.metadata = metadata
        metadata.token_count = count_message_tokens(message, token_counter)
        metadata.should_cache = not metadata.is_reminder
    result: list[Message] = []
    if system_prompt is not None:
        result.append(system_prompt.model_copy())
    if user_info_prompt is not None:
        result.append(user_info_prompt.model_copy())
    if custom_agent_prompt is not None:
        result.append(custom_agent_prompt.model_copy())
    if context_files and (context_files.file_texts or context_files.image_files):
        result.append(
            _create_context_files_message(context_files, context_file_citations)
        )
    for message in result:
        message.metadata = prompt_metadata(message).model_copy(
            update={"should_cache": True}
        )
    result.extend(history)
    if request_context_message is not None:
        result.append(
            request_context_message.model_copy(
                update={
                    "cacheable": False,
                    "metadata": prompt_metadata(request_context_message).model_copy(
                        update={"should_cache": False}
                    ),
                }
            )
        )

    # Tool-dependent file notices change between rounds, so keep them after
    # the stable history and before the reminder, outside the cacheable prefix.
    if context_files and context_files.file_metadata_for_tool:
        result.append(
            _create_file_tool_metadata_message(
                context_files.file_metadata_for_tool,
                token_counter,
                available_tool_names,
            )
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
    if reminder_message is not None:
        result.append(reminder_message)
    return (
        prepare_model_messages(result, llm_config, token_counter=token_counter)
        if llm_config
        else [message.model_copy(deep=True) for message in result]
    )


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

    The python tier lists only files that actually reached
    ``chat_files_for_tools`` (see ``FileToolMetadata.staged_for_tools``) —
    summary-truncated files are listed for the LLM but never staged, so naming
    python for them would send the model after bytes it does not have. Other
    files in the same notice go under the no-reader header. The
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

    def _entries(metas: list[FileToolMetadata]) -> list[str]:
        return [
            f'- filename="{meta.filename}" (~{meta.approx_char_count:,} chars)'
            for meta in metas
        ]

    if SearchTool.NAME in offered:
        lines = [
            "These files are attached but too large to include in full. Their "
            "contents are indexed — use internal search to find the relevant "
            "passages. Do not guess them or search the web for them:",
            *_entries(file_metadata),
        ]
        return _finalize_file_metadata_message(lines, token_counter)

    python_offered = PythonTool.NAME in offered
    staged = [
        meta for meta in file_metadata if python_offered and meta.staged_for_tools
    ]
    unreadable = [
        meta for meta in file_metadata if not (python_offered and meta.staged_for_tools)
    ]
    lines = []
    if staged:
        lines.append(
            "These files are attached but too large to include in full. The "
            "python tool receives them — read them there, listing the working "
            "directory if a name does not resolve. Do not guess their contents "
            "or search the web for them:"
        )
        lines.extend(_entries(staged))
    if unreadable:
        lines.append(
            "These files are attached but too large to include in full, and no "
            "tool here can read them. Do not guess their contents or search the "
            "web for them — say they are too large to read in this conversation:"
        )
        lines.extend(_entries(unreadable))
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
    citation_numbers: Mapping[str, int] | None = None,
) -> Message:
    """Build a user message with numbered document text and titles."""
    documents: list[ContextDocument] = []
    for idx, file_text in enumerate(context_files.file_texts, start=1):
        metadata = (
            context_files.file_metadata[idx - 1]
            if idx - 1 < len(context_files.file_metadata)
            else None
        )
        documents.append(
            ContextDocument(
                document=citation_numbers[metadata.file_id]
                if citation_numbers is not None and metadata is not None
                else idx,
                title=metadata.filename or None if metadata is not None else None,
                contents=file_text,
            )
        )

    documents_json = json.dumps(
        ContextDocuments(documents=documents).model_dump(exclude_none=True), indent=2
    )
    message_content = (
        f"Here are some documents provided for context, they may not all be relevant:\n{documents_json}"
        if documents
        else "Here are images provided for context."
    )

    return UserMessage(
        content=message_content,
        metadata=PromptMetadata(
            token_count=context_files.total_token_count,
            image_files=context_files.image_files or None,
            image_token_count=sum(
                image.token_count for image in context_files.image_files
            ),
        ),
    )
