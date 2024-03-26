from danswer.indexing.models import InferenceChunk
from danswer.search.models import SearchDoc


def chunks_to_search_docs(chunks: list[InferenceChunk] | None) -> list[SearchDoc]:
    search_docs = (
        [
            SearchDoc(
                document_id=chunk.document_id,
                chunk_ind=chunk.chunk_id,
                semantic_identifier=chunk.semantic_identifier or "Unknown",
                link=chunk.source_links.get(0) if chunk.source_links else None,
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
            )
            for chunk in chunks
        ]
        if chunks
        else []
    )
    return search_docs
