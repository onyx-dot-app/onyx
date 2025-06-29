import json
import time
from pathlib import Path
from typing import Any
from unittest.mock import Mock
from unittest.mock import patch

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.drupal_wiki.connector import DrupalWikiConnector
from onyx.connectors.models import Document


def load_test_data(file_name: str = "test_drupal_wiki_data.json") -> dict[str, Any]:
    """Load test data from JSON file"""
    current_dir = Path(__file__).parent
    with open(current_dir / file_name, "r") as f:
        return json.load(f)


@pytest.fixture
def drupal_wiki_connector() -> DrupalWikiConnector:
    """Create a DrupalWikiConnector instance for testing"""
    connector = DrupalWikiConnector(
        base_url="https://help.drupal-wiki.com",
        spaces=["1"],  # Test with space ID 1
    )
    connector.load_credentials(
        {
            "drupal_wiki_api_token": "pat:test12345",
        }
    )
    return connector


def test_drupal_wiki_connector_basic(
    drupal_wiki_connector: DrupalWikiConnector,
) -> None:
    """Test basic functionality of the Drupal Wiki connector"""

    # Mock API responses based on the sample responses provided
    mock_space_response = {
        "totalPages": 1,
        "totalElements": 1,
        "first": True,
        "last": True,
        "sort": {"sorted": True, "unsorted": False, "empty": False},
        "size": 20,
        "content": [
            {
                "description": "Research and Development workspace",
                "accessStatus": "PRIVATE",
                "color": "blue",
                "name": "Research and Development",
                "type": "BASIC",
                "id": 1,
            }
        ],
        "number": 0,
        "numberOfElements": 1,
        "pageable": {
            "sort": {"sorted": True, "unsorted": False, "empty": False},
            "offset": 0,
            "paged": True,
            "pageNumber": 0,
            "pageSize": 20,
            "unpaged": False,
        },
        "empty": False,
    }

    mock_page_response = {
        "totalPages": 1,
        "totalElements": 1,
        "first": True,
        "last": True,
        "sort": {"sorted": True, "unsorted": False, "empty": False},
        "size": 20,
        "content": [
            {
                "lastModified": 1722935527,
                "title": "Research and Development Best Practices",
                "homeSpace": 1,
                "id": 123,
                "type": "DOCUMENT",
            }
        ],
        "number": 0,
        "numberOfElements": 1,
        "pageable": {
            "sort": {"sorted": True, "unsorted": False, "empty": False},
            "offset": 0,
            "paged": True,
            "pageNumber": 0,
            "pageSize": 20,
            "unpaged": False,
        },
        "empty": False,
    }

    mock_page_content = {
        "id": 123,
        "title": "Research and Development Best Practices",
        "body": (
            "<h1>Welcome to My Research Page</h1>"
            "<h2>Introduction</h2>"
            "<p>This is a detailed research page about Data Science methodologies and best practices. "
            "This page contains comprehensive information about various approaches to data analysis.</p>"
            "<h2>Data Collection</h2>"
            "<p>When collecting data, it's important to consider the following factors:</p>"
            "<ul>"
            "<li>Data quality and integrity</li>"
            "<li>Sample size and representativeness</li>"
            "<li>Bias mitigation strategies</li>"
            "</ul>"
            "<h2>Analysis Methods</h2>"
            "<p>We recommend using statistical analysis and machine learning techniques to extract "
            "meaningful insights from your data.</p>"
            "<h2>Conclusion</h2>"
            "<p>Following these guidelines will help ensure robust and reliable research outcomes.</p>"
        ),
        "homeSpace": 1,
        "lastModified": 1722935527,
        "type": "DOCUMENT",
    }

    def mock_get(*args: Any, **kwargs: Any) -> Mock:
        """Mock requests.get to return appropriate responses"""
        mock_response = Mock()
        mock_response.raise_for_status = Mock()

        url = args[0]
        if "/api/rest/scope/api/space" in url:
            mock_response.json.return_value = mock_space_response
        elif "/api/rest/scope/api/page" in url and not url.endswith("/page/123"):
            # This is for getting pages in a space
            mock_response.json.return_value = mock_page_response
        elif url.endswith("/page/123"):
            # This is for getting specific page content
            mock_response.json.return_value = mock_page_content
        else:
            mock_response.json.return_value = {}

        return mock_response

    with patch.object(drupal_wiki_connector, "_rate_limited_get", side_effect=mock_get):
        # Collect all documents
        all_docs: list[Document] = []
        target_test_doc_id = "https://help.drupal-wiki.com/node/123"
        target_test_doc: Document | None = None

        # Use load_from_checkpoint which is the main method for checkpointed connectors
        checkpoint = drupal_wiki_connector.build_dummy_checkpoint()

        for doc_or_failure in drupal_wiki_connector.load_from_checkpoint(
            0, time.time(), checkpoint
        ):
            if isinstance(doc_or_failure, Document):
                all_docs.append(doc_or_failure)
                if doc_or_failure.id == target_test_doc_id:
                    target_test_doc = doc_or_failure

    # Verify we got the expected number of documents
    assert len(all_docs) == 1
    assert target_test_doc is not None

    # Load expected test data
    desired_test_data = load_test_data()

    # Verify document properties
    assert (
        target_test_doc.semantic_identifier == desired_test_data["semantic_identifier"]
    )
    assert target_test_doc.source == DocumentSource.DRUPAL_WIKI
    assert target_test_doc.metadata == desired_test_data["metadata"]
    assert target_test_doc.primary_owners is None
    assert target_test_doc.secondary_owners is None
    assert target_test_doc.title is None
    assert target_test_doc.from_ingestion_api is False
    assert target_test_doc.additional_info is None

    # Verify sections
    assert len(target_test_doc.sections) == 1
    section = target_test_doc.sections[0]
    assert section.text is not None
    assert section.text.strip() == desired_test_data["section_text"].strip()
    assert section.link == desired_test_data["link"]


