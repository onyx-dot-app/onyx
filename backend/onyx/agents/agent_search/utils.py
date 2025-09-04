from typing import Any
from typing import cast

from langchain_core.messages import BaseMessage
from langchain_core.messages import HumanMessage
from langchain_core.messages import SystemMessage

from onyx.context.search.models import InferenceSection


def create_citation_format_list(
    document_citations: list[InferenceSection],
) -> list[dict[str, Any]]:
    citation_list: list[dict[str, Any]] = []
    for document_citation in document_citations:
        document_citation_dict = {
            "link": "",
            "blurb": document_citation.center_chunk.blurb,
            "content": document_citation.center_chunk.content,
            "metadata": document_citation.center_chunk.metadata,
            "updated_at": str(document_citation.center_chunk.updated_at),
            "document_id": document_citation.center_chunk.document_id,
            "source_type": "file",
            "source_links": document_citation.center_chunk.source_links,
            "match_highlights": document_citation.center_chunk.match_highlights,
            "semantic_identifier": document_citation.center_chunk.semantic_identifier,
        }

        citation_list.append(document_citation_dict)

    return citation_list


def create_question_prompt(
    system_prompt: str | None,
    human_prompt: str,
    uploaded_image_context: list[dict[str, Any]] | None = None,
) -> list[BaseMessage]:

    if uploaded_image_context:
        return [
            SystemMessage(content=system_prompt or ""),
            HumanMessage(
                content=cast(
                    list[str | dict[str, Any]],
                    [{"type": "text", "text": human_prompt}] + uploaded_image_context,
                )
            ),
        ]
    else:
        return [
            SystemMessage(content=system_prompt or ""),
            HumanMessage(content=human_prompt),
        ]
