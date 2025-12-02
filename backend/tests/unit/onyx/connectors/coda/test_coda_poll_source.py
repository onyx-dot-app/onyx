"""
Unit tests for CodaConnector.poll_source() method.

Tests poll_source functionality with mocked API responses,
following patterns from Confluence and Jira connector tests.

Run with: pytest tests/unit/onyx/connectors/coda/test_coda_poll_source.py -v
"""

from collections.abc import Callable
from datetime import datetime
from datetime import timezone
from typing import Any
from unittest.mock import patch

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.coda.connector import CodaConnector
from onyx.connectors.models import Document


@pytest.fixture
def mock_export_content() -> str:
    """Mock markdown content returned from page export"""
    return "# Test Content\n\nThis is test content for a Coda page."


class TestPollSourceTimeFiltering:
    """Test suite for time-based filtering in poll_source"""

    def test_poll_source_filters_docs_by_time(
        self,
        coda_connector: CodaConnector,
        create_mock_doc: Callable[..., dict[str, Any]],
        create_mock_page: Callable[..., dict[str, Any]],
        mock_export_content: str,
    ) -> None:
        """Test that only docs updated within time window are processed"""
        # Create docs with different timestamps
        old_doc = create_mock_doc(
            id="doc-old", name="Old Doc", updated="2023-01-01T00:00:00.000Z"
        )
        in_range_doc = create_mock_doc(
            id="doc-in-range",
            name="In Range Doc",
            updated="2023-01-02T12:00:00.000Z",
        )
        future_doc = create_mock_doc(
            id="doc-future", name="Future Doc", updated="2023-01-05T00:00:00.000Z"
        )

        # Create a page for the in-range doc
        in_range_page = create_mock_page(
            id="page-1", name="Page 1", updated="2023-01-02T12:00:00.000Z"
        )

        # Mock API responses
        with (
            patch.object(coda_connector, "_fetch_docs") as mock_fetch_docs,
            patch.object(coda_connector, "_fetch_pages") as mock_fetch_pages,
            patch.object(
                coda_connector, "_export_page_content", return_value=mock_export_content
            ),
        ):
            # Return all docs in one call
            mock_fetch_docs.return_value = {
                "items": [old_doc, in_range_doc, future_doc],
            }

            # Return pages for the in-range doc
            mock_fetch_pages.return_value = {"items": [in_range_page]}

            # Poll for time window: 2023-01-02 00:00 to 2023-01-03 00:00
            start = datetime(2023, 1, 2, tzinfo=timezone.utc).timestamp()
            end = datetime(2023, 1, 3, tzinfo=timezone.utc).timestamp()

            batches = list(coda_connector.poll_source(start, end))

            # Should only process the in-range doc
            assert len(batches) == 1
            assert len(batches[0]) == 1

            doc = batches[0][0]
            assert isinstance(doc, Document)
            assert doc.metadata["doc_id"] == "doc-in-range"
            assert doc.metadata["doc_name"] == "In Range Doc"

    def test_poll_source_filters_pages_by_time(
        self,
        coda_connector: CodaConnector,
        create_mock_doc: Callable[..., dict[str, Any]],
        create_mock_page: Callable[..., dict[str, Any]],
        mock_export_content: str,
    ) -> None:
        """Test that only pages updated within time window are yielded"""
        # Create a doc that's in range
        doc = create_mock_doc(
            id="doc-1", name="Test Doc", updated="2023-01-02T12:00:00.000Z"
        )

        # Create pages with different timestamps
        old_page = create_mock_page(
            id="page-old", name="Old Page", updated="2023-01-01T00:00:00.000Z"
        )
        in_range_page1 = create_mock_page(
            id="page-1", name="Page 1", updated="2023-01-02T06:00:00.000Z"
        )
        in_range_page2 = create_mock_page(
            id="page-2", name="Page 2", updated="2023-01-02T18:00:00.000Z"
        )
        future_page = create_mock_page(
            id="page-future", name="Future Page", updated="2023-01-05T00:00:00.000Z"
        )

        with (
            patch.object(coda_connector, "_fetch_docs") as mock_fetch_docs,
            patch.object(coda_connector, "_fetch_pages") as mock_fetch_pages,
            patch.object(
                coda_connector, "_export_page_content", return_value=mock_export_content
            ),
        ):
            mock_fetch_docs.return_value = {"items": [doc]}
            mock_fetch_pages.return_value = {
                "items": [old_page, in_range_page1, in_range_page2, future_page]
            }

            # Poll for time window: 2023-01-02 00:00 to 2023-01-03 00:00
            start = datetime(2023, 1, 2, tzinfo=timezone.utc).timestamp()
            end = datetime(2023, 1, 3, tzinfo=timezone.utc).timestamp()

            batches = list(coda_connector.poll_source(start, end))

            # Should yield 2 pages (in_range_page1 and in_range_page2)
            all_docs = [doc for batch in batches for doc in batch]
            assert len(all_docs) == 2

            page_ids = {doc.metadata["page_id"] for doc in all_docs}
            assert page_ids == {"page-1", "page-2"}

    def test_poll_source_empty_time_window(
        self,
        coda_connector: CodaConnector,
        create_mock_doc: Callable[..., dict[str, Any]],
    ) -> None:
        """Test poll_source with no docs/pages in time window"""
        # Create docs outside the time window
        old_doc = create_mock_doc(
            id="doc-old", name="Old Doc", updated="2023-01-01T00:00:00.000Z"
        )

        with patch.object(coda_connector, "_fetch_docs") as mock_fetch_docs:
            mock_fetch_docs.return_value = {"items": [old_doc]}

            # Poll for future time window
            start = datetime(2023, 6, 1, tzinfo=timezone.utc).timestamp()
            end = datetime(2023, 6, 2, tzinfo=timezone.utc).timestamp()

            batches = list(coda_connector.poll_source(start, end))

            # Should return empty results
            assert len(batches) == 0


