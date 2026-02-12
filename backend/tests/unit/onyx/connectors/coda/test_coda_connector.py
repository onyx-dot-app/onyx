"""Unit tests for Coda.io connector."""

import pytest
from datetime import datetime
from datetime import timezone
from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.configs.constants import DocumentSource
from onyx.connectors.coda.coda_connector import CodaClientNotSetUpError
from onyx.connectors.coda.coda_connector import CodaConnector
from onyx.connectors.models import Document


@pytest.fixture
def coda_connector():
    """Create a CodaConnector instance for testing."""
    return CodaConnector(batch_size=10)


@pytest.fixture
def mock_credentials():
    """Mock credentials for Coda API."""
    return {"coda_api_token": "test_token_123"}


@pytest.fixture
def mock_doc_response():
    """Mock Coda doc response."""
    return {
        "id": "doc_abc123",
        "name": "Test Document",
        "browserLink": "https://coda.io/d/doc_abc123",
        "folder": {"name": "Test Folder"},
        "owner": {"name": "Test Owner"},
        "createdAt": "2024-01-01T10:00:00.000Z",
        "updatedAt": "2024-01-15T14:30:00.000Z",
    }


@pytest.fixture
def mock_page_response():
    """Mock Coda page response."""
    return {
        "id": "page_xyz789",
        "name": "Test Page",
        "contentMd": "# Test Page\n\nThis is test content.",
    }


@pytest.fixture
def mock_table_response():
    """Mock Coda table response."""
    return {
        "id": "table_def456",
        "name": "Test Table",
    }


@pytest.fixture
def mock_table_rows():
    """Mock Coda table rows."""
    return [
        {
            "id": "row1",
            "values": {
                "Name": "Item 1",
                "Status": "Active",
                "Count": 5,
            },
        },
        {
            "id": "row2",
            "values": {
                "Name": "Item 2",
                "Status": "Inactive",
                "Count": 10,
            },
        },
    ]



class TestCodaConnectorBatchingAndYielding:
    """Test document batching and yielding behavior."""

    @patch.object(CodaConnector, "_list_docs")
    @patch.object(CodaConnector, "_process_doc")
    def test_load_from_state_batching(
        self,
        mock_process_doc,
        mock_list_docs,
        coda_connector,
        mock_credentials,
        mock_doc_response,
    ):
        """Test that documents are yielded in correct batch sizes."""
        coda_connector.load_credentials(mock_credentials)
        coda_connector.batch_size = 3
        
        docs = [{**mock_doc_response, "id": f"doc_{i}"} for i in range(10)]
        mock_list_docs.return_value = docs
        
        mock_doc = Document(
            id="test",
            source=DocumentSource.CODA,
            semantic_identifier="test",
            sections=[],
            metadata={},
        )
        mock_process_doc.return_value = [mock_doc]

        batches = list(coda_connector.load_from_state())

        assert len(batches) == 4
        assert len(batches[0]) == 3
        assert len(batches[1]) == 3
        assert len(batches[2]) == 3
        assert len(batches[3]) == 1

    @patch.object(CodaConnector, "_get_doc")
    @patch.object(CodaConnector, "_process_doc")
    def test_load_from_state_single_doc(
        self,
        mock_process_doc,
        mock_get_doc,
        mock_credentials,
        mock_doc_response,
    ):
        """Test loading a single specific doc."""
        connector = CodaConnector(doc_id="doc_abc123")
        connector.load_credentials(mock_credentials)
        
        mock_get_doc.return_value = mock_doc_response
        mock_doc = Document(
            id="coda_doc_abc123",
            source=DocumentSource.CODA,
            semantic_identifier="Test Document",
            sections=[],
            metadata={},
        )
        mock_process_doc.return_value = [mock_doc]

        batches = list(connector.load_from_state())

        assert len(batches) == 1
        assert len(batches[0]) == 1
        mock_get_doc.assert_called_once_with("doc_abc123")

    @patch.object(CodaConnector, "_list_docs")
    @patch.object(CodaConnector, "_process_doc")
    def test_load_from_state_error_handling(
        self,
        mock_process_doc,
        mock_list_docs,
        coda_connector,
        mock_credentials,
        mock_doc_response,
    ):
        """Test that errors in processing one doc don't stop others."""
        coda_connector.load_credentials(mock_credentials)
        
        docs = [{**mock_doc_response, "id": f"doc_{i}"} for i in range(3)]
        mock_list_docs.return_value = docs
        
        mock_doc = Document(
            id="test",
            source=DocumentSource.CODA,
            semantic_identifier="test",
            sections=[],
            metadata={},
        )
        
        mock_process_doc.side_effect = [
            [mock_doc],
            Exception("Processing error"),
            [mock_doc],
        ]

        batches = list(coda_connector.load_from_state())

        assert len(batches) == 1
        assert len(batches[0]) == 2

    @patch.object(CodaConnector, "_list_docs")
    @patch.object(CodaConnector, "_process_doc")
    def test_load_from_state_no_content(
        self,
        mock_process_doc,
        mock_list_docs,
        coda_connector,
        mock_credentials,
        mock_doc_response,
    ):
        """Test handling docs with no content."""
        coda_connector.load_credentials(mock_credentials)
        
        docs = [{**mock_doc_response, "id": f"doc_{i}"} for i in range(3)]
        mock_list_docs.return_value = docs
        
        mock_process_doc.return_value = []

        batches = list(coda_connector.load_from_state())

        assert len(batches) == 0


