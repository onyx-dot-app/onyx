import os
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from unittest.mock import MagicMock

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import Document
from onyx.connectors.sharepoint.connector import SharepointConnector


@dataclass
class ExpectedDocument:
    semantic_identifier: str
    content: str
    folder_path: str | None = None
    library: str = "Shared Documents"  # Default to main library


EXPECTED_DOCUMENTS = [
    ExpectedDocument(
        semantic_identifier="test1.docx",
        content="test1",
        folder_path="test",
    ),
    ExpectedDocument(
        semantic_identifier="test2.docx",
        content="test2",
        folder_path="test/nested with spaces",
    ),
    ExpectedDocument(
        semantic_identifier="should-not-index-on-specific-folder.docx",
        content="should-not-index-on-specific-folder",
        folder_path=None,  # root folder
    ),
    ExpectedDocument(
        semantic_identifier="other.docx",
        content="other",
        folder_path=None,
        library="Other Library",
    ),
]


def verify_document_metadata(doc: Document) -> None:
    """Verify common metadata that should be present on all documents."""
    assert isinstance(doc.doc_updated_at, datetime)
    assert doc.doc_updated_at.tzinfo == timezone.utc
    assert doc.source == DocumentSource.SHAREPOINT
    assert doc.primary_owners is not None
    assert len(doc.primary_owners) == 1
    owner = doc.primary_owners[0]
    assert owner.display_name is not None
    assert owner.email is not None


def verify_document_content(doc: Document, expected: ExpectedDocument) -> None:
    """Verify a document matches its expected content."""
    assert doc.semantic_identifier == expected.semantic_identifier
    assert len(doc.sections) == 1
    assert doc.sections[0].text is not None
    assert expected.content in doc.sections[0].text
    verify_document_metadata(doc)


def find_document(documents: list[Document], semantic_identifier: str) -> Document:
    """Find a document by its semantic identifier."""
    matching_docs = [
        d for d in documents if d.semantic_identifier == semantic_identifier
    ]
    assert (
        len(matching_docs) == 1
    ), f"Expected exactly one document with identifier {semantic_identifier}"
    return matching_docs[0]


@pytest.fixture
def sharepoint_credentials() -> dict[str, str]:
    return {
        "sp_client_id": os.environ["SHAREPOINT_CLIENT_ID"],
        "sp_client_secret": os.environ["SHAREPOINT_CLIENT_SECRET"],
        "sp_directory_id": os.environ["SHAREPOINT_CLIENT_DIRECTORY_ID"],
    }


def test_sharepoint_connector_all_sites__docs_only(
    mock_get_unstructured_api_key: MagicMock,
    sharepoint_credentials: dict[str, str],
) -> None:
    # Initialize connector with no sites
    connector = SharepointConnector(include_site_pages=False)

    # Load credentials
    connector.load_credentials(sharepoint_credentials)

    # Not asserting expected sites because that can change in test tenant at any time
    # Finding any docs is good enough to verify that the connector is working
    document_batches = list(connector.load_from_state())
    assert document_batches, "Should find documents from all sites"


def test_sharepoint_connector_specific_folder(
    mock_get_unstructured_api_key: MagicMock,
    sharepoint_credentials: dict[str, str],
) -> None:
    # Initialize connector with the test site URL and specific folder
    connector = SharepointConnector(
        sites=[os.environ["SHAREPOINT_SITE"] + "/Shared Documents/test"]
    )

    # Load credentials
    connector.load_credentials(sharepoint_credentials)

    # Get all documents
    document_batches = list(connector.load_from_state())
    found_documents: list[Document] = [
        doc for batch in document_batches for doc in batch
    ]

    # Should only find documents in the test folder
    test_folder_docs = [
        doc
        for doc in EXPECTED_DOCUMENTS
        if doc.folder_path and doc.folder_path.startswith("test")
    ]
    assert len(found_documents) == len(
        test_folder_docs
    ), "Should only find documents in test folder"

    # Verify each expected document
    for expected in test_folder_docs:
        doc = find_document(found_documents, expected.semantic_identifier)
        verify_document_content(doc, expected)