class TestPollSourceDocIdsFiltering:
    """Test suite for doc_ids filtering in poll_source"""

    def test_poll_source_with_doc_ids_filtering(
        self,
        create_mock_doc: Callable[..., dict[str, Any]],
        create_mock_page: Callable[..., dict[str, Any]],
        mock_export_content: str,
        coda_api_token: str,
    ) -> None:
        """Test that poll_source respects doc_ids configuration"""
        # Create connector with specific doc_ids
        connector = CodaConnector(batch_size=5, doc_ids=["doc-1", "doc-3"])
        connector.load_credentials({"coda_api_token": coda_api_token})

        # Create multiple docs
        doc1 = create_mock_doc(
            id="doc-1", name="Doc 1", updated="2023-01-02T12:00:00.000Z"
        )
        doc2 = create_mock_doc(
            id="doc-2", name="Doc 2", updated="2023-01-02T12:00:00.000Z"
        )
        doc3 = create_mock_doc(
            id="doc-3", name="Doc 3", updated="2023-01-02T12:00:00.000Z"
        )

        # Create pages for each doc
        page1 = create_mock_page(
            id="page-1", name="Page 1", updated="2023-01-02T12:00:00.000Z"
        )
        page2 = create_mock_page(
            id="page-2", name="Page 2", updated="2023-01-02T12:00:00.000Z"
        )
        page3 = create_mock_page(
            id="page-3", name="Page 3", updated="2023-01-02T12:00:00.000Z"
        )

        with (
            patch.object(connector, "_fetch_docs") as mock_fetch_docs,
            patch.object(connector, "_fetch_pages") as mock_fetch_pages,
            patch.object(
                connector, "_export_page_content", return_value=mock_export_content
            ),
        ):
            # Return all docs
            mock_fetch_docs.return_value = {"items": [doc1, doc2, doc3]}

            # Return pages based on doc_id
            def fetch_pages_side_effect(doc_id: str, page_token: str | None = None):
                if doc_id == "doc-1":
                    return {"items": [page1]}
                elif doc_id == "doc-2":
                    return {"items": [page2]}
                elif doc_id == "doc-3":
                    return {"items": [page3]}
                return {"items": []}

            mock_fetch_pages.side_effect = fetch_pages_side_effect

            # Poll for time window
            start = datetime(2023, 1, 2, tzinfo=timezone.utc).timestamp()
            end = datetime(2023, 1, 3, tzinfo=timezone.utc).timestamp()

            batches = list(connector.poll_source(start, end))

            # Should only process doc-1 and doc-3 (not doc-2)
            all_docs = [doc for batch in batches for doc in batch]
            assert len(all_docs) == 2

            doc_ids = {doc.metadata["doc_id"] for doc in all_docs}
            assert doc_ids == {"doc-1", "doc-3"}

            # Verify doc-2 was not processed
            assert "doc-2" not in doc_ids

    def test_poll_source_without_doc_ids_processes_all(
        self,
        coda_connector: CodaConnector,
        create_mock_doc: Callable[..., dict[str, Any]],
        create_mock_page: Callable[..., dict[str, Any]],
        mock_export_content: str,
    ) -> None:
        """Test that poll_source processes all docs when doc_ids is None"""
        # Create multiple docs
        doc1 = create_mock_doc(
            id="doc-1", name="Doc 1", updated="2023-01-02T12:00:00.000Z"
        )
        doc2 = create_mock_doc(
            id="doc-2", name="Doc 2", updated="2023-01-02T12:00:00.000Z"
        )

        # Create pages
        page1 = create_mock_page(
            id="page-1", name="Page 1", updated="2023-01-02T12:00:00.000Z"
        )
        page2 = create_mock_page(
            id="page-2", name="Page 2", updated="2023-01-02T12:00:00.000Z"
        )

        with (
            patch.object(coda_connector, "_fetch_docs") as mock_fetch_docs,
            patch.object(coda_connector, "_fetch_pages") as mock_fetch_pages,
            patch.object(
                coda_connector, "_export_page_content", return_value=mock_export_content
            ),
        ):
            mock_fetch_docs.return_value = {"items": [doc1, doc2]}

            def fetch_pages_side_effect(doc_id: str, page_token: str | None = None):
                if doc_id == "doc-1":
                    return {"items": [page1]}
                elif doc_id == "doc-2":
                    return {"items": [page2]}
                return {"items": []}

            mock_fetch_pages.side_effect = fetch_pages_side_effect

            start = datetime(2023, 1, 2, tzinfo=timezone.utc).timestamp()
            end = datetime(2023, 1, 3, tzinfo=timezone.utc).timestamp()

            batches = list(coda_connector.poll_source(start, end))

            # Should process all docs
            all_docs = [doc for batch in batches for doc in batch]
            assert len(all_docs) == 2

            doc_ids = {doc.metadata["doc_id"] for doc in all_docs}
            assert doc_ids == {"doc-1", "doc-2"}


