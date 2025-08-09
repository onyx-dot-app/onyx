import os
import time

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import Document
from onyx.connectors.outline.connector import OutlineConnector


@pytest.fixture
def outline_connector() -> OutlineConnector:
    """Create OutlineConnector with credentials from environment variables"""
    outline_base_url = os.environ.get("OUTLINE_BASE_URL")
    outline_api_token = os.environ.get("OUTLINE_API_TOKEN")

    if not outline_base_url or not outline_api_token:
        pytest.skip(
            "OUTLINE_BASE_URL and OUTLINE_API_TOKEN environment variables must be set"
        )

    connector = OutlineConnector(batch_size=10)
    connector.load_credentials(
        {
            "outline_base_url": outline_base_url,
            "outline_api_token": outline_api_token,
        }
    )
    return connector


def test_outline_connector_basic(outline_connector: OutlineConnector) -> None:
    """Test the OutlineConnector with a real Outline instance.

    This test requires the following environment variables:
    - OUTLINE_BASE_URL: The base URL of your Outline instance
    - OUTLINE_API_TOKEN: Valid API token for accessing Outline

    Example setup:
    export OUTLINE_BASE_URL="https://your-outline-instance.com"
    export OUTLINE_API_TOKEN="your-api-token-here"
    """
    # Validate connector settings
    outline_connector.validate_connector_settings()

    # Test full load
    documents: list[Document] = []
    for doc_batch in outline_connector.load_from_state():
        documents.extend(doc_batch)

    # Basic assertions
    assert len(documents) > 0, "Should find at least some documents"

    # Separate collections and documents for detailed testing
    collections = [doc for doc in documents if doc.metadata.get("type") == "collection"]
    docs = [doc for doc in documents if doc.metadata.get("type") == "document"]

    assert len(collections) > 0, "Should find at least one collection"

    # Test collection structure
    collection = collections[0]
    assert collection.id.startswith("outline_collection__")
    assert collection.source == DocumentSource.OUTLINE
    assert collection.title is not None
    assert len(collection.sections) == 1
    assert collection.sections[0].text is not None
    assert collection.metadata["type"] == "collection"
    assert "collection_id" in collection.metadata

    # Test document structure (if any documents exist)
    if docs:
        document = docs[0]
        assert document.id.startswith("outline_document__")
        assert document.source == DocumentSource.OUTLINE
        assert document.title is not None
        assert len(document.sections) == 1
        assert document.sections[0].text is not None
        assert document.metadata["type"] == "document"
        assert "collection_id" in document.metadata
        assert "document_id" in document.metadata

        # Verify link format
        section_link = document.sections[0].link
        assert section_link is not None
        assert "/doc/" in section_link

    # Test poll functionality (last 7 days to increase chance of finding updates)
    current_time = time.time()
    week_ago = current_time - 7 * 24 * 60 * 60

    poll_documents: list[Document] = []
    for doc_batch in outline_connector.poll_source(week_ago, current_time):
        poll_documents.extend(doc_batch)

    # Poll results should be subset of full load (or equal)
    assert len(poll_documents) <= len(documents)

    # If there are poll results, verify they have proper update times
    for doc in poll_documents:
        if doc.doc_updated_at is not None:
            assert doc.doc_updated_at.timestamp() >= week_ago
            assert doc.doc_updated_at.timestamp() <= current_time


def test_outline_connector_invalid_credentials() -> None:
    """Test connector behavior with invalid credentials"""
    from onyx.connectors.models import ConnectorMissingCredentialError
    from onyx.connectors.exceptions import CredentialExpiredError

    connector = OutlineConnector()

    # Test with missing credentials
    with pytest.raises(ConnectorMissingCredentialError):
        connector.load_credentials({})

    # Test with missing base URL
    with pytest.raises(ConnectorMissingCredentialError):
        connector.load_credentials({"outline_api_token": "some-token"})

    # Test with missing API token
    with pytest.raises(ConnectorMissingCredentialError):
        connector.load_credentials({"outline_base_url": "https://example.com"})

    # Test with invalid token (this will attempt real connection)
    with pytest.raises(
        (CredentialExpiredError, Exception)
    ):  # May vary based on response
        connector.load_credentials(
            {
                "outline_base_url": "https://httpbin.org",  # Valid URL that won't work with Outline
                "outline_api_token": "invalid-token",
            }
        )


def test_outline_connector_invalid_url() -> None:
    """Test connector behavior with invalid URL"""
    from onyx.connectors.exceptions import ConnectorValidationError

    connector = OutlineConnector()

    # Test with completely invalid URL format
    with pytest.raises(ConnectorValidationError, match="Invalid Outline base URL"):
        connector.load_credentials(
            {
                "outline_base_url": "http://",  # Invalid URL with no netloc
                "outline_api_token": "some-token",
            }
        )

    # Test with URL that passes validation but fails connection
    with pytest.raises(ConnectorValidationError):  # Connection should fail
        connector.load_credentials(
            {
                "outline_base_url": "https://not-a-valid-url.invalid",
                "outline_api_token": "some-token",
            }
        )
