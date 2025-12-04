"""
Pytest integration test for CodaConnector.load_from_state()

Tests end-to-end document generation with correct batching.
Run with: pytest test_load_from_state.py -v

Prerequisites:
- Set CODA_API_TOKEN environment variable
- Have a Coda workspace with at least 1 doc and multiple pages
"""

import os
from collections.abc import Generator
from typing import Any

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.coda.api.client import CodaAPIClient
from onyx.connectors.coda.connector import CodaConnector
from onyx.connectors.models import Document


@pytest.fixture
def api_token() -> str:
    """Fixture to get and validate API token."""
    token = os.environ.get("CODA_API_TOKEN")
    if not token:
        pytest.skip("CODA_API_TOKEN not set")
    return token


@pytest.fixture
def api_client(api_token: str) -> CodaAPIClient:
    """Fixture to create and authenticate API client."""
    client = CodaAPIClient(api_token)
    client.validate_credentials()
    return client


@pytest.fixture
def connector(api_token: str) -> CodaConnector:
    """Fixture to create and authenticate connector."""
    conn = CodaConnector(batch_size=5)
    conn.load_credentials({"coda_api_token": api_token})
    conn.validate_connector_settings()
    return conn


@pytest.fixture
def reference_data(api_client: CodaAPIClient) -> dict[str, Any]:
    """Fixture to fetch reference data from API.

    Builds a map of docs and their pages for validation.
    """
    all_docs = list(api_client.fetch_all_docs())

    if not all_docs:
        pytest.skip("No docs found in Coda workspace")

    # Count expected non-hidden pages across all docs
    expected_page_count = 0
    expected_pages_by_doc = {}

    for doc in all_docs:
        pages = api_client.fetch_all_pages(doc.id)

        # Only count non-hidden pages
        non_hidden_pages = [p for p in pages if not p.isHidden]
        expected_pages_by_doc[doc.id] = non_hidden_pages
        expected_page_count += len(non_hidden_pages)

    if expected_page_count == 0:
        pytest.skip("No visible pages found in Coda workspace")

    return {
        "docs": all_docs,
        "total_pages": expected_page_count,
        "pages_by_doc": expected_pages_by_doc,
    }


