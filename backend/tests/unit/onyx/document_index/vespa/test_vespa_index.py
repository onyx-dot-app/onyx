"""Unit tests for VespaDocumentIndex.index().

These tests mock all external I/O (HTTP calls, thread pools) and verify
the streaming logic, ID cleaning/mapping, and DocumentInsertionRecord
construction.
"""

from collections.abc import Iterator
from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import uuid4

from onyx.access.models import DocumentAccess
from onyx.connectors.models import Document
from onyx.connectors.models import DocumentSource
from onyx.connectors.models import TextSection
from onyx.document_index.interfaces import EnrichedDocumentIndexingInfo
from onyx.document_index.interfaces_new import IndexingMetadata
from onyx.document_index.interfaces_new import TenantState
from onyx.document_index.vespa.vespa_document_index import VespaDocumentIndex
from onyx.indexing.models import ChunkEmbedding
from onyx.indexing.models import DocMetadataAwareIndexChunk
from onyx.indexing.models import IndexChunk


def _make_chunk(
    doc_id: str,
    chunk_id: int = 0,
    content: str = "test content",
) -> DocMetadataAwareIndexChunk:
    doc = Document(
        id=doc_id,
        semantic_identifier="test_doc",
        sections=[TextSection(text=content, link=None)],
        source=DocumentSource.NOT_APPLICABLE,
        metadata={},
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
        title_embedding=None,
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


def _stub_enrich(
    doc_id: str,
    old_chunk_cnt: int,
) -> EnrichedDocumentIndexingInfo:
    """Build an EnrichedDocumentIndexingInfo that says 'no chunks to delete'
    when old_chunk_cnt == 0, or 'has existing chunks' otherwise."""
    return EnrichedDocumentIndexingInfo(
        doc_id=doc_id,
        chunk_start_index=0,
        old_version=False,
        chunk_end_index=old_chunk_cnt,
    )


@patch("onyx.document_index.vespa.vespa_document_index.batch_index_vespa_chunks")
@patch("onyx.document_index.vespa.vespa_document_index.delete_vespa_chunks")
@patch(
    "onyx.document_index.vespa.vespa_document_index.get_document_chunk_ids",
    return_value=[],
)
@patch("onyx.document_index.vespa.vespa_document_index._enrich_basic_chunk_info")
def test_index_single_new_doc(
    mock_enrich: MagicMock,
    mock_get_chunk_ids: MagicMock,  # noqa: ARG001
    mock_delete: MagicMock,  # noqa: ARG001
    mock_batch_index: MagicMock,
) -> None:
    """Indexing a single new document returns one record with already_existed=False."""
    mock_enrich.return_value = _stub_enrich("doc1", old_chunk_cnt=0)

    index = VespaDocumentIndex(
        index_name="test_index",
        tenant_state=TenantState(tenant_id="test_tenant", multitenant=False),
        large_chunks_enabled=False,
        httpx_client=MagicMock(),
    )

    chunk = _make_chunk("doc1")
    metadata = _make_indexing_metadata(["doc1"], old_counts=[0], new_counts=[1])

    results = index.index(chunks=[chunk], indexing_metadata=metadata)

    assert len(results) == 1
    assert results[0].document_id == "doc1"
    assert results[0].already_existed is False

    # batch_index_vespa_chunks should be called once with a single cleaned chunk
    mock_batch_index.assert_called_once()
    call_kwargs = mock_batch_index.call_args
    indexed_chunks = call_kwargs.kwargs["chunks"]
    assert len(indexed_chunks) == 1
    assert indexed_chunks[0].source_document.id == "doc1"
    assert call_kwargs.kwargs["index_name"] == "test_index"
    assert call_kwargs.kwargs["multitenant"] is False


@patch("onyx.document_index.vespa.vespa_document_index.batch_index_vespa_chunks")
@patch("onyx.document_index.vespa.vespa_document_index.delete_vespa_chunks")
@patch(
    "onyx.document_index.vespa.vespa_document_index.get_document_chunk_ids",
    return_value=[],
)
@patch("onyx.document_index.vespa.vespa_document_index._enrich_basic_chunk_info")
def test_index_existing_doc_already_existed_true(
    mock_enrich: MagicMock,
    mock_get_chunk_ids: MagicMock,
    mock_delete: MagicMock,
    mock_batch_index: MagicMock,
) -> None:
    """Re-indexing a doc with previous chunks deletes old chunks, indexes
    new ones, and returns already_existed=True."""
    fake_chunk_ids = [uuid4(), uuid4()]
    mock_enrich.return_value = _stub_enrich("doc1", old_chunk_cnt=5)
    mock_get_chunk_ids.return_value = fake_chunk_ids

    index = VespaDocumentIndex(
        index_name="test_index",
        tenant_state=TenantState(tenant_id="test_tenant", multitenant=False),
        large_chunks_enabled=False,
        httpx_client=MagicMock(),
    )

    chunk = _make_chunk("doc1")
    metadata = _make_indexing_metadata(["doc1"], old_counts=[5], new_counts=[1])

    results = index.index(chunks=[chunk], indexing_metadata=metadata)

    assert len(results) == 1
    assert results[0].already_existed is True

    # Old chunks should be deleted
    mock_delete.assert_called_once()
    delete_kwargs = mock_delete.call_args.kwargs
    assert delete_kwargs["doc_chunk_ids"] == fake_chunk_ids
    assert delete_kwargs["index_name"] == "test_index"

    # New chunk should be indexed
    mock_batch_index.assert_called_once()
    indexed_chunks = mock_batch_index.call_args.kwargs["chunks"]
    assert len(indexed_chunks) == 1
    assert indexed_chunks[0].source_document.id == "doc1"


@patch("onyx.document_index.vespa.vespa_document_index.batch_index_vespa_chunks")
@patch("onyx.document_index.vespa.vespa_document_index.delete_vespa_chunks")
@patch(
    "onyx.document_index.vespa.vespa_document_index.get_document_chunk_ids",
    return_value=[],
)
@patch("onyx.document_index.vespa.vespa_document_index._enrich_basic_chunk_info")
def test_index_multiple_docs(
    mock_enrich: MagicMock,
    mock_get_chunk_ids: MagicMock,  # noqa: ARG001
    mock_delete: MagicMock,  # noqa: ARG001
    mock_batch_index: MagicMock,
) -> None:
    """Indexing multiple documents returns one record per unique document."""
    mock_enrich.side_effect = [
        _stub_enrich("doc1", old_chunk_cnt=0),
        _stub_enrich("doc2", old_chunk_cnt=3),
    ]

    index = VespaDocumentIndex(
        index_name="test_index",
        tenant_state=TenantState(tenant_id="test_tenant", multitenant=False),
        large_chunks_enabled=False,
        httpx_client=MagicMock(),
    )

    chunks = [
        _make_chunk("doc1", chunk_id=0),
        _make_chunk("doc1", chunk_id=1),
        _make_chunk("doc2", chunk_id=0),
    ]
    metadata = _make_indexing_metadata(
        ["doc1", "doc2"], old_counts=[0, 3], new_counts=[2, 1]
    )

    results = index.index(chunks=chunks, indexing_metadata=metadata)

    result_map = {r.document_id: r.already_existed for r in results}
    assert len(result_map) == 2
    assert result_map["doc1"] is False
    assert result_map["doc2"] is True

    # All 3 chunks fit in one batch (BATCH_SIZE=128), so one call
    mock_batch_index.assert_called_once()
    indexed_chunks = mock_batch_index.call_args.kwargs["chunks"]
    assert len(indexed_chunks) == 3
    indexed_doc_ids = [c.source_document.id for c in indexed_chunks]
    assert indexed_doc_ids == ["doc1", "doc1", "doc2"]


@patch("onyx.document_index.vespa.vespa_document_index.batch_index_vespa_chunks")
@patch("onyx.document_index.vespa.vespa_document_index.delete_vespa_chunks")
@patch(
    "onyx.document_index.vespa.vespa_document_index.get_document_chunk_ids",
    return_value=[],
)
@patch("onyx.document_index.vespa.vespa_document_index._enrich_basic_chunk_info")
def test_index_cleans_doc_ids(
    mock_enrich: MagicMock,
    mock_get_chunk_ids: MagicMock,  # noqa: ARG001
    mock_delete: MagicMock,  # noqa: ARG001
    mock_batch_index: MagicMock,
) -> None:
    """Documents with invalid Vespa characters get cleaned IDs, but
    the returned DocumentInsertionRecord uses the original ID."""
    doc_id_with_quote = "doc'1"
    mock_enrich.return_value = _stub_enrich(doc_id_with_quote, old_chunk_cnt=0)

    index = VespaDocumentIndex(
        index_name="test_index",
        tenant_state=TenantState(tenant_id="test_tenant", multitenant=False),
        large_chunks_enabled=False,
        httpx_client=MagicMock(),
    )

    chunk = _make_chunk(doc_id_with_quote)
    metadata = _make_indexing_metadata(
        [doc_id_with_quote], old_counts=[0], new_counts=[1]
    )

    results = index.index(chunks=[chunk], indexing_metadata=metadata)

    assert len(results) == 1
    # The returned ID should be the original (unclean) ID
    assert results[0].document_id == doc_id_with_quote

    # The chunk passed to batch_index_vespa_chunks should have the cleaned ID
    indexed_chunks = mock_batch_index.call_args.kwargs["chunks"]
    assert len(indexed_chunks) == 1
    assert indexed_chunks[0].source_document.id == "doc_1"  # quote replaced with _


@patch("onyx.document_index.vespa.vespa_document_index.batch_index_vespa_chunks")
@patch("onyx.document_index.vespa.vespa_document_index.delete_vespa_chunks")
@patch(
    "onyx.document_index.vespa.vespa_document_index.get_document_chunk_ids",
    return_value=[],
)
@patch("onyx.document_index.vespa.vespa_document_index._enrich_basic_chunk_info")
def test_index_deduplicates_doc_ids_in_results(
    mock_enrich: MagicMock,
    mock_get_chunk_ids: MagicMock,  # noqa: ARG001
    mock_delete: MagicMock,  # noqa: ARG001
    mock_batch_index: MagicMock,
) -> None:
    """Multiple chunks from the same document produce only one
    DocumentInsertionRecord."""
    mock_enrich.return_value = _stub_enrich("doc1", old_chunk_cnt=0)

    index = VespaDocumentIndex(
        index_name="test_index",
        tenant_state=TenantState(tenant_id="test_tenant", multitenant=False),
        large_chunks_enabled=False,
        httpx_client=MagicMock(),
    )

    chunks = [_make_chunk("doc1", chunk_id=i) for i in range(5)]
    metadata = _make_indexing_metadata(["doc1"], old_counts=[0], new_counts=[5])

    results = index.index(chunks=chunks, indexing_metadata=metadata)

    assert len(results) == 1
    assert results[0].document_id == "doc1"

    # All 5 chunks should be passed to batch_index_vespa_chunks
    mock_batch_index.assert_called_once()
    indexed_chunks = mock_batch_index.call_args.kwargs["chunks"]
    assert len(indexed_chunks) == 5
    assert all(c.source_document.id == "doc1" for c in indexed_chunks)


@patch("onyx.document_index.vespa.vespa_document_index.batch_index_vespa_chunks")
@patch("onyx.document_index.vespa.vespa_document_index.delete_vespa_chunks")
@patch(
    "onyx.document_index.vespa.vespa_document_index.get_document_chunk_ids",
    return_value=[],
)
@patch("onyx.document_index.vespa.vespa_document_index._enrich_basic_chunk_info")
@patch(
    "onyx.document_index.vespa.vespa_document_index.BATCH_SIZE",
    3,
)
def test_index_respects_batch_size(
    mock_enrich: MagicMock,
    mock_get_chunk_ids: MagicMock,  # noqa: ARG001
    mock_delete: MagicMock,  # noqa: ARG001
    mock_batch_index: MagicMock,
) -> None:
    """When chunks exceed BATCH_SIZE, batch_index_vespa_chunks is called
    multiple times with correctly sized batches."""
    mock_enrich.return_value = _stub_enrich("doc1", old_chunk_cnt=0)

    index = VespaDocumentIndex(
        index_name="test_index",
        tenant_state=TenantState(tenant_id="test_tenant", multitenant=False),
        large_chunks_enabled=False,
        httpx_client=MagicMock(),
    )

    chunks = [_make_chunk("doc1", chunk_id=i) for i in range(7)]
    metadata = _make_indexing_metadata(["doc1"], old_counts=[0], new_counts=[7])

    results = index.index(chunks=chunks, indexing_metadata=metadata)

    assert len(results) == 1

    # With BATCH_SIZE=3 and 7 chunks: batches of 3, 3, 1
    assert mock_batch_index.call_count == 3
    batch_sizes = [len(c.kwargs["chunks"]) for c in mock_batch_index.call_args_list]
    assert batch_sizes == [3, 3, 1]

    # Verify all chunks are accounted for and in order
    all_indexed = [
        chunk for c in mock_batch_index.call_args_list for chunk in c.kwargs["chunks"]
    ]
    assert len(all_indexed) == 7
    assert [c.chunk_id for c in all_indexed] == list(range(7))


@patch("onyx.document_index.vespa.vespa_document_index.batch_index_vespa_chunks")
@patch("onyx.document_index.vespa.vespa_document_index.delete_vespa_chunks")
@patch(
    "onyx.document_index.vespa.vespa_document_index.get_document_chunk_ids",
    return_value=[],
)
@patch("onyx.document_index.vespa.vespa_document_index._enrich_basic_chunk_info")
def test_index_streams_chunks_lazily(
    mock_enrich: MagicMock,
    mock_get_chunk_ids: MagicMock,  # noqa: ARG001
    mock_delete: MagicMock,  # noqa: ARG001
    mock_batch_index: MagicMock,  # noqa: ARG001
) -> None:
    """Chunks are consumed lazily via a generator, not materialized upfront."""
    mock_enrich.return_value = _stub_enrich("doc1", old_chunk_cnt=0)

    index = VespaDocumentIndex(
        index_name="test_index",
        tenant_state=TenantState(tenant_id="test_tenant", multitenant=False),
        large_chunks_enabled=False,
        httpx_client=MagicMock(),
    )

    consumed: list[int] = []

    def chunk_generator() -> Iterator[DocMetadataAwareIndexChunk]:
        for i in range(3):
            consumed.append(i)
            yield _make_chunk("doc1", chunk_id=i)

    metadata = _make_indexing_metadata(["doc1"], old_counts=[0], new_counts=[3])

    # Before calling index, nothing consumed
    gen = chunk_generator()
    assert len(consumed) == 0

    results = index.index(chunks=gen, indexing_metadata=metadata)

    # After calling index, all chunks should have been consumed
    assert consumed == [0, 1, 2]
    assert len(results) == 1
