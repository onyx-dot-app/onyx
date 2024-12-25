import json
from pathlib import Path

from onyx.configs.constants import DocumentSource
from onyx.connectors.web.connector import WebConnector


def load_test_data(file_name: str = "test_web_data.json") -> dict:
    current_dir = Path(__file__).parent
    with open(current_dir / file_name, "r") as f:
        return json.load(f)


def test_web_connector_basic() -> None:
    """Test basic document loading functionality"""
    web_connector = WebConnector("https://docs.onyx.app/")
    all_docs = []
    target_url = load_test_data()["test_page"]["id"]
    target_doc = None

    for doc_batch in web_connector.load_from_state():
        for doc in doc_batch:
            all_docs.append(doc)
            if doc.id == target_url:
                target_doc = doc

    assert len(all_docs) > 0, "No documents were loaded from the web connector"
    assert target_doc is not None, f"Document with URL {target_url} not found"
    assert target_doc.source == DocumentSource.WEB, "Document source is not set to WEB"
    assert len(target_doc.sections) == 1, "Document should have exactly one section"
    assert (
        target_doc.sections[0].link == target_url
    ), "Document section link does not match target URL"


def test_web_connector_slim() -> None:
    """Test slim document functionality matches full documents"""
    full_connector = WebConnector("https://docs.onyx.app/")
    slim_connector = WebConnector("https://docs.onyx.app/")

    # Get full document IDs
    full_doc_ids: set[str] = set()
    for doc_batch in full_connector.load_from_state():
        full_doc_ids.update(doc.id for doc in doc_batch)

    # Get slim document IDs
    slim_doc_ids: set[str] = set()
    for slim_batch in slim_connector.retrieve_all_slim_documents():
        slim_doc_ids.update(doc.id for doc in slim_batch)

    # Full docs should be subset of slim docs
    assert full_doc_ids.issubset(
        slim_doc_ids
    ), "Full document IDs should be a subset of slim document IDs"


def test_web_connector_credentials() -> None:
    """Test credentials handling"""
    connector = WebConnector("https://example.com")
    assert (
        connector.load_credentials({"some": "cred"}) is None
    ), "Credential loading should return None"
