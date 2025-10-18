import os
from unittest.mock import patch

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.joplin.connector import JoplinConnector


@pytest.fixture
def joplin_connector() -> JoplinConnector:
    connector = JoplinConnector(
        base_url=os.environ.get("JOPLIN_TEST_BASE_URL", "http://localhost:41184")
    )
    connector.load_credentials(
        {"joplin_api_token": os.environ.get("JOPLIN_TEST_API_TOKEN", "test_token")}
    )
    return connector


def test_joplin_connector_init() -> None:
    connector = JoplinConnector()
    assert connector.base_url == "http://localhost:41184"
    assert connector.batch_size > 0


def test_joplin_connector_custom_url() -> None:
    custom_url = "http://joplin.example.com:41184"
    connector = JoplinConnector(base_url=custom_url)
    assert connector.base_url == custom_url


def test_joplin_connector_load_credentials() -> None:
    connector = JoplinConnector()
    credentials = {"joplin_api_token": "test_token_123"}

    connector.load_credentials(credentials)

    assert connector.api_token == "test_token_123"
    assert "Authorization" in connector.headers
    assert connector.headers["Authorization"] == "Bearer test_token_123"


def test_joplin_connector_missing_credentials() -> None:
    connector = JoplinConnector()

    with pytest.raises(Exception):
        connector.load_credentials({})


def test_joplin_ms_to_seconds() -> None:
    connector = JoplinConnector()

    timestamp_ms = 1634567890123
    expected_seconds = 1634567890.123

    result = connector._ms_to_seconds(timestamp_ms)
    assert result == expected_seconds


def test_joplin_ms_to_seconds_none() -> None:
    connector = JoplinConnector()

    result = connector._ms_to_seconds(None)
    assert result is None


def test_joplin_build_folder_path_single() -> None:
    connector = JoplinConnector()
    connector.load_credentials({"joplin_api_token": "test"})

    with patch.object(connector, "_fetch_folder") as mock_fetch:
        mock_fetch.return_value = {
            "id": "folder1",
            "title": "My Notes",
            "parent_id": None,
        }

        path = connector._build_folder_path("folder1")
        assert path == "My Notes"


def test_joplin_build_folder_path_nested() -> None:
    connector = JoplinConnector()
    connector.load_credentials({"joplin_api_token": "test"})

    def mock_fetch_folder(folder_id: str):
        folders = {
            "folder1": {"id": "folder1", "title": "Root", "parent_id": None},
            "folder2": {"id": "folder2", "title": "Work", "parent_id": "folder1"},
            "folder3": {"id": "folder3", "title": "Projects", "parent_id": "folder2"},
        }
        return folders.get(folder_id)

    with patch.object(connector, "_fetch_folder", side_effect=mock_fetch_folder):
        path = connector._build_folder_path("folder3")
        assert path == "Root > Work > Projects"


def test_joplin_convert_to_document() -> None:
    connector = JoplinConnector()
    connector.load_credentials({"joplin_api_token": "test"})

    note = {
        "id": "note123",
        "title": "Test Note",
        "body": "# This is a test note\n\nWith some content.",
        "parent_id": "folder1",
        "created_time": 1634567890123,
        "updated_time": 1634567890456,
        "is_todo": 0,
        "source_url": "",
    }

    folder_path = "Work > Projects"
    tags = ["important", "review"]

    document = connector._convert_to_document(note, folder_path, tags)

    assert document.id == "note123"
    assert document.semantic_identifier == "Test Note"
    assert document.source == DocumentSource.JOPLIN
    assert document.metadata["folder_path"] == "Work > Projects"
    assert document.metadata["tags"] == ["important", "review"]
    assert len(document.sections) == 1
    assert "This is a test note" in document.sections[0].text


def test_joplin_convert_to_document_with_todo() -> None:
    connector = JoplinConnector()
    connector.load_credentials({"joplin_api_token": "test"})

    note = {
        "id": "note456",
        "title": "Todo Note",
        "body": "- [ ] Task 1\n- [ ] Task 2",
        "parent_id": None,
        "created_time": 1634567890123,
        "updated_time": 1634567890456,
        "is_todo": 1,
        "source_url": "https://example.com",
    }

    document = connector._convert_to_document(note, "Root", [])

    assert document.metadata["is_todo"] == "true"
    assert document.metadata["source_url"] == "https://example.com"


def test_joplin_connector_with_folder_filter() -> None:
    connector = JoplinConnector(include_folders=["Work", "Personal"])
    assert connector.include_folders == ["Work", "Personal"]


def test_joplin_connector_with_tag_filter() -> None:
    connector = JoplinConnector(include_tags=["important", "urgent"])
    assert connector.include_tags == ["important", "urgent"]
