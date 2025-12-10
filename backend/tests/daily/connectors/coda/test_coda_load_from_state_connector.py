"""
Pytest integration test for CodaConnector.load_from_state()

Tests end-to-end document generation with correct batching.
Run with: pytest test_load_from_state.py -v

Prerequisites:
- Set CODA_API_TOKEN environment variable
- Set CODA_FOLDER_ID environment variable
"""

from collections.abc import Generator
from typing import Any

from onyx.configs.constants import DocumentSource
from onyx.connectors.coda.api.client import CodaAPIClient
from onyx.connectors.coda.connector import CodaConnector
from onyx.connectors.coda.models.common import CodaObjectType
from onyx.connectors.models import Document
from onyx.connectors.models import ImageSection
from onyx.connectors.models import TextSection
from onyx.utils.logger import setup_logger

logger = setup_logger()


class TestDocCreation:
    """Test suite for doc creation and manipulation."""

    def test_doc_was_created(self, template_test_doc: dict[str, Any]) -> None:
        """Test that the test doc fixture was created successfully."""
        # Verify response structure
        assert "id" in template_test_doc, "Response should contain doc ID"
        assert "name" in template_test_doc, "Response should contain doc name"
        assert "href" in template_test_doc, "Response should contain API href"
        assert (
            "browserLink" in template_test_doc
        ), "Response should contain browser link"

        # Verify the doc was created with correct title
        assert (
            template_test_doc["name"]
            == "Two-way writeups: Coda's secret to shipping fast"
        ), f"Doc name should match, got: {template_test_doc['name']}"

        # Verify doc type
        assert template_test_doc.get("type") == "doc", "Response type should be 'doc'"

        # Log the doc info
        logger.info(f"Test doc verified: {template_test_doc['name']}")
        logger.info(f"Doc ID: {template_test_doc['id']}")
        logger.info(f"Browser link: {template_test_doc['browserLink']}")

    def test_can_fetch_created_doc(
        self, api_client: CodaAPIClient, template_test_doc: dict[str, Any]
    ) -> None:
        """Test that we can fetch the created doc via the API."""
        doc_id = template_test_doc["id"]

        # Fetch the doc
        response = api_client._make_request("GET", f"/docs/{doc_id}")

        # Verify we got the same doc
        assert response["id"] == doc_id, "Fetched doc ID should match"
        assert response["name"] == "Two-way writeups: Coda's secret to shipping fast"
        logger.info(f"Successfully fetched doc: {response['name']}")


class TestLoadFromStateEndToEnd:
    """Test suite for load_from_state end-to-end functionality."""

    def test_returns_generator(self, template_connector: CodaConnector) -> None:
        """Test that load_from_state returns a generator."""
        gen = template_connector.load_from_state()
        assert isinstance(gen, Generator), "load_from_state should return a Generator"

    def test_batch_sizes_respect_config(
        self,
        template_connector: CodaConnector,
        template_test_doc: dict[str, Any],
        all_batches: list[list[Document]],
    ) -> None:
        """Test that batches respect the configured batch_size."""
        batch_size = template_connector.batch_size

        batch_sizes = []
        for batch in all_batches:
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
        self,
        all_documents: list[Document],
        reference_data: dict[str, Any],
    ) -> None:
        """Test that documents are generated from non-hidden pages.

        Note: The actual count may be less than the API page count because:
        - Some pages may fail to export
        - Some pages may have empty content
        """
        total_documents = len(all_documents)
        expected_count = reference_data["total_pages"]

        # We should get at least some documents
        assert total_documents > 0, "Expected at least one document"

        logger.info(f"Total documents: {total_documents}")
        logger.info(f"Expected count: {expected_count}")

        # Log if there's a significant mismatch (for debugging)
        assert (
            not total_documents < expected_count
        ), f"Expected at least {expected_count} documents, got {total_documents}"

    def test_document_required_fields(
        self,
        all_documents: list[Document],
        reference_data: dict[str, Any],
    ) -> None:
        """Test that all documents have required fields."""
        for doc in all_documents:
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
                if isinstance(section, TextSection):
                    assert section.text is not None
                    assert len(section.text) > 0
                elif isinstance(section, ImageSection):
                    assert section.image_file_id is not None

            assert "doc_id" in doc.metadata
            assert "page_id" in doc.metadata or "table_id" in doc.metadata
            assert "path" in doc.metadata or "table_name" in doc.metadata

    def test_hidden_pages_excluded(
        self, all_documents: list[Document], reference_data: dict[str, Any]
    ) -> None:
        """Test that hidden pages are not included in results."""
        # Collect all yielded page IDs
        yielded_page_ids = set()
        for doc in all_documents:
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
        self, all_documents: list[Document], reference_data: dict[str, Any]
    ) -> None:
        """Test that no documents are yielded twice."""
        document_ids = [doc.id for doc in all_documents]

        unique_ids = set(document_ids)
        assert len(document_ids) == len(
            unique_ids
        ), f"Found {len(document_ids) - len(unique_ids)} duplicate documents"

    def test_all_docs_processed(
        self, all_documents: list[Document], template_connector: CodaConnector
    ) -> None:
        """Test that pages from all docs are included."""
        processed_doc_ids = set[str]()
        for doc in all_documents:
            doc_id = doc.metadata.get("doc_id")
            processed_doc_ids.add(doc_id)

        logger.info(f"Processed doc IDs: {processed_doc_ids}")
        logger.info(f"Expected doc IDs: {template_connector.doc_ids}")

        expected_doc_ids = template_connector.doc_ids
        assert (
            processed_doc_ids == expected_doc_ids
        ), f"Not all docs were processed. Expected {expected_doc_ids}, got {processed_doc_ids}"

    def test_document_content_not_empty(
        self,
        all_documents: list[Document],
        reference_data: dict[str, Any],
        template_connector: CodaConnector,
    ) -> None:
        """Test that all documents have meaningful content (not just title)."""
        for doc in all_documents:
            assert doc.semantic_identifier

            for section in doc.sections:
                if isinstance(section, ImageSection):
                    assert section.image_file_id is not None
                    continue

                assert section.text is not None, f"Section text is None for {doc.id}"

                assert len(section.text) > 0, f"Section text is empty for doc {doc.id}"

                if doc.metadata.get("type") != CodaObjectType.TABLE:
                    content_len = len(section.text)
                    assert (
                        content_len > 10
                    ), f"Document {doc.id} lacks meaningful content (only {content_len} chars) {doc.semantic_identifier}"

    def test_metadata_contains_hierarchy_info(
        self, all_documents: list[Document], reference_data: dict[str, Any]
    ) -> None:
        """Test that metadata contains page hierarchy information."""
        for doc in all_documents:
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