def test_sharepoint_connector_root_folder__docs_only(
    mock_get_unstructured_api_key: MagicMock,
    sharepoint_credentials: dict[str, str],
) -> None:
    # Initialize connector with the base site URL
    connector = SharepointConnector(
        sites=[os.environ["SHAREPOINT_SITE"]], include_site_pages=False
    )

    # Load credentials
    connector.load_credentials(sharepoint_credentials)

    # Get all documents
    document_batches = list(connector.load_from_state())
    found_documents: list[Document] = [
        doc for batch in document_batches for doc in batch
    ]

    assert len(found_documents) == len(
        EXPECTED_DOCUMENTS
    ), "Should find all documents in main library"

    # Verify each expected document
    for expected in EXPECTED_DOCUMENTS:
        doc = find_document(found_documents, expected.semantic_identifier)
        verify_document_content(doc, expected)


def test_sharepoint_connector_other_library(
    mock_get_unstructured_api_key: MagicMock,
    sharepoint_credentials: dict[str, str],
) -> None:
    # Initialize connector with the other library
    connector = SharepointConnector(
        sites=[
            os.environ["SHAREPOINT_SITE"] + "/Other Library",
        ]
    )

    # Load credentials
    connector.load_credentials(sharepoint_credentials)

    # Get all documents
    document_batches = list(connector.load_from_state())
    found_documents: list[Document] = [
        doc for batch in document_batches for doc in batch
    ]
    expected_documents: list[ExpectedDocument] = [
        doc for doc in EXPECTED_DOCUMENTS if doc.library == "Other Library"
    ]

    # Should find all documents in `Other Library`
    assert len(found_documents) == len(
        expected_documents
    ), "Should find all documents in `Other Library`"

    # Verify each expected document
    for expected in expected_documents:
        doc = find_document(found_documents, expected.semantic_identifier)
        verify_document_content(doc, expected)


def test_sharepoint_connector_poll(
    mock_get_unstructured_api_key: MagicMock,
    sharepoint_credentials: dict[str, str],
) -> None:
    # Initialize connector with the base site URL
    connector = SharepointConnector(
        sites=["https://danswerai.sharepoint.com/sites/sharepoint-tests"]
    )

    # Load credentials
    connector.load_credentials(sharepoint_credentials)

    # Set time window to only capture test1.docx (modified at 2025-01-28 20:51:42+00:00)
    start = datetime(2025, 1, 28, 20, 51, 30, tzinfo=timezone.utc)  # 12 seconds before
    end = datetime(2025, 1, 28, 20, 51, 50, tzinfo=timezone.utc)  # 8 seconds after

    # Get documents within the time window
    document_batches = list(connector._fetch_from_sharepoint(start=start, end=end))
    found_documents: list[Document] = [
        doc for batch in document_batches for doc in batch
    ]

    # Should only find test1.docx
    assert len(found_documents) == 1, "Should only find one document in the time window"
    doc = found_documents[0]
    assert doc.semantic_identifier == "test1.docx"
    verify_document_metadata(doc)
    verify_document_content(
        doc, [d for d in EXPECTED_DOCUMENTS if d.semantic_identifier == "test1.docx"][0]
    )


def test_sharepoint_connector_pages(
    mock_get_unstructured_api_key: MagicMock,
    sharepoint_credentials: dict[str, str],
) -> None:
    # Initialize connector with the base site URL
    connector = SharepointConnector(
        sites=["https://danswerai.sharepoint.com/sites/sharepoint-tests-pages"]
    )

    # Load credentials
    connector.load_credentials(sharepoint_credentials)

    # Get documents within the time window
    document_batches = list(connector.load_from_state())
    found_documents: list[Document] = [
        doc for batch in document_batches for doc in batch
    ]

    # Should only find CollabHome
    assert len(found_documents) == 1, "Should only find one page"
    doc = found_documents[0]
    assert doc.semantic_identifier == "CollabHome"
    verify_document_metadata(doc)
    assert len(doc.sections) == 1
    assert (
        doc.sections[0].text
        == """
# Home

Display recent news.

## News

Show recent activities from your site

## Site activity

## Quick links

Learn about a team site

Learn how to add a page

Add links to important documents and pages.

## Quick links

Documents

Add a document library

## Document library
""".strip()
    )
