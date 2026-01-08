"""External dependency unit tests for OpenSearchClient.

These tests assume OpenSearch is running and test all implemented methods
using real schemas, pipelines, and search queries from the codebase.
"""

import uuid
from collections.abc import Generator
from typing import Any

import pytest

from onyx.document_index.interfaces_new import TenantState
from onyx.document_index.opensearch.client import OpenSearchClient
from onyx.document_index.opensearch.constants import DEFAULT_MAX_CHUNK_SIZE
from onyx.document_index.opensearch.schema import DocumentChunk
from onyx.document_index.opensearch.schema import DocumentSchema
from onyx.document_index.opensearch.schema import get_opensearch_doc_chunk_id
from onyx.document_index.opensearch.search import DocumentQuery
from onyx.document_index.opensearch.search import (
    MIN_MAX_NORMALIZATION_PIPELINE_CONFIG,
)
from onyx.document_index.opensearch.search import MIN_MAX_NORMALIZATION_PIPELINE_NAME


def _create_test_document_chunk(
    document_id: str = "test-doc-1",
    chunk_index: int = 0,
    content: str = "Test content",
    content_vector: list[float] | None = None,
    title: str | None = None,
    title_vector: list[float] | None = None,
    public: bool = True,
    hidden: bool = False,
    **kwargs: Any,
) -> DocumentChunk:
    if content_vector is None:
        # Generate dummy vector - 128 dimensions for fast testing.
        content_vector = [0.1] * 128

    # If title is provided but no vector, generate one.
    if title is not None and title_vector is None:
        title_vector = [0.2] * 128

    return DocumentChunk(
        document_id=document_id,
        chunk_index=chunk_index,
        content=content,
        content_vector=content_vector,
        title=title,
        title_vector=title_vector,
        # This is not how tokenization necessarily works, this is just for quick
        # testing.
        num_tokens=len(content.split()),
        source_type="test_source",
        public=public,
        hidden=hidden,
        **kwargs,
    )


def _generate_test_vector(base_value: float = 0.1, dimension: int = 128) -> list[float]:
    """Generate a test vector with slight variations."""
    return [base_value + (i * 0.001) for i in range(dimension)]


@pytest.fixture(scope="module")
def opensearch_available() -> None:
    """Verify OpenSearch is running, skip all tests if not."""
    client = OpenSearchClient(index_name="test_ping")
    try:
        if not client.ping():
            pytest.skip("OpenSearch is not available")
    finally:
        client.close()


@pytest.fixture(scope="function")
def test_client(opensearch_available: None) -> Generator[OpenSearchClient, None, None]:
    """Creates an OpenSearch client for testing with automatic cleanup."""
    test_index_name = f"test_index_{uuid.uuid4().hex[:8]}"
    client = OpenSearchClient(index_name=test_index_name)

    yield client  # Test runs here.

    # Cleanup after test completes.
    try:
        client.delete_index()
    except Exception:
        pass
    finally:
        client.close()


@pytest.fixture(scope="function")
def search_pipeline(test_client: OpenSearchClient) -> Generator[None, None, None]:
    """Creates a search pipeline for testing with automatic cleanup."""
    test_client.create_search_pipeline(
        pipeline_id=MIN_MAX_NORMALIZATION_PIPELINE_NAME,
        pipeline_body=MIN_MAX_NORMALIZATION_PIPELINE_CONFIG,
    )
    yield  # Test runs here.
    try:
        test_client.delete_search_pipeline(
            pipeline_id=MIN_MAX_NORMALIZATION_PIPELINE_NAME,
        )
    except Exception:
        pass


