from langchain.schema.messages import HumanMessage

from danswer.chat.models import LlmDoc
from danswer.configs.chat_configs import LANGUAGE_HINT
from danswer.configs.chat_configs import MULTILINGUAL_QUERY_EXPANSION
from danswer.configs.chat_configs import QA_PROMPT_OVERRIDE
from danswer.llm.answering.models import PromptConfig
from danswer.prompts.direct_qa_prompts import CONTEXT_BLOCK
from danswer.prompts.direct_qa_prompts import HISTORY_BLOCK
from danswer.prompts.direct_qa_prompts import JSON_PROMPT
from danswer.prompts.direct_qa_prompts import WEAK_LLM_PROMPT
from danswer.prompts.prompt_utils import add_date_time_to_prompt
from danswer.prompts.prompt_utils import build_complete_context_str
from danswer.search.models import InferenceChunk


def _build_weak_llm_quotes_prompt(
    question: str,
    context_docs: list[LlmDoc] | list[InferenceChunk],
    history_str: str,
    prompt: PromptConfig,
    use_language_hint: bool,
) -> HumanMessage:
    """Since Danswer supports a variety of LLMs, this less demanding prompt is provided
    as an option to use with weaker LLMs such as small version, low float precision, quantized,
    or distilled models. It only uses one context document and has very weak requirements of
    output format.
    """
    context_block = ""
    if context_docs:
        context_block = CONTEXT_BLOCK.format(context_docs_str=context_docs[0].content)

    prompt_str = WEAK_LLM_PROMPT.format(
        system_prompt=prompt.system_prompt,
        context_block=context_block,
        task_prompt=prompt.task_prompt,
        user_query=question,
    )

    if prompt.datetime_aware:
        prompt_str = add_date_time_to_prompt(prompt_str=prompt_str)

    return HumanMessage(content=prompt_str)


def _build_strong_llm_quotes_prompt(
    question: str,
    context_docs: list[LlmDoc] | list[InferenceChunk],
    history_str: str,
    prompt: PromptConfig,
    use_language_hint: bool,
) -> HumanMessage:
    context_block = ""
    if context_docs:
        context_docs_str = build_complete_context_str(context_docs)
        context_block = CONTEXT_BLOCK.format(context_docs_str=context_docs_str)

    history_block = ""
    if history_str:
        history_block = HISTORY_BLOCK.format(history_str=history_str)

    full_prompt = JSON_PROMPT.format(
        system_prompt=prompt.system_prompt,
        context_block=context_block,
        history_block=history_block,
        task_prompt=prompt.task_prompt,
        user_query=question,
        language_hint_or_none=LANGUAGE_HINT.strip() if use_language_hint else "",
    ).strip()

    if prompt.datetime_aware:
        full_prompt = add_date_time_to_prompt(prompt_str=full_prompt)

    return HumanMessage(content=full_prompt)


def build_quotes_user_message(
    question: str,
    context_docs: list[LlmDoc] | list[InferenceChunk],
    history_str: str,
    prompt: PromptConfig,
    use_language_hint: bool = bool(MULTILINGUAL_QUERY_EXPANSION),
) -> HumanMessage:
    prompt_builder = (
        _build_weak_llm_quotes_prompt
        if QA_PROMPT_OVERRIDE == "weak"
        else _build_strong_llm_quotes_prompt
    )

    return prompt_builder(
        question=question,
        context_docs=context_docs,
        history_str=history_str,
        prompt=prompt,
        use_language_hint=use_language_hint,
    )


def build_quotes_prompt(
    question: str,
    context_docs: list[LlmDoc] | list[InferenceChunk],
    history_str: str,
    prompt: PromptConfig,
    use_language_hint: bool = bool(MULTILINGUAL_QUERY_EXPANSION),
) -> HumanMessage:
    prompt_builder = (
        _build_weak_llm_quotes_prompt
        if QA_PROMPT_OVERRIDE == "weak"
        else _build_strong_llm_quotes_prompt
    )

    return prompt_builder(
        question=question,
        context_docs=context_docs,
        history_str=history_str,
        prompt=prompt,
        use_language_hint=use_language_hint,
    )