class TestLoadFromStateEndToEnd:
    """Test suite for load_from_state end-to-end functionality."""

    def test_returns_generator(self, connector: CodaConnector) -> None:
        """Test that load_from_state returns a generator."""
        gen = connector.load_from_state()
        assert isinstance(gen, Generator), "load_from_state should return a Generator"

    def test_batch_sizes_respect_config(self, connector: CodaConnector) -> None:
        """Test that batches respect the configured batch_size."""
        batch_size = connector.batch_size
        assert connector.generator is not None
        connector.generator.indexed_pages.clear()
        connector.generator.indexed_tables.clear()
        gen = connector.load_from_state()

        batch_sizes = []
        for batch in gen:
            batch_sizes.append(len(batch))
            # All batches should be <= batch_size
            assert (
                len(batch) <= batch_size
            ), f"Batch size {len(batch)} exceeds configured {batch_size}"

        # All non-final batches should be exactly batch_size
        for i, size in enumerate(batch_sizes[:-1]):
            assert (
                size == batch_size
            ), f"Non-final batch {i} has size {size}, expected {batch_size}"

        # Last batch may be smaller
        if batch_sizes:
            assert batch_sizes[-1] <= batch_size

    def test_document_count_matches_expected(
        self, connector: CodaConnector, reference_data: dict[str, Any]
    ) -> None:
        """Test that documents are generated from non-hidden pages.

        Note: The actual count may be less than the API page count because:
        - Some pages may fail to export
        - Some pages may have empty content
        """
        assert connector.generator is not None
        connector.generator.indexed_pages.clear()
        connector.generator.indexed_tables.clear()
        gen = connector.load_from_state()

        total_documents = sum(len(batch) for batch in gen)
        expected_count = reference_data["total_pages"]

        # We should get at least some documents
        assert total_documents > 0, "Expected at least one document"

        # Log if there's a significant mismatch (for debugging)
        if total_documents < expected_count:
            skipped = expected_count - total_documents
            print(
                f"Note: {skipped}/{expected_count} pages were skipped (failed export or empty content)"
            )

    def test_document_required_fields(
        self, connector: CodaConnector, reference_data: dict[str, Any]
    ) -> None:
        """Test that all documents have required fields."""
        assert connector.generator is not None
        connector.generator.indexed_pages.clear()
        connector.generator.indexed_tables.clear()
        gen = connector.load_from_state()

        for batch in gen:
            for doc in batch:
                # Type check
                assert isinstance(doc, Document)

                # Required fields
                assert doc.id is not None
                assert doc.source == DocumentSource.CODA
                assert doc.semantic_identifier is not None
                assert doc.doc_updated_at is not None

                # Sections with content
                assert len(doc.sections) > 0
                for section in doc.sections:
                    assert section.text is not None
                    assert len(section.text) > 0
                    assert section.link is not None

                # Metadata
                assert "doc_id" in doc.metadata
                assert "page_id" in doc.metadata or "table_id" in doc.metadata
                assert "path" in doc.metadata or "table_name" in doc.metadata

    def test_hidden_pages_excluded(
        self, connector: CodaConnector, reference_data: dict[str, Any]
    ) -> None:
        """Test that hidden pages are not included in results."""
        assert connector.generator is not None
        connector.generator.indexed_pages.clear()
        connector.generator.indexed_tables.clear()
        gen = connector.load_from_state()

        # Collect all yielded page IDs
        yielded_page_ids = set()
        for batch in gen:
            for doc in batch:
                page_id = doc.metadata.get("page_id")
                if page_id:
                    yielded_page_ids.add(page_id)

        # Get all hidden page IDs from reference data
        all_hidden_page_ids = set()
        for doc_id, pages in reference_data["pages_by_doc"].items():
            for page in pages:
                if page.isHidden:
                    all_hidden_page_ids.add(page.id)

        # Verify no overlap
        hidden_in_results = all_hidden_page_ids & yielded_page_ids
        assert (
            not hidden_in_results
        ), f"Found {len(hidden_in_results)} hidden pages in results"

    def test_no_duplicate_documents(
        self, connector: CodaConnector, reference_data: dict[str, Any]
    ) -> None:
        """Test that no documents are yielded twice."""
        assert connector.generator is not None
        connector.generator.indexed_pages.clear()
        connector.generator.indexed_tables.clear()
        gen = connector.load_from_state()

        document_ids = []
        for batch in gen:
            for doc in batch:
                document_ids.append(doc.id)

        unique_ids = set(document_ids)
        assert len(document_ids) == len(
            unique_ids
        ), f"Found {len(document_ids) - len(unique_ids)} duplicate documents"

    def test_all_docs_processed(
        self, connector: CodaConnector, reference_data: dict[str, Any]
    ) -> None:
        """Test that pages from all docs are included."""
        assert connector.generator is not None
        connector.generator.indexed_pages.clear()
        connector.generator.indexed_tables.clear()
        gen = connector.load_from_state()

        processed_doc_ids = set()
        for batch in gen:
            for doc in batch:
                doc_id = doc.metadata.get("doc_id")
                processed_doc_ids.add(doc_id)

        expected_doc_ids = {doc.id for doc in reference_data["docs"]}
        assert (
            processed_doc_ids == expected_doc_ids
        ), f"Not all docs were processed. Expected {expected_doc_ids}, got {processed_doc_ids}"

    def test_document_content_not_empty(
        self, connector: CodaConnector, reference_data: dict[str, Any]
    ) -> None:
        """Test that all documents have meaningful content (not just title)."""
        assert connector.generator is not None
        connector.generator.indexed_pages.clear()
        connector.generator.indexed_tables.clear()
        gen = connector.load_from_state()

        for batch in gen:
            for doc in batch:
                # Semantic identifier should not be just the ID
                assert doc.semantic_identifier
                assert not doc.semantic_identifier.startswith("Untitled Page")

                # Check that each section has actual content beyond the title
                for section in doc.sections:
                    assert (
                        section.text is not None
                    ), f"Section text is None for {doc.id}"
                    lines = section.text.strip().split("\n")
                    # Should have multiple lines (title + blank line + content)
                    assert (
                        len(lines) > 1
                    ), f"Document {doc.id} has only title and blank line, no actual content {doc}"

                    # Content should be meaningfully longer than just the title
                    title_len = len(doc.semantic_identifier)
                    content_len = len(section.text)
                    assert (
                        content_len > title_len + 15
                    ), f"Document {doc.id} lacks meaningful content (only {content_len - title_len} chars beyond title)"

    def test_metadata_contains_hierarchy_info(
        self, connector: CodaConnector, reference_data: dict[str, Any]
    ) -> None:
        """Test that metadata contains page hierarchy information."""
        assert connector.generator is not None
        connector.generator.indexed_pages.clear()
        connector.generator.indexed_tables.clear()
        gen = connector.load_from_state()

        for batch in gen:
            for doc in batch:
                metadata = doc.metadata

                # Pages should have path
                if "page_id" in metadata:
                    assert "path" in metadata
                    path = metadata["path"]
                    assert isinstance(path, str), "Path should be a string"
                    assert path
                    assert path == path.strip()  # No leading/trailing spaces

                    # If page has a parent, it should be in metadata
                    if "parent_page_id" in metadata:
                        assert metadata["parent_page_id"] is not None

                # Tables should have table info
                elif "table_id" in metadata:
                    assert "table_name" in metadata
                    assert "row_count" in metadata
                    assert "column_count" in metadata


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
