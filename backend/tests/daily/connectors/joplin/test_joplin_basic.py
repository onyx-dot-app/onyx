import os
import time

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.joplin.connector import JoplinConnector


@pytest.fixture
def joplin_connector() -> JoplinConnector:
    connector = JoplinConnector(
        base_url=os.environ.get("JOPLIN_TEST_BASE_URL", "http://localhost:41184")
    )
    connector.load_credentials(
        {
            "joplin_api_token": os.environ["JOPLIN_TEST_API_TOKEN"],
        }
    )
    return connector


def test_joplin_connector_basic_load(joplin_connector: JoplinConnector) -> None:
    doc_count = 0
    note_titles = []

    for doc_batch in joplin_connector.load_from_state():
        doc_count += len(doc_batch)
        for doc in doc_batch:
            assert doc.id
            assert doc.semantic_identifier
            assert doc.source == DocumentSource.JOPLIN
            assert "folder_path" in doc.metadata
            assert len(doc.sections) > 0

            note_titles.append(doc.semantic_identifier)

    assert doc_count > 0, "Should have indexed at least one note"
    print(f"\nIndexed {doc_count} notes")
    print(f"Sample titles: {note_titles[:5]}")


def test_joplin_connector_poll_source(joplin_connector: JoplinConnector) -> None:
    current_time = time.time()
    one_hour_ago = current_time - 3600

    doc_count = 0

    for doc_batch in joplin_connector.poll_source(one_hour_ago, current_time):
        doc_count += len(doc_batch)
        for doc in doc_batch:
            assert doc.id
            assert doc.source == DocumentSource.JOPLIN

    print(f"\nFound {doc_count} notes modified in last hour")


def test_joplin_connector_with_folder_filter() -> None:
    connector = JoplinConnector(
        base_url=os.environ.get("JOPLIN_TEST_BASE_URL", "http://localhost:41184"),
        include_folders=["Work"],
    )
    connector.load_credentials(
        {
            "joplin_api_token": os.environ["JOPLIN_TEST_API_TOKEN"],
        }
    )

    for doc_batch in connector.load_from_state():
        for doc in doc_batch:
            folder_path = doc.metadata.get("folder_path", "")
            assert folder_path == "Work"


def test_joplin_connector_validates_credentials() -> None:
    connector = JoplinConnector(
        base_url=os.environ.get("JOPLIN_TEST_BASE_URL", "http://localhost:41184")
    )
    connector.load_credentials(
        {
            "joplin_api_token": os.environ["JOPLIN_TEST_API_TOKEN"],
        }
    )

    connector.validate_connector_settings()


def test_joplin_connector_invalid_token() -> None:
    connector = JoplinConnector(
        base_url=os.environ.get("JOPLIN_TEST_BASE_URL", "http://localhost:41184")
    )
    connector.load_credentials({"joplin_api_token": "invalid_token_12345"})

    with pytest.raises(Exception):
        connector.validate_connector_settings()
