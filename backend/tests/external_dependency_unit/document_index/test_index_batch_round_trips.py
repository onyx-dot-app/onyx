"""Counts the OpenSearch HTTP requests that one indexing batch sends.

These tests assume OpenSearch is running. They use their own index and delete
it at the end.
"""

import uuid
from collections.abc import Generator
from typing import Any
from unittest.mock import patch

import pytest

from onyx.db.enums import VectorQuantization
from onyx.document_index.interfaces import TenantState
from onyx.document_index.opensearch.client import wait_for_opensearch_with_timeout
from onyx.document_index.opensearch.opensearch_document_index import (
    OpenSearchDocumentIndex,
)
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.external_dependency_unit.document_index.conftest import (
    EMBEDDING_DIM,
    make_chunk,
    make_indexing_metadata,
)

DOCS_PER_BATCH = 16
CHUNKS_PER_DOC = 3


@pytest.fixture
def own_index(
    tenant_context: None,  # noqa: ARG001
) -> Generator[OpenSearchDocumentIndex, None, None]:
    if not wait_for_opensearch_with_timeout():
        pytest.fail("OpenSearch is not available.")
    index = OpenSearchDocumentIndex(
        tenant_state=TenantState(
            tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE, multitenant=False
        ),
        index_name=f"test_batch_rt_{uuid.uuid4().hex[:8]}",
        embedding_dim=EMBEDDING_DIM,
        vector_quantization=VectorQuantization.NONE,
    )
    index.verify_and_create_index_if_necessary(embedding_dim=EMBEDDING_DIM)
    try:
        yield index
    finally:
        index._client.delete_index()


def _index_batch_and_count_requests(
    index: OpenSearchDocumentIndex, doc_ids: list[str], old_count: int
) -> tuple[int, dict[str, bool]]:
    chunks = [
        make_chunk(doc_id, chunk_id=i, content=f"{doc_id} chunk {i}")
        for doc_id in doc_ids
        for i in range(CHUNKS_PER_DOC)
    ]
    metadata = make_indexing_metadata(
        doc_ids,
        old_counts=[old_count] * len(doc_ids),
        new_counts=[CHUNKS_PER_DOC] * len(doc_ids),
    )
    transport = index._client._client.transport
    real_perform_request = transport.perform_request
    calls: list[str] = []

    def _counting_perform_request(
        method: str, url: str, *args: Any, **kwargs: Any
    ) -> Any:
        calls.append(f"{method} {url}")
        return real_perform_request(method, url, *args, **kwargs)

    with patch.object(transport, "perform_request", _counting_perform_request):
        results = index.index(chunks=chunks, indexing_metadata=metadata)
    print(f"OpenSearch requests for {len(doc_ids)} docs: {len(calls)} {calls}")
    return len(calls), {r.document_id: r.already_existed for r in results}


def test_index_batch_uses_one_delete_and_one_bulk(
    own_index: OpenSearchDocumentIndex,
) -> None:
    doc_ids = [f"batch_rt_{i}_{uuid.uuid4().hex[:6]}" for i in range(DOCS_PER_BATCH)]

    num_requests, existed = _index_batch_and_count_requests(
        own_index, doc_ids, old_count=0
    )
    assert num_requests == 2
    assert existed == dict.fromkeys(doc_ids, False)

    # Re-index the same docs: the old chunks go and the docs count as existing.
    own_index._client.refresh_index()
    num_requests, existed = _index_batch_and_count_requests(
        own_index, doc_ids, old_count=CHUNKS_PER_DOC
    )
    assert num_requests == 2
    assert existed == dict.fromkeys(doc_ids, True)

    own_index._client.refresh_index()
    assert own_index.get_documents_with_any_chunk(doc_ids) == set(doc_ids)


def test_index_drops_tail_chunks_of_shorter_docs(
    own_index: OpenSearchDocumentIndex,
) -> None:
    doc_ids = [f"batch_tail_{i}_{uuid.uuid4().hex[:6]}" for i in range(4)]
    long_chunks = [
        make_chunk(doc_id, chunk_id=i) for doc_id in doc_ids for i in range(5)
    ]
    own_index.index(
        chunks=long_chunks,
        indexing_metadata=make_indexing_metadata(
            doc_ids, old_counts=[0] * 4, new_counts=[5] * 4
        ),
    )
    own_index._client.refresh_index()

    short_chunks = [make_chunk(doc_id, chunk_id=0) for doc_id in doc_ids]
    own_index.index(
        chunks=short_chunks,
        indexing_metadata=make_indexing_metadata(
            doc_ids, old_counts=[5] * 4, new_counts=[1] * 4
        ),
    )
    own_index._client.refresh_index()

    remaining: list[tuple[str, int]] = [
        (chunk.document_id, chunk.chunk_index)
        for page in own_index._client.iter_chunks_for_doc_ids(
            doc_ids, tenant_state=own_index._tenant_state
        )
        for chunk in page
    ]
    assert sorted(remaining) == sorted((doc_id, 0) for doc_id in doc_ids)
