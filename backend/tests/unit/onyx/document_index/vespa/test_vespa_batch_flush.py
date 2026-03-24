"""Unit tests for VespaDocumentIndex.index().

These tests mock all external I/O (HTTP calls, thread pools) and verify
the streaming logic, ID cleaning/mapping, and DocumentInsertionRecord
construction.
"""

from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.access.models import DocumentAccess
from onyx.configs.constants import DocumentSource
from onyx.connectors.models import Document
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
