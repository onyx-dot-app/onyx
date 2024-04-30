from collections.abc import Callable
from functools import lru_cache
from typing import cast

from langchain.schema.messages import BaseMessage
from langchain.schema.messages import HumanMessage
from langchain.schema.messages import SystemMessage

from danswer.chat.models import LlmDoc
from danswer.configs.chat_configs import MULTILINGUAL_QUERY_EXPANSION
from danswer.configs.model_configs import GEN_AI_SINGLE_USER_MESSAGE_EXPECTED_MAX_TOKENS
from danswer.db.chat import get_default_prompt
from danswer.db.models import Persona
from danswer.file_store.utils import InMemoryChatFile
from danswer.llm.answering.models import PreviousMessage
from danswer.llm.answering.models import PromptConfig
from danswer.llm.factory import get_llm_for_persona
from danswer.llm.interfaces import LLMConfig
from danswer.llm.utils import build_content_with_imgs
from danswer.llm.utils import check_number_of_tokens
from danswer.llm.utils import get_default_llm_tokenizer
from danswer.llm.utils import get_max_input_tokens
from danswer.llm.utils import translate_history_to_basemessages
from danswer.prompts.chat_prompts import ADDITIONAL_INFO
from danswer.prompts.chat_prompts import CHAT_USER_CONTEXT_FREE_PROMPT
from danswer.prompts.chat_prompts import NO_CITATION_STATEMENT
from danswer.prompts.chat_prompts import REQUIRE_CITATION_STATEMENT
from danswer.prompts.constants import DEFAULT_IGNORE_STATEMENT
from danswer.prompts.direct_qa_prompts import (
    CITATIONS_PROMPT,
)
from danswer.prompts.prompt_utils import build_complete_context_str
from danswer.prompts.prompt_utils import build_task_prompt_reminders
from danswer.prompts.prompt_utils import get_current_llm_day_time
from danswer.prompts.token_counts import ADDITIONAL_INFO_TOKEN_CNT
from danswer.prompts.token_counts import (
    CHAT_USER_PROMPT_WITH_CONTEXT_OVERHEAD_TOKEN_CNT,
)
from danswer.prompts.token_counts import CITATION_REMINDER_TOKEN_CNT
from danswer.prompts.token_counts import CITATION_STATEMENT_TOKEN_CNT
from danswer.prompts.token_counts import LANGUAGE_HINT_TOKEN_CNT
from danswer.search.models import InferenceChunk


_PER_MESSAGE_TOKEN_BUFFER = 7


def find_last_index(lst: list[int], max_prompt_tokens: int) -> int:
    """From the back, find the index of the last element to include
    before the list exceeds the maximum"""
    running_sum = 0

    last_ind = 0
    for i in range(len(lst) - 1, -1, -1):
        running_sum += lst[i] + _PER_MESSAGE_TOKEN_BUFFER
        if running_sum > max_prompt_tokens:
            last_ind = i + 1
            break
    if last_ind >= len(lst):
        raise ValueError("Last message alone is too large!")
    return last_ind


def _drop_messages_history_overflow(
    system_msg: BaseMessage | None,
    system_token_count: int,
    history_msgs: list[BaseMessage],
    history_token_counts: list[int],
    final_msg: BaseMessage,
    final_msg_token_count: int,
    max_allowed_tokens: int,
) -> list[BaseMessage]:
    """As message history grows, messages need to be dropped starting from the furthest in the past.
    The System message should be kept if at all possible and the latest user input which is inserted in the
    prompt template must be included"""
    if len(history_msgs) != len(history_token_counts):
        # This should never happen
        raise ValueError("Need exactly 1 token count per message for tracking overflow")

    prompt: list[BaseMessage] = []

    # Start dropping from the history if necessary
    all_tokens = history_token_counts + [system_token_count, final_msg_token_count]
    ind_prev_msg_start = find_last_index(
        all_tokens, max_prompt_tokens=max_allowed_tokens
    )

    if system_msg and ind_prev_msg_start <= len(history_msgs):
        prompt.append(system_msg)

    prompt.extend(history_msgs[ind_prev_msg_start:])

    prompt.append(final_msg)

    return prompt


def get_prompt_tokens(prompt_config: PromptConfig) -> int:
    # Note: currently custom prompts do not allow datetime aware, only default prompts
    return (
        check_number_of_tokens(prompt_config.system_prompt)
        + check_number_of_tokens(prompt_config.task_prompt)
        + CHAT_USER_PROMPT_WITH_CONTEXT_OVERHEAD_TOKEN_CNT
        + CITATION_STATEMENT_TOKEN_CNT
        + CITATION_REMINDER_TOKEN_CNT
        + (LANGUAGE_HINT_TOKEN_CNT if bool(MULTILINGUAL_QUERY_EXPANSION) else 0)
        + (ADDITIONAL_INFO_TOKEN_CNT if prompt_config.datetime_aware else 0)
    )


# buffer just to be safe so that we don't overflow the token limit due to
# a small miscalculation
_MISC_BUFFER = 40


