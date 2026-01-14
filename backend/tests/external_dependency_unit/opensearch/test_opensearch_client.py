"""External dependency unit tests for OpenSearchClient.

These tests assume OpenSearch is running and test all implemented methods
using real schemas, pipelines, and search queries from the codebase.
"""

import json
import uuid
from collections.abc import Generator
from datetime import datetime
from datetime import timezone

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
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA


def _patch_global_tenant_state(monkeypatch: pytest.MonkeyPatch, state: bool) -> None:
    """Patches MULTI_TENANT wherever necessary for this test file.

    Args:
        monkeypatch: The test instance's monkeypatch instance, used for
            patching.
        state: The intended state of MULTI_TENANT.
    """
    monkeypatch.setattr("shared_configs.configs.MULTI_TENANT", state)
    monkeypatch.setattr("onyx.document_index.opensearch.schema.MULTI_TENANT", state)


def _create_test_document_chunk(
    document_id: str,
    chunk_index: int,
    content: str,
    tenant_state: TenantState,
    content_vector: list[float] | None = None,
    title: str | None = None,
    title_vector: list[float] | None = None,
    public: bool = True,
    hidden: bool = False,
) -> DocumentChunk:
    if content_vector is None:
        # Generate dummy vector - 128 dimensions for fast testing.
        content_vector = [0.1] * 128

    # If title is provided but no vector, generate one.
    if title is not None and title_vector is None:
        title_vector = [0.2] * 128

    now = datetime.now(timezone.utc)
    # We only store millisecond precision, so to make sure asserts work in this
    # test file manually lose some precision from datetime.now().
    now = now.replace(microsecond=(now.microsecond // 1000) * 1000)

    return DocumentChunk(
        document_id=document_id,
        chunk_index=chunk_index,
        title=title,
        title_vector=title_vector,
        content=content,
        content_vector=content_vector,
        source_type="test_source",
        metadata=json.dumps({}),
        last_updated=now,
        public=public,
        access_control_list=[],
        hidden=hidden,
        global_boost=0,
        semantic_identifier="Test semantic identifier",
        image_file_id=None,
        source_links=None,
        blurb="Test blurb",
        doc_summary="Test doc summary",
        chunk_context="Test chunk context",
        document_sets=None,
        project_ids=None,
        primary_owners=None,
        secondary_owners=None,
        tenant_id=tenant_state,
    )


def _generate_test_vector(base_value: float = 0.1, dimension: int = 128) -> list[float]:
    """Generates a test vector with slight variations.

    We round to eliminate floating point precision errors when comparing chunks
    for equality.
    """
    return [round(base_value + (i * 0.001), 5) for i in range(dimension)]


@pytest.fixture(scope="module")
def opensearch_available() -> None:
    """Verifies OpenSearch is running, skips all tests if not."""
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

    def test_index_document(
        self, test_client: OpenSearchClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tests indexing a document."""
        # Precondition.
        _patch_global_tenant_state(monkeypatch, False)
        tenant_state = TenantState(tenant_id=POSTGRES_DEFAULT_SCHEMA, multitenant=False)
        mappings = DocumentSchema.get_document_schema(
            vector_dimension=128, multitenant=tenant_state.multitenant
        )
        settings = DocumentSchema.get_index_settings()
        test_client.create_index(mappings=mappings, settings=settings)

        doc = _create_test_document_chunk(
            document_id="test-doc-1",
            chunk_index=0,
            content="Test content for indexing",
            tenant_state=tenant_state,
        )

        # Under test and postcondition.
        # Should not raise.
        test_client.index_document(document=doc)

    def test_index_duplicate_document(
        self, test_client: OpenSearchClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tests indexing a duplicate document raises an error."""
        # Precondition.
        _patch_global_tenant_state(monkeypatch, False)
        tenant_state = TenantState(tenant_id=POSTGRES_DEFAULT_SCHEMA, multitenant=False)
        mappings = DocumentSchema.get_document_schema(
            vector_dimension=128, multitenant=tenant_state.multitenant
        )
        settings = DocumentSchema.get_index_settings()
        test_client.create_index(mappings=mappings, settings=settings)

        doc = _create_test_document_chunk(
            document_id="test-doc-duplicate",
            chunk_index=0,
            content="Duplicate test",
            tenant_state=tenant_state,
        )

        # Index once - should succeed.
        test_client.index_document(document=doc)

        # Under test and postcondition.
        # Index again - should raise.
        with pytest.raises(Exception, match="already exists"):
            test_client.index_document(document=doc)

    def test_get_document(
        self, test_client: OpenSearchClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tests getting a document."""
        # Precondition.
        _patch_global_tenant_state(monkeypatch, False)
        tenant_state = TenantState(tenant_id=POSTGRES_DEFAULT_SCHEMA, multitenant=False)
        mappings = DocumentSchema.get_document_schema(
            vector_dimension=128, multitenant=tenant_state.multitenant
        )
        settings = DocumentSchema.get_index_settings()
        test_client.create_index(mappings=mappings, settings=settings)

        original_doc = _create_test_document_chunk(
            document_id="test-doc-get",
            chunk_index=0,
            content="Content to retrieve",
            tenant_state=tenant_state,
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

    def test_get_nonexistent_document(
        self, test_client: OpenSearchClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tests getting a nonexistent document raises an error."""
        # Precondition.
        _patch_global_tenant_state(monkeypatch, False)
        mappings = DocumentSchema.get_document_schema(
            vector_dimension=128, multitenant=False
        )
        settings = DocumentSchema.get_index_settings()
        test_client.create_index(mappings=mappings, settings=settings)

        # Under test and postcondition.
        with pytest.raises(Exception, match="404"):
            test_client.get_document(
                document_chunk_id="test_source__nonexistent__512__0"
            )

    def test_delete_existing_document(
        self, test_client: OpenSearchClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tests deleting an existing document returns True."""
        # Precondition.
        _patch_global_tenant_state(monkeypatch, False)
        tenant_state = TenantState(tenant_id=POSTGRES_DEFAULT_SCHEMA, multitenant=False)
        mappings = DocumentSchema.get_document_schema(
            vector_dimension=128, multitenant=tenant_state.multitenant
        )
        settings = DocumentSchema.get_index_settings()
        test_client.create_index(mappings=mappings, settings=settings)

        doc = _create_test_document_chunk(
            document_id="test-doc-delete",
            chunk_index=0,
            content="Content to delete",
            tenant_state=tenant_state,
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

    def test_delete_nonexistent_document(
        self, test_client: OpenSearchClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tests deleting a nonexistent document returns False."""
        # Precondition.
        _patch_global_tenant_state(monkeypatch, False)
        tenant_state = TenantState(tenant_id=POSTGRES_DEFAULT_SCHEMA, multitenant=False)
        mappings = DocumentSchema.get_document_schema(
            vector_dimension=128, multitenant=tenant_state.multitenant
        )
        settings = DocumentSchema.get_index_settings()
        test_client.create_index(mappings=mappings, settings=settings)

        # Under test.
        result = test_client.delete_document(
            document_chunk_id="test_source__nonexistent__512__0"
        )

        # Postcondition.
        assert result is False

    def test_delete_by_query(
        self, test_client: OpenSearchClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tests deleting documents by query."""
        # Precondition.
        _patch_global_tenant_state(monkeypatch, False)
        tenant_state = TenantState(tenant_id=POSTGRES_DEFAULT_SCHEMA, multitenant=False)
        mappings = DocumentSchema.get_document_schema(
            vector_dimension=128, multitenant=tenant_state.multitenant
        )
        settings = DocumentSchema.get_index_settings()
        test_client.create_index(mappings=mappings, settings=settings)

        # Index multiple documents.
        docs_to_delete = [
            _create_test_document_chunk(
                document_id="delete-me",
                chunk_index=i,
                content=f"Delete this {i}",
                tenant_state=tenant_state,
            )
            for i in range(3)
        ]
        docs_to_keep = [
            _create_test_document_chunk(
                document_id="keep-me",
                chunk_index=0,
                content="Keep this",
                tenant_state=tenant_state,
            )
        ]

        for doc in docs_to_delete + docs_to_keep:
            test_client.index_document(document=doc)
        test_client.refresh_index()

        query_body = DocumentQuery.delete_from_document_id_query(
            document_id="delete-me",
            tenant_state=tenant_state,
        )

        # Under test.
        num_deleted = test_client.delete_by_query(query_body=query_body)

        # Postcondition.
        assert num_deleted == 3

        # Verify deletion - the deleted documents should no longer exist.
        test_client.refresh_index()
        search_query = DocumentQuery.get_from_document_id_query(
            document_id="delete-me",
            tenant_state=tenant_state,
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
            tenant_state=tenant_state,
            max_chunk_size=DEFAULT_MAX_CHUNK_SIZE,
            min_chunk_index=None,
            max_chunk_index=None,
            get_full_document=False,
        )
        keep_ids = test_client.search_for_document_ids(body=keep_query)
        assert len(keep_ids) == 1

    def test_update_document(
        self, test_client: OpenSearchClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tests updating a document's properties."""
        # Precondition.
        _patch_global_tenant_state(monkeypatch, False)
        tenant_state = TenantState(tenant_id=POSTGRES_DEFAULT_SCHEMA, multitenant=False)
        mappings = DocumentSchema.get_document_schema(
            vector_dimension=128, multitenant=tenant_state.multitenant
        )
        settings = DocumentSchema.get_index_settings()
        test_client.create_index(mappings=mappings, settings=settings)

        # Create a document to update.
        doc = _create_test_document_chunk(
            document_id="test-doc-update",
            chunk_index=0,
            content="Original content",
            tenant_state=tenant_state,
            public=True,
            hidden=False,
        )
        test_client.index_document(document=doc)

        # Under test.
        doc_chunk_id = get_opensearch_doc_chunk_id(
            document_id=doc.document_id,
            chunk_index=doc.chunk_index,
            max_chunk_size=doc.max_chunk_size,
        )
        properties_to_update = {
            "hidden": True,
            "global_boost": 5,
        }
        test_client.update_document(
            document_chunk_id=doc_chunk_id,
            properties_to_update=properties_to_update,
        )

        # Postcondition.
        # Retrieve the document and verify updates were applied.
        updated_doc = test_client.get_document(document_chunk_id=doc_chunk_id)
        assert updated_doc.hidden is True
        assert updated_doc.global_boost == 5
        # Other properties should remain unchanged.
        assert updated_doc.document_id == doc.document_id
        assert updated_doc.content == doc.content
        assert updated_doc.public == doc.public

    def test_update_nonexistent_document(
        self, test_client: OpenSearchClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tests updating a nonexistent document raises an error."""
        # Precondition.
        _patch_global_tenant_state(monkeypatch, False)
        tenant_state = TenantState(tenant_id=POSTGRES_DEFAULT_SCHEMA, multitenant=False)
        mappings = DocumentSchema.get_document_schema(
            vector_dimension=128, multitenant=tenant_state.multitenant
        )
        settings = DocumentSchema.get_index_settings()
        test_client.create_index(mappings=mappings, settings=settings)

        # Under test and postcondition.
        # Try to update a document that doesn't exist.
        with pytest.raises(Exception, match="404"):
            test_client.update_document(
                document_chunk_id="test_source__nonexistent__512__0",
                properties_to_update={"hidden": True},
            )

    def test_search_basic(
        self, test_client: OpenSearchClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tests basic search functionality."""
        # Precondition.
        _patch_global_tenant_state(monkeypatch, False)
        tenant_state = TenantState(tenant_id=POSTGRES_DEFAULT_SCHEMA, multitenant=False)
        mappings = DocumentSchema.get_document_schema(
            vector_dimension=128, multitenant=tenant_state.multitenant
        )
        settings = DocumentSchema.get_index_settings()
        test_client.create_index(mappings=mappings, settings=settings)

        # Index multiple documents with different content and vectors.
        docs = {
            "search-doc-1": _create_test_document_chunk(
                document_id="search-doc-1",
                chunk_index=0,
                content="Python programming language tutorial",
                content_vector=_generate_test_vector(0.1),
                tenant_state=tenant_state,
            ),
            "search-doc-2": _create_test_document_chunk(
                document_id="search-doc-2",
                chunk_index=0,
                content="How to make cheese",
                content_vector=_generate_test_vector(0.2),
                tenant_state=tenant_state,
            ),
            "search-doc-3": _create_test_document_chunk(
                document_id="search-doc-3",
                chunk_index=0,
                content="C++ for newborns",
                content_vector=_generate_test_vector(0.15),
                tenant_state=tenant_state,
            ),
        }
        for doc in docs.values():
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
            tenant_state=tenant_state,
        )

        # Under test.
        results = test_client.search(body=search_body, search_pipeline_id=None)

        # Postcondition.
        assert len(results) == 3
        # Assert that all the chunks above are present.
        assert all(
            chunk.document_id in ["search-doc-1", "search-doc-2", "search-doc-3"]
            for chunk in results
        )
        # Make sure the chunk contents are preserved.
        for chunk in results:
            assert chunk == docs[chunk.document_id]

    def test_search_with_pipeline(
        self,
        test_client: OpenSearchClient,
        search_pipeline: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Tests search with a normalization pipeline."""
        # Precondition.
        _patch_global_tenant_state(monkeypatch, False)
        tenant_state = TenantState(tenant_id=POSTGRES_DEFAULT_SCHEMA, multitenant=False)
        mappings = DocumentSchema.get_document_schema(
            vector_dimension=128, multitenant=tenant_state.multitenant
        )
        settings = DocumentSchema.get_index_settings()
        test_client.create_index(mappings=mappings, settings=settings)

        # Index documents.
        docs = {
            "pipeline-doc-1": _create_test_document_chunk(
                document_id="pipeline-doc-1",
                chunk_index=0,
                content="Machine learning algorithms for single-celled organisms",
                content_vector=_generate_test_vector(0.3),
                tenant_state=tenant_state,
            ),
            "pipeline-doc-2": _create_test_document_chunk(
                document_id="pipeline-doc-2",
                chunk_index=0,
                content="Deep learning shallow neural networks",
                content_vector=_generate_test_vector(0.35),
                tenant_state=tenant_state,
            ),
        }
        for doc in docs.values():
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
            tenant_state=tenant_state,
        )

        # Under test.
        results = test_client.search(
            body=search_body, search_pipeline_id=MIN_MAX_NORMALIZATION_PIPELINE_NAME
        )

        # Postcondition.
        assert len(results) == 2
        # Assert that all the chunks above are present.
        assert all(
            chunk.document_id in ["pipeline-doc-1", "pipeline-doc-2"]
            for chunk in results
        )
        # Make sure the chunk contents are preserved.
        for chunk in results:
            assert chunk == docs[chunk.document_id]

    def test_search_empty_index(
        self, test_client: OpenSearchClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tests search on an empty index returns an empty list."""
        # Precondition.
        _patch_global_tenant_state(monkeypatch, False)
        tenant_state = TenantState(tenant_id=POSTGRES_DEFAULT_SCHEMA, multitenant=False)
        mappings = DocumentSchema.get_document_schema(
            vector_dimension=128, multitenant=tenant_state.multitenant
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
            tenant_state=tenant_state,
        )

        # Under test.
        results = test_client.search(body=search_body, search_pipeline_id=None)

        # Postcondition.
        assert len(results) == 0

    def test_search_filters(
        self, test_client: OpenSearchClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        Tests search filters for public/hidden documents and tenant isolation.
        """
        # Precondition.
        _patch_global_tenant_state(monkeypatch, True)
        tenant_x = TenantState(tenant_id="tenant-x", multitenant=True)
        tenant_y = TenantState(tenant_id="tenant-y", multitenant=True)
        mappings = DocumentSchema.get_document_schema(
            vector_dimension=128, multitenant=tenant_x.multitenant
        )
        settings = DocumentSchema.get_index_settings()
        test_client.create_index(mappings=mappings, settings=settings)

        # Index documents with different public/hidden and tenant states.
        docs = {
            "public-doc-1": _create_test_document_chunk(
                document_id="public-doc-1",
                chunk_index=0,
                content="Public document content",
                public=True,
                hidden=False,
                tenant_state=tenant_x,
            ),
            "hidden-doc-1": _create_test_document_chunk(
                document_id="hidden-doc-1",
                chunk_index=0,
                content="Hidden document content, spooky",
                public=True,
                hidden=True,
                tenant_state=tenant_x,
            ),
            "private-doc-1": _create_test_document_chunk(
                document_id="private-doc-1",
                chunk_index=0,
                content="Private document content, btw my SSN is 123-45-6789",
                public=False,
                hidden=False,
                tenant_state=tenant_x,
            ),
            "should-not-exist-from-tenant-x-pov": _create_test_document_chunk(
                document_id="should-not-exist-from-tenant-x-pov",
                chunk_index=0,
                content="This is an entirely different tenant, x should never see this",
                # Make this as permissive as possible to exercise tenant
                # isolation.
                public=True,
                hidden=False,
                tenant_state=tenant_y,
            ),
        }
        for doc in docs.values():
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
            tenant_state=tenant_x,
        )

        # Under test.
        results = test_client.search(body=search_body, search_pipeline_id=None)

        # Postcondition.
        # Should only get the public, non-hidden document.
        assert len(results) == 1
        assert results[0].document_id == "public-doc-1"
        # Make sure the chunk contents are preserved.
        assert results[0] == docs["public-doc-1"]

    def test_search_with_pipeline_and_filters_returns_chunks_with_related_content_first(
        self,
        test_client: OpenSearchClient,
        search_pipeline: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        Tests search with a normalization pipeline and filters returns chunks
        with related content first.
        """
        # Precondition.
        _patch_global_tenant_state(monkeypatch, True)
        tenant_x = TenantState(tenant_id="tenant-x", multitenant=True)
        mappings = DocumentSchema.get_document_schema(
            vector_dimension=128, multitenant=tenant_x.multitenant
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
                tenant_state=tenant_x,
            ),
            _create_test_document_chunk(
                document_id="somewhat-relevant-1",
                chunk_index=0,
                content="Computer programming with various languages",
                content_vector=_generate_test_vector(0.5),  # Far from query vector.
                public=True,
                hidden=False,
                tenant_state=tenant_x,
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
                tenant_state=tenant_x,
            ),
            # These should be filtered out by public/hidden filters.
            _create_test_document_chunk(
                document_id="hidden-but-relevant-1",
                chunk_index=0,
                content="Artificial intelligence research papers",
                content_vector=_generate_test_vector(0.05),  # Very close but hidden.
                public=True,
                hidden=True,
                tenant_state=tenant_x,
            ),
            _create_test_document_chunk(
                document_id="private-but-relevant-1",
                chunk_index=0,
                content="Artificial intelligence industry analysis",
                content_vector=_generate_test_vector(0.08),  # Very close but private.
                public=False,
                hidden=False,
                tenant_state=tenant_x,
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
            tenant_state=tenant_x,
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

    def test_delete_by_query_multitenant_isolation(
        self, test_client: OpenSearchClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        Tests delete_by_query respects tenant boundaries in multi-tenant mode.
        """
        # Precondition.
        _patch_global_tenant_state(monkeypatch, True)
        tenant_x = TenantState(tenant_id="tenant-x", multitenant=True)
        tenant_y = TenantState(tenant_id="tenant-y", multitenant=True)
        mappings = DocumentSchema.get_document_schema(
            vector_dimension=128, multitenant=tenant_x.multitenant
        )
        settings = DocumentSchema.get_index_settings()
        test_client.create_index(mappings=mappings, settings=settings)

        # Index chunks for different doc IDs for different tenants.
        # NOTE: Since get_opensearch_doc_chunk_id doesn't include tenant_id yet,
        # we use different document IDs to avoid ID conflicts.
        tenant_x_chunks = [
            _create_test_document_chunk(
                document_id="doc-tenant-x",
                chunk_index=i,
                content=f"Tenant A Chunk {i}",
                tenant_state=tenant_x,
            )
            for i in range(3)
        ]

        tenant_y_chunks = [
            _create_test_document_chunk(
                document_id="doc-tenant-y",
                chunk_index=i,
                content=f"Tenant B Chunk {i}",
                tenant_state=tenant_y,
            )
            for i in range(2)
        ]

        for chunk in tenant_x_chunks + tenant_y_chunks:
            test_client.index_document(document=chunk)
        test_client.refresh_index()

        # Build deletion query for tenant-x only.
        query_body = DocumentQuery.delete_from_document_id_query(
            document_id="doc-tenant-x",
            tenant_state=tenant_x,
        )

        # Under test.
        # Delete tenant-x chunks using delete_by_query.
        num_deleted = test_client.delete_by_query(query_body=query_body)

        # Postcondition.
        assert num_deleted == 3

        # Verify tenant-x chunks are deleted.
        test_client.refresh_index()
        verify_query_x = DocumentQuery.get_from_document_id_query(
            document_id="doc-tenant-x",
            tenant_state=tenant_x,
            max_chunk_size=DEFAULT_MAX_CHUNK_SIZE,
            min_chunk_index=None,
            max_chunk_index=None,
            get_full_document=False,
        )
        remaining_a_ids = test_client.search_for_document_ids(body=verify_query_x)
        assert len(remaining_a_ids) == 0

        # Verify tenant-y chunks still exist.
        verify_query_y = DocumentQuery.get_from_document_id_query(
            document_id="doc-tenant-y",
            tenant_state=tenant_y,
            max_chunk_size=DEFAULT_MAX_CHUNK_SIZE,
            min_chunk_index=None,
            max_chunk_index=None,
            get_full_document=False,
        )
        remaining_y_ids = test_client.search_for_document_ids(body=verify_query_y)
        assert len(remaining_y_ids) == 2
        expected_y_ids = {
            get_opensearch_doc_chunk_id(
                document_id=chunk.document_id,
                chunk_index=chunk.chunk_index,
                max_chunk_size=chunk.max_chunk_size,
            )
            for chunk in tenant_y_chunks
        }
        assert set(remaining_y_ids) == expected_y_ids

    def test_delete_by_query_nonexistent_document(
        self, test_client: OpenSearchClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        Tests delete_by_query for non-existent document returns 0 deleted.
        """
        # Precondition.
        _patch_global_tenant_state(monkeypatch, False)
        tenant_state = TenantState(tenant_id=POSTGRES_DEFAULT_SCHEMA, multitenant=False)
        mappings = DocumentSchema.get_document_schema(
            vector_dimension=128, multitenant=tenant_state.multitenant
        )
        settings = DocumentSchema.get_index_settings()
        test_client.create_index(mappings=mappings, settings=settings)

        # Don't index any documents.

        # Build deletion query.
        query_body = DocumentQuery.delete_from_document_id_query(
            document_id="nonexistent-doc",
            tenant_state=tenant_state,
        )

        # Under test.
        num_deleted = test_client.delete_by_query(query_body=query_body)

        # Postcondition.
        assert num_deleted == 0

    def test_search_for_document_ids(
        self, test_client: OpenSearchClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tests search_for_document_ids method returns correct chunk IDs."""
        # Precondition.
        _patch_global_tenant_state(monkeypatch, False)
        tenant_state = TenantState(tenant_id=POSTGRES_DEFAULT_SCHEMA, multitenant=False)
        mappings = DocumentSchema.get_document_schema(
            vector_dimension=128, multitenant=tenant_state.multitenant
        )
        settings = DocumentSchema.get_index_settings()
        test_client.create_index(mappings=mappings, settings=settings)

        # Index chunks for two different documents.
        doc1_chunks = [
            _create_test_document_chunk(
                document_id="doc-1",
                chunk_index=i,
                content=f"Doc 1 Chunk {i}",
                tenant_state=tenant_state,
            )
            for i in range(3)
        ]
        doc2_chunks = [
            _create_test_document_chunk(
                document_id="doc-2",
                chunk_index=i,
                content=f"Doc 2 Chunk {i}",
                tenant_state=tenant_state,
            )
            for i in range(2)
        ]

        for chunk in doc1_chunks + doc2_chunks:
            test_client.index_document(document=chunk)
        test_client.refresh_index()

        # Build query for doc-1.
        query_body = DocumentQuery.get_from_document_id_query(
            document_id="doc-1",
            tenant_state=tenant_state,
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
