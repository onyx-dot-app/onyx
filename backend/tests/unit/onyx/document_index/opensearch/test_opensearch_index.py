"""Unit tests for OpenSearchDocumentIndex.index().

These tests mock the OpenSearch client and verify the buffered
flush-by-document logic, DocumentInsertionRecord construction, and
delete-before-insert semantics.
"""

from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.access.models import DocumentAccess
from onyx.connectors.models import Document
from onyx.connectors.models import DocumentSource
from onyx.connectors.models import TextSection
from onyx.document_index.interfaces_new import IndexingMetadata
from onyx.document_index.interfaces_new import TenantState
from onyx.document_index.opensearch.opensearch_document_index import (
    OpenSearchDocumentIndex,
)
from onyx.indexing.models import ChunkEmbedding
from onyx.indexing.models import DocMetadataAwareIndexChunk
from onyx.indexing.models import IndexChunk


def _make_chunk(
    doc_id: str,
    chunk_id: int = 0,
    content: str = "test content",
    chunk_count: int | None = None,
) -> DocMetadataAwareIndexChunk:
    doc = Document(
        id=doc_id,
        semantic_identifier="test_doc",
        sections=[TextSection(text=content, link=None)],
        source=DocumentSource.NOT_APPLICABLE,
        metadata={},
        chunk_count=chunk_count,
    )
    index_chunk = IndexChunk(
        chunk_id=chunk_id,
        blurb=content[:50],
        content=content,
        source_links=None,
        image_file_id=None,
        section_continuation=False,
        source_document=doc,
        title_prefix="",
        metadata_suffix_semantic="",
        metadata_suffix_keyword="",
        contextual_rag_reserved_tokens=0,
        doc_summary="",
        chunk_context="",
        mini_chunk_texts=None,
        large_chunk_id=None,
        embeddings=ChunkEmbedding(
            full_embedding=[0.1] * 10,
            mini_chunk_embeddings=[],
        ),
        title_embedding=[0.1] * 10,
    )
    access = DocumentAccess.build(
        user_emails=[],
        user_groups=[],
        external_user_emails=[],
        external_user_group_ids=[],
        is_public=True,
    )
    return DocMetadataAwareIndexChunk.from_index_chunk(
        index_chunk=index_chunk,
        access=access,
        document_sets=set(),
        user_project=[],
        personas=[],
        boost=0,
        aggregated_chunk_boost_factor=1.0,
        tenant_id="test_tenant",
    )


def _make_indexing_metadata(
    doc_ids: list[str],
    old_counts: list[int],
    new_counts: list[int],
) -> IndexingMetadata:
    return IndexingMetadata(
        doc_id_to_chunk_cnt_diff={
            doc_id: IndexingMetadata.ChunkCounts(
                old_chunk_cnt=old,
                new_chunk_cnt=new,
            )
            for doc_id, old, new in zip(doc_ids, old_counts, new_counts)
        }
    )


def _make_os_index(mock_client: MagicMock) -> OpenSearchDocumentIndex:
    """Create an OpenSearchDocumentIndex with a mocked client."""
    with patch.object(
        OpenSearchDocumentIndex,
        "__init__",
        lambda _self, *_a, **_kw: None,
    ):
        idx = OpenSearchDocumentIndex.__new__(OpenSearchDocumentIndex)

    idx._index_name = "test_index"
    idx._tenant_state = TenantState(tenant_id="test_tenant", multitenant=False)
    idx._client = mock_client
    return idx


def test_index_single_new_doc() -> None:
    """Indexing a single new document returns one record with already_existed=False."""
    mock_client = MagicMock()
    mock_client.bulk_index_documents.return_value = None

    idx = _make_os_index(mock_client)

    # Patch delete to return 0 (no existing chunks)
    with patch.object(idx, "delete", return_value=0) as mock_delete:
        chunk = _make_chunk("doc1")
        metadata = _make_indexing_metadata(["doc1"], old_counts=[0], new_counts=[1])

        results = idx.index(chunks=[chunk], indexing_metadata=metadata)

    assert len(results) == 1
    assert results[0].document_id == "doc1"
    assert results[0].already_existed is False
    mock_delete.assert_called_once()
    mock_client.bulk_index_documents.assert_called_once()