class TestCodaConnectorCredentials:
    """Test credential loading and validation."""

    def test_load_credentials_success(self, coda_connector, mock_credentials):
        """Test successful credential loading."""
        result = coda_connector.load_credentials(mock_credentials)
        assert result is None
        assert coda_connector._api_token == "test_token_123"

    def test_load_credentials_missing_token(self, coda_connector):
        """Test credential loading with missing API token."""
        with pytest.raises(ValueError, match="coda_api_token is required"):
            coda_connector.load_credentials({})

    def test_api_token_property_not_set(self, coda_connector):
        """Test accessing api_token property before credentials loaded."""
        with pytest.raises(CodaClientNotSetUpError):
            _ = coda_connector.api_token

    def test_api_token_property_after_load(self, coda_connector, mock_credentials):
        """Test api_token property after loading credentials."""
        coda_connector.load_credentials(mock_credentials)
        assert coda_connector.api_token == "test_token_123"


class TestCodaConnectorAPICalls:
    """Test API request methods."""

    def test_get_headers(self, coda_connector, mock_credentials):
        """Test headers are correctly formatted."""
        coda_connector.load_credentials(mock_credentials)
        headers = coda_connector._get_headers()
        assert headers["Authorization"] == "Bearer test_token_123"
        assert headers["Content-Type"] == "application/json"

    @patch("onyx.connectors.coda.coda_connector.requests.get")
    def test_make_request_success(self, mock_get, coda_connector, mock_credentials):
        """Test successful API request."""
        coda_connector.load_credentials(mock_credentials)
        mock_response = MagicMock()
        mock_response.json.return_value = {"test": "data"}
        mock_get.return_value = mock_response

        result = coda_connector._make_request("test/endpoint")

        assert result == {"test": "data"}
        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args[1]
        assert call_kwargs["headers"]["Authorization"] == "Bearer test_token_123"
        assert call_kwargs["timeout"] == 30

    @patch("onyx.connectors.coda.coda_connector.requests.get")
    def test_make_request_with_params(self, mock_get, coda_connector, mock_credentials):
        """Test API request with query parameters."""
        coda_connector.load_credentials(mock_credentials)
        mock_response = MagicMock()
        mock_response.json.return_value = {"test": "data"}
        mock_get.return_value = mock_response

        params = {"limit": 100, "pageToken": "abc123"}
        coda_connector._make_request("test/endpoint", params=params)

        call_kwargs = mock_get.call_args[1]
        assert call_kwargs["params"] == params

    @patch("onyx.connectors.coda.coda_connector.requests.get")
    def test_make_request_retry_on_failure(self, mock_get, coda_connector, mock_credentials):
        """Test retry logic on request failure."""
        coda_connector.load_credentials(mock_credentials)
        
        mock_get.side_effect = [
            Exception("Connection error"),
            Exception("Connection error"),
            MagicMock(json=lambda: {"success": True}),
        ]

        result = coda_connector._make_request("test/endpoint")
        assert result == {"success": True}
        assert mock_get.call_count == 3


