from langchain.schema.messages import HumanMessage
from langchain.schema.messages import SystemMessage

from onyx.chat.models import LlmDoc
from onyx.chat.models import PromptConfig
from onyx.configs.model_configs import GEN_AI_SINGLE_USER_MESSAGE_EXPECTED_MAX_TOKENS
from onyx.context.search.models import InferenceChunk
from onyx.db.models import Persona
from onyx.db.search_settings import get_multilingual_expansion
from onyx.file_store.models import InMemoryChatFile
from onyx.llm.factory import get_llms_for_persona
from onyx.llm.factory import get_main_llm_from_tuple
from onyx.llm.interfaces import LLMConfig
from onyx.llm.utils import build_content_with_imgs
from onyx.llm.utils import check_number_of_tokens
from onyx.prompts.chat_prompts import REQUIRE_CITATION_STATEMENT
from onyx.prompts.constants import DEFAULT_IGNORE_STATEMENT
from onyx.prompts.direct_qa_prompts import CITATIONS_PROMPT
from onyx.prompts.direct_qa_prompts import CITATIONS_PROMPT_FOR_TOOL_CALLING
from onyx.prompts.direct_qa_prompts import HISTORY_BLOCK
from onyx.prompts.prompt_utils import build_complete_context_str
from onyx.prompts.prompt_utils import build_task_prompt_reminders
from onyx.prompts.prompt_utils import handle_onyx_date_awareness
from onyx.prompts.token_counts import ADDITIONAL_INFO_TOKEN_CNT
from onyx.prompts.token_counts import (
    CHAT_USER_PROMPT_WITH_CONTEXT_OVERHEAD_TOKEN_CNT,
)
from onyx.prompts.token_counts import CITATION_REMINDER_TOKEN_CNT
from onyx.prompts.token_counts import CITATION_STATEMENT_TOKEN_CNT
from onyx.prompts.token_counts import LANGUAGE_HINT_TOKEN_CNT
from onyx.utils.logger import setup_logger

logger = setup_logger()


def get_prompt_tokens(prompt_config: PromptConfig) -> int:
    # Note: currently custom prompts do not allow datetime aware, only default prompts
    return (
        check_number_of_tokens(prompt_config.system_prompt)
        + check_number_of_tokens(prompt_config.task_prompt)
        + CHAT_USER_PROMPT_WITH_CONTEXT_OVERHEAD_TOKEN_CNT
        + CITATION_STATEMENT_TOKEN_CNT
        + CITATION_REMINDER_TOKEN_CNT
        + (LANGUAGE_HINT_TOKEN_CNT if get_multilingual_expansion() else 0)
        + (ADDITIONAL_INFO_TOKEN_CNT if prompt_config.datetime_aware else 0)
    )


# buffer just to be safe so that we don't overflow the token limit due to
# a small miscalculation
_MISC_BUFFER = 40


def compute_max_document_tokens(
    prompt_config: PromptConfig,
    llm_config: LLMConfig,
    actual_user_input: str | None = None,
    tool_token_count: int = 0,
) -> int:
    """Estimates the number of tokens available for context documents. Formula is roughly:

    (
        model_context_window - reserved_output_tokens - prompt_tokens
        - (actual_user_input OR reserved_user_message_tokens) - buffer (just to be safe)
    )

    The actual_user_input is used at query time. If we are calculating this before knowing the exact input (e.g.
    if we're trying to determine if the user should be able to select another document) then we just set an
    arbitrary "upper bound".
    """
    # if we can't find a number of tokens, just assume some common default
    prompt_tokens = get_prompt_tokens(prompt_config)

    user_input_tokens = (
        check_number_of_tokens(actual_user_input)
        if actual_user_input is not None
        else GEN_AI_SINGLE_USER_MESSAGE_EXPECTED_MAX_TOKENS
    )

    return (
        llm_config.max_input_tokens
        - prompt_tokens
        - user_input_tokens
        - tool_token_count
        - _MISC_BUFFER
    )


def compute_max_document_tokens_for_persona(
    persona: Persona,
    actual_user_input: str | None = None,
) -> int:
    # Use the persona directly since prompts are now embedded
    return compute_max_document_tokens(
        prompt_config=PromptConfig.from_model(persona),
        llm_config=get_main_llm_from_tuple(get_llms_for_persona(persona)).config,
        actual_user_input=actual_user_input,
    )


def compute_max_llm_input_tokens(llm_config: LLMConfig) -> int:
    """Maximum tokens allows in the input to the LLM (of any type)."""
    return llm_config.max_input_tokens - _MISC_BUFFER


def build_citations_system_message(
    prompt_config: PromptConfig,
) -> SystemMessage:
    system_prompt = prompt_config.system_prompt.strip()
    # Citations are always enabled
    system_prompt += REQUIRE_CITATION_STATEMENT
    tag_handled_prompt = handle_onyx_date_awareness(
        system_prompt, prompt_config, add_additional_info_if_no_tag=True
    )

    return SystemMessage(content=tag_handled_prompt)


def build_citations_user_message(
    user_query: str,
    files: list[InMemoryChatFile],
    prompt_config: PromptConfig,
    context_docs: list[LlmDoc] | list[InferenceChunk],
    all_doc_useful: bool,
    history_message: str = "",
    context_type: str = "context documents",
) -> HumanMessage:
    multilingual_expansion = get_multilingual_expansion()
    task_prompt_with_reminder = build_task_prompt_reminders(
        prompt=prompt_config, use_language_hint=bool(multilingual_expansion)
    )

    history_block = (
        HISTORY_BLOCK.format(history_str=history_message) if history_message else ""
    )

    if context_docs:
        context_docs_str = build_complete_context_str(context_docs)
        optional_ignore = "" if all_doc_useful else DEFAULT_IGNORE_STATEMENT

        user_prompt = CITATIONS_PROMPT.format(
            context_type=context_type,
            optional_ignore_statement=optional_ignore,
            context_docs_str=context_docs_str,
            task_prompt=task_prompt_with_reminder,
            user_query=user_query,
            history_block=history_block,
        )
    else:
        # if no context docs provided, assume we're in the tool calling flow
        user_prompt = CITATIONS_PROMPT_FOR_TOOL_CALLING.format(
            context_type=context_type,
            task_prompt=task_prompt_with_reminder,
            user_query=user_query,
            history_block=history_block,
        )

    user_prompt = user_prompt.strip()
    tag_handled_prompt = handle_onyx_date_awareness(user_prompt, prompt_config)
    user_msg = HumanMessage(
        content=(
            build_content_with_imgs(tag_handled_prompt, files)
            if files
            else tag_handled_prompt
        )
    )

    return user_msg
