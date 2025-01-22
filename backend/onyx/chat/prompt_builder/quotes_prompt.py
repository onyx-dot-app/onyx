from langchain.schema.messages import HumanMessage

from onyx.chat.models import LlmDoc
from onyx.chat.models import PromptConfig
from onyx.configs.chat_configs import LANGUAGE_HINT
from onyx.context.search.models import InferenceChunk
from onyx.db.search_settings import get_multilingual_expansion
from onyx.llm.utils import message_to_prompt_and_imgs
from onyx.prompts.direct_qa_prompts import CONTEXT_BLOCK
from onyx.prompts.direct_qa_prompts import HISTORY_BLOCK
from onyx.prompts.direct_qa_prompts import JSON_PROMPT
from onyx.prompts.prompt_utils import build_complete_context_str
from onyx.prompts.prompt_utils import handle_onyx_date_awareness


def _build_strong_llm_quotes_prompt(
    question: str,
    context_docs: list[LlmDoc] | list[InferenceChunk],
    history_str: str,
    prompt: PromptConfig,
) -> HumanMessage:
    use_language_hint = bool(get_multilingual_expansion())

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

    tag_handled_prompt = handle_onyx_date_awareness(
        full_prompt, prompt, add_additional_info_if_no_tag=True
    )

    return HumanMessage(content=tag_handled_prompt)


def build_quotes_user_message(
    message: HumanMessage,
    context_docs: list[LlmDoc] | list[InferenceChunk],
    history_str: str,
    prompt: PromptConfig,
) -> HumanMessage:
    query, _ = message_to_prompt_and_imgs(message)

    return _build_strong_llm_quotes_prompt(
        question=query,
        context_docs=context_docs,
        history_str=history_str,
        prompt=prompt,
    )