def test_drupal_wiki_connector_slim(drupal_wiki_connector: DrupalWikiConnector) -> None:
    """Test slim document retrieval functionality"""

    # Mock the same responses as in basic test
    mock_space_response = {
        "totalPages": 1,
        "totalElements": 1,
        "first": True,
        "last": True,
        "sort": {"sorted": True, "unsorted": False, "empty": False},
        "size": 20,
        "content": [
            {
                "description": "Research and Development workspace",
                "accessStatus": "PRIVATE",
                "color": "blue",
                "name": "Research and Development",
                "type": "BASIC",
                "id": 1,
            }
        ],
        "number": 0,
        "numberOfElements": 1,
        "empty": False,
    }

    mock_page_response = {
        "totalPages": 1,
        "totalElements": 1,
        "first": True,
        "last": True,
        "sort": {"sorted": True, "unsorted": False, "empty": False},
        "size": 20,
        "content": [
            {
                "lastModified": 1722935527,
                "title": "Research and Development Best Practices",
                "homeSpace": 1,
                "id": 123,
                "type": "DOCUMENT",
            }
        ],
        "number": 0,
        "numberOfElements": 1,
        "empty": False,
    }

    def mock_get(*args: Any, **kwargs: Any) -> Mock:
        """Mock requests.get for slim document testing"""
        mock_response = Mock()
        mock_response.raise_for_status = Mock()

        url = args[0]
        if "/api/rest/scope/api/space" in url:
            mock_response.json.return_value = mock_space_response
        elif "/api/rest/scope/api/page" in url:
            mock_response.json.return_value = mock_page_response
        else:
            mock_response.json.return_value = {}

        return mock_response

    with patch.object(drupal_wiki_connector, "_rate_limited_get", side_effect=mock_get):
        # Get all doc IDs from the full connector
        all_full_doc_ids = set()
        checkpoint = drupal_wiki_connector.build_dummy_checkpoint()

        for doc_or_failure in drupal_wiki_connector.load_from_checkpoint(
            0, time.time(), checkpoint
        ):
            if isinstance(doc_or_failure, Document):
                all_full_doc_ids.add(doc_or_failure.id)

        # Get all doc IDs from the slim connector
        all_slim_doc_ids = set()
        for slim_doc_batch in drupal_wiki_connector.retrieve_all_slim_documents():
            all_slim_doc_ids.update([doc.id for doc in slim_doc_batch])

        # The set of full doc IDs should always be a subset of the slim doc IDs
        assert all_full_doc_ids.issubset(all_slim_doc_ids)
