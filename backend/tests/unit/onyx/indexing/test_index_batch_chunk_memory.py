"""index_doc_batch frees the chunk list before the index write."""

import gc
import weakref
from collections.abc import Callable, Iterable
from typing import Any
from unittest.mock import MagicMock, patch

from onyx.connectors.models import (
    ConnectorFailure,
    Document,
    DocumentSource,
    IndexingDocument,
    TextSection,
)
from onyx.document_index.interfaces import DocumentInsertionRecord
from onyx.indexing.indexing_pipeline import DocumentBatchPrepareContext, index_doc_batch
from onyx.indexing.models import ChunkEmbedding, DocAwareChunk, IndexChunk
from onyx.utils.pydantic_util import shallow_model_dump

_PATCH_PREFIX = "onyx.indexing.indexing_pipeline"
_CHUNKS_PER_DOC = 3


def _make_chunk(document: IndexingDocument, chunk_id: int) -> DocAwareChunk:
    return DocAwareChunk(
        chunk_id=chunk_id,
        blurb="blurb",
        content=f"content {chunk_id}",
        source_links={0: "link"},
        image_file_id=None,
        section_continuation=False,
        source_document=document,
        title_prefix="",
        metadata_suffix_semantic="",
        metadata_suffix_keyword="",
        mini_chunk_texts=None,
        large_chunk_id=None,
        doc_summary="",
        chunk_context="",
        contextual_rag_reserved_tokens=0,
    )


def _embed(
    chunks: list[DocAwareChunk], **_kwargs: Any
) -> tuple[list[IndexChunk], list[ConnectorFailure]]:
    return (
        [
            IndexChunk.model_construct(
                **shallow_model_dump(chunk),
                embeddings=ChunkEmbedding(
                    full_embedding=[0.1, 0.2], mini_chunk_embeddings=[]
                ),
            )
            for chunk in chunks
        ],
        [],
    )


def test_index_batch_frees_the_chunks_before_the_index_write() -> None:
    document = Document(
        id="doc",
        semantic_identifier="doc",
        source=DocumentSource.FILE,
        sections=[TextSection(text="text", link=None)],
        metadata={},
    )
    chunk_refs: list[weakref.ref[DocAwareChunk]] = []
    chunks_alive_at_write: list[int] = []
    written_chunk_ids: list[int] = []

    # Plain functions and classes: a mock would keep its arguments alive.
    class _Chunker:
        chunk_token_limit = 512

        def chunk(self, documents: list[IndexingDocument]) -> list[DocAwareChunk]:
            chunks = [_make_chunk(documents[0], i) for i in range(_CHUNKS_PER_DOC)]
            chunk_refs.extend(weakref.ref(chunk) for chunk in chunks)
            return chunks

    def prepare_enrichment(**_kwargs: Any) -> MagicMock:
        enricher = MagicMock(
            doc_id_to_previous_chunk_cnt={},
            doc_id_to_new_chunk_cnt={"doc": _CHUNKS_PER_DOC},
        )
        enricher.enrich_chunk = lambda chunk, _score: chunk
        return enricher

    def write(
        make_chunks: Callable[[], Iterable[IndexChunk]], **_kwargs: Any
    ) -> tuple[list[DocumentInsertionRecord], list[ConnectorFailure]]:
        gc.collect()
        chunks_alive_at_write.append(
            sum(1 for chunk_ref in chunk_refs if chunk_ref() is not None)
        )
        written_chunk_ids.extend(chunk.chunk_id for chunk in make_chunks())
        return [DocumentInsertionRecord(document_id="doc", already_existed=False)], []

    adapter = MagicMock()
    adapter.index_attempt_metadata = None
    adapter.prepare.return_value = DocumentBatchPrepareContext(
        updatable_docs=[document], id_to_boost_map={}
    )
    adapter.prepare_enrichment = prepare_enrichment
    embedder = MagicMock()
    embedder.embedding_model.wait_totals.snapshot.return_value = (0.0, 0.0)

    with (
        patch(
            f"{_PATCH_PREFIX}._apply_document_ingestion_hook",
            side_effect=lambda documents: documents,
        ),
        patch(f"{_PATCH_PREFIX}.embed_chunks_with_failure_handling", new=_embed),
        patch(f"{_PATCH_PREFIX}.write_chunks_to_vector_db_with_backoff", new=write),
        patch(f"{_PATCH_PREFIX}.update_docs_content_hash__no_commit"),
        patch(f"{_PATCH_PREFIX}.update_docs_source_info__no_commit"),
        patch(f"{_PATCH_PREFIX}._written_settings_are_present", return_value=True),
        patch(f"{_PATCH_PREFIX}._maybe_push_documents"),
    ):
        result = index_doc_batch(
            written_search_settings_id=1,
            document_batch=[document],
            chunker=_Chunker(),  # ty: ignore[invalid-argument-type]
            embedder=embedder,
            document_index=MagicMock(),
            request_id=None,
            tenant_id="tenant",
            adapter=adapter,
        )

    assert len(chunk_refs) == _CHUNKS_PER_DOC
    assert chunks_alive_at_write == [0]
    assert written_chunk_ids == list(range(_CHUNKS_PER_DOC))
    assert result.total_chunks == _CHUNKS_PER_DOC