def compute_max_document_tokens(
    prompt_config: PromptConfig,
    llm_config: LLMConfig,
    actual_user_input: str | None = None,
    max_llm_token_override: int | None = None,
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
    max_input_tokens = (
        max_llm_token_override
        if max_llm_token_override
        else get_max_input_tokens(
            model_name=llm_config.model_name, model_provider=llm_config.model_provider
        )
    )
    prompt_tokens = get_prompt_tokens(prompt_config)

    user_input_tokens = (
        check_number_of_tokens(actual_user_input)
        if actual_user_input is not None
        else GEN_AI_SINGLE_USER_MESSAGE_EXPECTED_MAX_TOKENS
    )

    return max_input_tokens - prompt_tokens - user_input_tokens - _MISC_BUFFER


def compute_max_document_tokens_for_persona(
    persona: Persona,
    actual_user_input: str | None = None,
    max_llm_token_override: int | None = None,
) -> int:
    prompt = persona.prompts[0] if persona.prompts else get_default_prompt()
    return compute_max_document_tokens(
        prompt_config=PromptConfig.from_model(prompt),
        llm_config=get_llm_for_persona(persona).config,
        actual_user_input=actual_user_input,
        max_llm_token_override=max_llm_token_override,
    )


def compute_max_llm_input_tokens(llm_config: LLMConfig) -> int:
    """Maximum tokens allows in the input to the LLM (of any type)."""

    input_tokens = get_max_input_tokens(
        model_name=llm_config.model_name, model_provider=llm_config.model_provider
    )
    return input_tokens - _MISC_BUFFER


@lru_cache()
def _build_system_message(
    prompt_config: PromptConfig,
    context_exists: bool,
    llm_tokenizer_encode_func: Callable,
    citation_line: str = REQUIRE_CITATION_STATEMENT,
    no_citation_line: str = NO_CITATION_STATEMENT,
) -> tuple[SystemMessage | None, int]:
    system_prompt = prompt_config.system_prompt.strip()
    if prompt_config.include_citations:
        if context_exists:
            system_prompt += citation_line
        else:
            system_prompt += no_citation_line
    if prompt_config.datetime_aware:
        if system_prompt:
            system_prompt += ADDITIONAL_INFO.format(
                datetime_info=get_current_llm_day_time()
            )
        else:
            system_prompt = get_current_llm_day_time()

    if not system_prompt:
        return None, 0

    token_count = len(llm_tokenizer_encode_func(system_prompt))
    system_msg = SystemMessage(content=system_prompt)

    return system_msg, token_count


def _build_user_message(
    question: str,
    prompt_config: PromptConfig,
    context_docs: list[LlmDoc] | list[InferenceChunk],
    files: list[InMemoryChatFile],
    all_doc_useful: bool,
    history_message: str,
) -> tuple[HumanMessage, int]:
    llm_tokenizer = get_default_llm_tokenizer()
    llm_tokenizer_encode_func = cast(Callable[[str], list[int]], llm_tokenizer.encode)

    if not context_docs:
        # Simpler prompt for cases where there is no context
        user_prompt = (
            CHAT_USER_CONTEXT_FREE_PROMPT.format(
                task_prompt=prompt_config.task_prompt, user_query=question
            )
            if prompt_config.task_prompt
            else question
        )
        user_prompt = user_prompt.strip()
        token_count = len(llm_tokenizer_encode_func(user_prompt))
        user_msg = HumanMessage(
            content=build_content_with_imgs(user_prompt, files)
            if files
            else user_prompt
        )
        return user_msg, token_count

    context_docs_str = build_complete_context_str(context_docs)
    optional_ignore = "" if all_doc_useful else DEFAULT_IGNORE_STATEMENT

    task_prompt_with_reminder = build_task_prompt_reminders(prompt_config)

    user_prompt = CITATIONS_PROMPT.format(
        optional_ignore_statement=optional_ignore,
        context_docs_str=context_docs_str,
        task_prompt=task_prompt_with_reminder,
        user_query=question,
        history_block=history_message,
    )

    user_prompt = user_prompt.strip()
    token_count = len(llm_tokenizer_encode_func(user_prompt))
    user_msg = HumanMessage(
        content=build_content_with_imgs(user_prompt, files) if files else user_prompt
    )

    return user_msg, token_count


def build_citations_prompt(
    question: str,
    message_history: list[PreviousMessage],
    prompt_config: PromptConfig,
    llm_config: LLMConfig,
    context_docs: list[LlmDoc] | list[InferenceChunk],
    latest_query_files: list[InMemoryChatFile],
    all_doc_useful: bool,
    history_message: str,
    llm_tokenizer_encode_func: Callable,
) -> list[BaseMessage]:
    context_exists = len(context_docs) > 0

    system_message_or_none, system_tokens = _build_system_message(
        prompt_config=prompt_config,
        context_exists=context_exists,
        llm_tokenizer_encode_func=llm_tokenizer_encode_func,
    )

    history_basemessages, history_token_counts = translate_history_to_basemessages(
        message_history
    )

    # Be sure the context_docs passed to build_chat_user_message
    # Is the same as passed in later for extracting citations
    user_message, user_tokens = _build_user_message(
        question=question,
        prompt_config=prompt_config,
        context_docs=context_docs,
        files=latest_query_files,
        all_doc_useful=all_doc_useful,
        history_message=history_message,
    )

    final_prompt_msgs = _drop_messages_history_overflow(
        system_msg=system_message_or_none,
        system_token_count=system_tokens,
        history_msgs=history_basemessages,
        history_token_counts=history_token_counts,
        final_msg=user_message,
        final_msg_token_count=user_tokens,
        max_allowed_tokens=compute_max_llm_input_tokens(llm_config),
    )

    return final_prompt_msgs
