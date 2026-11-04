"""Read any tool result the same way, including the calls inside a code mode result."""

import json
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from onyx.chat.citation_processor import CitationMapping, cited_documents
from onyx.context.search.models import SearchDoc, SearchDocsResponse
from onyx.deep_research.models import ResearchAgentCallResult
from onyx.llm.models import ToolResultMessage
from onyx.prompts.chat_prompts import TOOL_CALL_RESPONSE_CROSS_MESSAGE
from onyx.tools.tool_implementations.code_mode.models import (
    CodeModeCall,
    CodeModeExecutionResult,
)
from onyx.tools.tool_implementations.code_mode.prompt import omitted_observation_notes
from onyx.tools.tool_implementations.images.models import (
    FinalImageGenerationResponse,
    ImageResult,
)


class ResultSources(BaseModel):
    """Documents carried by one tool result and the citation numbers it gave them."""

    model_config = ConfigDict(frozen=True)

    # Every document the result gathered.
    documents: list[SearchDoc]
    # The documents to show for the call; a search can select a subset. None when
    # the call shows no documents of its own.
    displayed: list[SearchDoc] | None
    citations: CitationMapping


def _by_id(documents: Sequence[SearchDoc]) -> dict[str, SearchDoc]:
    """Documents by id; the first of a repeated id wins."""
    found: dict[str, SearchDoc] = {}
    for document in documents:
        found.setdefault(document.document_id, document)
    return found


def _search_sources(searches: Sequence[SearchDocsResponse]) -> ResultSources:
    """The documents and citations of search details, merged in order."""
    documents = _by_id(
        [
            document
            for search in searches
            for document in [*search.search_docs, *(search.displayed_docs or [])]
        ]
    )
    mapping = {
        number: document_id
        for search in searches
        for number, document_id in search.citation_mapping.items()
    }
    return ResultSources(
        documents=list(documents.values()),
        displayed=list(documents.values()),
        citations=cited_documents(dict(sorted(mapping.items())), documents),
    )


def tool_result_sources(details: BaseModel | None) -> ResultSources | None:
    """The documents and citations of any tool result; None if it carries none."""
    if isinstance(details, ResearchAgentCallResult):
        return ResultSources(
            documents=list(details.citation_mapping.values()),
            displayed=None,
            citations=dict(details.citation_mapping),
        )
    if isinstance(details, SearchDocsResponse):
        return ResultSources(
            documents=list(details.search_docs),
            displayed=list(
                details.displayed_docs
                if details.displayed_docs is not None
                else details.search_docs
            ),
            citations=cited_documents(
                details.citation_mapping, _by_id(details.search_docs)
            ),
        )
    if isinstance(details, CodeModeExecutionResult):
        # The nested searches of every window, the closing record's included.
        return _search_sources(
            [
                call.details
                for call in details.all_calls()
                if isinstance(call.details, SearchDocsResponse)
            ]
        )
    return None


def tool_result_parts(result: ToolResultMessage) -> list[ToolResultMessage]:
    """The result, then a result for each tool call that it made."""
    details = result.details
    if not isinstance(details, CodeModeExecutionResult):
        return [result]
    return [
        result,
        *(call.as_result() for call in details.all_calls()),
    ]


def omitted_result_text(
    result: ToolResultMessage, earlier_calls: Sequence[CodeModeCall] = ()
) -> str:
    """What a later turn reads in place of a tool result.

    A code mode observation keeps the notes of `omitted_observation_notes`, with
    the calls of its cell's earlier observations (`earlier_calls`). It keeps the
    file id and prompt of each generated image, also of images made inside a
    program, so a later message can edit them.
    """
    sections = [TOOL_CALL_RESPONSE_CROSS_MESSAGE]
    if isinstance(result.details, CodeModeExecutionResult):
        sections.extend(omitted_observation_notes(result.details, earlier_calls))
    images = [
        ImageResult(
            file_id=image.file_id, revised_prompt=image.revised_prompt
        ).model_dump()
        for part in tool_result_parts(result)
        if isinstance(part.details, FinalImageGenerationResponse)
        for image in part.details.generated_images
    ]
    if images:
        sections.append(f"Generated images: {json.dumps(images)}")
    return "\n".join(sections)
