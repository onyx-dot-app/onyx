"""Unit tests for embed_chunks_in_batches.

Tests cover:
  - Single batch, no failures
  - Multiple batches, no failures
  - Failure in a single batch
  - Cross-batch document failure scrubbing
  - Later batches skip already-failed docs
  - Empty input
  - All chunks fail
"""

import pickle
from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import Document
from onyx.connectors.models import DocumentFailure
from onyx.connectors.models import DocumentSource
from onyx.connectors.models import TextSection
from onyx.indexing.indexing_pipeline import _embed_chunks_to_disk
from onyx.indexing.models import ChunkEmbedding
from onyx.indexing.models import DocAwareChunk
from onyx.indexing.models import IndexChunk


def _make_doc(doc_id: str) -> Document:
    return Document(
        id=doc_id,
        semantic_identifier="test",
        source=DocumentSource.FILE,
        sections=[TextSection(text="test", link=None)],
        metadata={},
    )


def _make_chunk(doc_id: str, chunk_id: int) -> DocAwareChunk:
    return DocAwareChunk(
        chunk_id=chunk_id,
        blurb="test",
        content="test content",
        source_links=None,
        image_file_id=None,
        section_continuation=False,
        source_document=_make_doc(doc_id),
        title_prefix="",
        metadata_suffix_semantic="",
        metadata_suffix_keyword="",
        mini_chunk_texts=None,
        large_chunk_id=None,
        doc_summary="",
        chunk_context="",
        contextual_rag_reserved_tokens=0,
    )


def _make_index_chunk(doc_id: str, chunk_id: int) -> IndexChunk:
    """Create an IndexChunk (a DocAwareChunk with embeddings)."""
    return IndexChunk(
        chunk_id=chunk_id,
        blurb="test",
        content="test content",
        source_links=None,
        image_file_id=None,
        section_continuation=False,
        source_document=_make_doc(doc_id),
        title_prefix="",
        metadata_suffix_semantic="",
        metadata_suffix_keyword="",
        mini_chunk_texts=None,
        large_chunk_id=None,
        doc_summary="",
        chunk_context="",
        contextual_rag_reserved_tokens=0,
        embeddings=ChunkEmbedding(
            full_embedding=[0.1] * 10,
            mini_chunk_embeddings=[],
        ),
        title_embedding=None,
    )


def _make_failure(doc_id: str) -> ConnectorFailure:
    return ConnectorFailure(
        failed_document=DocumentFailure(document_id=doc_id, document_link=None),
        failure_message="embedding failed",
        exception=RuntimeError("embedding failed"),
    )


def _mock_embed_success(
    chunks: list[DocAwareChunk], **_kwargs: object
) -> tuple[list[IndexChunk], list[ConnectorFailure]]:
    """Simulate successful embedding of all chunks."""
    return (
        [_make_index_chunk(c.source_document.id, c.chunk_id) for c in chunks],
        [],
    )


def _mock_embed_fail_doc(
    fail_doc_id: str,
) -> "callable":
    """Return an embed mock that fails all chunks for a specific doc."""

    def _embed(
        chunks: list[DocAwareChunk], **_kwargs: object
    ) -> tuple[list[IndexChunk], list[ConnectorFailure]]:
        successes = [
            _make_index_chunk(c.source_document.id, c.chunk_id)
            for c in chunks
            if c.source_document.id != fail_doc_id
        ]
        failures = (
            [_make_failure(fail_doc_id)]
            if any(c.source_document.id == fail_doc_id for c in chunks)
            else []
        )
        return successes, failures

    return _embed


