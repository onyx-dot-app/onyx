"""Tests for DisabledDocumentIndex — verifies all methods raise RuntimeError.

This is the safety net for the DISABLE_VECTOR_DB feature. Every method on
DisabledDocumentIndex must raise RuntimeError with the standard error message
so any accidental vector-DB call is caught immediately.
"""

import re

import pytest

from onyx.context.search.enums import QueryType
from onyx.context.search.models import IndexFilters
from onyx.db.enums import EmbeddingPrecision
from onyx.document_index.disabled import DisabledDocumentIndex
from onyx.document_index.disabled import VECTOR_DB_DISABLED_ERROR
from onyx.document_index.interfaces_new import IndexingMetadata
from onyx.document_index.interfaces_new import MetadataUpdateRequest

ESCAPED_ERROR = re.escape(VECTOR_DB_DISABLED_ERROR)


@pytest.fixture
def disabled_index() -> DisabledDocumentIndex:
    return DisabledDocumentIndex()


def _stub_filters() -> IndexFilters:
    return IndexFilters(access_control_list=None)


def test_verify_and_create_no_op(disabled_index: DisabledDocumentIndex) -> None:
    disabled_index.verify_and_create_index_if_necessary(
        embedding_dim=768,
        embedding_precision=EmbeddingPrecision.FLOAT,
    )


def test_index_raises(disabled_index: DisabledDocumentIndex) -> None:
    with pytest.raises(RuntimeError, match=ESCAPED_ERROR):
        disabled_index.index(
            chunks=[],
            indexing_metadata=IndexingMetadata(doc_id_to_chunk_cnt_diff={}),
        )


def test_delete_raises(disabled_index: DisabledDocumentIndex) -> None:
    with pytest.raises(RuntimeError, match=ESCAPED_ERROR):
        disabled_index.delete(document_id="doc-1", chunk_count=None)


def test_update_raises(disabled_index: DisabledDocumentIndex) -> None:
    update_request = MetadataUpdateRequest(
        document_ids=["doc-1"],
        doc_id_to_chunk_cnt={"doc-1": -1},
    )
    with pytest.raises(RuntimeError, match=ESCAPED_ERROR):
        disabled_index.update(update_requests=[update_request])


def test_id_based_retrieval_raises(disabled_index: DisabledDocumentIndex) -> None:
    with pytest.raises(RuntimeError, match=ESCAPED_ERROR):
        disabled_index.id_based_retrieval(
            chunk_requests=[],
            filters=_stub_filters(),
        )


def test_hybrid_retrieval_raises(disabled_index: DisabledDocumentIndex) -> None:
    with pytest.raises(RuntimeError, match=ESCAPED_ERROR):
        disabled_index.hybrid_retrieval(
            query="test",
            query_embedding=[0.0] * 768,
            final_keywords=None,
            query_type=QueryType.SEMANTIC,
            filters=_stub_filters(),
            num_to_retrieve=10,
        )


def test_keyword_retrieval_raises(disabled_index: DisabledDocumentIndex) -> None:
    with pytest.raises(RuntimeError, match=ESCAPED_ERROR):
        disabled_index.keyword_retrieval(
            query="test",
            filters=_stub_filters(),
            num_to_retrieve=10,
        )


def test_semantic_retrieval_raises(disabled_index: DisabledDocumentIndex) -> None:
    with pytest.raises(RuntimeError, match=ESCAPED_ERROR):
        disabled_index.semantic_retrieval(
            query_embedding=[0.0] * 768,
            filters=_stub_filters(),
            num_to_retrieve=10,
        )


def test_random_retrieval_raises(disabled_index: DisabledDocumentIndex) -> None:
    with pytest.raises(RuntimeError, match=ESCAPED_ERROR):
        disabled_index.random_retrieval(filters=_stub_filters())
