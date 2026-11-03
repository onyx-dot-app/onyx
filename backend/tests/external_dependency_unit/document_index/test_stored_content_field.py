"""External dependency tests for the content field's store setting.

New indices do not store content separately; reads use _source. Indices created
before that keep their stored copy, because OpenSearch cannot change an existing
field's store setting, so startup must keep it and still apply the rest of the
mapping.
"""

import uuid
from typing import Any

import pytest

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
    CONTENT_FIELD_NAME,
    DocumentSchema,
)
from onyx.indexing.models import ChunkEmbedding, DocMetadataAwareIndexChunk
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.external_dependency_unit.document_index.conftest import (
    EMBEDDING_DIM,
    make_chunk,
    make_indexing_metadata,
)

_DOC_ID = "stored_content_doc"
_CONTENT = "quarterly revenue grew in the third quarter"


def _stored_content_mappings() -> dict[str, Any]:
    """The current schema with content stored separately, as older code made it."""
    mappings: dict[str, Any] = DocumentSchema.get_document_schema(
        vector_dimension=EMBEDDING_DIM, multitenant=False
    )
    mappings["properties"][CONTENT_FIELD_NAME]["store"] = True
    return mappings


def _chunk(doc_id: str) -> DocMetadataAwareIndexChunk:
    embedding: list[float] = [1.0] + [0.0] * (EMBEDDING_DIM - 1)
    return make_chunk(doc_id, content=_CONTENT).model_copy(
        update={
            "embeddings": ChunkEmbedding(
                full_embedding=embedding, mini_chunk_embeddings=[]
            )
        }
    )


def _index_and_search(
    document_index: OpenSearchDocumentIndex, client: OpenSearchIndexClient
) -> list[InferenceChunk]:
    document_index.index(
        chunks=[_chunk(_DOC_ID)],
        indexing_metadata=make_indexing_metadata(
            [_DOC_ID], old_counts=[0], new_counts=[1]
        ),
    )
    client.refresh_index()
    query_embedding: list[float] = [1.0] + [0.0] * (EMBEDDING_DIM - 1)
    return document_index.hybrid_retrieval(
        query="quarterly revenue",
        query_embedding=query_embedding,
        final_keywords=None,
        query_type=QueryType.KEYWORD,
        filters=IndexFilters(
            access_control_list=[PUBLIC_DOC_PAT],
            tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
        ),
        num_to_retrieve=5,
    )


def _document_index(index_name: str) -> OpenSearchDocumentIndex:
    return OpenSearchDocumentIndex(
        tenant_state=TenantState(
            tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE, multitenant=False
        ),
        index_name=index_name,
        embedding_dim=EMBEDDING_DIM,
        vector_quantization=VectorQuantization.NONE,
    )


def test_new_index_does_not_store_content(
    tenant_context: None,  # noqa: ARG001
) -> None:
    """A new index has no stored copy of content, and search still returns
    the content from _source."""
    if not wait_for_opensearch_with_timeout():
        pytest.fail("OpenSearch is not available.")

    index_name: str = f"test_stored_content_{uuid.uuid4().hex[:8]}"
    document_index: OpenSearchDocumentIndex = _document_index(index_name)
    with OpenSearchIndexClient(index_name=index_name) as client:
        try:
            document_index.verify_and_create_index_if_necessary(
                embedding_dim=EMBEDDING_DIM
            )
            content_field: dict[str, Any] | None = client.get_field_mapping(
                CONTENT_FIELD_NAME
            )
            assert content_field is not None
            assert not content_field.get("store", False)

            results: list[InferenceChunk] = _index_and_search(document_index, client)
            assert [c.document_id for c in results] == [_DOC_ID]
            assert _CONTENT in results[0].content
        finally:
            client.delete_index()


def test_index_with_stored_content_still_starts(
    tenant_context: None,  # noqa: ARG001
) -> None:
    """An index created when content was stored passes startup, keeps its
    stored copy, takes new chunks, and serves search."""
    if not wait_for_opensearch_with_timeout():
        pytest.fail("OpenSearch is not available.")

    index_name: str = f"test_stored_content_{uuid.uuid4().hex[:8]}"
    document_index: OpenSearchDocumentIndex = _document_index(index_name)
    with OpenSearchIndexClient(index_name=index_name) as client:
        try:
            client.create_index(
                mappings=_stored_content_mappings(),
                settings=DocumentSchema.get_index_settings_based_on_environment(),
            )
            # Startup applies the current mapping; it must not raise.
            document_index.verify_and_create_index_if_necessary(
                embedding_dim=EMBEDDING_DIM
            )
            content_field: dict[str, Any] | None = client.get_field_mapping(
                CONTENT_FIELD_NAME
            )
            assert content_field is not None
            assert content_field.get("store") is True

            results: list[InferenceChunk] = _index_and_search(document_index, client)
            assert [c.document_id for c in results] == [_DOC_ID]
            assert _CONTENT in results[0].content
        finally:
            client.delete_index()
