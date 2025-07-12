from onyx.context.search.models import SearchDoc
from onyx.tools.tool_implementations.internet_search.internet_search_tool import (
    InternetSearchResponseSummary,
)


def internet_search_response_to_search_docs(
    internet_search_response: InternetSearchResponseSummary,
) -> list[SearchDoc]:
    """Process internet search response top sections in the same way as search tool sections.

    This follows the same pattern as chunks_or_sections_to_search_docs but for internet search results.
    """
    if not internet_search_response.top_sections:
        return []

    search_docs = []
    for section in internet_search_response.top_sections:
        chunk = section.center_chunk
        search_doc = SearchDoc(
            document_id=chunk.document_id,
            chunk_ind=chunk.chunk_id,
            semantic_identifier=chunk.semantic_identifier or "Unknown",
            link=chunk.source_links[0] if chunk.source_links else None,
            blurb=chunk.blurb,
            source_type=chunk.source_type,
            boost=chunk.boost,
            hidden=chunk.hidden,
            metadata=chunk.metadata,
            score=chunk.score,
            match_highlights=chunk.match_highlights,
            updated_at=chunk.updated_at,
            primary_owners=chunk.primary_owners,
            secondary_owners=chunk.secondary_owners,
            is_internet=True,
        )
        search_docs.append(search_doc)

    return search_docs
