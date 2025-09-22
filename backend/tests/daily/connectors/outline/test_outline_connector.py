import os
import time
from typing import Any

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.outline.connector import OutlineConnector


class TestOutlineConnector:
    """Comprehensive test suite for the OutlineConnector."""

    @pytest.fixture
    def connector(self) -> OutlineConnector:
        """Create an Outline connector instance."""
        return OutlineConnector(batch_size=10)

    @pytest.fixture
    def credentials(self) -> dict[str, Any]:
        """Provide test credentials from environment variables."""
        outline_base_url = os.environ.get("OUTLINE_BASE_URL")
        outline_api_token = os.environ.get("OUTLINE_API_TOKEN")

        if not outline_base_url or not outline_api_token:
            pytest.skip(
                "OUTLINE_BASE_URL and OUTLINE_API_TOKEN environment variables must be set"
            )

        return {
            "outline_api_token": outline_api_token,
            "outline_base_url": outline_base_url,
        }

    def test_credentials_missing_raises_exception(self) -> None:
        """Should raise if credentials are missing."""
        connector = OutlineConnector()

        with pytest.raises(ConnectorMissingCredentialError) as exc_info:
            list(connector.load_from_state())
        assert "Outline" in str(exc_info.value)

    def test_load_credentials(
        self, connector: OutlineConnector, credentials: dict[str, Any]
    ) -> None:
        """Credentials should load correctly."""
        result = connector.load_credentials(credentials)

        assert result is None
        assert connector.outline_client is not None
        assert connector.outline_client.api_token == credentials["outline_api_token"]
        assert connector.outline_client.base_url == credentials[
            "outline_base_url"
        ].rstrip("/")

    def test_outline_connector_basic(
        self, connector: OutlineConnector, credentials: dict[str, Any]
    ) -> None:
        """Validate that connector fetches and structures documents properly."""
        connector.load_credentials(credentials)

        documents: list[Document] = []
        for batch in connector.load_from_state():
            documents.extend(batch)

        assert len(documents) > 0, "Expected at least one document/collection"

        collections = [d for d in documents if d.metadata.get("type") == "collection"]
        docs = [d for d in documents if d.metadata.get("type") == "document"]

        assert len(collections) > 0, "Should find at least one collection"

        collection = collections[0]
        assert collection.id.startswith("outline_collection__")
        assert collection.source == DocumentSource.OUTLINE
        assert collection.title is not None
        assert len(collection.sections) == 1
        assert collection.sections[0].text is not None
        assert collection.metadata["type"] == "collection"

        if docs:
            document = docs[0]
            assert document.id.startswith("outline_document__")
            assert document.source == DocumentSource.OUTLINE
            assert document.title is not None
            assert len(document.sections) == 1
            assert document.sections[0].text is not None
            assert document.metadata["type"] == "document"

            section_link = document.sections[0].link
            assert section_link is not None
            assert "/doc/" in section_link

    def test_outline_connector_time_filtering(
        self, connector: OutlineConnector, credentials: dict[str, Any]
    ) -> None:
        """Validate poll_source with time range filtering."""
        connector.load_credentials(credentials)

        end_time = time.time()
        start_time = end_time - 30 * 24 * 60 * 60

        docs: list[Document] = []
        for batch in connector.poll_source(start_time, end_time):
            docs.extend(batch)

        for doc in docs:
            assert isinstance(doc, Document)
            assert doc.source == DocumentSource.OUTLINE
            if doc.doc_updated_at:
                assert start_time <= doc.doc_updated_at.timestamp() <= end_time

    def test_outline_connector_load_from_state(
        self, connector: OutlineConnector, credentials: dict[str, Any]
    ) -> None:
        """load_from_state should fetch documents."""
        connector.load_credentials(credentials)

        gen = connector.load_from_state()
        batch = next(gen)
        assert isinstance(batch, list)

        for doc in batch:
            assert isinstance(doc, Document)
            assert doc.source == DocumentSource.OUTLINE

    def test_outline_connector_batch_processing(
        self, credentials: dict[str, Any]
    ) -> None:
        """Connector should respect batch size."""
        small_batch_connector = OutlineConnector(batch_size=2)
        small_batch_connector.load_credentials(credentials)

        for batch in small_batch_connector.poll_source(0, time.time()):
            assert len(batch) <= 2
            break

    def test_outline_connector_document_types(
        self, connector: OutlineConnector, credentials: dict[str, Any]
    ) -> None:
        """Validate metadata for collections and documents."""
        connector.load_credentials(credentials)

        docs: list[Document] = []
        for batch in connector.poll_source(0, time.time()):
            docs.extend(batch)

        if docs:
            doc_types = {d.metadata["type"] for d in docs}
            assert doc_types.issubset({"document", "collection"})

            for doc in docs:
                if doc.metadata["type"] == "document":
                    assert any(
                        (s.text.strip() if s.text else None) for s in doc.sections
                    )
                elif doc.metadata["type"] == "collection":
                    assert len(doc.sections) >= 1

    def test_outline_connector_invalid_credentials(self) -> None:
        """Should raise with invalid/missing credentials."""
        connector = OutlineConnector()

        # Missing everything
        with pytest.raises(ConnectorMissingCredentialError):
            connector.load_credentials({})

        # Missing base URL
        with pytest.raises(ConnectorMissingCredentialError):
            connector.load_credentials({"outline_api_token": "token"})

        # Missing token
        with pytest.raises(ConnectorMissingCredentialError):
            connector.load_credentials({"outline_base_url": "https://example.com"})

        # Invalid credentials will be caught during validation, not credential loading
        connector.load_credentials(
            {
                "outline_base_url": "https://invalid.invalid",
                "outline_api_token": "invalid",
            }
        )
        # Validation should catch invalid credentials
        with pytest.raises((CredentialExpiredError, ConnectorValidationError)):
            connector.validate_connector_settings()

    def test_outline_connector_invalid_url(self) -> None:
        """Invalid URL should raise validation error during validation."""
        connector = OutlineConnector()

        # Load credentials with invalid URL
        connector.load_credentials(
            {
                "outline_base_url": "https://not-a-valid-url.invalid",
                "outline_api_token": "token",
            }
        )

        # Validation should catch invalid URL
        with pytest.raises(ConnectorValidationError):
            connector.validate_connector_settings()