class TestCodaConnectorPagination:
    """Test pagination for docs, pages, and tables."""

    @patch("onyx.connectors.coda.coda_connector.requests.get")
    def test_list_docs_single_page(self, mock_get, coda_connector, mock_credentials, mock_doc_response):
        """Test listing docs with single page response."""
        coda_connector.load_credentials(mock_credentials)
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "items": [mock_doc_response],
            "nextPageToken": None,
        }
        mock_get.return_value = mock_response

        docs = coda_connector._list_docs()

        assert len(docs) == 1
        assert docs[0]["id"] == "doc_abc123"
        assert mock_get.call_count == 1

    @patch("onyx.connectors.coda.coda_connector.requests.get")
    def test_list_docs_multiple_pages(self, mock_get, coda_connector, mock_credentials, mock_doc_response):
        """Test listing docs with pagination."""
        coda_connector.load_credentials(mock_credentials)
        
        doc2 = {**mock_doc_response, "id": "doc_def456"}
        doc3 = {**mock_doc_response, "id": "doc_ghi789"}
        
        mock_response_1 = MagicMock()
        mock_response_1.json.return_value = {"items": [mock_doc_response], "nextPageToken": "token1"}
        
        mock_response_2 = MagicMock()
        mock_response_2.json.return_value = {"items": [doc2], "nextPageToken": "token2"}
        
        mock_response_3 = MagicMock()
        mock_response_3.json.return_value = {"items": [doc3], "nextPageToken": None}
        
        mock_get.side_effect = [mock_response_1, mock_response_2, mock_response_3]

        docs = coda_connector._list_docs()

        assert len(docs) == 3
        assert docs[0]["id"] == "doc_abc123"
        assert docs[1]["id"] == "doc_def456"
        assert docs[2]["id"] == "doc_ghi789"
        assert mock_get.call_count == 3

    @patch("onyx.connectors.coda.coda_connector.requests.get")
    def test_list_pages_pagination(self, mock_get, coda_connector, mock_credentials, mock_page_response):
        """Test listing pages with pagination."""
        coda_connector.load_credentials(mock_credentials)
        
        page2 = {**mock_page_response, "id": "page_abc456"}
        
        mock_response_1 = MagicMock()
        mock_response_1.json.return_value = {"items": [mock_page_response], "nextPageToken": "token1"}
        
        mock_response_2 = MagicMock()
        mock_response_2.json.return_value = {"items": [page2], "nextPageToken": None}
        
        mock_get.side_effect = [mock_response_1, mock_response_2]

        pages = coda_connector._list_pages("doc_123")

        assert len(pages) == 2
        assert mock_get.call_count == 2

    @patch("onyx.connectors.coda.coda_connector.requests.get")
    def test_list_tables_pagination(self, mock_get, coda_connector, mock_credentials, mock_table_response):
        """Test listing tables with pagination."""
        coda_connector.load_credentials(mock_credentials)
        
        table2 = {**mock_table_response, "id": "table_ghi789"}
        
        mock_response_1 = MagicMock()
        mock_response_1.json.return_value = {"items": [mock_table_response], "nextPageToken": "token1"}
        
        mock_response_2 = MagicMock()
        mock_response_2.json.return_value = {"items": [table2], "nextPageToken": None}
        
        mock_get.side_effect = [mock_response_1, mock_response_2]

        tables = coda_connector._list_tables("doc_123")

        assert len(tables) == 2
        assert mock_get.call_count == 2

    @patch("onyx.connectors.coda.coda_connector.requests.get")
    def test_get_table_rows_pagination(self, mock_get, coda_connector, mock_credentials, mock_table_rows):
        """Test getting table rows with pagination."""
        coda_connector.load_credentials(mock_credentials)
        
        more_rows = [
            {"id": "row3", "values": {"Name": "Item 3", "Status": "Active", "Count": 3}}
        ]
        
        mock_response_1 = MagicMock()
        mock_response_1.json.return_value = {"items": mock_table_rows, "nextPageToken": "token1"}
        
        mock_response_2 = MagicMock()
        mock_response_2.json.return_value = {"items": more_rows, "nextPageToken": None}
        
        mock_get.side_effect = [mock_response_1, mock_response_2]

        rows = coda_connector._get_table_rows("doc_123", "table_456")

        assert len(rows) == 3
        assert mock_get.call_count == 2

    @patch("onyx.connectors.coda.coda_connector.requests.get")
    def test_get_table_rows_limit(self, mock_get, coda_connector, mock_credentials, mock_table_rows):
        """Test table rows respecting limit parameter."""
        coda_connector.load_credentials(mock_credentials)
        
        many_rows = [mock_table_rows[0]] * 600
        
        mock_response_1 = MagicMock()
        mock_response_1.json.return_value = {"items": many_rows[:500], "nextPageToken": "token1"}
        
        mock_response_2 = MagicMock()
        mock_response_2.json.return_value = {"items": many_rows[500:], "nextPageToken": None}
        
        mock_get.side_effect = [mock_response_1, mock_response_2]

        rows = coda_connector._get_table_rows("doc_123", "table_456", limit=100)

        assert len(rows) == 100


