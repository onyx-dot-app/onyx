from collections.abc import Callable
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.db.memory import UserMemoryContext
from onyx.db.persona import get_default_behavior_persona
from onyx.db.user_file import calculate_user_files_token_count
from onyx.file_store.models import FileDescriptor
from onyx.prompts.chat_prompts import CITATION_REMINDER
from onyx.prompts.chat_prompts import DEFAULT_SYSTEM_PROMPT
from onyx.prompts.chat_prompts import FILE_REMINDER
from onyx.prompts.chat_prompts import LAST_CYCLE_CITATION_REMINDER
from onyx.prompts.chat_prompts import REQUIRE_CITATION_GUIDANCE
from onyx.prompts.prompt_utils import get_company_context
from onyx.prompts.prompt_utils import handle_onyx_date_awareness
from onyx.prompts.prompt_utils import replace_citation_guidance_tag
from onyx.prompts.prompt_utils import replace_reminder_tag
from onyx.prompts.tool_prompts import GENERATE_IMAGE_GUIDANCE
from onyx.prompts.tool_prompts import INTERNAL_SEARCH_GUIDANCE
from onyx.prompts.tool_prompts import MEMORY_GUIDANCE
from onyx.prompts.tool_prompts import OPEN_URLS_GUIDANCE
from onyx.prompts.tool_prompts import PYTHON_TOOL_GUIDANCE
from onyx.prompts.tool_prompts import TOOL_DESCRIPTION_SEARCH_GUIDANCE
from onyx.prompts.tool_prompts import TOOL_SECTION_HEADER
from onyx.prompts.tool_prompts import WEB_SEARCH_GUIDANCE
from onyx.prompts.tool_prompts import WEB_SEARCH_SITE_DISABLED_GUIDANCE
from onyx.prompts.user_info import BASIC_INFORMATION_PROMPT
from onyx.prompts.user_info import TEAM_INFORMATION_PROMPT
from onyx.prompts.user_info import USER_INFORMATION_HEADER
from onyx.prompts.user_info import USER_MEMORIES_PROMPT
from onyx.prompts.user_info import USER_PREFERENCES_PROMPT
from onyx.prompts.user_info import USER_ROLE_PROMPT
from onyx.tools.interface import Tool
from onyx.tools.tool_implementations.images.image_generation_tool import (
    ImageGenerationTool,
)
from onyx.tools.tool_implementations.memory.memory_tool import MemoryTool
from onyx.tools.tool_implementations.open_url.open_url_tool import OpenURLTool
from onyx.tools.tool_implementations.python.python_tool import PythonTool
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool
from onyx.utils.timing import log_function_time


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
    base_system_prompt = get_default_base_system_prompt(db_session)

    # This is for token estimation purposes
    fake_system_prompt = build_system_prompt(
        base_system_prompt=base_system_prompt,
        datetime_aware=True,
        user_memory_context=user_memory_context,
        tools=None,
        should_cite_documents=True,
        include_all_guidance=True,
    )

    custom_agent_prompt = persona_system_prompt if persona_system_prompt else ""

    reserved_token_count = token_counter(
        # Annoying that the dict has no attributes now
        custom_agent_prompt
        + " "
        + fake_system_prompt
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
    if include_file_reminder:
        reminder += "\n\n" + FILE_REMINDER
    reminder = reminder.strip()
    return reminder if reminder else None


def _build_user_information_section(
    user_memory_context: UserMemoryContext | None,
    company_context: str | None,
) -> str:
    """Build the complete '# User Information' section with all sub-sections
    in the correct order: Basic Info → Team Info → Preferences → Memories."""
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

    if company_context:
        sections.append(
            TEAM_INFORMATION_PROMPT.format(team_information=company_context.strip())
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

    if not sections:
        return ""

    return USER_INFORMATION_HEADER + "".join(sections)


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
    system_prompt = handle_onyx_date_awareness(base_system_prompt, datetime_aware)

    # Replace citation guidance placeholder if present
    system_prompt, should_append_citation_guidance = replace_citation_guidance_tag(
        system_prompt,
        should_cite_documents=should_cite_documents,
        include_all_guidance=include_all_guidance,
    )

    # Replace reminder tag placeholder if present
    system_prompt = replace_reminder_tag(system_prompt)

    company_context = get_company_context()
    user_info_section = _build_user_information_section(
        user_memory_context, company_context
    )
    system_prompt += user_info_section

    # Append citation guidance after company context if placeholder was not present
    # This maintains backward compatibility and ensures citations are always enforced when needed
    if should_append_citation_guidance:
        system_prompt += REQUIRE_CITATION_GUIDANCE

    if include_all_guidance:
        system_prompt += (
            TOOL_SECTION_HEADER
            + TOOL_DESCRIPTION_SEARCH_GUIDANCE
            + INTERNAL_SEARCH_GUIDANCE
            + WEB_SEARCH_GUIDANCE.format(
                site_colon_disabled=WEB_SEARCH_SITE_DISABLED_GUIDANCE
            )
            + OPEN_URLS_GUIDANCE
            + PYTHON_TOOL_GUIDANCE
            + GENERATE_IMAGE_GUIDANCE
            + MEMORY_GUIDANCE
        )
        return system_prompt

    if tools:
        system_prompt += TOOL_SECTION_HEADER

        has_web_search = any(isinstance(tool, WebSearchTool) for tool in tools)
        has_internal_search = any(isinstance(tool, SearchTool) for tool in tools)
        has_open_urls = any(isinstance(tool, OpenURLTool) for tool in tools)
        has_python = any(isinstance(tool, PythonTool) for tool in tools)
        has_generate_image = any(
            isinstance(tool, ImageGenerationTool) for tool in tools
        )
        has_memory = any(isinstance(tool, MemoryTool) for tool in tools)

        if has_web_search or has_internal_search or include_all_guidance:
            system_prompt += TOOL_DESCRIPTION_SEARCH_GUIDANCE

        # These are not included at the Tool level because the ordering may matter.
        if has_internal_search or include_all_guidance:
            system_prompt += INTERNAL_SEARCH_GUIDANCE

        if has_web_search or include_all_guidance:
            site_disabled_guidance = ""
            if has_web_search:
                web_search_tool = next(
                    (t for t in tools if isinstance(t, WebSearchTool)), None
                )
                if web_search_tool and not web_search_tool.supports_site_filter:
                    site_disabled_guidance = WEB_SEARCH_SITE_DISABLED_GUIDANCE
            system_prompt += WEB_SEARCH_GUIDANCE.format(
                site_colon_disabled=site_disabled_guidance
            )

        if has_open_urls or include_all_guidance:
            system_prompt += OPEN_URLS_GUIDANCE

        if has_python or include_all_guidance:
            system_prompt += PYTHON_TOOL_GUIDANCE

        if has_generate_image or include_all_guidance:
            system_prompt += GENERATE_IMAGE_GUIDANCE

        if has_memory or include_all_guidance:
            system_prompt += MEMORY_GUIDANCE

    return system_prompt
