"""External dependency tests for indices created before title_vector was removed.

These indices still map and store title_vector. The current code must keep
starting up against them, writing chunks without the field, and searching them.
"""

import uuid
from typing import Any

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
from onyx.document_index.opensearch.opensearch_document_index import (
    OpenSearchDocumentIndex,
)
from onyx.document_index.opensearch.schema import (
    CONTENT_VECTOR_FIELD_NAME,
    DOCUMENT_ID_FIELD_NAME,
    TITLE_VECTOR_FIELD_NAME,
    DocumentSchema,
)
from onyx.indexing.models import ChunkEmbedding, DocMetadataAwareIndexChunk
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.external_dependency_unit.document_index.conftest import (
    EMBEDDING_DIM,
    make_chunk,
    make_indexing_metadata,
)

_LEGACY_DOC_ID = "legacy_doc"
_NEW_DOC_ID = "new_doc"


def _unit_vector(position: int) -> list[float]:
    vector = [0.0] * EMBEDDING_DIM
    vector[position] = 1.0
    return vector


def _chunk(doc_id: str, embedding: list[float]) -> DocMetadataAwareIndexChunk:
    return make_chunk(doc_id, content=f"quarterly revenue {doc_id}").model_copy(
        update={
            "embeddings": ChunkEmbedding(
                full_embedding=embedding, mini_chunk_embeddings=[]
            )
        }
    )


def _legacy_mappings() -> dict[str, Any]:
    """The current schema plus the title_vector field older indices carry."""
    mappings = DocumentSchema.get_document_schema(
        vector_dimension=EMBEDDING_DIM, multitenant=False
    )
    mappings["properties"][TITLE_VECTOR_FIELD_NAME] = dict(
        mappings["properties"][CONTENT_VECTOR_FIELD_NAME]
    )
    return mappings


def test_legacy_index_with_title_vector_still_works(
    tenant_context: None,  # noqa: ARG001
) -> None:
    """Startup, writes without title_vector, and search all work on an index
    that still maps and stores title_vector."""
    if not wait_for_opensearch_with_timeout():
        pytest.fail("OpenSearch is not available.")

    index_name = f"test_legacy_title_vector_{uuid.uuid4().hex[:8]}"
    document_index = OpenSearchDocumentIndex(
        tenant_state=TenantState(
            tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE, multitenant=False
        ),
        index_name=index_name,
        embedding_dim=EMBEDDING_DIM,
        vector_quantization=VectorQuantization.NONE,
    )
    with OpenSearchIndexClient(index_name=index_name) as client:
        client.create_index(
            mappings=_legacy_mappings(),
            settings=DocumentSchema.get_index_settings_based_on_environment(),
        )
        try:
            # A chunk written by older code carries a stored title_vector.
            document_index.index(
                chunks=[_chunk(_LEGACY_DOC_ID, _unit_vector(0))],
                indexing_metadata=make_indexing_metadata(
                    [_LEGACY_DOC_ID], old_counts=[0], new_counts=[1]
                ),
            )
            client.refresh_index()
            legacy_hit = client._client.search(
                index=index_name,
                body={"query": {"term": {DOCUMENT_ID_FIELD_NAME: _LEGACY_DOC_ID}}},
            )["hits"]["hits"][0]
            client._client.update(
                index=index_name,
                id=legacy_hit["_id"],
                body={"doc": {TITLE_VECTOR_FIELD_NAME: _unit_vector(1)}},
            )

            # Startup re-puts the current mapping, which no longer has the field.
            document_index.verify_and_create_index_if_necessary(
                embedding_dim=EMBEDDING_DIM
            )
            mapping_properties = client._client.indices.get_mapping(index=index_name)[
                index_name
            ]["mappings"]["properties"]
            assert TITLE_VECTOR_FIELD_NAME in mapping_properties

            # Current code writes chunks without title_vector.
            document_index.index(
                chunks=[_chunk(_NEW_DOC_ID, _unit_vector(0))],
                indexing_metadata=make_indexing_metadata(
                    [_NEW_DOC_ID], old_counts=[0], new_counts=[1]
                ),
            )
            client.refresh_index()
            title_vector_count = client._client.count(
                index=index_name,
                body={"query": {"exists": {"field": TITLE_VECTOR_FIELD_NAME}}},
            )["count"]
            assert title_vector_count == 1

            filters = IndexFilters(
                access_control_list=[PUBLIC_DOC_PAT],
                tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
            )
            semantic_results = document_index.semantic_retrieval(
                query_embedding=_unit_vector(0),
                filters=filters,
                num_to_retrieve=5,
            )
            hybrid_results = document_index.hybrid_retrieval(
                query="quarterly revenue",
                query_embedding=_unit_vector(0),
                final_keywords=None,
                query_type=QueryType.SEMANTIC,
                filters=filters,
                num_to_retrieve=5,
            )
            expected_doc_ids = {_LEGACY_DOC_ID, _NEW_DOC_ID}
            assert {c.document_id for c in semantic_results} == expected_doc_ids
            assert {c.document_id for c in hybrid_results} == expected_doc_ids
        finally:
            client.delete_index()