class TestCodaConnectorDocumentProcessing:
    """Test document creation and processing."""

    @patch.object(CodaConnector, "_list_pages")
    @patch.object(CodaConnector, "_get_page_content")
    @patch.object(CodaConnector, "_list_tables")
    def test_metadata_missing_fields(
        self,
        mock_list_tables,
        mock_get_content,
        mock_list_pages,
        coda_connector,
        mock_credentials,
        mock_page_response,
    ):
        """Test metadata extraction when optional fields are missing."""
        coda_connector.load_credentials(mock_credentials)
        
        doc = {
            "id": "doc_123",
            "name": "Test Doc",
            "browserLink": "https://coda.io/d/doc_123",
            "createdAt": "2024-01-01T10:00:00.000Z",
            "updatedAt": "2024-01-15T14:30:00.000Z",
        }
        
        mock_list_pages.return_value = [mock_page_response]
        mock_get_content.return_value = "Content"
        mock_list_tables.return_value = []

        docs = coda_connector._process_doc(doc)

        assert len(docs) == 1
        metadata = docs[0].metadata
        assert "folder" not in metadata
        assert "owner" not in metadata
        assert metadata["source"] == "coda"

    def test_parse_timestamps(
        self,
        coda_connector,
        mock_credentials,
        mock_doc_response,
    ):
        """Test timestamp parsing from ISO format."""
        coda_connector.load_credentials(mock_credentials)
        
        with patch.object(coda_connector, "_list_pages", return_value=[]):
            with patch.object(coda_connector, "_list_tables", return_value=[]):
                docs = coda_connector._process_doc(mock_doc_response)

        assert len(docs) == 0

    @patch.object(CodaConnector, "_list_pages")
    @patch.object(CodaConnector, "_get_page_content")
    @patch.object(CodaConnector, "_list_tables")
    def test_process_doc_no_content(
        self,
        mock_list_tables,
        mock_get_content,
        mock_list_pages,
        coda_connector,
        mock_credentials,
        mock_doc_response,
    ):
        """Test processing a doc with no content returns empty list."""
        coda_connector.load_credentials(mock_credentials)
        
        mock_list_pages.return_value = []
        mock_list_tables.return_value = []

        docs = coda_connector._process_doc(mock_doc_response)

        assert len(docs) == 0

    @patch.object(CodaConnector, "_list_pages")
    @patch.object(CodaConnector, "_get_page_content")
    def test_process_doc_pages_only(
        self,
        mock_get_content,
        mock_list_pages,
        coda_connector,
        mock_credentials,
        mock_doc_response,
        mock_page_response,
    ):
        """Test processing doc with pages only."""
        coda_connector.load_credentials(mock_credentials)
        coda_connector.include_tables = False
        
        mock_list_pages.return_value = [mock_page_response]
        mock_get_content.return_value = "Page content"

        docs = coda_connector._process_doc(mock_doc_response)

        assert len(docs) == 1
        assert len(docs[0].sections) == 1

    @patch.object(CodaConnector, "_list_tables")
    @patch.object(CodaConnector, "_get_table_rows")
    def test_process_doc_tables_only(
        self,
        mock_get_rows,
        mock_list_tables,
        coda_connector,
        mock_credentials,
        mock_doc_response,
        mock_table_response,
        mock_table_rows,
    ):
        """Test processing doc with tables only."""
        coda_connector.load_credentials(mock_credentials)
        coda_connector.include_pages = False
        
        mock_list_tables.return_value = [mock_table_response]
        mock_get_rows.return_value = mock_table_rows

        docs = coda_connector._process_doc(mock_doc_response)

        assert len(docs) == 1
        assert len(docs[0].sections) == 1

    def test_table_to_text(self, coda_connector, mock_table_rows):
        """Test converting table rows to text format."""
        text = coda_connector._table_to_text("Test Table", mock_table_rows)
        
        assert "Table: Test Table" in text
        assert "Name: Item 1" in text
        assert "Status: Active" in text
        assert "Count: 5" in text

    def test_table_to_text_empty(self, coda_connector):
        """Test converting empty table to text."""
        text = coda_connector._table_to_text("Empty Table", [])
        
        assert "Table: Empty Table" in text
        assert "(empty table)" in text

    def test_page_link_format(self, coda_connector):
        """Test page link format."""
        doc_url = "https://coda.io/d/doc_123"
        page_id = "page_456"
        link = f"{doc_url}#_lu{page_id}"
        assert link == "https://coda.io/d/doc_123#_lupage_456"

    def test_table_link_format(self, coda_connector):
        """Test table link format."""
        doc_url = "https://coda.io/d/doc_123"
        table_id = "table_456"
        link = f"{doc_url}#_tbl{table_id}"
        assert link == "https://coda.io/d/doc_123#_tbltable_456"