class TestPollSourceBatchingAndPagination:
    """Test suite for batching and pagination behavior"""

    def test_poll_source_respects_batch_size(
        self,
        create_mock_doc: Callable[..., dict[str, Any]],
        create_mock_page: Callable[..., dict[str, Any]],
        mock_export_content: str,
        coda_api_token: str,
    ) -> None:
        """Test that poll_source yields batches of configured size"""
        # Create connector with small batch size
        connector = CodaConnector(batch_size=2)
        connector.load_credentials({"coda_api_token": coda_api_token})

        # Create doc with multiple pages
        doc = create_mock_doc(
            id="doc-1", name="Test Doc", updated="2023-01-02T12:00:00.000Z"
        )

        # Create 5 pages (should result in 3 batches: 2, 2, 1)
        pages = [
            create_mock_page(
                id=f"page-{i}", name=f"Page {i}", updated="2023-01-02T12:00:00.000Z"
            )
            for i in range(1, 6)
        ]

        with (
            patch.object(connector, "_fetch_docs") as mock_fetch_docs,
            patch.object(connector, "_fetch_pages") as mock_fetch_pages,
            patch.object(
                connector, "_export_page_content", return_value=mock_export_content
            ),
        ):
            mock_fetch_docs.return_value = {"items": [doc]}
            mock_fetch_pages.return_value = {"items": pages}

            start = datetime(2023, 1, 2, tzinfo=timezone.utc).timestamp()
            end = datetime(2023, 1, 3, tzinfo=timezone.utc).timestamp()

            batches = list(connector.poll_source(start, end))

            # Should have 3 batches
            assert len(batches) == 3

            # First two batches should have 2 items
            assert len(batches[0]) == 2
            assert len(batches[1]) == 2

            # Last batch should have 1 item
            assert len(batches[2]) == 1

    def test_poll_source_handles_doc_pagination(
        self,
        coda_connector: CodaConnector,
        create_mock_doc: Callable[..., dict[str, Any]],
        create_mock_page: Callable[..., dict[str, Any]],
        mock_export_content: str,
    ) -> None:
        """Test that poll_source handles paginated doc responses"""
        # Create docs for pagination
        doc1 = create_mock_doc(
            id="doc-1", name="Doc 1", updated="2023-01-02T12:00:00.000Z"
        )
        doc2 = create_mock_doc(
            id="doc-2", name="Doc 2", updated="2023-01-02T12:00:00.000Z"
        )

        page1 = create_mock_page(
            id="page-1", name="Page 1", updated="2023-01-02T12:00:00.000Z"
        )
        page2 = create_mock_page(
            id="page-2", name="Page 2", updated="2023-01-02T12:00:00.000Z"
        )

        with (
            patch.object(coda_connector, "_fetch_docs") as mock_fetch_docs,
            patch.object(coda_connector, "_fetch_pages") as mock_fetch_pages,
            patch.object(
                coda_connector, "_export_page_content", return_value=mock_export_content
            ),
        ):
            # Simulate pagination: first call returns doc1 with nextPageToken,
            # second call returns doc2 without nextPageToken
            mock_fetch_docs.side_effect = [
                {"items": [doc1], "nextPageToken": "token-123"},
                {"items": [doc2]},
            ]

            def fetch_pages_side_effect(doc_id: str, page_token: str | None = None):
                if doc_id == "doc-1":
                    return {"items": [page1]}
                elif doc_id == "doc-2":
                    return {"items": [page2]}
                return {"items": []}

            mock_fetch_pages.side_effect = fetch_pages_side_effect

            start = datetime(2023, 1, 2, tzinfo=timezone.utc).timestamp()
            end = datetime(2023, 1, 3, tzinfo=timezone.utc).timestamp()

            batches = list(coda_connector.poll_source(start, end))

            # Should process both docs
            all_docs = [doc for batch in batches for doc in batch]
            assert len(all_docs) == 2

            # Verify _fetch_docs was called twice (pagination)
            assert mock_fetch_docs.call_count == 2

    def test_poll_source_handles_page_pagination(
        self,
        coda_connector: CodaConnector,
        create_mock_doc: Callable[..., dict[str, Any]],
        create_mock_page: Callable[..., dict[str, Any]],
        mock_export_content: str,
    ) -> None:
        """Test that poll_source handles paginated page responses"""
        doc = create_mock_doc(
            id="doc-1", name="Test Doc", updated="2023-01-02T12:00:00.000Z"
        )

        page1 = create_mock_page(
            id="page-1", name="Page 1", updated="2023-01-02T12:00:00.000Z"
        )
        page2 = create_mock_page(
            id="page-2", name="Page 2", updated="2023-01-02T12:00:00.000Z"
        )

        with (
            patch.object(coda_connector, "_fetch_docs") as mock_fetch_docs,
            patch.object(coda_connector, "_fetch_pages") as mock_fetch_pages,
            patch.object(
                coda_connector, "_export_page_content", return_value=mock_export_content
            ),
        ):
            mock_fetch_docs.return_value = {"items": [doc]}

            # Simulate page pagination
            mock_fetch_pages.side_effect = [
                {"items": [page1], "nextPageToken": "page-token-123"},
                {"items": [page2]},
            ]

            start = datetime(2023, 1, 2, tzinfo=timezone.utc).timestamp()
            end = datetime(2023, 1, 3, tzinfo=timezone.utc).timestamp()

            batches = list(coda_connector.poll_source(start, end))

            # Should process both pages
            all_docs = [doc for batch in batches for doc in batch]
            assert len(all_docs) == 2

            # Verify _fetch_pages was called twice (pagination)
            assert mock_fetch_pages.call_count == 2


