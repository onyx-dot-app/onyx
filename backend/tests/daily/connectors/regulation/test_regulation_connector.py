import pytest
from bs4 import BeautifulSoup
from unittest.mock import patch

from onyx.connectors.models import Document
from onyx.connectors.regulation.connector import RegulationConnector


@pytest.fixture
def regulation_connector() -> RegulationConnector:
    connector = RegulationConnector(
        base_url="https://regulation.example.com",
    )
    return connector


def test_regulation_connector_initialization(regulation_connector: RegulationConnector) -> None:
    assert regulation_connector.base_url == "https://regulation.example.com"
    assert regulation_connector.batch_size == 100
    assert regulation_connector.to_visit_list == ["https://regulation.example.com"]


def test_regulation_connector_credentials(regulation_connector: RegulationConnector) -> None:
    # Regulation connector doesn't need credentials
    assert regulation_connector.load_credentials({}) is None


@patch("requests.get")
def test_regulation_connector_load_from_state(
    mock_get,
    regulation_connector: RegulationConnector,
) -> None:
    # Mock the response for the base URL
    mock_response = type("Response", (), {
        "text": """
        <html>
            <head><title>Test Regulation</title></head>
            <body>
                <h1>Test Regulation</h1>
                <p>This is a test regulation page.</p>
                <a href="/section1">Section 1</a>
                <a href="/section2">Section 2</a>
            </body>
        </html>
        """,
        "headers": {"Last-Modified": "Thu, 21 Mar 2024 10:00:00 GMT"},
        "raise_for_status": lambda: None,
    })
    mock_get.return_value = mock_response

    # Get the first batch of documents
    doc_batches = regulation_connector.load_from_state()
    first_batch = next(doc_batches)

    # Verify the document structure
    assert len(first_batch) == 1
    doc = first_batch[0]
    assert isinstance(doc, Document)
    assert doc.id == "https://regulation.example.com"
    assert doc.source == "regulation"
    assert doc.semantic_identifier == "Test Regulation"
    assert "This is a test regulation page" in doc.sections[0].text


def test_regulation_connector_validate_settings(regulation_connector: RegulationConnector) -> None:
    # Test with valid settings
    regulation_connector.validate_connector_settings()

    # Test with empty URL list
    regulation_connector.to_visit_list = []
    with pytest.raises(Exception) as exc_info:
        regulation_connector.validate_connector_settings()
    assert "No URL configured" in str(exc_info.value) 