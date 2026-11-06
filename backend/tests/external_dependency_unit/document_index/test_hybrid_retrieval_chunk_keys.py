"""External dependency tests for hybrid retrieval that reads only chunk keys.

Hybrid retrieval first runs the hybrid query with doc values only, then fetches
the source of the top hits. These tests check that it returns the same chunks,
order and scores as one hybrid query that returns the source.
"""

import random
import uuid
from unittest.mock import patch

import pytest

from onyx.configs.constants import PUBLIC_DOC_PAT
from onyx.context.search.enums import QueryType
from onyx.context.search.models import IndexFilters, InferenceChunk
from onyx.db.enums import VectorQuantization
from onyx.document_index.interfaces import TenantState
from onyx.document_index.opensearch import opensearch_document_index
from onyx.document_index.opensearch.client import (
    OpenSearchIndexClient,
    wait_for_opensearch_with_timeout,
)
from onyx.document_index.opensearch.opensearch_document_index import (
    OpenSearchDocumentIndex,
)
from onyx.indexing.models import ChunkEmbedding, DocMetadataAwareIndexChunk
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.external_dependency_unit.document_index.conftest import (
    EMBEDDING_DIM,
    make_chunk,
    make_indexing_metadata,
)

_NUM_DOCS = 12
_CHUNKS_PER_DOC = 3
_NUM_HITS = 10
_WORDS = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot"]


def _make_chunk(
    doc_id: str, chunk_index: int, rng: random.Random
) -> DocMetadataAwareIndexChunk:
    content = " ".join(rng.choice(_WORDS) for _ in range(8))
    return make_chunk(doc_id, chunk_id=chunk_index, content=content).model_copy(
        update={
            "embeddings": ChunkEmbedding(
                full_embedding=[rng.gauss(0.0, 1.0) for _ in range(EMBEDDING_DIM)],
                mini_chunk_embeddings=[],
            ),
        }
    )


def _hybrid_retrieval(
    document_index: OpenSearchDocumentIndex, query_embedding: list[float]
) -> list[InferenceChunk]:
    return document_index.hybrid_retrieval(
        query="alpha bravo",
        query_embedding=query_embedding,
        final_keywords=None,
        query_type=QueryType.SEMANTIC,
        filters=IndexFilters(
            access_control_list=[PUBLIC_DOC_PAT],
            tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
        ),
        num_to_retrieve=_NUM_HITS,
    )


def test_hybrid_retrieval_by_chunk_keys_matches_single_request(
    tenant_context: None,  # noqa: ARG001
) -> None:
    if not wait_for_opensearch_with_timeout():
        pytest.fail("OpenSearch is not available.")

    index_name = f"test_hybrid_chunk_keys_{uuid.uuid4().hex[:8]}"
    document_index = OpenSearchDocumentIndex(
        tenant_state=TenantState(
            tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE, multitenant=False
        ),
        index_name=index_name,
        embedding_dim=EMBEDDING_DIM,
        vector_quantization=VectorQuantization.NONE,
    )
    with OpenSearchIndexClient(index_name=index_name) as client:
        try:
            document_index.verify_and_create_index_if_necessary(
                embedding_dim=EMBEDDING_DIM,
            )
            rng = random.Random(7)
            doc_ids = [f"chunk_keys_doc_{i}" for i in range(_NUM_DOCS)]
            document_index.index(
                chunks=[
                    _make_chunk(doc_id, chunk_index, rng)
                    for doc_id in doc_ids
                    for chunk_index in range(_CHUNKS_PER_DOC)
                ],
                indexing_metadata=make_indexing_metadata(
                    doc_ids,
                    old_counts=[0] * _NUM_DOCS,
                    new_counts=[_CHUNKS_PER_DOC] * _NUM_DOCS,
                ),
            )
            client.refresh_index()
            query_embedding = [rng.gauss(0.0, 1.0) for _ in range(EMBEDDING_DIM)]

            with patch.object(
                OpenSearchIndexClient,
                "_run_search",
                autospec=True,
                side_effect=OpenSearchIndexClient._run_search,
            ) as search_spy:
                chunk_keys_results = _hybrid_retrieval(document_index, query_embedding)
            # The hybrid query reads no stored fields; the second request
            # fetches only the top hits.
            hybrid_body, fetch_body = (
                search_call.kwargs["body"] for search_call in search_spy.call_args_list
            )
            assert hybrid_body["stored_fields"] == "_none_"
            assert "_source" not in hybrid_body
            assert fetch_body["size"] == _NUM_HITS

            # Explain needs the source in the hybrid query, so it keeps the
            # single-request path.
            with patch.object(
                opensearch_document_index, "OPENSEARCH_EXPLAIN_ENABLED", True
            ):
                single_request_results = _hybrid_retrieval(
                    document_index, query_embedding
                )

            assert len(chunk_keys_results) == _NUM_HITS
            assert [
                (chunk.document_id, chunk.chunk_id, chunk.score, chunk.content)
                for chunk in chunk_keys_results
            ] == [
                (chunk.document_id, chunk.chunk_id, chunk.score, chunk.content)
                for chunk in single_request_results
            ]
        finally:
            client.delete_index()
