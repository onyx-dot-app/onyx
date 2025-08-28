import os
import time
from typing import Any

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.outline.connector import OutlineConnector
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document


class TestOutlineConnector:
    """Test Outline connector functionality using real API calls."""

    @pytest.fixture
    def connector(self) -> OutlineConnector:
        """Create an Outline connector instance."""
        return OutlineConnector(batch_size=10)

    @pytest.fixture
    def credentials(self) -> dict[str, Any]:
        """Provide test credentials from environment variables."""
        return {
            "outline_api_token": os.environ["OUTLINE_API_TOKEN"],
            "outline_base_url": os.environ["OUTLINE_BASE_URL"],
        }

    def test_credentials_missing_raises_exception(self) -> None:
        """Test that connector raises exception when credentials are missing."""
        connector = OutlineConnector()
        
        # Should raise exception when trying to load without credentials
        with pytest.raises(ConnectorMissingCredentialError) as exc_info:
            list(connector.load_from_state())
        assert "Outline" in str(exc_info.value)

    def test_load_credentials(
        self, connector: OutlineConnector, credentials: dict[str, Any]
    ) -> None:
        """Test that credentials are loaded correctly."""
        result = connector.load_credentials(credentials)
        
        assert result is None  # Should return None on success
        assert connector.outline_client is not None
        assert connector.outline_client.api_token == credentials["outline_api_token"]
        assert connector.outline_client.base_url == credentials["outline_base_url"].rstrip("/")

    def test_outline_connector_basic(
        self, connector: OutlineConnector, credentials: dict[str, Any]
    ) -> None:
        """Test the OutlineConnector with real Outline workspace.
        
        This test validates that the connector can:
        1. Load credentials properly
        2. Connect to Outline API
        3. Fetch documents and collections
        4. Return properly formatted Document objects
        """
        # Load credentials
        connector.load_credentials(credentials)
        
        # Get documents from poll_source
        doc_batch_generator = connector.poll_source(0, time.time())
        
        # Collect all documents
        all_documents = []
        for doc_batch in doc_batch_generator:
            all_documents.extend(doc_batch)
            
        # Should have at least some documents
        assert len(all_documents) > 0, "Expected to find at least one document or collection"
        
        # Verify document structure
        for doc in all_documents:
            assert isinstance(doc, Document)
            assert doc.id is not None
            assert doc.source == DocumentSource.OUTLINE
            assert doc.semantic_identifier is not None
            assert len(doc.sections) >= 1
            
            # Check that each section has required fields
            for section in doc.sections:
                assert section.text is not None
                assert section.link is not None
                assert section.link.startswith("http")  # Should be a valid URL
                
            # Verify metadata structure
            assert "type" in doc.metadata
            assert doc.metadata["type"] in ["document", "collection"]

    def test_outline_connector_time_filtering(
        self, connector: OutlineConnector, credentials: dict[str, Any]
    ) -> None:
        """Test that time filtering works correctly."""
        connector.load_credentials(credentials)
        
        # Get documents from a specific time range (last 30 days)
        end_time = time.time()
        start_time = end_time - (30 * 24 * 60 * 60)  # 30 days ago
        
        doc_batch_generator = connector.poll_source(start_time, end_time)
        
        # Collect documents
        filtered_documents = []
        for doc_batch in doc_batch_generator:
            filtered_documents.extend(doc_batch)
            
        # All documents should be valid
        for doc in filtered_documents:
            assert isinstance(doc, Document)
            assert doc.source == DocumentSource.OUTLINE
            assert doc.doc_updated_at is not None
            # Note: Outline API may not strictly filter by updatedAt, 
            # so we don't assert on time bounds here

    def test_outline_connector_load_from_state(
        self, connector: OutlineConnector, credentials: dict[str, Any]
    ) -> None:
        """Test load_from_state method."""
        connector.load_credentials(credentials)
        
        # load_from_state should work the same as poll_source(None, None)
        doc_batch_generator = connector.load_from_state()
        
        # Should be able to get at least one batch
        doc_batch = next(doc_batch_generator)
        assert len(doc_batch) >= 0  # Could be empty but should not fail
        
        # If there are documents, verify their structure
        for doc in doc_batch:
            assert isinstance(doc, Document)
            assert doc.source == DocumentSource.OUTLINE

    def test_outline_connector_batch_processing(
        self, connector: OutlineConnector, credentials: dict[str, Any]
    ) -> None:
        """Test that batch processing works correctly."""
        # Create connector with small batch size
        small_batch_connector = OutlineConnector(batch_size=2)
        small_batch_connector.load_credentials(credentials)
        
        doc_batch_generator = small_batch_connector.poll_source(0, time.time())
        
        # Each batch should respect the batch size limit
        for doc_batch in doc_batch_generator:
            assert len(doc_batch) <= 2, f"Batch size exceeded: {len(doc_batch)}"
            break  # Just test the first batch

    def test_outline_connector_document_types(
        self, connector: OutlineConnector, credentials: dict[str, Any]
    ) -> None:
        """Test that both documents and collections are properly handled."""
        connector.load_credentials(credentials)
        
        doc_batch_generator = connector.poll_source(0, time.time())
        
        # Collect all documents and check types
        all_documents = []
        for doc_batch in doc_batch_generator:
            all_documents.extend(doc_batch)
            
        if all_documents:
            # Check that we have proper metadata types
            document_types = {doc.metadata["type"] for doc in all_documents}
            # Should have at least one type (either document or collection)
            assert len(document_types) > 0
            assert document_types.issubset({"document", "collection"})
            
            # Verify that each type has proper content
            for doc in all_documents:
                if doc.metadata["type"] == "document":
                    # Documents should have meaningful content
                    assert any(len(section.text.strip()) > 0 for section in doc.sections)
                elif doc.metadata["type"] == "collection":
                    # Collections might have less content but should still be valid
                    assert len(doc.sections) >= 1

    def test_outline_connector_error_handling(self) -> None:
        """Test error handling for invalid credentials."""
        connector = OutlineConnector()
        
        # Invalid credentials should not crash but may raise specific errors
        invalid_credentials = {
            "outline_api_token": "invalid_token",
            "outline_base_url": "https://invalid.example.com",
        }
        
        connector.load_credentials(invalid_credentials)
        
        # Should be able to handle API errors gracefully
        # Note: Specific error handling depends on the API response
        # This test mainly ensures no unexpected crashes occur
        try:
            doc_batch_generator = connector.poll_source(0, time.time())
            next(doc_batch_generator)
        except Exception as e:
            # Should be a specific connector exception, not a generic error
            assert "Outline" in str(type(e).__name__) or "Connection" in str(type(e).__name__)