class TestEmbedChunksInBatches:
    @patch(
        "onyx.indexing.indexing_pipeline.embed_chunks_with_failure_handling",
    )
    @patch("onyx.indexing.indexing_pipeline.MAX_CHUNKS_PER_DOC_BATCH", 100)
    def test_single_batch_no_failures(
        self, mock_embed: MagicMock, tmp_path: Path
    ) -> None:
        """All chunks fit in one batch and embed successfully."""
        mock_embed.side_effect = _mock_embed_success

        chunks = [_make_chunk("doc1", i) for i in range(3)]
        result = _embed_chunks_to_disk(
            chunks=chunks,
            embedder=MagicMock(),
            tenant_id="test",
            request_id=None,
            tmpdir=tmp_path,
        )

        assert len(result.successful_chunk_ids) == 3
        assert len(result.connector_failures) == 0
        assert tmp_path.exists()

        # Verify pickle contents
        batch_files = list(tmp_path.glob("batch_*.pkl"))
        assert len(batch_files) == 1
        with open(batch_files[0], "rb") as f:
            stored = pickle.load(f)
        assert len(stored) == 3

    @patch(
        "onyx.indexing.indexing_pipeline.embed_chunks_with_failure_handling",
    )
    @patch("onyx.indexing.indexing_pipeline.MAX_CHUNKS_PER_DOC_BATCH", 3)
    def test_multiple_batches_no_failures(
        self, mock_embed: MagicMock, tmp_path: Path
    ) -> None:
        """Chunks are split across multiple batches, all succeed."""
        mock_embed.side_effect = _mock_embed_success

        chunks = [_make_chunk("doc1", i) for i in range(7)]
        result = _embed_chunks_to_disk(
            chunks=chunks,
            embedder=MagicMock(),
            tenant_id="test",
            request_id=None,
            tmpdir=tmp_path,
        )

        assert len(result.successful_chunk_ids) == 7
        assert len(result.connector_failures) == 0

        batch_files = list(tmp_path.glob("batch_*.pkl"))
        assert len(batch_files) == 3  # 3 + 3 + 1

    @patch(
        "onyx.indexing.indexing_pipeline.embed_chunks_with_failure_handling",
    )
    @patch("onyx.indexing.indexing_pipeline.MAX_CHUNKS_PER_DOC_BATCH", 100)
    def test_single_batch_with_failure(
        self, mock_embed: MagicMock, tmp_path: Path
    ) -> None:
        """One doc fails embedding, its chunks are excluded from results."""
        mock_embed.side_effect = _mock_embed_fail_doc("doc2")

        chunks = [
            _make_chunk("doc1", 0),
            _make_chunk("doc2", 1),
            _make_chunk("doc1", 2),
        ]
        result = _embed_chunks_to_disk(
            chunks=chunks,
            embedder=MagicMock(),
            tenant_id="test",
            request_id=None,
            tmpdir=tmp_path,
        )

        assert len(result.connector_failures) == 1
        successful_doc_ids = {doc_id for _, doc_id in result.successful_chunk_ids}
        assert "doc2" not in successful_doc_ids
        assert "doc1" in successful_doc_ids

    @patch(
        "onyx.indexing.indexing_pipeline.embed_chunks_with_failure_handling",
    )
    @patch("onyx.indexing.indexing_pipeline.MAX_CHUNKS_PER_DOC_BATCH", 3)
    def test_cross_batch_failure_scrubs_earlier_batch(
        self, mock_embed: MagicMock, tmp_path: Path
    ) -> None:
        """Doc A spans batches 0 and 1.  It succeeds in batch 0 but fails in
        batch 1.  Its chunks should be scrubbed from batch 0's pickle file."""
        call_count = 0

        def _embed(
            chunks: list[DocAwareChunk], **_kwargs: object
        ) -> tuple[list[IndexChunk], list[ConnectorFailure]]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_embed_success(chunks)
            else:
                return _mock_embed_fail_doc("docA")(chunks)

        mock_embed.side_effect = _embed

        chunks = [
            _make_chunk("docA", 0),
            _make_chunk("docA", 1),
            _make_chunk("docA", 2),
            _make_chunk("docA", 3),
            _make_chunk("docB", 0),
            _make_chunk("docB", 1),
        ]
        result = _embed_chunks_to_disk(
            chunks=chunks,
            embedder=MagicMock(),
            tenant_id="test",
            request_id=None,
            tmpdir=tmp_path,
        )

        # docA should be fully excluded from results
        successful_doc_ids = {doc_id for _, doc_id in result.successful_chunk_ids}
        assert "docA" not in successful_doc_ids
        assert "docB" in successful_doc_ids
        assert len(result.connector_failures) == 1

        # Verify batch 0 pickle was scrubbed of docA chunks
        all_stored: list[IndexChunk] = []
        for batch_file in sorted(tmp_path.glob("batch_*.pkl")):
            with open(batch_file, "rb") as f:
                all_stored.extend(pickle.load(f))
        stored_doc_ids = {c.source_document.id for c in all_stored}
        assert "docA" not in stored_doc_ids
        assert "docB" in stored_doc_ids

    @patch(
        "onyx.indexing.indexing_pipeline.embed_chunks_with_failure_handling",
    )
    @patch("onyx.indexing.indexing_pipeline.MAX_CHUNKS_PER_DOC_BATCH", 3)
    def test_later_batch_skips_already_failed_doc(
        self, mock_embed: MagicMock, tmp_path: Path
    ) -> None:
        """If docA fails in batch 0, its chunks in batch 1 are skipped
        entirely (never sent to the embedder)."""
        embedded_doc_ids: list[str] = []

        def _embed(
            chunks: list[DocAwareChunk], **_kwargs: object
        ) -> tuple[list[IndexChunk], list[ConnectorFailure]]:
            for c in chunks:
                embedded_doc_ids.append(c.source_document.id)
            return _mock_embed_fail_doc("docA")(chunks)

        mock_embed.side_effect = _embed

        chunks = [
            _make_chunk("docA", 0),
            _make_chunk("docA", 1),
            _make_chunk("docA", 2),
            _make_chunk("docA", 3),
            _make_chunk("docB", 0),
            _make_chunk("docB", 1),
        ]
        _embed_chunks_to_disk(
            chunks=chunks,
            embedder=MagicMock(),
            tenant_id="test",
            request_id=None,
            tmpdir=tmp_path,
        )

        # docA should only appear in batch 0, not batch 1
        batch_1_doc_ids = embedded_doc_ids[3:]
        assert "docA" not in batch_1_doc_ids

    @patch(
        "onyx.indexing.indexing_pipeline.embed_chunks_with_failure_handling",
    )
    @patch("onyx.indexing.indexing_pipeline.MAX_CHUNKS_PER_DOC_BATCH", 3)
    def test_failed_doc_skipped_in_later_batch_while_other_doc_succeeds(
        self, mock_embed: MagicMock, tmp_path: Path
    ) -> None:
        """doc1 spans batches 0 and 1, doc2 only in batch 1.  Batch 0 fails
        doc1.  In batch 1, doc1 chunks should be skipped but doc2 chunks
        should still be embedded successfully."""
        embedded_chunks: list[list[str]] = []

        def _embed(
            chunks: list[DocAwareChunk], **_kwargs: object
        ) -> tuple[list[IndexChunk], list[ConnectorFailure]]:
            embedded_chunks.append([c.source_document.id for c in chunks])
            return _mock_embed_fail_doc("doc1")(chunks)

        mock_embed.side_effect = _embed

        chunks = [
            _make_chunk("doc1", 0),
            _make_chunk("doc1", 1),
            _make_chunk("doc1", 2),
            _make_chunk("doc1", 3),
            _make_chunk("doc2", 0),
            _make_chunk("doc2", 1),
        ]
        result = _embed_chunks_to_disk(
            chunks=chunks,
            embedder=MagicMock(),
            tenant_id="test",
            request_id=None,
            tmpdir=tmp_path,
        )

        # doc1 should be fully excluded, doc2 fully included
        successful_doc_ids = {doc_id for _, doc_id in result.successful_chunk_ids}
        assert "doc1" not in successful_doc_ids
        assert "doc2" in successful_doc_ids
        assert len(result.successful_chunk_ids) == 2  # doc2's 2 chunks

        # Batch 1 should only contain doc2 (doc1 was filtered before embedding)
        assert len(embedded_chunks) == 2
        assert "doc1" not in embedded_chunks[1]
        assert embedded_chunks[1] == ["doc2", "doc2"]

        # Verify on-disk state has no doc1 chunks
        all_stored: list[IndexChunk] = []
        for batch_file in sorted(tmp_path.glob("batch_*.pkl")):
            with open(batch_file, "rb") as f:
                all_stored.extend(pickle.load(f))
        assert all(c.source_document.id == "doc2" for c in all_stored)

    @patch(
        "onyx.indexing.indexing_pipeline.embed_chunks_with_failure_handling",
    )
    def test_empty_input(self, mock_embed: MagicMock, tmp_path: Path) -> None:
        """Empty chunk list produces empty results."""
        mock_embed.side_effect = _mock_embed_success

        result = _embed_chunks_to_disk(
            chunks=[],
            embedder=MagicMock(),
            tenant_id="test",
            request_id=None,
            tmpdir=tmp_path,
        )

        assert len(result.successful_chunk_ids) == 0
        assert len(result.connector_failures) == 0
        mock_embed.assert_not_called()

    @patch(
        "onyx.indexing.indexing_pipeline.embed_chunks_with_failure_handling",
    )
    @patch("onyx.indexing.indexing_pipeline.MAX_CHUNKS_PER_DOC_BATCH", 100)
    def test_all_chunks_fail(self, mock_embed: MagicMock, tmp_path: Path) -> None:
        """When all documents fail, results have no successful chunks."""

        def _fail_all(
            chunks: list[DocAwareChunk], **_kwargs: object
        ) -> tuple[list[IndexChunk], list[ConnectorFailure]]:
            doc_ids = {c.source_document.id for c in chunks}
            return [], [_make_failure(doc_id) for doc_id in doc_ids]

        mock_embed.side_effect = _fail_all

        chunks = [_make_chunk("doc1", 0), _make_chunk("doc2", 1)]
        result = _embed_chunks_to_disk(
            chunks=chunks,
            embedder=MagicMock(),
            tenant_id="test",
            request_id=None,
            tmpdir=tmp_path,
        )

        assert len(result.successful_chunk_ids) == 0
        assert len(result.connector_failures) == 2