class TestOpenSearchClient:
    """Tests for OpenSearchClient."""

    def test_create_index(self, test_client: OpenSearchClient) -> None:
        """Tests creating an index with a real schema."""
        # Precondition.
        mappings = DocumentSchema.get_document_schema(
            vector_dimension=128, multitenant=True
        )
        settings = DocumentSchema.get_index_settings()

        # Under test.
        # Should not raise.
        test_client.create_index(mappings=mappings, settings=settings)

        # Postcondition.
        # Verify index exists.
        assert test_client.validate_index(expected_mappings=mappings) is True

    def test_delete_existing_index(self, test_client: OpenSearchClient) -> None:
        """Tests deleting an existing index returns True."""
        # Precondition.
        mappings = DocumentSchema.get_document_schema(
            vector_dimension=128, multitenant=True
        )
        settings = DocumentSchema.get_index_settings()
        test_client.create_index(mappings=mappings, settings=settings)

        # Under test.
        # Delete should return True.
        result = test_client.delete_index()

        # Postcondition.
        assert result is True
        assert test_client.validate_index(expected_mappings=mappings) is False

    def test_delete_nonexistent_index(self, test_client: OpenSearchClient) -> None:
        """Tests deleting a nonexistent index returns False."""
        # Under test.
        # Don't create index, just try to delete.
        result = test_client.delete_index()

        # Postcondition.
        assert result is False

    def test_index_exists(self, test_client: OpenSearchClient) -> None:
        """Tests checking if an index exists."""
        # Precondition.
        # Index should not exist before creation.
        assert test_client.index_exists() is False

        mappings = DocumentSchema.get_document_schema(
            vector_dimension=128, multitenant=True
        )
        settings = DocumentSchema.get_index_settings()

        test_client.create_index(mappings=mappings, settings=settings)

        # Under test and postcondition.
        # Index should exist after creation.
        assert test_client.index_exists() is True

    def test_validate_index(self, test_client: OpenSearchClient) -> None:
        """Tests validating an index."""
        # Precondition.
        mappings = DocumentSchema.get_document_schema(
            vector_dimension=128, multitenant=True
        )
        settings = DocumentSchema.get_index_settings()

        # Under test and postcondition.
        # Should return False before creation.
        assert test_client.validate_index(expected_mappings=mappings) is False

        # Precondition.
        # Create index.
        test_client.create_index(mappings=mappings, settings=settings)

        # Under test and postcondition.
        # Should return True after creation.
        assert test_client.validate_index(expected_mappings=mappings) is True

    def test_create_duplicate_index(self, test_client: OpenSearchClient) -> None:
        """Tests creating an index twice raises an error."""
        # Precondition.
        mappings = DocumentSchema.get_document_schema(
            vector_dimension=128, multitenant=True
        )
        settings = DocumentSchema.get_index_settings()
        # Create once - should succeed.
        test_client.create_index(mappings=mappings, settings=settings)

        # Under test and postcondition.
        # Create again - should raise.
        with pytest.raises(Exception, match="already exists"):
            test_client.create_index(mappings=mappings, settings=settings)

    def test_update_settings(self, test_client: OpenSearchClient) -> None:
        """Tests that update_settings raises NotImplementedError."""
        # Under test and postcondition.
        with pytest.raises(NotImplementedError):
            test_client.update_settings(settings={})

    def test_create_and_delete_search_pipeline(
        self, test_client: OpenSearchClient
    ) -> None:
        """Tests creating and deleting a search pipeline."""
        # Under test and postcondition.
        # Should not raise.
        test_client.create_search_pipeline(
            pipeline_id=MIN_MAX_NORMALIZATION_PIPELINE_NAME,
            pipeline_body=MIN_MAX_NORMALIZATION_PIPELINE_CONFIG,
        )

        # Under test and postcondition.
        # Should not raise.
        test_client.delete_search_pipeline(
            pipeline_id=MIN_MAX_NORMALIZATION_PIPELINE_NAME
        )

    def test_index_document(self, test_client: OpenSearchClient) -> None:
        """Tests indexing a document."""
        # Precondition.
        mappings = DocumentSchema.get_document_schema(
            vector_dimension=128, multitenant=True
        )
        settings = DocumentSchema.get_index_settings()
        test_client.create_index(mappings=mappings, settings=settings)

        doc = _create_test_document_chunk(
            document_id="test-doc-1",
            chunk_index=0,
            content="Test content for indexing",
        )

        # Under test and postcondition.
        # Should not raise.
        test_client.index_document(document=doc)

    def test_index_duplicate_document(self, test_client: OpenSearchClient) -> None:
        """Tests indexing a duplicate document raises an error."""
        # Precondition.
        mappings = DocumentSchema.get_document_schema(
            vector_dimension=128, multitenant=True
        )
        settings = DocumentSchema.get_index_settings()
        test_client.create_index(mappings=mappings, settings=settings)

        doc = _create_test_document_chunk(
            document_id="test-doc-duplicate",
            chunk_index=0,
            content="Duplicate test",
        )

        # Index once - should succeed.
        test_client.index_document(document=doc)

        # Under test and postcondition.
        # Index again - should raise.
        with pytest.raises(Exception, match="already exists"):
            test_client.index_document(document=doc)

    def test_get_document(self, test_client: OpenSearchClient) -> None:
        """Tests getting a document."""
        # Precondition.
        mappings = DocumentSchema.get_document_schema(
            vector_dimension=128, multitenant=True
        )
        settings = DocumentSchema.get_index_settings()
        test_client.create_index(mappings=mappings, settings=settings)

        original_doc = _create_test_document_chunk(
            document_id="test-doc-get",
            chunk_index=0,
            content="Content to retrieve",
        )
        test_client.index_document(document=original_doc)

        # Under test.
        doc_chunk_id = get_opensearch_doc_chunk_id(
            document_id=original_doc.document_id,
            chunk_index=original_doc.chunk_index,
            max_chunk_size=original_doc.max_chunk_size,
        )
        retrieved_doc = test_client.get_document(document_chunk_id=doc_chunk_id)

        # Postcondition.
        assert retrieved_doc == original_doc

    def test_get_nonexistent_document(self, test_client: OpenSearchClient) -> None:
        """Tests getting a nonexistent document raises an error."""
        # Precondition.
        mappings = DocumentSchema.get_document_schema(
            vector_dimension=128, multitenant=True
        )
        settings = DocumentSchema.get_index_settings()
        test_client.create_index(mappings=mappings, settings=settings)

        # Under test and postcondition.
        with pytest.raises(Exception, match="404"):
            test_client.get_document(
                document_chunk_id="test_source__nonexistent__512__0"
            )

    def test_delete_existing_document(self, test_client: OpenSearchClient) -> None:
        """Tests deleting an existing document returns True."""
        # Precondition.
        mappings = DocumentSchema.get_document_schema(
            vector_dimension=128, multitenant=True
        )
        settings = DocumentSchema.get_index_settings()
        test_client.create_index(mappings=mappings, settings=settings)

        doc = _create_test_document_chunk(
            document_id="test-doc-delete",
            chunk_index=0,
            content="Content to delete",
        )
        test_client.index_document(document=doc)

        # Under test.
        doc_chunk_id = get_opensearch_doc_chunk_id(
            document_id=doc.document_id,
            chunk_index=doc.chunk_index,
            max_chunk_size=doc.max_chunk_size,
        )
        result = test_client.delete_document(document_chunk_id=doc_chunk_id)

        # Postcondition.
        assert result is True
        # Verify the document is gone.
        with pytest.raises(Exception, match="404"):
            test_client.get_document(document_chunk_id=doc_chunk_id)

    def test_delete_nonexistent_document(self, test_client: OpenSearchClient) -> None:
        """Tests deleting a nonexistent document returns False."""
        # Precondition.
        mappings = DocumentSchema.get_document_schema(
            vector_dimension=128, multitenant=True
        )
        settings = DocumentSchema.get_index_settings()
        test_client.create_index(mappings=mappings, settings=settings)

        # Under test.
        result = test_client.delete_document(
            document_chunk_id="test_source__nonexistent__512__0"
        )

        # Postcondition.
        assert result is False

    def test_delete_by_query(self, test_client: OpenSearchClient) -> None:
        """Tests deleting documents by query."""
        # Precondition.
        mappings = DocumentSchema.get_document_schema(
            vector_dimension=128, multitenant=True
        )
        settings = DocumentSchema.get_index_settings()
        test_client.create_index(mappings=mappings, settings=settings)

        # Index multiple documents.
        docs_to_delete = [
            _create_test_document_chunk(
                document_id="delete-me",
                chunk_index=i,
                content=f"Delete this {i}",
                tenant_id="tenant-x",
            )
            for i in range(3)
        ]
        docs_to_keep = [
            _create_test_document_chunk(
                document_id="keep-me",
                chunk_index=0,
                content="Keep this",
                tenant_id="tenant-x",
            )
        ]

        for doc in docs_to_delete + docs_to_keep:
            test_client.index_document(document=doc)
        test_client.refresh_index()

        query_body = DocumentQuery.delete_from_document_id_query(
            document_id="delete-me",
            tenant_state=TenantState(tenant_id="tenant-x", multitenant=True),
        )

        # Under test.
        num_deleted = test_client.delete_by_query(query_body=query_body)

        # Postcondition.
        assert num_deleted == 3

        # Verify deletion - the deleted documents should no longer exist.
        test_client.refresh_index()
        search_query = DocumentQuery.get_from_document_id_query(
            document_id="delete-me",
            tenant_state=TenantState(tenant_id="tenant-x", multitenant=True),
            max_chunk_size=DEFAULT_MAX_CHUNK_SIZE,
            min_chunk_index=None,
            max_chunk_index=None,
            get_full_document=False,
        )
        remaining_ids = test_client.search_for_document_ids(body=search_query)
        assert len(remaining_ids) == 0

        # Verify other documents still exist.
        keep_query = DocumentQuery.get_from_document_id_query(
            document_id="keep-me",
            tenant_state=TenantState(tenant_id="tenant-x", multitenant=True),
            max_chunk_size=DEFAULT_MAX_CHUNK_SIZE,
            min_chunk_index=None,
            max_chunk_index=None,
            get_full_document=False,
        )
        keep_ids = test_client.search_for_document_ids(body=keep_query)
        assert len(keep_ids) == 1

    def test_update_document(self, test_client: OpenSearchClient) -> None:
        """Tests that update_document raises a NotImplementedError."""
        with pytest.raises(NotImplementedError):
            test_client.update_document()

    def test_search_basic(self, test_client: OpenSearchClient) -> None:
        """Tests basic search functionality."""
        # Precondition.
        mappings = DocumentSchema.get_document_schema(
            vector_dimension=128, multitenant=False
        )
        settings = DocumentSchema.get_index_settings()
        test_client.create_index(mappings=mappings, settings=settings)

        # Index multiple documents with different content and vectors.
        docs = [
            _create_test_document_chunk(
                document_id="search-doc-1",
                chunk_index=0,
                content="Python programming language tutorial",
                content_vector=_generate_test_vector(0.1),
            ),
            _create_test_document_chunk(
                document_id="search-doc-2",
                chunk_index=0,
                content="How to make cheese",
                content_vector=_generate_test_vector(0.2),
            ),
            _create_test_document_chunk(
                document_id="search-doc-3",
                chunk_index=0,
                content="C++ for newborns",
                content_vector=_generate_test_vector(0.15),
            ),
        ]
        for doc in docs:
            test_client.index_document(document=doc)

        # Refresh index to make documents searchable.
        test_client.refresh_index()

        # Search query.
        query_text = "Python programming"
        query_vector = _generate_test_vector(0.12)
        search_body = DocumentQuery.get_hybrid_search_query(
            query_text=query_text,
            query_vector=query_vector,
            num_candidates=10,
            num_hits=5,
            tenant_state=TenantState(tenant_id="", multitenant=False),
        )

        # Under test.
        results = test_client.search(body=search_body, search_pipeline_id=None)

        # Postcondition.
        assert len(results) > 0
        # Assert that all the chunks above are present.
        assert all(
            chunk.document_id in ["search-doc-1", "search-doc-2", "search-doc-3"]
            for chunk in results
        )

    def test_search_with_pipeline(
        self, test_client: OpenSearchClient, search_pipeline: None
    ) -> None:
        """Tests search with a normalization pipeline."""
        # Precondition.
        mappings = DocumentSchema.get_document_schema(
            vector_dimension=128, multitenant=False
        )
        settings = DocumentSchema.get_index_settings()
        test_client.create_index(mappings=mappings, settings=settings)

        # Index documents.
        docs = [
            _create_test_document_chunk(
                document_id="pipeline-doc-1",
                chunk_index=0,
                content="Machine learning algorithms for single-celled organisms",
                content_vector=_generate_test_vector(0.3),
            ),
            _create_test_document_chunk(
                document_id="pipeline-doc-2",
                chunk_index=0,
                content="Deep learning shallow neural networks",
                content_vector=_generate_test_vector(0.35),
            ),
        ]
        for doc in docs:
            test_client.index_document(document=doc)

        # Refresh index to make documents searchable
        test_client.refresh_index()

        # Search query.
        query_text = "machine learning"
        query_vector = _generate_test_vector(0.32)
        search_body = DocumentQuery.get_hybrid_search_query(
            query_text=query_text,
            query_vector=query_vector,
            num_candidates=10,
            num_hits=5,
            tenant_state=TenantState(tenant_id="", multitenant=False),
        )

        # Under test.
        results = test_client.search(
            body=search_body, search_pipeline_id=MIN_MAX_NORMALIZATION_PIPELINE_NAME
        )

        # Postcondition.
        assert len(results) > 0
        # Assert that all the chunks above are present.
        assert all(
            chunk.document_id in ["pipeline-doc-1", "pipeline-doc-2"]
            for chunk in results
        )

    def test_search_empty_index(self, test_client: OpenSearchClient) -> None:
        """Tests search on an empty index returns an empty list."""
        # Precondition.
        mappings = DocumentSchema.get_document_schema(
            vector_dimension=128, multitenant=False
        )
        settings = DocumentSchema.get_index_settings()
        test_client.create_index(mappings=mappings, settings=settings)
        # Note no documents were indexed.

        # Search query.
        query_text = "test query"
        query_vector = _generate_test_vector(0.5)
        search_body = DocumentQuery.get_hybrid_search_query(
            query_text=query_text,
            query_vector=query_vector,
            num_candidates=10,
            num_hits=5,
            tenant_state=TenantState(tenant_id="", multitenant=False),
        )

        # Under test.
        results = test_client.search(body=search_body, search_pipeline_id=None)

        # Postcondition.
        assert len(results) == 0

    def test_search_filters(self, test_client: OpenSearchClient) -> None:
        """Tests search filters for public/hidden documents."""
        # Precondition.
        mappings = DocumentSchema.get_document_schema(
            vector_dimension=128, multitenant=True
        )
        settings = DocumentSchema.get_index_settings()
        test_client.create_index(mappings=mappings, settings=settings)

        # Index documents with different public/hidden states.
        docs = [
            _create_test_document_chunk(
                document_id="public-doc-1",
                chunk_index=0,
                content="Public document content",
                public=True,
                hidden=False,
                tenant_id="tenant-x",
            ),
            _create_test_document_chunk(
                document_id="hidden-doc-1",
                chunk_index=0,
                content="Hidden document content, spooky",
                public=True,
                hidden=True,
                tenant_id="tenant-x",
            ),
            _create_test_document_chunk(
                document_id="private-doc-1",
                chunk_index=0,
                content="Private document content, btw my SSN is 123-45-6789",
                public=False,
                hidden=False,
                tenant_id="tenant-x",
            ),
        ]
        for doc in docs:
            test_client.index_document(document=doc)

        # Refresh index to make documents searchable.
        test_client.refresh_index()

        # Search with default filters (public=True, hidden=False).
        # The DocumentQuery.get_hybrid_search_query uses filters that should
        # only return public, non-hidden documents.
        query_text = "document content"
        query_vector = _generate_test_vector(0.6)
        search_body = DocumentQuery.get_hybrid_search_query(
            query_text=query_text,
            query_vector=query_vector,
            num_candidates=10,
            num_hits=5,
            tenant_state=TenantState(tenant_id="tenant-x", multitenant=True),
        )

        # Under test.
        results = test_client.search(body=search_body, search_pipeline_id=None)

        # Postcondition.
        # Should only get the public, non-hidden document.
        assert len(results) == 1
        assert results[0].document_id == "public-doc-1"
        assert results[0].public is True
        assert results[0].hidden is False

    def test_search_with_pipeline_and_filters_returns_chunks_with_related_content_first(
        self, test_client: OpenSearchClient, search_pipeline: None
    ) -> None:
        """
        Tests search with a normalization pipeline and filters returns chunks
        with related content first.
        """
        # Precondition.
        mappings = DocumentSchema.get_document_schema(
            vector_dimension=128, multitenant=True
        )
        settings = DocumentSchema.get_index_settings()
        test_client.create_index(mappings=mappings, settings=settings)

        # Index documents with varying relevance to the query.
        # Vectors closer to query_vector (0.1) should rank higher.
        docs = [
            _create_test_document_chunk(
                document_id="highly-relevant-1",
                chunk_index=0,
                content="Artificial intelligence and machine learning transform technology",
                content_vector=_generate_test_vector(
                    0.1
                ),  # Very close to query vector.
                public=True,
                hidden=False,
                tenant_id="tenant-x",
            ),
            _create_test_document_chunk(
                document_id="somewhat-relevant-1",
                chunk_index=0,
                content="Computer programming with various languages",
                content_vector=_generate_test_vector(0.5),  # Far from query vector.
                public=True,
                hidden=False,
                tenant_id="tenant-x",
            ),
            _create_test_document_chunk(
                document_id="not-very-relevant-1",
                chunk_index=0,
                content="Cooking recipes for delicious meals",
                content_vector=_generate_test_vector(
                    0.9
                ),  # Very far from query vector.
                public=True,
                hidden=False,
                tenant_id="tenant-x",
            ),
            # These should be filtered out by public/hidden filters.
            _create_test_document_chunk(
                document_id="hidden-but-relevant-1",
                chunk_index=0,
                content="Artificial intelligence research papers",
                content_vector=_generate_test_vector(0.05),  # Very close but hidden.
                public=True,
                hidden=True,
                tenant_id="tenant-x",
            ),
            _create_test_document_chunk(
                document_id="private-but-relevant-1",
                chunk_index=0,
                content="Artificial intelligence industry analysis",
                content_vector=_generate_test_vector(0.08),  # Very close but private.
                public=False,
                hidden=False,
                tenant_id="tenant-x",
            ),
        ]
        for doc in docs:
            test_client.index_document(document=doc)

        # Refresh index to make documents searchable.
        test_client.refresh_index()

        # Search query matching "highly-relevant-1" most closely.
        query_text = "artificial intelligence"
        query_vector = _generate_test_vector(0.1)
        search_body = DocumentQuery.get_hybrid_search_query(
            query_text=query_text,
            query_vector=query_vector,
            num_candidates=10,
            num_hits=5,
            tenant_state=TenantState(tenant_id="tenant-x", multitenant=True),
        )

        # Under test.
        results = test_client.search(
            body=search_body, search_pipeline_id=MIN_MAX_NORMALIZATION_PIPELINE_NAME
        )

        # Postcondition.
        # Should only get public, non-hidden documents (3 out of 5).
        assert len(results) == 3
        result_ids = [chunk.document_id for chunk in results]
        assert "highly-relevant-1" in result_ids
        assert "somewhat-relevant-1" in result_ids
        assert "not-very-relevant-1" in result_ids
        # Filtered out by public/hidden constraints.
        assert "hidden-but-relevant-1" not in result_ids
        assert "private-but-relevant-1" not in result_ids

        # Most relevant document should be first due to normalization pipeline.
        assert results[0].document_id == "highly-relevant-1"

    def test_search_for_ids_basic(self, test_client: OpenSearchClient) -> None:
        """Tests search_for_ids method returns correct chunk IDs."""
        # Precondition.
        mappings = DocumentSchema.get_document_schema(
            vector_dimension=128, multitenant=False
        )
        settings = DocumentSchema.get_index_settings()
        test_client.create_index(mappings=mappings, settings=settings)

        # Index chunks for two different documents.
        doc1_chunks = [
            _create_test_document_chunk(
                document_id="doc-1", chunk_index=i, content=f"Doc 1 Chunk {i}"
            )
            for i in range(3)
        ]

        doc2_chunks = [
            _create_test_document_chunk(
                document_id="doc-2", chunk_index=i, content=f"Doc 2 Chunk {i}"
            )
            for i in range(2)
        ]

        for chunk in doc1_chunks + doc2_chunks:
            test_client.index_document(document=chunk)

        test_client.refresh_index()

        # Build query for doc-1.
        query_body = DocumentQuery.get_from_document_id_query(
            document_id="doc-1",
            tenant_state=TenantState(tenant_id="", multitenant=False),
            max_chunk_size=DEFAULT_MAX_CHUNK_SIZE,
            min_chunk_index=None,
            max_chunk_index=None,
            get_full_document=False,
        )

        # Under test.
        chunk_ids = test_client.search_for_document_ids(body=query_body)

        # Postcondition.
        # Should get 3 IDs for doc-1.
        assert len(chunk_ids) == 3

        # Verify IDs match expected chunk IDs.
        expected_ids = {
            get_opensearch_doc_chunk_id(
                document_id=chunk.document_id,
                chunk_index=chunk.chunk_index,
                max_chunk_size=chunk.max_chunk_size,
            )
            for chunk in doc1_chunks
        }
        assert set(chunk_ids) == expected_ids

    def test_delete_by_query_multitenant_isolation(
        self, test_client: OpenSearchClient
    ) -> None:
        """
        Tests delete_by_query respects tenant boundaries in multi-tenant mode.
        """
        # Precondition.
        mappings = DocumentSchema.get_document_schema(
            vector_dimension=128, multitenant=True
        )
        settings = DocumentSchema.get_index_settings()
        test_client.create_index(mappings=mappings, settings=settings)

        # Index chunks for different doc IDs for different tenants.
        # NOTE: Since get_opensearch_doc_chunk_id doesn't include tenant_id yet,
        # we use different document IDs to avoid ID conflicts.
        tenant_a_chunks = [
            _create_test_document_chunk(
                document_id="doc-tenant-a",
                chunk_index=i,
                content=f"Tenant A Chunk {i}",
                tenant_id="tenant-a",
            )
            for i in range(3)
        ]

        tenant_b_chunks = [
            _create_test_document_chunk(
                document_id="doc-tenant-b",
                chunk_index=i,
                content=f"Tenant B Chunk {i}",
                tenant_id="tenant-b",
            )
            for i in range(2)
        ]

        for chunk in tenant_a_chunks + tenant_b_chunks:
            test_client.index_document(document=chunk)
        test_client.refresh_index()

        # Build deletion query for tenant-a only.
        query_body = DocumentQuery.get_from_document_id_query(
            document_id="doc-tenant-a",
            tenant_state=TenantState(tenant_id="tenant-a", multitenant=True),
            max_chunk_size=DEFAULT_MAX_CHUNK_SIZE,
            min_chunk_index=None,
            max_chunk_index=None,
            get_full_document=False,
        )

        chunk_ids = test_client.search_for_document_ids(body=query_body)

        assert len(chunk_ids) == 3
        expected_ids = {
            get_opensearch_doc_chunk_id(
                document_id=chunk.document_id,
                chunk_index=chunk.chunk_index,
                max_chunk_size=chunk.max_chunk_size,
            )
            for chunk in tenant_a_chunks
        }
        assert set(chunk_ids) == expected_ids

        # Under test.
        # Delete tenant-a chunks.
        for chunk_id in chunk_ids:
            result = test_client.delete_document(chunk_id)
            assert result is True

        # Postcondition.
        # Verify tenant-a chunks are deleted.
        test_client.refresh_index()
        verify_query_a = DocumentQuery.get_from_document_id_query(
            document_id="doc-tenant-a",
            tenant_state=TenantState(tenant_id="tenant-a", multitenant=True),
            max_chunk_size=DEFAULT_MAX_CHUNK_SIZE,
            min_chunk_index=None,
            max_chunk_index=None,
            get_full_document=False,
        )
        remaining_a_ids = test_client.search_for_document_ids(body=verify_query_a)
        assert len(remaining_a_ids) == 0

        # Verify tenant-b chunks still exist.
        verify_query_b = DocumentQuery.get_from_document_id_query(
            document_id="doc-tenant-b",
            tenant_state=TenantState(tenant_id="tenant-b", multitenant=True),
            max_chunk_size=DEFAULT_MAX_CHUNK_SIZE,
            min_chunk_index=None,
            max_chunk_index=None,
            get_full_document=False,
        )
        remaining_b_ids = test_client.search_for_document_ids(body=verify_query_b)
        assert len(remaining_b_ids) == 2
        expected_b_ids = {
            get_opensearch_doc_chunk_id(
                document_id=chunk.document_id,
                chunk_index=chunk.chunk_index,
                max_chunk_size=chunk.max_chunk_size,
            )
            for chunk in tenant_b_chunks
        }
        assert set(remaining_b_ids) == expected_b_ids

    def test_delete_by_query_nonexistent_document(
        self, test_client: OpenSearchClient
    ) -> None:
        """
        Tests delete_by_query for non-existent document returns 0 deleted.
        """
        # Precondition.
        mappings = DocumentSchema.get_document_schema(
            vector_dimension=128, multitenant=False
        )
        settings = DocumentSchema.get_index_settings()
        test_client.create_index(mappings=mappings, settings=settings)

        # Don't index any documents.

        # Build deletion query.
        query_body = DocumentQuery.get_from_document_id_query(
            document_id="nonexistent-doc",
            tenant_state=TenantState(tenant_id="", multitenant=False),
            max_chunk_size=DEFAULT_MAX_CHUNK_SIZE,
            min_chunk_index=None,
            max_chunk_index=None,
            get_full_document=False,
        )

        # Under test.
        chunk_ids = test_client.search_for_document_ids(body=query_body)

        # Postcondition.
        assert len(chunk_ids) == 0

    def test_search_for_document_ids(self, test_client: OpenSearchClient) -> None:
        """Tests search_for_document_ids method returns correct chunk IDs."""
        # Precondition.
        mappings = DocumentSchema.get_document_schema(
            vector_dimension=128, multitenant=False
        )
        settings = DocumentSchema.get_index_settings()
        test_client.create_index(mappings=mappings, settings=settings)

        # Index chunks for two different documents.
        doc1_chunks = [
            _create_test_document_chunk(
                document_id="doc-1", chunk_index=i, content=f"Doc 1 Chunk {i}"
            )
            for i in range(3)
        ]
        doc2_chunks = [
            _create_test_document_chunk(
                document_id="doc-2", chunk_index=i, content=f"Doc 2 Chunk {i}"
            )
            for i in range(2)
        ]

        for chunk in doc1_chunks + doc2_chunks:
            test_client.index_document(document=chunk)
        test_client.refresh_index()

        # Build query for doc-1.
        query_body = DocumentQuery.get_from_document_id_query(
            document_id="doc-1",
            tenant_state=TenantState(tenant_id="", multitenant=False),
            max_chunk_size=DEFAULT_MAX_CHUNK_SIZE,
            min_chunk_index=None,
            max_chunk_index=None,
            get_full_document=False,
        )

        # Under test.
        chunk_ids = test_client.search_for_document_ids(body=query_body)

        # Postcondition.
        assert len(chunk_ids) == 3
        expected_ids = {
            get_opensearch_doc_chunk_id(
                document_id=chunk.document_id,
                chunk_index=chunk.chunk_index,
                max_chunk_size=chunk.max_chunk_size,
            )
            for chunk in doc1_chunks
        }
        assert set(chunk_ids) == expected_ids