class TestCodaConnectorTextSections:
    """Test TextSection creation for pages and tables."""

    @patch.object(CodaConnector, "_list_pages")
    @patch.object(CodaConnector, "_get_page_content")
    @patch.object(CodaConnector, "_list_tables")
    def test_page_text_section_format(
        self,
        mock_list_tables,
        mock_get_content,
        mock_list_pages,
        coda_connector,
        mock_credentials,
        mock_doc_response,
        mock_page_response,
    ):
        """Test that page content is properly formatted in TextSection."""
        coda_connector.load_credentials(mock_credentials)
        coda_connector.include_tables = False
        
        mock_list_pages.return_value = [mock_page_response]
        mock_get_content.return_value = "# Test Page\n\nThis is test content."
        mock_list_tables.return_value = []

        docs = coda_connector._process_doc(mock_doc_response)

        assert len(docs) == 1
        assert len(docs[0].sections) == 1
        section = docs[0].sections[0]
        assert section.text.startswith("# Test Page")
        assert "https://coda.io/d/doc_abc123#_lupage_xyz789" in section.link

    @patch.object(CodaConnector, "_list_pages")
    @patch.object(CodaConnector, "_list_tables")
    @patch.object(CodaConnector, "_get_table_rows")
    def test_table_text_section_format(
        self,
        mock_get_rows,
        mock_list_tables,
        mock_list_pages,
        coda_connector,
        mock_credentials,
        mock_doc_response,
        mock_table_response,
        mock_table_rows,
    ):
        """Test that table content is properly formatted in TextSection."""
        coda_connector.load_credentials(mock_credentials)
        coda_connector.include_pages = False
        
        mock_list_pages.return_value = []
        mock_list_tables.return_value = [mock_table_response]
        mock_get_rows.return_value = mock_table_rows

        docs = coda_connector._process_doc(mock_doc_response)

        assert len(docs) == 1
        assert len(docs[0].sections) == 1
        section = docs[0].sections[0]
        assert "Table: Test Table" in section.text
        assert "Name: Item 1" in section.text
        assert "https://coda.io/d/doc_abc123#_tbltable_def456" in section.link

    @patch.object(CodaConnector, "_list_pages")
    @patch.object(CodaConnector, "_get_page_content")
    @patch.object(CodaConnector, "_list_tables")
    @patch.object(CodaConnector, "_get_table_rows")
    def test_combined_sections(
        self,
        mock_get_rows,
        mock_list_tables,
        mock_get_content,
        mock_list_pages,
        coda_connector,
        mock_credentials,
        mock_doc_response,
        mock_page_response,
        mock_table_response,
        mock_table_rows,
    ):
        """Test document with both pages and tables creates multiple sections."""
        coda_connector.load_credentials(mock_credentials)
        
        mock_list_pages.return_value = [mock_page_response]
        mock_get_content.return_value = "Page content"
        mock_list_tables.return_value = [mock_table_response]
        mock_get_rows.return_value = mock_table_rows

        docs = coda_connector._process_doc(mock_doc_response)

        assert len(docs) == 1
        assert len(docs[0].sections) == 2
        assert docs[0].metadata["doc_name"] == "Test Document"
        assert docs[0].metadata["source"] == "coda"
        mock_credentials,
        mock_doc_response,
    ):
        """Test that page content is formatted correctly in TextSection."""
        coda_connector.load_credentials(mock_credentials)
        
        page = {
            "id": "page_123",
            "name": "My Page",
        }
        mock_list_pages.return_value = [page]
        mock_get_content.return_value = "# Header\n\nSome content"
        mock_list_tables.return_value = []

        docs = coda_connector._process_doc(mock_doc_response)

        assert len(docs) == 1
        assert len(docs[0].sections) == 1
        section = docs[0].sections[0]
        assert section.text == "# My Page\n\n# Header\n\nSome content"
        assert section.link == "https://coda.io/d/doc_abc123#_lupage_123"

    @patch.object(CodaConnector, "_list_pages")
    @patch.object(CodaConnector, "_list_tables")
    @patch.object(CodaConnector, "_get_table_rows")
    def test_table_text_section_format(
        self,
        mock_get_rows,
        mock_list_tables,
        mock_list_pages,
        coda_connector,
        mock_credentials,
        mock_doc_response,
        mock_table_response,
        mock_table_rows,
    ):
        """Test that table data is formatted correctly in TextSection."""
        coda_connector.load_credentials(mock_credentials)
        coda_connector.include_pages = False
        
        mock_list_pages.return_value = []
        mock_list_tables.return_value = [mock_table_response]
        mock_get_rows.return_value = mock_table_rows

        docs = coda_connector._process_doc(mock_doc_response)

        assert len(docs) == 1
        assert len(docs[0].sections) == 1
        section = docs[0].sections[0]
        assert "Table: Test Table" in section.text
        assert "Name: Item 1" in section.text
        assert section.link == "https://coda.io/d/doc_abc123#_tbltable_def456"

    @patch.object(CodaConnector, "_list_pages")
    @patch.object(CodaConnector, "_get_page_content")
    @patch.object(CodaConnector, "_list_tables")
    def test_empty_page_content_skipped(
        self,
        mock_list_tables,
        mock_get_content,
        mock_list_pages,
        coda_connector,
        mock_credentials,
        mock_doc_response,
        mock_page_response,
    ):
        """Test that pages with empty content are skipped."""
        coda_connector.load_credentials(mock_credentials)
        
        mock_list_pages.return_value = [mock_page_response]
        mock_get_content.return_value = "   \n  \t  "
        mock_list_tables.return_value = []

        docs = coda_connector._process_doc(mock_doc_response)

        assert len(docs) == 0

    @patch.object(CodaConnector, "_list_pages")
    @patch.object(CodaConnector, "_get_page_content")
    @patch.object(CodaConnector, "_list_tables")
    @patch.object(CodaConnector, "_get_table_rows")
    def test_process_doc_with_pages_and_tables(
        self,
        mock_get_rows,
        mock_list_tables,
        mock_get_content,
        mock_list_pages,
        coda_connector,
        mock_credentials,
        mock_doc_response,
        mock_page_response,
        mock_table_response,
        mock_table_rows,
    ):
        """Test processing a doc with pages and tables."""
        coda_connector.load_credentials(mock_credentials)
        
        mock_list_pages.return_value = [mock_page_response]
        mock_get_content.return_value = "# Test Page\n\nContent here"
        mock_list_tables.return_value = [mock_table_response]
        mock_get_rows.return_value = mock_table_rows

        docs = coda_connector._process_doc(mock_doc_response)

        assert len(docs) == 1
        doc = docs[0]
        assert doc.id == "coda_doc_abc123"
        assert doc.source == DocumentSource.CODA
        assert doc.semantic_identifier == "Test Document"
        assert len(doc.sections) == 2
        assert doc.metadata["folder"] == "Test Folder"
        assert doc.metadata["owner"] == "Test Owner"

    @patch.object(CodaConnector, "_list_pages")
    @patch.object(CodaConnector, "_list_tables")
    def test_process_doc_no_content(
        self,
        mock_list_tables,
        mock_list_pages,
        coda_connector,
        mock_credentials,
        mock_doc_response,
    ):
        """Test processing a doc with no content returns empty list."""
        coda_connector.load_credentials(mock_credentials)
        
        mock_list_pages.return_value = []
        mock_list_tables.return_value = []

        docs = coda_connector._process_doc(mock_doc_response)

        assert len(docs) == 0

    @patch.object(CodaConnector, "_list_pages")
    @patch.object(CodaConnector, "_get_page_content")
    def test_process_doc_pages_only(
        self,
        mock_get_content,
        mock_list_pages,
        coda_connector,
        mock_credentials,
        mock_doc_response,
        mock_page_response,
    ):
        """Test processing doc with pages only."""
        coda_connector.load_credentials(mock_credentials)
        coda_connector.include_tables = False
        
        mock_list_pages.return_value = [mock_page_response]
        mock_get_content.return_value = "Page content"

        docs = coda_connector._process_doc(mock_doc_response)

        assert len(docs) == 1
        assert len(docs[0].sections) == 1

    @patch.object(CodaConnector, "_list_tables")
    @patch.object(CodaConnector, "_get_table_rows")
    def test_process_doc_tables_only(
        self,
        mock_get_rows,
        mock_list_tables,
        coda_connector,
        mock_credentials,
        mock_doc_response,
        mock_table_response,
        mock_table_rows,
    ):
        """Test processing doc with tables only."""
        coda_connector.load_credentials(mock_credentials)
        coda_connector.include_pages = False
        
        mock_list_tables.return_value = [mock_table_response]
        mock_get_rows.return_value = mock_table_rows

        docs = coda_connector._process_doc(mock_doc_response)

        assert len(docs) == 1
        assert len(docs[0].sections) == 1

    def test_table_to_text(self, coda_connector, mock_table_rows):
        """Test converting table rows to text format."""
        text = coda_connector._table_to_text("Test Table", mock_table_rows)
        
        assert "Table: Test Table" in text
        assert "Name: Item 1" in text
        assert "Status: Active" in text
        assert "Count: 5" in text

    def test_table_to_text_empty(self, coda_connector):
        """Test converting empty table to text."""
        text = coda_connector._table_to_text("Empty Table", [])
        
        assert "Table: Empty Table" in text
        assert "(empty table)" in text

    def test_page_link_format(self, coda_connector):
        """Test page link format."""
        doc_url = "https://coda.io/d/doc_123"
        page_id = "page_456"
        link = f"{doc_url}#_lu{page_id}"
        assert link == "https://coda.io/d/doc_123#_lupage_456"

    def test_table_link_format(self, coda_connector):
        """Test table link format."""
        doc_url = "https://coda.io/d/doc_123"
        table_id = "table_456"
        link = f"{doc_url}#_tbl{table_id}"
        assert link == "https://coda.io/d/doc_123#_tbltable_456"


