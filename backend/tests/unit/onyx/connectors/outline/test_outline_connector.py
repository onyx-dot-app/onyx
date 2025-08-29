from datetime import datetime
from datetime import timezone
from unittest.mock import Mock
from unittest.mock import patch

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.outline.client import OutlineApiClient
from onyx.connectors.outline.client import OutlineClientAuthenticationError
from onyx.connectors.outline.connector import OutlineConnector


class TestOutlineConnector:
    """Unit tests for OutlineConnector"""

    def test_init(self) -> None:
        """Test connector initialization"""
        connector = OutlineConnector(batch_size=50)
        assert connector.batch_size == 50
        assert connector.outline_client is None

    def test_load_credentials_success(self) -> None:
        """Test successful credential loading"""
        with patch.object(OutlineApiClient, "get_collections") as mock_get_collections:
            mock_get_collections.return_value = {"data": []}

            connector = OutlineConnector()
            result = connector.load_credentials(
                {
                    "outline_base_url": "https://example.com",
                    "outline_api_token": "valid-token",
                }
            )

            assert result is None
            assert connector.outline_client is not None
            assert isinstance(connector.outline_client, OutlineApiClient)

    def test_load_credentials_missing_url(self) -> None:
        """Test loading credentials with missing base URL"""
        connector = OutlineConnector()

        with pytest.raises(ConnectorMissingCredentialError) as exc_info:
            connector.load_credentials({"outline_api_token": "token"})

        assert "outline_base_url" in str(exc_info.value)

    def test_load_credentials_missing_token(self) -> None:
        """Test loading credentials with missing API token"""
        connector = OutlineConnector()

        with pytest.raises(ConnectorMissingCredentialError) as exc_info:
            connector.load_credentials({"outline_base_url": "https://example.com"})

        assert "outline_api_token" in str(exc_info.value)

    def test_load_credentials_authentication_error(self) -> None:
        """Test credential loading with authentication error"""
        with patch.object(OutlineApiClient, "get_collections") as mock_get_collections:
            mock_get_collections.side_effect = OutlineClientAuthenticationError()

            connector = OutlineConnector()

            with pytest.raises(CredentialExpiredError):
                connector.load_credentials(
                    {
                        "outline_base_url": "https://example.com",
                        "outline_api_token": "invalid-token",
                    }
                )

    def test_validate_connector_settings_success(self) -> None:
        """Test successful connector validation"""
        connector = OutlineConnector()
        connector.outline_client = Mock(spec=OutlineApiClient)
        connector.outline_client.get_collections.return_value = {"data": []}

        # Should not raise any exception
        connector.validate_connector_settings()

    def test_validate_connector_settings_no_client(self) -> None:
        """Test connector validation without initialized client"""
        connector = OutlineConnector()

        with pytest.raises(
            ConnectorValidationError, match="Outline client not initialized"
        ):
            connector.validate_connector_settings()

    def test_collection_to_document(self) -> None:
        """Test conversion of collection to Onyx document"""
        connector = OutlineConnector()

        # Mock the outline_client
        mock_client = Mock()
        mock_client.base_url = "https://example.com"
        connector.outline_client = mock_client

        collection_data = {
            "id": "col123",
            "name": "Test Collection",
            "description": "A test collection",
            "slug": "test-collection",
            "updatedAt": "2023-12-01T10:00:00Z",
        }

        with patch(
            "onyx.connectors.cross_connector_utils.miscellaneous_utils.time_str_to_utc"
        ) as mock_time_str:
            mock_time_str.return_value = datetime(
                2023, 12, 1, 10, 0, 0, tzinfo=timezone.utc
            )

            document = connector._collection_to_document(collection_data)

            assert document.id == "outline_collection__col123"
            assert document.source == DocumentSource.OUTLINE
            assert document.title == "Test Collection"
            assert document.semantic_identifier == "Collection: Test Collection"
            assert len(document.sections) == 1
            assert document.sections[0].text == "Test Collection\n\nA test collection"
            assert document.metadata["type"] == "collection"
            assert document.metadata["collection_id"] == "col123"
            assert document.metadata["description"] == "A test collection"

    def test_document_to_onyx_document(self) -> None:
        """Test conversion of document to Onyx document"""
        connector = OutlineConnector()

        # Mock the outline_client
        mock_client = Mock()
        mock_client.base_url = "https://example.com"
        connector.outline_client = mock_client

        document_data = {
            "id": "doc123",
            "title": "Test Document",
            "text": "This is the document content",
            "urlId": "test-doc-slug",
            "updatedAt": "2023-12-01T11:00:00Z",
            "emoji": "📝",
        }

        collection_data = {
            "id": "col123",
            "name": "Test Collection",
            "slug": "test-collection",
        }

        with patch(
            "onyx.connectors.cross_connector_utils.miscellaneous_utils.time_str_to_utc"
        ) as mock_time_str:
            mock_time_str.return_value = datetime(
                2023, 12, 1, 11, 0, 0, tzinfo=timezone.utc
            )

            document = connector._document_to_onyx_document(
                document_data, collection_data
            )

            assert document.id == "outline_document__doc123"
            assert document.source == DocumentSource.OUTLINE
            assert document.title == "Test Document"
            assert document.semantic_identifier == "Document: Test Document"
            assert len(document.sections) == 1
            assert document.sections[0].text == "This is the document content"
            assert document.metadata["type"] == "document"
            assert document.metadata["collection_id"] == "col123"
            assert document.metadata["document_id"] == "doc123"
            assert document.metadata["emoji"] == "📝"

    def test_document_updated_in_range(self) -> None:
        """Test document time range filtering"""
        connector = OutlineConnector()

        # Create a mock document with update time
        document = Mock(spec=Document)
        mock_datetime = Mock()
        mock_datetime.timestamp.return_value = 1000.0
        document.doc_updated_at = mock_datetime

        # Test document within range
        assert connector._document_updated_in_range(document, 900.0, 1100.0) is True

        # Test document before range
        assert connector._document_updated_in_range(document, 1100.0, 1200.0) is False

        # Test document after range
        assert connector._document_updated_in_range(document, 800.0, 900.0) is False

        # Test with no time constraints
        assert connector._document_updated_in_range(document, None, None) is True

    def test_document_updated_in_range_no_update_time(self) -> None:
        """Test document filtering with no update time"""
        connector = OutlineConnector()

        document = Mock(spec=Document)
        document.doc_updated_at = None

        # Should include during full load (no start time)
        assert connector._document_updated_in_range(document, None, 1000.0) is True

        # Should exclude during polling (with start time)
        assert connector._document_updated_in_range(document, 900.0, 1000.0) is False

    def test_process_collection(self) -> None:
        """Test processing a collection with documents"""
        connector = OutlineConnector(batch_size=2)

        # Mock the client
        mock_client = Mock(spec=OutlineApiClient)
        connector.outline_client = mock_client

        # Mock collection data
        collection_data = {"id": "col123", "name": "Test Collection"}

        # Mock documents response - first call returns docs, second call returns empty to stop loop
        mock_client.get_collection_documents.side_effect = [
            {"data": [{"id": "doc1"}, {"id": "doc2"}]},
            {"data": []},  # Empty to stop the loop
        ]

        # Mock the conversion methods
        with patch.object(
            connector, "_collection_to_document"
        ) as mock_col_to_doc, patch.object(
            connector, "_document_to_onyx_document"
        ) as mock_doc_to_onyx, patch.object(
            connector, "_document_updated_in_range"
        ) as mock_in_range:

            mock_col_to_doc.return_value = Mock(spec=Document)
            mock_doc_to_onyx.side_effect = [Mock(spec=Document), Mock(spec=Document)]
            mock_in_range.return_value = True

            documents = list(connector._process_collection(collection_data))

            # Should return collection + 2 documents = 3 total
            assert len(documents) == 3
            # Should be called twice: once with docs, once returning empty to stop loop
            assert mock_client.get_collection_documents.call_count == 2

    def test_generate_documents_stream_integration(self) -> None:
        """Test the document stream generation flow with proper pagination termination"""
        connector = OutlineConnector(batch_size=1)

        # Mock the client
        mock_client = Mock(spec=OutlineApiClient)
        connector.outline_client = mock_client

        # Mock collections response - first call returns collections, second call returns empty to stop pagination
        mock_client.get_collections.side_effect = [
            {"data": [{"id": "col1", "name": "Collection 1"}]},
            {"data": []},  # Empty to stop pagination loop
        ]

        # Mock process_collection to return documents from the collection
        with patch.object(connector, "_process_collection") as mock_process:
            # Return 1 document per collection processed
            mock_documents = [Mock(spec=Document)]
            mock_process.return_value = iter(mock_documents)

            # Test the generator - should terminate naturally when collections are exhausted
            documents = []
            for doc in connector._generate_documents_stream():
                documents.append(doc)

            # Should generate exactly 1 document (from the 1 collection)
            assert len(documents) >= 1
            # Should process the collection we provided
            assert mock_process.call_count >= 1
            # Should call get_collections until it gets empty data
            assert mock_client.get_collections.call_count >= 1

    def test_yield_document_batches_integration(self) -> None:
        """Test the document batch yielding with mocked stream"""
        connector = OutlineConnector(batch_size=2)
        connector.outline_client = Mock(spec=OutlineApiClient)  # Initialize client

        # Mock the document stream generation
        with patch.object(
            connector, "_generate_documents_stream"
        ) as mock_generate_stream:
            mock_documents = [
                Mock(spec=Document),
                Mock(spec=Document),
                Mock(spec=Document),
            ]
            mock_generate_stream.return_value = iter(mock_documents)

            # Test the batch yielding
            batches = list(connector._yield_document_batches())

            # Should yield documents in batches of batch_size
            assert len(batches) == 2  # 2 documents in first batch, 1 in second
            assert len(batches[0]) == 2
            assert len(batches[1]) == 1

    def test_load_from_state(self) -> None:
        """Test load_from_state method"""
        connector = OutlineConnector()

        with patch.object(connector, "_yield_document_batches") as mock_yield_batches:
            mock_yield_batches.return_value = iter([[Mock(spec=Document)]])

            result = connector.load_from_state()

            # Should return a generator - verify it's iterable and callable
            assert hasattr(result, "__iter__")
            mock_yield_batches.assert_called_once_with()

    def test_poll_source(self) -> None:
        """Test poll_source method"""
        connector = OutlineConnector()

        with patch.object(connector, "_yield_document_batches") as mock_yield_batches:
            mock_yield_batches.return_value = iter([[Mock(spec=Document)]])

            result = connector.poll_source(100.0, 200.0)

            # Should return a generator - verify it's iterable and callable
            assert hasattr(result, "__iter__")
            mock_yield_batches.assert_called_once_with(100.0, 200.0)
