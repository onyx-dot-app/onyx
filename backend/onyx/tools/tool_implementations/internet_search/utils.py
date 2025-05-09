from onyx.chat.models import LlmDoc
from onyx.configs.constants import DocumentSource
from onyx.context.search.models import SearchDoc
from onyx.indexing.models import IndexChunk
from onyx.tools.tool_implementations.internet_search.models import (
    InternetSearchResponse,
)


# TODO: Temp, shouldn't be feeding in chunks here I think, but that's what we're left with after pruning
def internet_search_chunk_to_llm_doc(chunk: IndexChunk) -> LlmDoc:
    return LlmDoc(
        document_id=chunk.source_document.id,
        content=chunk.content,
        blurb=chunk.blurb,
        semantic_identifier=chunk.source_document.title,
        source_type=DocumentSource.NOT_APPLICABLE,
        metadata={},
        updated_at=chunk.source_document.doc_updated_at,
        link=chunk.source_document.id,
        source_links={0: chunk.source_document.id},
        match_highlights=[],
    )


def internet_search_response_to_search_docs(
    internet_search_response: InternetSearchResponse,
) -> list[SearchDoc]:
    return [
        SearchDoc(
            document_id=doc.url,
            chunk_ind=-1,
            semantic_identifier=doc.title,
            link=doc.url,
            blurb=doc.summary,
            source_type=DocumentSource.NOT_APPLICABLE,
            boost=0,
            hidden=False,
            metadata={},
            score=doc.score,
            match_highlights=[],
            updated_at=doc.published_date,
            primary_owners=[],
            secondary_owners=[],
            is_internet=True,
        )
        for doc in internet_search_response.internet_results
    ]
