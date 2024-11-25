from typing import cast

from danswer.chat.models import LlmDoc
from danswer.llm.answering.models import AnswerStyleConfig
from danswer.llm.answering.models import PromptConfig
from danswer.llm.answering.prompts.build import AnswerPromptBuilder
from danswer.llm.answering.prompts.citations_prompt import (
    build_citations_system_message,
)
from danswer.llm.answering.prompts.citations_prompt import build_citations_user_message
from danswer.llm.answering.prompts.quotes_prompt import build_quotes_user_message
from danswer.tools.message import ToolCallSummary
from danswer.tools.models import ToolResponse


FINAL_CONTEXT_DOCUMENTS_ID = "final_context_documents"


def build_next_prompt_for_search_like_tool(
    prompt_builder: AnswerPromptBuilder,
    tool_call_summary: ToolCallSummary,
    tool_responses: list[ToolResponse],
    using_tool_calling_llm: bool,
    answer_style_config: AnswerStyleConfig,
    prompt_config: PromptConfig,
) -> AnswerPromptBuilder:
    if not using_tool_calling_llm:
        final_context_docs_response = next(
            response
            for response in tool_responses
            if response.id == FINAL_CONTEXT_DOCUMENTS_ID
        )
        final_context_documents = cast(
            list[LlmDoc], final_context_docs_response.response
        )
    else:
        # if using tool calling llm, then the final context documents are the tool responses
        final_context_documents = []

    if answer_style_config.citation_config:
        prompt_builder.update_system_prompt(
            build_citations_system_message(prompt_config)
        )
        prompt_builder.update_user_prompt(
            build_citations_user_message(
                message=prompt_builder.user_message_and_token_cnt[0],
                prompt_config=prompt_config,
                context_docs=final_context_documents,
                all_doc_useful=(
                    answer_style_config.citation_config.all_docs_useful
                    if answer_style_config.citation_config
                    else False
                ),
                history_message=prompt_builder.single_message_history or "",
            )
        )
    elif answer_style_config.quotes_config:
        prompt_builder.update_user_prompt(
            build_quotes_user_message(
                message=prompt_builder.user_message_and_token_cnt[0],
                context_docs=final_context_documents,
                history_str=prompt_builder.single_message_history or "",
                prompt=prompt_config,
            )
        )

    if using_tool_calling_llm:
        prompt_builder.append_message(tool_call_summary.tool_call_request)
        prompt_builder.append_message(tool_call_summary.tool_call_result)

    return prompt_builder
