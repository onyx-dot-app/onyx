from typing import cast

from onyx.chat.models import AnswerStyleConfig
from onyx.chat.models import LlmDoc
from onyx.chat.models import PromptConfig
from onyx.chat.prompt_builder.answer_prompt_builder import AnswerPromptBuilder
from onyx.chat.prompt_builder.citations_prompt import (
    build_citations_system_message,
)
from onyx.chat.prompt_builder.citations_prompt import build_citations_user_message
from onyx.connectors.models import Document
from onyx.connectors.models import IndexingDocument
from onyx.connectors.models import Section
from onyx.tools.message import ToolCallSummary
from onyx.tools.models import ToolResponse


FINAL_CONTEXT_DOCUMENTS_ID = "final_context_documents"


def build_next_prompt_for_search_like_tool(
    prompt_builder: AnswerPromptBuilder,
    tool_call_summary: ToolCallSummary,
    tool_responses: list[ToolResponse],
    using_tool_calling_llm: bool,
    answer_style_config: AnswerStyleConfig,
    prompt_config: PromptConfig,
    context_type: str = "context documents",
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

    prompt_builder.update_system_prompt(build_citations_system_message(prompt_config))
    prompt_builder.update_user_prompt(
        build_citations_user_message(
            # make sure to use the original user query here in order to avoid duplication
            # of the task prompt
            user_query=prompt_builder.raw_user_query,
            files=prompt_builder.raw_user_uploaded_files,
            prompt_config=prompt_config,
            context_docs=final_context_documents,
            all_doc_useful=(
                answer_style_config.citation_config.all_docs_useful
                if answer_style_config.citation_config
                else False
            ),
            history_message=prompt_builder.single_message_history or "",
            context_type=context_type,
        )
    )

    if using_tool_calling_llm:
        prompt_builder.append_message(tool_call_summary.tool_call_request)
        prompt_builder.append_message(tool_call_summary.tool_call_result)

    return prompt_builder


def documents_to_indexing_documents(
    documents: list[Document],
) -> list[IndexingDocument]:
    indexing_documents = []

    for document in documents:
        processed_sections = []
        for section in document.sections:
            processed_section = Section(
                text=section.text or "",
                link=section.link,
                image_file_id=None,
            )
            processed_sections.append(processed_section)

        indexed_document = IndexingDocument(
            **document.model_dump(), processed_sections=processed_sections
        )
        indexing_documents.append(indexed_document)
    return indexing_documents
