"""Read the documents and citations of any tool result the same way."""

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from onyx.chat.citation_processor import CitationMapping, cited_documents
from onyx.context.search.models import SearchDoc, SearchDocsResponse
from onyx.deep_research.models import ResearchAgentCallResult


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
    return None
