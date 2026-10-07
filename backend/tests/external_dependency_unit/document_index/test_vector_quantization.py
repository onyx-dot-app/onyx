"""External dependency tests for OpenSearch vector quantization.

These tests assume OpenSearch 3.6 or later is running (1-bit quantization needs
3.6).
"""

import random
import uuid
from typing import Any
from unittest.mock import patch

import pytest

from onyx.configs.constants import PUBLIC_DOC_PAT
from onyx.context.search.enums import QueryType
from onyx.context.search.models import IndexFilters
from onyx.db.enums import VectorQuantization
from onyx.document_index.interfaces import TenantState
from onyx.document_index.opensearch.client import (
    OpenSearchIndexClient,
    wait_for_opensearch_with_timeout,
)
from onyx.document_index.opensearch.constants import LUCENE_SCALAR_QUANTIZATION
from onyx.document_index.opensearch.opensearch_document_index import (
    OpenSearchDocumentIndex,
)
from onyx.document_index.opensearch.schema import (
    CONTENT_VECTOR_FIELD_NAME,
    TITLE_VECTOR_FIELD_NAME,
)
from onyx.indexing.models import ChunkEmbedding, DocMetadataAwareIndexChunk
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.external_dependency_unit.document_index.conftest import (
    EMBEDDING_DIM,
    make_chunk,
    make_indexing_metadata,
)

_NUM_DOCS = 20
_TARGET_DOC_INDEX = 7


def _random_vector(rng: random.Random) -> list[float]:
    return [rng.gauss(0.0, 1.0) for _ in range(EMBEDDING_DIM)]


def _get_knn_field_queries(search_body: dict[str, Any]) -> list[dict[str, Any]]:
    """Returns the per-field body of every knn clause in a search request."""
    query: dict[str, Any] = search_body["query"]
    clauses: list[dict[str, Any]] = (
        query["hybrid"]["queries"] if "hybrid" in query else [query]
    )
    return [
        knn_field_query
        for clause in clauses
        if "knn" in clause
        for knn_field_query in clause["knn"].values()
    ]


def _make_chunk_with_embedding(
    doc_id: str, embedding: list[float]
) -> DocMetadataAwareIndexChunk:
    return make_chunk(doc_id, content=f"document {doc_id}").model_copy(
        update={
            "embeddings": ChunkEmbedding(
                full_embedding=embedding, mini_chunk_embeddings=[]
            ),
            "title_embedding": embedding,
        }
    )


@pytest.mark.parametrize("vector_quantization", list(VectorQuantization))
def test_vector_quantization_mapping_and_retrieval(
    vector_quantization: VectorQuantization,
    tenant_context: None,  # noqa: ARG001
) -> None:
    """Creates an index with each quantization level.

    Checks the vector field mappings, that the mapping refresh on startup
    accepts the existing index, that semantic and hybrid retrieval return the
    nearest chunk first, and that their knn clauses ask for rescoring exactly
    when the index is quantized.
    """
    if not wait_for_opensearch_with_timeout():
        pytest.fail("OpenSearch is not available.")

    index_name = f"test_quantization_{uuid.uuid4().hex[:8]}"
    document_index = OpenSearchDocumentIndex(
        tenant_state=TenantState(
            tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE, multitenant=False
        ),
        index_name=index_name,
        embedding_dim=EMBEDDING_DIM,
        vector_quantization=vector_quantization,
    )
    with OpenSearchIndexClient(index_name=index_name) as client:
        try:
            document_index.verify_and_create_index_if_necessary(
                embedding_dim=EMBEDDING_DIM,
            )

            mapping_properties = client._client.indices.get_mapping(index=index_name)[
                index_name
            ]["mappings"]["properties"]
            lucene_scalar_quantization = LUCENE_SCALAR_QUANTIZATION.get(
                vector_quantization
            )
            for vector_field_name in (
                TITLE_VECTOR_FIELD_NAME,
                CONTENT_VECTOR_FIELD_NAME,
            ):
                method_parameters = mapping_properties[vector_field_name]["method"][
                    "parameters"
                ]
                if lucene_scalar_quantization is None:
                    assert "encoder" not in method_parameters
                else:
                    assert method_parameters["encoder"] == {
                        "name": "sq",
                        "parameters": {"bits": lucene_scalar_quantization.bits},
                    }

            # Startup puts the mapping on the existing index again. OpenSearch
            # rejects a changed encoder, so this also checks nothing drifted.
            document_index.verify_and_create_index_if_necessary(
                embedding_dim=EMBEDDING_DIM,
            )

            rng = random.Random(42)
            doc_ids = [f"quantization_doc_{i}" for i in range(_NUM_DOCS)]
            embeddings = [_random_vector(rng) for _ in doc_ids]
            document_index.index(
                chunks=[
                    _make_chunk_with_embedding(doc_id, embedding)
                    for doc_id, embedding in zip(doc_ids, embeddings, strict=True)
                ],
                indexing_metadata=make_indexing_metadata(
                    doc_ids,
                    old_counts=[0] * _NUM_DOCS,
                    new_counts=[1] * _NUM_DOCS,
                ),
            )
            client.refresh_index()

            target_doc_id = doc_ids[_TARGET_DOC_INDEX]
            query_embedding = [
                value + rng.gauss(0.0, 0.1) for value in embeddings[_TARGET_DOC_INDEX]
            ]
            filters = IndexFilters(
                access_control_list=[PUBLIC_DOC_PAT],
                tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
            )

            # Spy on the search bodies; the real queries still run.
            with patch.object(
                OpenSearchIndexClient,
                "search",
                autospec=True,
                side_effect=OpenSearchIndexClient.search,
            ) as search_spy:
                semantic_results = document_index.semantic_retrieval(
                    query_embedding=query_embedding,
                    filters=filters,
                    num_to_retrieve=5,
                )
                # The query text matches no chunk, so the vector subquery sets
                # the rank.
                hybrid_results = document_index.hybrid_retrieval(
                    query="unmatched",
                    query_embedding=query_embedding,
                    final_keywords=None,
                    query_type=QueryType.SEMANTIC,
                    filters=filters,
                    num_to_retrieve=5,
                )
            assert semantic_results[0].document_id == target_doc_id
            assert hybrid_results[0].document_id == target_doc_id

            # With few documents the target ranks first even without
            # rescoring, so check the rescore clause in each sent query.
            expected_rescore = (
                None
                if lucene_scalar_quantization is None
                else {
                    "oversample_factor": lucene_scalar_quantization.rescore_oversample_factor
                }
            )
            assert search_spy.call_count == 2
            for search_call in search_spy.call_args_list:
                knn_field_queries = _get_knn_field_queries(search_call.kwargs["body"])
                assert knn_field_queries
                for knn_field_query in knn_field_queries:
                    assert knn_field_query.get("rescore") == expected_rescore
        finally:
            client.delete_index()
