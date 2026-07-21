"""Offset (pagination) behavior of keyword/hybrid retrieval against a live
OpenSearch: an offset window must be the corresponding slice of the same
query's full ranking, and disjoint from the first window."""

import uuid

import pytest

from onyx.context.search.enums import QueryType
from onyx.context.search.models import IndexFilters
from onyx.document_index.opensearch.opensearch_document_index import (
    OpenSearchDocumentIndex,
)
from tests.external_dependency_unit.document_index.conftest import EMBEDDING_DIM
from tests.external_dependency_unit.document_index.conftest import make_chunk
from tests.external_dependency_unit.document_index.conftest import (
    make_indexing_metadata,
)

NUM_DOCS = 12
WINDOW = 4
QUERY = "pagination target content"


@pytest.fixture(scope="module")
def indexed_docs(opensearch_index: OpenSearchDocumentIndex) -> list[str]:
    doc_ids = [f"pagination_doc_{uuid.uuid4().hex[:8]}_{i}" for i in range(NUM_DOCS)]
    chunks = [
        make_chunk(
            doc_id,
            chunk_id=0,
            # Vary term frequency so BM25 scores differ across docs.
            content=("pagination target content " * (i + 1)).strip(),
        )
        for i, doc_id in enumerate(doc_ids)
    ]
    opensearch_index.index(
        chunks=chunks,
        indexing_metadata=make_indexing_metadata(
            doc_ids=doc_ids,
            old_counts=[0] * NUM_DOCS,
            new_counts=[1] * NUM_DOCS,
        ),
    )
    # OpenSearch is eventually consistent — make the new docs searchable now.
    opensearch_index._client.refresh_index()
    return doc_ids


def _ids(chunks: list) -> list[str]:
    return [chunk.document_id for chunk in chunks]


def test_keyword_retrieval_offset_windows(
    opensearch_index: OpenSearchDocumentIndex,
    indexed_docs: list[str],  # noqa: ARG001
) -> None:
    filters = IndexFilters(access_control_list=None)

    full = opensearch_index.keyword_retrieval(
        query=QUERY,
        filters=filters,
        num_to_retrieve=2 * WINDOW,
    )
    assert len(full) == 2 * WINDOW

    window_0 = opensearch_index.keyword_retrieval(
        query=QUERY,
        filters=filters,
        num_to_retrieve=WINDOW,
    )
    window_1 = opensearch_index.keyword_retrieval(
        query=QUERY,
        filters=filters,
        num_to_retrieve=WINDOW,
        offset=WINDOW,
    )

    assert _ids(window_0) == _ids(full)[:WINDOW]
    assert _ids(window_1) == _ids(full)[WINDOW : 2 * WINDOW]
    assert set(_ids(window_0)).isdisjoint(_ids(window_1))


def test_offset_past_end_of_results_returns_empty(
    opensearch_index: OpenSearchDocumentIndex,
    indexed_docs: list[str],  # noqa: ARG001
) -> None:
    """Hybrid queries raise a 400 when `from` is past the fused result set;
    the index must translate that to an empty result like keyword queries do."""
    filters = IndexFilters(access_control_list=None)
    deep_offset = 10 * NUM_DOCS

    hybrid = opensearch_index.hybrid_retrieval(
        query=QUERY,
        query_embedding=[1.0] + [0.0] * (EMBEDDING_DIM - 1),
        final_keywords=None,
        query_type=QueryType.SEMANTIC,
        filters=filters,
        num_to_retrieve=WINDOW,
        offset=deep_offset,
    )
    assert hybrid == []

    keyword = opensearch_index.keyword_retrieval(
        query=QUERY,
        filters=filters,
        num_to_retrieve=WINDOW,
        offset=deep_offset,
    )
    assert keyword == []


def test_hybrid_retrieval_offset_windows(
    opensearch_index: OpenSearchDocumentIndex,
    indexed_docs: list[str],  # noqa: ARG001
) -> None:
    filters = IndexFilters(access_control_list=None)
    query_embedding = [1.0] + [0.0] * (EMBEDDING_DIM - 1)

    full = opensearch_index.hybrid_retrieval(
        query=QUERY,
        query_embedding=query_embedding,
        final_keywords=None,
        query_type=QueryType.SEMANTIC,
        filters=filters,
        num_to_retrieve=2 * WINDOW,
    )
    assert len(full) == 2 * WINDOW

    window_0 = opensearch_index.hybrid_retrieval(
        query=QUERY,
        query_embedding=query_embedding,
        final_keywords=None,
        query_type=QueryType.SEMANTIC,
        filters=filters,
        num_to_retrieve=WINDOW,
    )
    window_1 = opensearch_index.hybrid_retrieval(
        query=QUERY,
        query_embedding=query_embedding,
        final_keywords=None,
        query_type=QueryType.SEMANTIC,
        filters=filters,
        num_to_retrieve=WINDOW,
        offset=WINDOW,
    )

    assert _ids(window_0) == _ids(full)[:WINDOW]
    assert _ids(window_1) == _ids(full)[WINDOW : 2 * WINDOW]
    assert set(_ids(window_0)).isdisjoint(_ids(window_1))
