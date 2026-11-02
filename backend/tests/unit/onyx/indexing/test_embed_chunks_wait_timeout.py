"""A rate limit wait that times out fails the batch without per-document retries."""

from unittest.mock import MagicMock

from onyx.indexing.embedder import embed_chunks_with_failure_handling
from onyx.natural_language_processing.embedding_rate_limit import (
    EmbeddingWaitTimeoutError,
)
from tests.unit.onyx.indexing.test_embed_chunks_in_batches import _make_chunk


def test_batch_wait_timeout_fails_every_document_without_retries() -> None:
    chunks = [_make_chunk("doc1", 0), _make_chunk("doc1", 1), _make_chunk("doc2", 0)]
    embedder = MagicMock()
    embedder.embed_chunks.side_effect = EmbeddingWaitTimeoutError("waited 6 hours")

    embedded, failures = embed_chunks_with_failure_handling(chunks, embedder)

    assert embedded == []
    assert sorted(
        f.failed_document.document_id for f in failures if f.failed_document
    ) == [
        "doc1",
        "doc2",
    ]
    assert all("waited 6 hours" in f.failure_message for f in failures)
    embedder.embed_chunks.assert_called_once()


def test_document_wait_timeout_fails_the_remaining_documents() -> None:
    """The batch fails for another reason, then a document times out: later
    documents fail without waiting again."""
    chunks = [_make_chunk("doc1", 0), _make_chunk("doc2", 0), _make_chunk("doc3", 0)]
    embedder = MagicMock()
    embedder.embed_chunks.side_effect = [
        RuntimeError("bad batch"),
        EmbeddingWaitTimeoutError("waited 6 hours"),
    ]

    embedded, failures = embed_chunks_with_failure_handling(chunks, embedder)

    assert embedded == []
    assert [f.failed_document.document_id for f in failures if f.failed_document] == [
        "doc1",
        "doc2",
        "doc3",
    ]
    assert embedder.embed_chunks.call_count == 2