class TestPollSourceEdgeCases:
    """Test suite for edge cases and special scenarios"""

    def test_poll_source_excludes_hidden_pages(
        self,
        coda_connector: CodaConnector,
        create_mock_doc: Callable[..., dict[str, Any]],
        create_mock_page: Callable[..., dict[str, Any]],
        mock_export_content: str,
    ) -> None:
        """Test that hidden pages are not yielded"""
        doc = create_mock_doc(
            id="doc-1", name="Test Doc", updated="2023-01-02T12:00:00.000Z"
        )

        visible_page = create_mock_page(
            id="page-visible",
            name="Visible Page",
            updated="2023-01-02T12:00:00.000Z",
            is_hidden=False,
        )
        hidden_page = create_mock_page(
            id="page-hidden",
            name="Hidden Page",
            updated="2023-01-02T12:00:00.000Z",
            is_hidden=True,
        )

        with (
            patch.object(coda_connector, "_fetch_docs") as mock_fetch_docs,
            patch.object(coda_connector, "_fetch_pages") as mock_fetch_pages,
            patch.object(
                coda_connector, "_export_page_content", return_value=mock_export_content
            ),
        ):
            mock_fetch_docs.return_value = {"items": [doc]}
            mock_fetch_pages.return_value = {"items": [visible_page, hidden_page]}

            start = datetime(2023, 1, 2, tzinfo=timezone.utc).timestamp()
            end = datetime(2023, 1, 3, tzinfo=timezone.utc).timestamp()

            batches = list(coda_connector.poll_source(start, end))

            # Should only yield the visible page
            all_docs = [doc for batch in batches for doc in batch]
            assert len(all_docs) == 1
            assert all_docs[0].metadata["page_id"] == "page-visible"

    def test_poll_source_skips_failed_exports(
        self,
        coda_connector: CodaConnector,
        create_mock_doc: Callable[..., dict[str, Any]],
        create_mock_page: Callable[..., dict[str, Any]],
        mock_export_content: str,
    ) -> None:
        """Test that pages with failed exports are skipped"""
        doc = create_mock_doc(
            id="doc-1", name="Test Doc", updated="2023-01-02T12:00:00.000Z"
        )

        page1 = create_mock_page(
            id="page-1", name="Page 1", updated="2023-01-02T12:00:00.000Z"
        )
        page2 = create_mock_page(
            id="page-2", name="Page 2", updated="2023-01-02T12:00:00.000Z"
        )

        with (
            patch.object(coda_connector, "_fetch_docs") as mock_fetch_docs,
            patch.object(coda_connector, "_fetch_pages") as mock_fetch_pages,
            patch.object(coda_connector, "_export_page_content") as mock_export,
        ):
            mock_fetch_docs.return_value = {"items": [doc]}
            mock_fetch_pages.return_value = {"items": [page1, page2]}

            # page-1 exports successfully, page-2 fails
            def export_side_effect(doc_id: str, page_id: str):
                if page_id == "page-1":
                    return mock_export_content
                return None  # Export failed

            mock_export.side_effect = export_side_effect

            start = datetime(2023, 1, 2, tzinfo=timezone.utc).timestamp()
            end = datetime(2023, 1, 3, tzinfo=timezone.utc).timestamp()

            batches = list(coda_connector.poll_source(start, end))

            # Should only yield page-1
            all_docs = [doc for batch in batches for doc in batch]
            assert len(all_docs) == 1
            assert all_docs[0].metadata["page_id"] == "page-1"

    def test_poll_source_skips_empty_content(
        self,
        coda_connector: CodaConnector,
        create_mock_doc: Callable[..., dict[str, Any]],
        create_mock_page: Callable[..., dict[str, Any]],
        mock_export_content: str,
    ) -> None:
        """Test that pages with empty content are skipped"""
        doc = create_mock_doc(
            id="doc-1", name="Test Doc", updated="2023-01-02T12:00:00.000Z"
        )

        page1 = create_mock_page(
            id="page-1", name="Page 1", updated="2023-01-02T12:00:00.000Z"
        )
        page2 = create_mock_page(
            id="page-2", name="Page 2", updated="2023-01-02T12:00:00.000Z"
        )

        with (
            patch.object(coda_connector, "_fetch_docs") as mock_fetch_docs,
            patch.object(coda_connector, "_fetch_pages") as mock_fetch_pages,
            patch.object(coda_connector, "_export_page_content") as mock_export,
        ):
            mock_fetch_docs.return_value = {"items": [doc]}
            mock_fetch_pages.return_value = {"items": [page1, page2]}

            # page-1 has content, page-2 is empty
            def export_side_effect(doc_id: str, page_id: str):
                if page_id == "page-1":
                    return mock_export_content
                return "   \n\n  "  # Empty/whitespace only

            mock_export.side_effect = export_side_effect

            start = datetime(2023, 1, 2, tzinfo=timezone.utc).timestamp()
            end = datetime(2023, 1, 3, tzinfo=timezone.utc).timestamp()

            batches = list(coda_connector.poll_source(start, end))

            # Should only yield page-1
            all_docs = [doc for batch in batches for doc in batch]
            assert len(all_docs) == 1
            assert all_docs[0].metadata["page_id"] == "page-1"

    def test_poll_source_document_structure(
        self,
        coda_connector: CodaConnector,
        create_mock_doc: Callable[..., dict[str, Any]],
        create_mock_page: Callable[..., dict[str, Any]],
        mock_export_content: str,
    ) -> None:
        """Test that yielded documents have correct structure and metadata"""
        doc = create_mock_doc(
            id="doc-1", name="Test Doc", updated="2023-01-02T12:00:00.000Z"
        )
        page = create_mock_page(
            id="page-1", name="Test Page", updated="2023-01-02T12:00:00.000Z"
        )

        with (
            patch.object(coda_connector, "_fetch_docs") as mock_fetch_docs,
            patch.object(coda_connector, "_fetch_pages") as mock_fetch_pages,
            patch.object(
                coda_connector, "_export_page_content", return_value=mock_export_content
            ),
        ):
            mock_fetch_docs.return_value = {"items": [doc]}
            mock_fetch_pages.return_value = {"items": [page]}

            start = datetime(2023, 1, 2, tzinfo=timezone.utc).timestamp()
            end = datetime(2023, 1, 3, tzinfo=timezone.utc).timestamp()

            batches = list(coda_connector.poll_source(start, end))

            assert len(batches) == 1
            assert len(batches[0]) == 1

            document = batches[0][0]

            # Verify document structure
            assert isinstance(document, Document)
            assert document.id == "doc-1:page-1"
            assert document.source == DocumentSource.CODA
            assert document.semantic_identifier == "Test Page"
            assert document.doc_updated_at is not None

            # Verify metadata
            assert document.metadata["doc_id"] == "doc-1"
            assert document.metadata["doc_name"] == "Test Doc"
            assert document.metadata["page_id"] == "page-1"
            assert "path" in document.metadata

            # Verify sections
            assert len(document.sections) > 0
            assert document.sections[0].text is not None
            assert len(document.sections[0].text) > 0
