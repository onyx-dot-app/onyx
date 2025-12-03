from collections.abc import Callable
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.chat.models import PromptConfig
from onyx.db.persona import get_default_behavior_persona
from onyx.db.user_file import calculate_user_files_token_count
from onyx.file_store.models import FileDescriptor
from onyx.file_store.models import InMemoryChatFile
from onyx.llm.interfaces import LLMConfig
from onyx.llm.message_types import SystemMessage
from onyx.llm.message_types import UserMessage
from onyx.llm.message_types import UserMessageWithText
from onyx.llm.utils import model_needs_formatting_reenabled
from onyx.prompts.chat_prompts import CHAT_USER_CONTEXT_FREE_PROMPT
from onyx.prompts.chat_prompts import CITATION_REMINDER
from onyx.prompts.chat_prompts import CODE_BLOCK_MARKDOWN
from onyx.prompts.chat_prompts import DEFAULT_SYSTEM_PROMPT
from onyx.prompts.chat_prompts import GENERATE_IMAGE_GUIDANCE
from onyx.prompts.chat_prompts import INTERNAL_SEARCH_GUIDANCE
from onyx.prompts.chat_prompts import OPEN_URLS_GUIDANCE
from onyx.prompts.chat_prompts import PYTHON_TOOL_GUIDANCE
from onyx.prompts.chat_prompts import REQUIRE_CITATION_GUIDANCE
from onyx.prompts.chat_prompts import TOOL_DESCRIPTION_SEARCH_GUIDANCE
from onyx.prompts.chat_prompts import TOOL_SECTION_HEADER
from onyx.prompts.chat_prompts import USER_INFO_HEADER
from onyx.prompts.chat_prompts import WEB_SEARCH_GUIDANCE
from onyx.prompts.direct_qa_prompts import HISTORY_BLOCK
from onyx.prompts.prompt_utils import get_company_context
from onyx.prompts.prompt_utils import handle_onyx_date_awareness
from onyx.tools.tool import Tool
from onyx.tools.tool_implementations.images.image_generation_tool import (
    ImageGenerationTool,
)
from onyx.tools.tool_implementations.open_url.open_url_tool import OpenURLTool
from onyx.tools.tool_implementations.python.python_tool import PythonTool
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool
from onyx.utils.timing import log_function_time


def get_default_base_system_prompt(db_session: Session) -> str:
    default_persona = get_default_behavior_persona(db_session)
    return (
        default_persona.system_prompt
        if default_persona and default_persona.system_prompt
        else DEFAULT_SYSTEM_PROMPT
    )


@log_function_time(print_only=True)
def calculate_reserved_tokens(
    db_session: Session,
    persona_system_prompt: str,
    tokenizer_encode_func: Callable[[str], list[int]],
    files: list[FileDescriptor] | None = None,
    memories: list[str] | None = None,
) -> int:
    """
    Calculate reserved token count for system prompt and user files.

    This is used for token estimation purposes to reserve space for:
    - The system prompt (base + custom agent prompt + all guidance)
    - User files attached to the message

    Args:
        db_session: Database session
        persona_system_prompt: Custom agent system prompt (can be empty string)
        tokenizer_encode_func: Function to encode strings to token lists
        files: List of file descriptors from the chat message (optional)
        memories: List of memory strings (optional)

    Returns:
        Total reserved token count
    """
    base_system_prompt = get_default_base_system_prompt(db_session)

    # This is for token estimation purposes
    fake_system_prompt = build_system_prompt(
        base_system_prompt=base_system_prompt,
        datetime_aware=True,
        memories=memories,
        tools=None,
        should_cite_documents=True,
        include_all_guidance=True,
    )

    custom_agent_prompt = persona_system_prompt if persona_system_prompt else ""

    reserved_token_count = len(
        tokenizer_encode_func(
            # Annoying that the dict has no attributes now
            custom_agent_prompt
            + " "
            + fake_system_prompt
        )
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
) -> str | None:
    reminder = reminder_text.strip() if reminder_text else ""
    if include_citation_reminder:
        reminder += "\n\n" + CITATION_REMINDER
    reminder = reminder.strip()
    return reminder if reminder else None


