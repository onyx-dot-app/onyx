"""External dependency unit tests for OpenSearchClient.

These tests assume OpenSearch is running and test all implemented methods
using real schemas, pipelines, and search queries from the codebase.
"""

import uuid
from collections.abc import Generator
from typing import Any

import pytest

from onyx.document_index.opensearch.client import OpenSearchClient
from onyx.document_index.opensearch.schema import DocumentChunk
from onyx.document_index.opensearch.schema import DocumentSchema
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
        doc_chunk_id = original_doc.get_opensearch_doc_chunk_id()
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
        doc_chunk_id = doc.get_opensearch_doc_chunk_id()
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

    def test_update_document(self, test_client: OpenSearchClient) -> None:
        """Tests that update_document raises a NotImplementedError."""
        with pytest.raises(NotImplementedError):
            test_client.update_document()

    def test_search_basic(self, test_client: OpenSearchClient) -> None:
        """Tests basic search functionality."""
        # Precondition.
        mappings = DocumentSchema.get_document_schema(
            vector_dimension=128, multitenant=True
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
            vector_dimension=128, multitenant=True
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
            vector_dimension=128, multitenant=True
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
            ),
            _create_test_document_chunk(
                document_id="hidden-doc-1",
                chunk_index=0,
                content="Hidden document content, spooky",
                public=True,
                hidden=True,
            ),
            _create_test_document_chunk(
                document_id="private-doc-1",
                chunk_index=0,
                content="Private document content, btw my SSN is 123-45-6789",
                public=False,
                hidden=False,
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
            ),
            _create_test_document_chunk(
                document_id="somewhat-relevant-1",
                chunk_index=0,
                content="Computer programming with various languages",
                content_vector=_generate_test_vector(0.5),  # Far from query vector.
                public=True,
                hidden=False,
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
            ),
            # These should be filtered out by public/hidden filters.
            _create_test_document_chunk(
                document_id="hidden-but-relevant-1",
                chunk_index=0,
                content="Artificial intelligence research papers",
                content_vector=_generate_test_vector(0.05),  # Very close but hidden.
                public=True,
                hidden=True,
            ),
            _create_test_document_chunk(
                document_id="private-but-relevant-1",
                chunk_index=0,
                content="Artificial intelligence industry analysis",
                content_vector=_generate_test_vector(0.08),  # Very close but private.
                public=False,
                hidden=False,
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
