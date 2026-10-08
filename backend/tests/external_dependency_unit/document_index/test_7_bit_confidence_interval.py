"""External dependency tests for 7-bit indices built before the encoder set
confidence_interval explicitly.

OpenSearch cannot change an existing field's encoder, so startup must keep the
old 7-bit field and still apply the rest of the mapping.
"""

import uuid
from typing import Any

import pytest
from opensearchpy.exceptions import RequestError

from onyx.configs.constants import PUBLIC_DOC_PAT
from onyx.context.search.enums import QueryType
from onyx.context.search.models import IndexFilters, InferenceChunk
from onyx.db.enums import VectorQuantization
from onyx.document_index.interfaces import TenantState
from onyx.document_index.opensearch.client import (
    OpenSearchIndexClient,
    wait_for_opensearch_with_timeout,
)
from onyx.document_index.opensearch.opensearch_document_index import (
    OpenSearchDocumentIndex,
)
from onyx.document_index.opensearch.schema import (
    CONTENT_VECTOR_FIELD_NAME,
    DocumentSchema,
)
from onyx.indexing.models import ChunkEmbedding, DocMetadataAwareIndexChunk
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.external_dependency_unit.document_index.conftest import (
    EMBEDDING_DIM,
    make_chunk,
    make_indexing_metadata,
)

_UNSET_CI_ENCODER: dict[str, Any] = {"name": "sq", "parameters": {"bits": 7}}
_DOC_ID = "seven_bit_doc"


def _unset_ci_mappings() -> dict[str, Any]:
    """The current float32 schema with the 7-bit encoder older code added."""
    mappings: dict[str, Any] = DocumentSchema.get_document_schema(
        vector_dimension=EMBEDDING_DIM, multitenant=False
    )
    mappings["properties"][CONTENT_VECTOR_FIELD_NAME]["method"]["parameters"][
        "encoder"
    ] = _UNSET_CI_ENCODER
    return mappings


def _chunk(doc_id: str) -> DocMetadataAwareIndexChunk:
    embedding: list[float] = [1.0] + [0.0] * (EMBEDDING_DIM - 1)
    return make_chunk(doc_id, content=f"quarterly revenue {doc_id}").model_copy(
        update={
            "embeddings": ChunkEmbedding(
                full_embedding=embedding, mini_chunk_embeddings=[]
            )
        }
    )


def test_7_bit_index_without_confidence_interval_still_starts(
    tenant_context: None,  # noqa: ARG001
) -> None:
    """A 7-bit index built without confidence_interval passes startup with
    current 7-bit settings, keeps its encoder, takes new chunks, and serves
    search."""
    if not wait_for_opensearch_with_timeout():
        pytest.fail("OpenSearch is not available.")

    index_name: str = f"test_7_bit_ci_{uuid.uuid4().hex[:8]}"
    document_index: OpenSearchDocumentIndex = OpenSearchDocumentIndex(
        tenant_state=TenantState(
            tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE, multitenant=False
        ),
        index_name=index_name,
        embedding_dim=EMBEDDING_DIM,
        vector_quantization=VectorQuantization.SCALAR_7_BIT,
    )
    with OpenSearchIndexClient(index_name=index_name) as client:
        client.create_index(
            mappings=_unset_ci_mappings(),
            settings=DocumentSchema.get_index_settings_based_on_environment(),
        )
        try:
            # Startup applies the current 7-bit mapping; it must not raise.
            document_index.verify_and_create_index_if_necessary(
                embedding_dim=EMBEDDING_DIM
            )
            encoder: dict[str, Any] | None = client.get_vector_field_encoder(
                CONTENT_VECTOR_FIELD_NAME
            )
            assert encoder == _UNSET_CI_ENCODER

            document_index.index(
                chunks=[_chunk(_DOC_ID)],
                indexing_metadata=make_indexing_metadata(
                    [_DOC_ID], old_counts=[0], new_counts=[1]
                ),
            )
            client.refresh_index()

            filters: IndexFilters = IndexFilters(
                access_control_list=[PUBLIC_DOC_PAT],
                tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
            )
            query_embedding: list[float] = [1.0] + [0.0] * (EMBEDDING_DIM - 1)
            semantic_results: list[InferenceChunk] = document_index.semantic_retrieval(
                query_embedding=query_embedding,
                filters=filters,
                num_to_retrieve=5,
            )
            hybrid_results: list[InferenceChunk] = document_index.hybrid_retrieval(
                query="quarterly revenue",
                query_embedding=query_embedding,
                final_keywords=None,
                query_type=QueryType.SEMANTIC,
                filters=filters,
                num_to_retrieve=5,
            )
            assert [c.document_id for c in semantic_results] == [_DOC_ID]
            assert [c.document_id for c in hybrid_results] == [_DOC_ID]
        finally:
            client.delete_index()


def test_other_mapping_conflicts_still_raise(
    tenant_context: None,  # noqa: ARG001
) -> None:
    """The 7-bit fallback is narrow: a 1-bit index opened with float32
    settings still fails startup."""
    if not wait_for_opensearch_with_timeout():
        pytest.fail("OpenSearch is not available.")

    index_name: str = f"test_7_bit_ci_{uuid.uuid4().hex[:8]}"
    tenant_state: TenantState = TenantState(
        tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE, multitenant=False
    )
    OpenSearchDocumentIndex(
        tenant_state=tenant_state,
        index_name=index_name,
        embedding_dim=EMBEDDING_DIM,
        vector_quantization=VectorQuantization.SCALAR_1_BIT,
    ).verify_and_create_index_if_necessary(embedding_dim=EMBEDDING_DIM)
    try:
        with pytest.raises(RequestError, match="conflicts with existing mapper"):
            OpenSearchDocumentIndex(
                tenant_state=tenant_state,
                index_name=index_name,
                embedding_dim=EMBEDDING_DIM,
                vector_quantization=VectorQuantization.NONE,
            ).verify_and_create_index_if_necessary(embedding_dim=EMBEDDING_DIM)
    finally:
        with OpenSearchIndexClient(index_name=index_name) as client:
            client.delete_index()
