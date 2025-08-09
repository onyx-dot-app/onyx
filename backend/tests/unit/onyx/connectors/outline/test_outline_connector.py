import datetime
from unittest.mock import Mock, patch

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.outline.client import OutlineApiClient
from onyx.connectors.outline.client import OutlineClientRequestFailedError
from onyx.connectors.outline.connector import OutlineConnector


@pytest.fixture
def outline_connector():
    """Create an OutlineConnector instance for testing."""
    return OutlineConnector(batch_size=10)


@pytest.fixture
def mock_outline_client():
    """Create a mock OutlineApiClient."""
    return Mock(spec=OutlineApiClient)


@pytest.fixture
def sample_collection():
    """Sample collection data from Outline API."""
    return {
        "id": "collection-123",
        "urlId": "test-collection",
        "name": "Test Collection",
        "description": "A test collection for unit tests",
        "updatedAt": "2024-01-15T10:30:00Z",
    }


@pytest.fixture
def sample_document():
    """Sample document data from Outline API."""
    return {
        "id": "document-456",
        "urlId": "test-document",
        "title": "Test Document",
        "text": "# Test Document\n\nThis is a test document with some content.",
        "collectionId": "collection-123",
        "updatedAt": "2024-01-15T11:00:00Z",
    }


class TestOutlineConnector:
    def test_load_credentials(self, outline_connector):
        """Test loading credentials."""
        credentials = {
            "outline_base_url": "https://test.getoutline.com",
            "outline_api_token": "test-token-123",
        }
        
        result = outline_connector.load_credentials(credentials)
        
        assert result is None
        assert outline_connector.outline_client is not None
        assert outline_connector.outline_client.base_url == "https://test.getoutline.com"
        assert outline_connector.outline_client.api_token == "test-token-123"

    def test_collection_to_document(self, sample_collection):
        """Test converting a collection to a Document."""
        mock_client = Mock()
        mock_client.build_app_url.return_value = "https://test.getoutline.com/collection/test-collection"
        
        document = OutlineConnector._collection_to_document(mock_client, sample_collection)
        
        assert isinstance(document, Document)
        assert document.id == "collection__collection-123"
        assert document.source == DocumentSource.OUTLINE
        assert document.semantic_identifier == "Collection: Test Collection"
        assert document.title == "Test Collection"
        assert len(document.sections) == 1
        assert document.sections[0].link == "https://test.getoutline.com/collection/test-collection"
        assert "Test Collection" in document.sections[0].text
        assert "A test collection for unit tests" in document.sections[0].text
        assert document.metadata == {"type": "collection"}
        assert document.doc_updated_at is not None

    def test_document_to_document(self, sample_document):
        """Test converting a document to a Document."""
        mock_client = Mock()
        mock_client.build_app_url.return_value = "https://test.getoutline.com/doc/test-document"
        
        document = OutlineConnector._document_to_document(mock_client, sample_document)
        
        assert isinstance(document, Document)
        assert document.id == "document__document-456"
        assert document.source == DocumentSource.OUTLINE
        assert document.semantic_identifier == "Document: Test Document"
        assert document.title == "Test Document"
        assert len(document.sections) == 1
        assert document.sections[0].link == "https://test.getoutline.com/doc/test-document"
        assert "Test Document" in document.sections[0].text
        assert document.metadata == {"type": "document", "collection_id": "collection-123"}
        assert document.doc_updated_at is not None

    def test_load_from_state_missing_credentials(self, outline_connector):
        """Test load_from_state raises error when credentials are missing."""
        with pytest.raises(ConnectorMissingCredentialError):
            list(outline_connector.load_from_state())

    def test_poll_source_missing_credentials(self, outline_connector):
        """Test poll_source raises error when credentials are missing."""
        with pytest.raises(ConnectorMissingCredentialError):
            list(outline_connector.poll_source(None, None))

    @patch('onyx.connectors.outline.connector.time.sleep')
    def test_poll_source_success(self, mock_sleep, outline_connector, mock_outline_client, 
                                 sample_collection, sample_document):
        """Test successful polling of source."""
        outline_connector.outline_client = mock_outline_client
        
        # Mock API responses
        mock_outline_client.post.side_effect = [
            {"data": [sample_collection]},  # collections.list response
            {"data": []},  # collections.list empty response (end of pagination)
            {"data": [sample_document]},  # documents.list response
            {"data": []},  # documents.list empty response (end of pagination)
        ]
        mock_outline_client.build_app_url.side_effect = [
            "https://test.getoutline.com/collection/test-collection",
            "https://test.getoutline.com/doc/test-document",
        ]
        
        documents = list(outline_connector.poll_source(None, None))
        
        assert len(documents) == 2  # Two batches: collections and documents
        assert len(documents[0]) == 1  # One collection
        assert len(documents[1]) == 1  # One document
        
        # Verify collection document
        collection_doc = documents[0][0]
        assert collection_doc.id == "collection__collection-123"
        assert collection_doc.semantic_identifier == "Collection: Test Collection"
        
        # Verify document
        document_doc = documents[1][0]
        assert document_doc.id == "document__document-456"
        assert document_doc.semantic_identifier == "Document: Test Document"

    def test_validate_connector_settings_missing_client(self, outline_connector):
        """Test validation fails when client is missing."""
        with pytest.raises(ConnectorMissingCredentialError):
            outline_connector.validate_connector_settings()

    def test_validate_connector_settings_success(self, outline_connector, mock_outline_client):
        """Test successful validation."""
        outline_connector.outline_client = mock_outline_client
        mock_outline_client.post.return_value = {"data": {"user": {"id": "user-123"}}}
        
        # Should not raise any exception
        outline_connector.validate_connector_settings()
        
        mock_outline_client.post.assert_called_once_with("auth.info")

    def test_validate_connector_settings_401_error(self, outline_connector, mock_outline_client):
        """Test validation handles 401 error."""
        outline_connector.outline_client = mock_outline_client
        mock_outline_client.post.side_effect = OutlineClientRequestFailedError(401, "Unauthorized")
        
        with pytest.raises(CredentialExpiredError):
            outline_connector.validate_connector_settings()

    def test_validate_connector_settings_403_error(self, outline_connector, mock_outline_client):
        """Test validation handles 403 error."""
        outline_connector.outline_client = mock_outline_client
        mock_outline_client.post.side_effect = OutlineClientRequestFailedError(403, "Forbidden")
        
        with pytest.raises(InsufficientPermissionsError):
            outline_connector.validate_connector_settings()

    def test_validate_connector_settings_other_error(self, outline_connector, mock_outline_client):
        """Test validation handles other HTTP errors."""
        outline_connector.outline_client = mock_outline_client
        mock_outline_client.post.side_effect = OutlineClientRequestFailedError(500, "Server Error")
        
        with pytest.raises(ConnectorValidationError):
            outline_connector.validate_connector_settings()

    def test_validate_connector_settings_unexpected_error(self, outline_connector, mock_outline_client):
        """Test validation handles unexpected errors."""
        outline_connector.outline_client = mock_outline_client
        mock_outline_client.post.side_effect = Exception("Unexpected error")
        
        with pytest.raises(ConnectorValidationError):
            outline_connector.validate_connector_settings()