def build_system_prompt(
    base_system_prompt: str,
    datetime_aware: bool = False,
    memories: list[str] | None = None,
    tools: Sequence[Tool] | None = None,
    should_cite_documents: bool = False,
    include_all_guidance: bool = False,
    open_ai_formatting_enabled: bool = False,
) -> str:
    """Should only be called with the default behavior system prompt.
    If the user has replaced the default behavior prompt with their custom agent prompt, do not call this function.
    """
    system_prompt = handle_onyx_date_awareness(base_system_prompt, datetime_aware)

    # See https://simonwillison.net/tags/markdown/ for context on why this is needed
    # for OpenAI reasoning models to have correct markdown generation
    if open_ai_formatting_enabled:
        system_prompt = CODE_BLOCK_MARKDOWN + system_prompt

    try:
        citation_guidance = (
            REQUIRE_CITATION_GUIDANCE
            if should_cite_documents or include_all_guidance
            else ""
        )
        system_prompt = system_prompt.format(
            citation_reminder_or_empty=citation_guidance
        )
    except Exception:
        # Even if the prompt is modified and there is not an explicit spot for citations, always require it
        # This is more a product decision as it's likely better to always enforce citations
        if should_cite_documents or include_all_guidance:
            system_prompt += REQUIRE_CITATION_GUIDANCE

    company_context = get_company_context()
    if company_context or memories:
        system_prompt += USER_INFO_HEADER
        if company_context:
            system_prompt += company_context
        if memories:
            system_prompt += "\n".join(
                memory.strip() for memory in memories if memory.strip()
            )

    if should_cite_documents or include_all_guidance:
        system_prompt += REQUIRE_CITATION_GUIDANCE

    if include_all_guidance:
        system_prompt += (
            TOOL_SECTION_HEADER
            + TOOL_DESCRIPTION_SEARCH_GUIDANCE
            + INTERNAL_SEARCH_GUIDANCE
            + WEB_SEARCH_GUIDANCE
            + OPEN_URLS_GUIDANCE
            + GENERATE_IMAGE_GUIDANCE
            + PYTHON_TOOL_GUIDANCE
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

        if has_web_search or has_internal_search or include_all_guidance:
            system_prompt += TOOL_DESCRIPTION_SEARCH_GUIDANCE

        # These are not included at the Tool level because the ordering may matter.
        if has_internal_search or include_all_guidance:
            system_prompt += INTERNAL_SEARCH_GUIDANCE

        if has_web_search or include_all_guidance:
            system_prompt += WEB_SEARCH_GUIDANCE

        if has_open_urls or include_all_guidance:
            system_prompt += OPEN_URLS_GUIDANCE

        if has_python or include_all_guidance:
            system_prompt += PYTHON_TOOL_GUIDANCE

        if has_generate_image or include_all_guidance:
            system_prompt += GENERATE_IMAGE_GUIDANCE

    return system_prompt


def default_build_system_message(
    prompt_config: PromptConfig,
    llm_config: LLMConfig,
    memories: list[str] | None = None,
) -> SystemMessage | None:
    # Build system prompt from default behavior and custom instructions
    # for backwards compatibility
    system_prompt = (
        prompt_config.custom_instructions
        or prompt_config.default_behavior_system_prompt
    )
    # See https://simonwillison.net/tags/markdown/ for context on why this is needed
    # for OpenAI reasoning models to have correct markdown generation
    if model_needs_formatting_reenabled(llm_config.model_name):
        system_prompt = CODE_BLOCK_MARKDOWN + system_prompt

    tag_handled_prompt = handle_onyx_date_awareness(
        prompt_str=system_prompt,
        datetime_aware=prompt_config.datetime_aware,
    )

    if not tag_handled_prompt:
        return None

    # tag_handled_prompt = handle_company_awareness(tag_handled_prompt)

    # if memories:
    #     tag_handled_prompt = handle_memories(tag_handled_prompt, memories)

    return SystemMessage(role="system", content=tag_handled_prompt)


def default_build_user_message(
    user_query: str,
    prompt_config: PromptConfig,
    files: list[InMemoryChatFile] = [],
    single_message_history: str | None = None,
) -> UserMessage:
    history_block = (
        HISTORY_BLOCK.format(history_str=single_message_history)
        if single_message_history
        else ""
    )

    user_prompt = (
        CHAT_USER_CONTEXT_FREE_PROMPT.format(
            history_block=history_block,
            task_prompt=prompt_config.reminder,
            user_query=user_query,
        )
        if prompt_config.reminder
        else user_query
    )

    user_prompt = user_prompt.strip()
    # tag_handled_prompt = handle_onyx_date_awareness(
    #     user_prompt, prompt_config.datetime_aware
    # )
    user_msg = UserMessageWithText(role="user", content="N/A")
    return user_msg
