"""Vespa-internal data types.

These were previously declared in the now-removed
`onyx.document_index.interfaces` module. They survive only to support Vespa's
chunk-id deletion / range-retrieval plumbing, which has not been ported to the
new generic DocumentIndex interface.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class VespaChunkRequest:
    document_id: str
    min_chunk_ind: int | None = None
    max_chunk_ind: int | None = None

    @property
    def is_capped(self) -> bool:
        # If the max chunk index is not None, then the chunk request is capped.
        # If the min chunk index is None, we can assume the min is 0.
        return self.max_chunk_ind is not None

    @property
    def range(self) -> int | None:
        if self.max_chunk_ind is not None:
            return (self.max_chunk_ind - (self.min_chunk_ind or 0)) + 1
        return None


@dataclass
class MinimalDocumentIndexingInfo:
    """Minimal information necessary for indexing a document."""

    doc_id: str
    chunk_start_index: int


@dataclass
class EnrichedDocumentIndexingInfo(MinimalDocumentIndexingInfo):
    """Enriched information necessary for indexing a document, including
    version and chunk range."""

    old_version: bool
    chunk_end_index: int