class TestOutlineApiClient:
    def test_init(self):
        """Test OutlineApiClient initialization."""
        client = OutlineApiClient("https://test.getoutline.com", "test-token")
        
        assert client.base_url == "https://test.getoutline.com"
        assert client.api_token == "test-token"

    def test_build_url(self):
        """Test URL building."""
        client = OutlineApiClient("https://test.getoutline.com/", "test-token")
        
        url = client._build_url("/collections.list")
        assert url == "https://test.getoutline.com/api/collections.list"
        
        url = client._build_url("documents.info")
        assert url == "https://test.getoutline.com/api/documents.info"

    def test_build_app_url(self):
        """Test app URL building."""
        client = OutlineApiClient("https://test.getoutline.com", "test-token")
        
        url = client.build_app_url("/collection/test")
        assert url == "https://test.getoutline.com/collection/test"
        
        url = client.build_app_url("doc/test-doc")
        assert url == "https://test.getoutline.com/doc/test-doc"

    def test_build_headers(self):
        """Test header building."""
        client = OutlineApiClient("https://test.getoutline.com", "test-token")
        
        headers = client._build_headers()
        
        assert headers["Authorization"] == "Bearer test-token"
        assert headers["Content-Type"] == "application/json"
        assert headers["Accept"] == "application/json"

    @patch('onyx.connectors.outline.client.requests.post')
    def test_post_success(self, mock_post):
        """Test successful POST request."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"test": "value"}}
        mock_post.return_value = mock_response
        
        client = OutlineApiClient("https://test.getoutline.com", "test-token")
        result = client.post("collections.list", {"limit": 10})
        
        assert result == {"data": {"test": "value"}}
        mock_post.assert_called_once()

    @patch('onyx.connectors.outline.client.requests.post')
    def test_post_error(self, mock_post):
        """Test POST request with error."""
        mock_response = Mock()
        mock_response.status_code = 400
        mock_response.reason = "Bad Request"
        mock_response.json.return_value = {"error": "Invalid request"}
        mock_post.return_value = mock_response
        
        client = OutlineApiClient("https://test.getoutline.com", "test-token")
        
        with pytest.raises(OutlineClientRequestFailedError) as exc_info:
            client.post("collections.list")
        
        assert exc_info.value.status_code == 400
        assert "Invalid request" in str(exc_info.value)
