import json
import os
import time
from pathlib import Path

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.highspot.connector import HighspotConnector
from onyx.connectors.models import Document


def load_test_data(file_name: str = "test_highspot_data.json") -> dict:
    """Load test data from JSON file."""
    current_dir = Path(__file__).parent
    with open(current_dir / file_name, "r") as f:
        return json.load(f)


@pytest.fixture
def highspot_connector() -> HighspotConnector:
    """Create a Highspot connector with credentials from environment variables."""
    # Check if required environment variables are set
    if not os.environ.get("HIGHSPOT_KEY") or not os.environ.get("HIGHSPOT_SECRET"):
        pytest.fail("HIGHSPOT_KEY or HIGHSPOT_SECRET environment variables not set")

    connector = HighspotConnector(
        spot_names=["Test content"],  # Use specific spot name instead of empty list
        batch_size=10,  # Smaller batch size for testing
    )
    connector.load_credentials(
        {
            "highspot_key": os.environ["HIGHSPOT_KEY"],
            "highspot_secret": os.environ["HIGHSPOT_SECRET"],
            "highspot_url": os.environ.get(
                "HIGHSPOT_URL", "https://api-su2.highspot.com/v1.0/"
            ),
        }
    )
    return connector


def test_highspot_connector_basic(highspot_connector: HighspotConnector) -> None:
    """Test basic functionality of the Highspot connector."""
    all_docs: list[Document] = []
    test_data = load_test_data()
    target_test_doc_id = test_data.get("target_doc_id")
    target_test_doc: Document | None = None

    # Test loading documents
    for doc_batch in highspot_connector.poll_source(0, time.time()):
        for doc in doc_batch:
            all_docs.append(doc)
            if doc.id == f"HIGHSPOT_{target_test_doc_id}":
                target_test_doc = doc

    # Verify documents were loaded
    assert len(all_docs) > 0

    # If we have a specific test document ID, validate it
    if target_test_doc_id and target_test_doc is not None:
        assert target_test_doc.semantic_identifier == test_data.get(
            "semantic_identifier"
        )
        assert target_test_doc.source == DocumentSource.HIGHSPOT
        assert target_test_doc.metadata is not None

        assert len(target_test_doc.sections) == 1
        section = target_test_doc.sections[0]
        assert section.link is not None
        # Only check if content exists, as exact content might change
        assert len(section.text) > 0


def test_highspot_connector_slim(highspot_connector: HighspotConnector) -> None:
    """Test slim document retrieval."""
    # Get all doc IDs from the full connector
    all_full_doc_ids = set()
    for doc_batch in highspot_connector.load_from_state():
        all_full_doc_ids.update([doc.id for doc in doc_batch])

    # Get all doc IDs from the slim connector
    all_slim_doc_ids = set()
    for slim_doc_batch in highspot_connector.retrieve_all_slim_documents():
        all_slim_doc_ids.update([doc.id for doc in slim_doc_batch])

    # The set of full doc IDs should be a subset of the slim doc IDs
    assert all_full_doc_ids.issubset(all_slim_doc_ids)
    # Make sure we actually got some documents
    assert len(all_slim_doc_ids) > 0


def test_highspot_connector_validate_credentials(
    highspot_connector: HighspotConnector,
) -> None:
    """Test credential validation."""
    assert highspot_connector.validate_credentials() is True
