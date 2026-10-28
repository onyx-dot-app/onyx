"""External dependency tests for write rejections under an index write block:
the raised error and the stored failure name the block in one short message
instead of carrying the per-chunk response body, and the indexing fallback
fails the batch once instead of retrying every document."""

import uuid
from collections.abc import Generator
from unittest.mock import patch

import pytest

from onyx.db.enums import EmbeddingPrecision
from onyx.document_index.interfaces_new import TenantState
from onyx.document_index.opensearch.client import (
    OpenSearchIndexClient,
    OpenSearchIndexWriteBlockedError,
    wait_for_opensearch_with_timeout,
)
from onyx.document_index.opensearch.opensearch_document_index import (
    OpenSearchDocumentIndex,
)
from onyx.document_index.opensearch.search import DocumentQuery
from onyx.indexing.models import DocMetadataAwareIndexChunk
from onyx.indexing.vector_db_insertion import write_chunks_to_vector_db_with_backoff
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.external_dependency_unit.document_index.conftest import (
    EMBEDDING_DIM,
    make_chunk,
    make_indexing_metadata,
)

_WRITE_BLOCK_SETTING = "index.blocks.write"
_CHUNKS_PER_DOC = 50
# Each per-chunk entry in the raw body is ~250 chars, so 50 chunks would be >10k.
_MAX_MESSAGE_CHARS = 1_000
_TENANT_STATE = TenantState(
    tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE, multitenant=False
)


@pytest.fixture
def blocked_index_with_docs(
    tenant_context: None,  # noqa: ARG001
) -> Generator[tuple[OpenSearchDocumentIndex, str, list[str]], None, None]:
    """Creates an index with two documents, then applies the API write block.
    Drops the index afterwards; clearing the block is always permitted."""
    if not wait_for_opensearch_with_timeout():
        pytest.fail("OpenSearch is not available.")
    index_name = f"test_write_blocked_{uuid.uuid4().hex[:8]}"
    document_index = OpenSearchDocumentIndex(
        tenant_state=_TENANT_STATE,
        index_name=index_name,
        embedding_dim=EMBEDDING_DIM,
        embedding_precision=EmbeddingPrecision.FLOAT,
    )
    client = OpenSearchIndexClient(index_name=index_name)
    try:
        document_index.verify_and_create_index_if_necessary(
            embedding_dim=EMBEDDING_DIM,
            embedding_precision=EmbeddingPrecision.FLOAT,
        )
        doc_ids = [f"blocked_{uuid.uuid4().hex[:8]}" for _ in range(2)]
        document_index.index(
            chunks=_chunks(doc_ids),
            indexing_metadata=make_indexing_metadata(
                doc_ids, old_counts=[0, 0], new_counts=[_CHUNKS_PER_DOC] * 2
            ),
        )
        client.refresh_index()
        client.update_settings({_WRITE_BLOCK_SETTING: True})
        yield document_index, index_name, doc_ids
    finally:
        if client.index_exists():
            client.update_settings({_WRITE_BLOCK_SETTING: None})
            client.delete_index()


def _chunks(doc_ids: list[str]) -> list[DocMetadataAwareIndexChunk]:
    return [
        make_chunk(doc_id, chunk_id=i, content="new content")
        for doc_id in doc_ids
        for i in range(_CHUNKS_PER_DOC)
    ]


def test_delete_by_query_raises_compact_block_error(
    blocked_index_with_docs: tuple[OpenSearchDocumentIndex, str, list[str]],
) -> None:
    _, index_name, doc_ids = blocked_index_with_docs
    query_body = DocumentQuery.delete_from_document_id_query(
        document_id=doc_ids[0], tenant_state=_TENANT_STATE
    )

    with pytest.raises(OpenSearchIndexWriteBlockedError) as exc_info:
        OpenSearchIndexClient(index_name=index_name).delete_by_query(query_body)

    message = str(exc_info.value)
    assert f"{_CHUNKS_PER_DOC}x op=by_query" in message
    assert "cluster_block_exception" in message
    assert "index write (api)" in message
    assert doc_ids[0] not in message
    assert len(message) < _MAX_MESSAGE_CHARS


@pytest.mark.parametrize("indexed_before", [True, False])
def test_vector_db_write_fails_batch_once_with_compact_failures(
    blocked_index_with_docs: tuple[OpenSearchDocumentIndex, str, list[str]],
    indexed_before: bool,
) -> None:
    """An indexed document hits the block on the chunk delete; a new document
    has nothing to delete and hits it on the bulk write."""
    document_index, _, indexed_doc_ids = blocked_index_with_docs
    doc_ids = (
        indexed_doc_ids
        if indexed_before
        else [f"new_{uuid.uuid4().hex[:8]}" for _ in range(2)]
    )
    old_count = _CHUNKS_PER_DOC if indexed_before else 0

    with patch.object(document_index, "index", wraps=document_index.index) as index_spy:
        records, failures = write_chunks_to_vector_db_with_backoff(
            document_index=document_index,
            make_chunks=lambda: _chunks(doc_ids),
            indexing_metadata=make_indexing_metadata(
                doc_ids,
                old_counts=[old_count] * 2,
                new_counts=[_CHUNKS_PER_DOC] * 2,
            ),
            tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
        )

    # One batch call; the per-document retry would add one call per document.
    assert index_spy.call_count == 1
    assert records == []
    assert [f.failed_document.document_id for f in failures if f.failed_document] == (
        doc_ids
    )
    for failure in failures:
        assert isinstance(failure.exception, OpenSearchIndexWriteBlockedError)
        assert "index write (api)" in failure.failure_message
        assert len(failure.failure_message) < _MAX_MESSAGE_CHARS
