import requests

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import Document
from onyx.connectors.web.connector import WebConnector


def test_web_connector_basic() -> None:
    """Test basic document loading functionality with live requests"""
    test_url = "https://docs.onyx.app/"

    # First verify the test URL is accessible
    response = requests.get(test_url)
    assert response.status_code == 200, f"Test URL {test_url} is not accessible"

    web_connector = WebConnector(test_url)
    all_docs: list[Document] = []

    for doc_batch in web_connector.load_from_state():
        for doc in doc_batch:
            all_docs.append(doc)

    assert len(all_docs) > 0, "No documents were loaded from the web connector"

    # Verify first document properties
    first_doc = all_docs[0]
    assert first_doc.source == DocumentSource.WEB
    assert len(first_doc.sections) == 1
    link = first_doc.sections[0].link
    assert link is not None and link.startswith("https://")
    assert len(first_doc.sections[0].text) > 0


def test_web_connector_single_page() -> None:
    """Test connector in single page mode"""
    test_url = "https://docs.onyx.app/introduction"

    # Verify the specific page is accessible
    response = requests.get(test_url)
    assert response.status_code == 200, f"Test URL {test_url} is not accessible"

    web_connector = WebConnector(test_url, web_connector_type="single")
    all_docs = []

    for doc_batch in web_connector.load_from_state():
        all_docs.extend(doc_batch)

    assert len(all_docs) == 1, "Single page mode should return exactly one document"
    doc = all_docs[0]
    assert doc.id == test_url
    assert len(doc.sections[0].text) > 0


def test_web_connector_slim() -> None:
    """Test slim document functionality with live data"""
    test_url = "https://docs.onyx.app/"

    # Verify site is accessible
    response = requests.get(test_url)
    assert response.status_code == 200, f"Test URL {test_url} is not accessible"

    full_connector = WebConnector(test_url)
    slim_connector = WebConnector(test_url, connector_id=1, credential_id=0)

    # Get full document IDs
    full_doc_ids: set[str] = set()
    for doc_batch in full_connector.load_from_state():
        full_doc_ids.update(doc.id for doc in doc_batch)

    assert len(full_doc_ids) > 0, "No full documents were loaded"

    # Get slim document IDs
    slim_doc_ids: set[str] = set()
    for slim_batch in slim_connector.retrieve_all_slim_documents():
        for doc in slim_batch:
            if doc.id is not None:  # Guard against None values
                slim_doc_ids.add(doc.id)

    assert len(slim_doc_ids) > 0, "No slim documents were loaded"


def test_web_connector_credentials() -> None:
    """Test credentials handling"""
    connector = WebConnector("https://docs.onyx.app/")
    assert (
        connector.load_credentials({"some": "cred"}) is None
    ), "Credential loading should return None"