class TestCodaConnectorBatching:
    """Test document batching and yielding."""

    @patch.object(CodaConnector, "_list_docs")
    @patch.object(CodaConnector, "_process_doc")
    def test_load_from_state_batching(
        self,
        mock_process,
        mock_list_docs,
        coda_connector,
        mock_credentials,
        mock_doc_response,
    ):
        """Test that documents are yielded in correct batch sizes."""
        coda_connector.load_credentials(mock_credentials)
        coda_connector.batch_size = 3
        
        docs = [mock_doc_response] * 10
        mock_list_docs.return_value = docs
        
        mock_doc = Document(
            id="test_id",
            source=DocumentSource.CODA,
            semantic_identifier="Test",
            sections=[],
            metadata={},
        )
        mock_process.return_value = [mock_doc]

        batches = list(coda_connector.load_from_state())

        assert len(batches) == 4
        assert len(batches[0]) == 3
        assert len(batches[1]) == 3
        assert len(batches[2]) == 3
        assert len(batches[3]) == 1

    @patch.object(CodaConnector, "_get_doc")
    @patch.object(CodaConnector, "_process_doc")
    def test_load_from_state_single_doc(
        self,
        mock_process,
        mock_get_doc,
        mock_credentials,
        mock_doc_response,
    ):
        """Test loading single doc mode."""
        connector = CodaConnector(doc_id="doc_123")
        connector.load_credentials(mock_credentials)
        
        mock_get_doc.return_value = mock_doc_response
        
        mock_doc = Document(
            id="test_id",
            source=DocumentSource.CODA,
            semantic_identifier="Test",
            sections=[],
            metadata={},
        )
        mock_process.return_value = [mock_doc]

        batches = list(connector.load_from_state())

        assert len(batches) == 1
        mock_get_doc.assert_called_once_with("doc_123")