def test_index_existing_doc_already_existed_true() -> None:
    """Re-indexing a doc with previous chunks returns already_existed=True."""
    mock_client = MagicMock()
    mock_client.bulk_index_documents.return_value = None

    idx = _make_os_index(mock_client)

    with patch.object(idx, "delete", return_value=5):
        chunk = _make_chunk("doc1")
        metadata = _make_indexing_metadata(["doc1"], old_counts=[5], new_counts=[1])

        results = idx.index(chunks=[chunk], indexing_metadata=metadata)

    assert len(results) == 1
    assert results[0].already_existed is True


def test_index_multiple_docs_flushed_separately() -> None:
    """Chunks from different documents are flushed in separate bulk calls."""
    mock_client = MagicMock()
    mock_client.bulk_index_documents.return_value = None

    idx = _make_os_index(mock_client)

    with patch.object(idx, "delete", return_value=0):
        chunks = [
            _make_chunk("doc1", chunk_id=0),
            _make_chunk("doc1", chunk_id=1),
            _make_chunk("doc2", chunk_id=0),
        ]
        metadata = _make_indexing_metadata(
            ["doc1", "doc2"], old_counts=[0, 0], new_counts=[2, 1]
        )

        results = idx.index(chunks=chunks, indexing_metadata=metadata)

    result_map = {r.document_id: r.already_existed for r in results}
    assert len(result_map) == 2
    assert result_map["doc1"] is False
    assert result_map["doc2"] is False
    # Two separate flushes: one for doc1 (2 chunks), one for doc2 (1 chunk)
    assert mock_client.bulk_index_documents.call_count == 2


def test_index_deletes_before_inserting() -> None:
    """For each document, delete is called before bulk_index_documents."""
    mock_client = MagicMock()
    mock_client.bulk_index_documents.return_value = None

    call_order: list[str] = []

    idx = _make_os_index(mock_client)

    def track_delete(*_args: object, **_kwargs: object) -> int:
        call_order.append("delete")
        return 3

    def track_bulk(*_args: object, **_kwargs: object) -> None:
        call_order.append("bulk_index")

    mock_client.bulk_index_documents.side_effect = track_bulk

    with patch.object(idx, "delete", side_effect=track_delete):
        chunk = _make_chunk("doc1")
        metadata = _make_indexing_metadata(["doc1"], old_counts=[3], new_counts=[1])

        idx.index(chunks=[chunk], indexing_metadata=metadata)

    assert call_order == ["delete", "bulk_index"]


def test_index_delete_called_once_per_doc() -> None:
    """Delete is called only once per document, even with multiple chunks."""
    mock_client = MagicMock()
    mock_client.bulk_index_documents.return_value = None

    idx = _make_os_index(mock_client)

    with patch.object(idx, "delete", return_value=0) as mock_delete:
        # 3 chunks, all same doc — should only delete once
        chunks = [_make_chunk("doc1", chunk_id=i) for i in range(3)]
        metadata = _make_indexing_metadata(["doc1"], old_counts=[0], new_counts=[3])

        idx.index(chunks=chunks, indexing_metadata=metadata)

    mock_delete.assert_called_once()


def test_index_flushes_on_doc_boundary() -> None:
    """When doc ID changes in the stream, the previous doc's chunks are flushed."""
    mock_client = MagicMock()
    mock_client.bulk_index_documents.return_value = None

    idx = _make_os_index(mock_client)

    bulk_call_chunk_counts: list[int] = []

    def track_bulk(documents: list[object], **_kwargs: object) -> None:
        bulk_call_chunk_counts.append(len(documents))

    mock_client.bulk_index_documents.side_effect = track_bulk

    with patch.object(idx, "delete", return_value=0):
        chunks = [
            _make_chunk("doc1", chunk_id=0),
            _make_chunk("doc1", chunk_id=1),
            _make_chunk("doc1", chunk_id=2),
            _make_chunk("doc2", chunk_id=0),
            _make_chunk("doc2", chunk_id=1),
        ]
        metadata = _make_indexing_metadata(
            ["doc1", "doc2"], old_counts=[0, 0], new_counts=[3, 2]
        )

        idx.index(chunks=chunks, indexing_metadata=metadata)

    # First flush: 3 chunks for doc1, second flush: 2 chunks for doc2
    assert bulk_call_chunk_counts == [3, 2]
