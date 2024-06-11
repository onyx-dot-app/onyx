from collections.abc import Sequence
from typing import TypeVar

from danswer.db.models import SearchDoc as DBSearchDoc
from danswer.search.models import InferenceChunk
from danswer.search.models import InferenceSection
from danswer.search.models import SearchDoc


T = TypeVar("T", InferenceSection, InferenceChunk, SearchDoc)


def dedupe_documents(items: list[T]) -> tuple[list[T], list[int]]:
    seen_ids = set()
    deduped_items = []
    dropped_indices = []
    for index, item in enumerate(items):
        if item.document_id not in seen_ids:
            seen_ids.add(item.document_id)
            deduped_items.append(item)
        else:
            dropped_indices.append(index)
    return deduped_items, dropped_indices


def drop_llm_indices(
    llm_indices: list[int], search_docs: list[DBSearchDoc], dropped_indices: list[int]
) -> list[int]:
    llm_bools = [True if i in llm_indices else False for i in range(len(search_docs))]
    if dropped_indices:
        llm_bools = [
            val for ind, val in enumerate(llm_bools) if ind not in dropped_indices
        ]
    return [i for i, val in enumerate(llm_bools) if val]


def chunks_or_sections_to_search_docs(
    chunks: Sequence[InferenceChunk | InferenceSection] | None,
) -> list[SearchDoc]:
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