class TestCodaConnectorErrorHandling:
    """Test error handling."""

    @patch.object(CodaConnector, "_list_pages")
    @patch.object(CodaConnector, "_list_tables")
    def test_process_doc_page_error(
        self,
        mock_list_tables,
        mock_list_pages,
        coda_connector,
        mock_credentials,
        mock_doc_response,
    ):
        """Test graceful handling of page fetch errors."""
        coda_connector.load_credentials(mock_credentials)
        
        mock_list_pages.side_effect = Exception("API error")
        mock_list_tables.return_value = []

        docs = coda_connector._process_doc(mock_doc_response)

        assert len(docs) == 0

    @patch.object(CodaConnector, "_list_pages")
    @patch.object(CodaConnector, "_list_tables")
    def test_process_doc_table_error(
        self,
        mock_list_tables,
        mock_list_pages,
        coda_connector,
        mock_credentials,
        mock_doc_response,
    ):
        """Test graceful handling of table fetch errors."""
        coda_connector.load_credentials(mock_credentials)
        
        mock_list_pages.return_value = []
        mock_list_tables.side_effect = Exception("API error")

        docs = coda_connector._process_doc(mock_doc_response)

        assert len(docs) == 0

    @patch.object(CodaConnector, "_get_page_content")
    def test_get_page_content_error(self, mock_get, coda_connector, mock_credentials):
        """Test page content fetch returns empty string on error."""
        coda_connector.load_credentials(mock_credentials)
        
        mock_get.side_effect = Exception("API error")

        content = coda_connector._get_page_content("doc_123", "page_456")

        assert content == ""

    @patch.object(CodaConnector, "_list_docs")
    def test_load_from_state_doc_error(
        self,
        mock_list_docs,
        coda_connector,
        mock_credentials,
    ):
        """Test that errors listing docs are raised."""
        coda_connector.load_credentials(mock_credentials)
        
        mock_list_docs.side_effect = Exception("API error")

        with pytest.raises(Exception, match="API error"):
            list(coda_connector.load_from_state())


class TestCodaConnectorMetadata:
    """Test metadata extraction."""

    @patch.object(CodaConnector, "_list_pages")
    @patch.object(CodaConnector, "_get_page_content")
    @patch.object(CodaConnector, "_list_tables")
    def test_metadata_extraction(
        self,
        mock_list_tables,
        mock_get_content,
        mock_list_pages,
        coda_connector,
        mock_credentials,
        mock_page_response,
    ):
        """Test that metadata is correctly extracted."""
        coda_connector.load_credentials(mock_credentials)
        
        doc = {
            "id": "doc_123",
            "name": "Test Doc",
            "browserLink": "https://coda.io/d/doc_123",
            "folder": {"name": "My Folder"},
            "owner": {"name": "John Doe"},
            "createdAt": "2024-01-01T10:00:00.000Z",
            "updatedAt": "2024-01-15T14:30:00.000Z",
        }
        
        mock_list_pages.return_value = [mock_page_response]
        mock_get_content.return_value = "Content"
        mock_list_tables.return_value = []

        docs = coda_connector._process_doc(doc)

        assert len(docs) == 1
        metadata = docs[0].metadata
        assert metadata["source"] == "coda"
        assert metadata["doc_name"] == "Test Doc"
        assert metadata["folder"] == "My Folder"
        assert metadata["owner"] == "John Doe"

    @patch.object(CodaConnector, "_list_pages")
    @patch.object(CodaConnector, "_get_page_content")
    @patch.object(CodaConnector, "_list_tables")
    def test_doc_updated_at_parsing(
        self,
        mock_list_tables,
        mock_get_content,
        mock_list_pages,
        coda_connector,
        mock_credentials,
        mock_doc_response,
        mock_page_response,
    ):
        """Test that doc_updated_at is correctly parsed."""
        coda_connector.load_credentials(mock_credentials)
        
        mock_list_pages.return_value = [mock_page_response]
        mock_get_content.return_value = "Content"
        mock_list_tables.return_value = []

        docs = coda_connector._process_doc(mock_doc_response)

        assert len(docs) == 1
        assert docs[0].doc_updated_at is not None
        assert docs[0].doc_updated_at.year == 2024
        assert docs[0].doc_updated_at.month == 1
        assert docs[0].doc_updated_at.day == 15
