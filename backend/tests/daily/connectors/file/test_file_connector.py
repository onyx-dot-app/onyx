import io
from datetime import datetime
from datetime import timezone
from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import uuid4

import pytest

from onyx.connectors.file.connector import LocalFileConnector


@pytest.fixture
def mock_db_session() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_file_store() -> MagicMock:
    store = MagicMock()
    return store


@pytest.fixture
def mock_filestore_record() -> MagicMock:
    record = MagicMock()
    record.file_id = uuid4()
    record.display_name = "test.txt"
    return record


@patch("onyx.connectors.file.connector.get_default_file_store")
@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key", return_value=None
)
def test_single_text_file_with_metadata(
    mock_get_unstructured_api_key: MagicMock,
    mock_get_session: MagicMock,
    mock_db_session: MagicMock,
    mock_file_store: MagicMock,
    mock_filestore_record: MagicMock,
) -> None:
    file_content = io.BytesIO(
        b'#ONYX_METADATA={"link": "https://onyx.app", "file_display_name":"my display name", "tag_of_your_choice": "test-tag", \
          "primary_owners": ["wenxi@onyx.app"], "secondary_owners": ["founders@onyx.app"], \
          "doc_updated_at": "2001-01-01T00:00:00Z"}\n'
        b"Test answer is 12345"
    )
    mock_get_filestore = MagicMock()
    mock_get_filestore.return_value = mock_file_store
    mock_file_store.read_file_record.return_value = mock_filestore_record
    mock_get_session.return_value.__enter__.return_value = mock_db_session
    mock_file_store.read_file.return_value = file_content

    with patch(
        "onyx.connectors.file.connector.get_default_file_store",
        return_value=mock_file_store,
    ):
        connector = LocalFileConnector(
            file_locations=["test.txt"], file_names=["test.txt"], zip_metadata={}
        )
        batches = list(connector.load_from_state())

    assert len(batches) == 1
    docs = batches[0]
    assert len(docs) == 1
    doc = docs[0]

    assert doc.sections[0].text == "Test answer is 12345"
    assert doc.sections[0].link == "https://onyx.app"
    assert doc.semantic_identifier == "my display name"
    assert doc.primary_owners[0].display_name == "wenxi@onyx.app"  # type: ignore
    assert doc.secondary_owners[0].display_name == "founders@onyx.app"  # type: ignore
    assert doc.doc_updated_at == datetime(2001, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


@patch(
    "onyx.file_processing.extract_file_text.get_unstructured_api_key", return_value=None
)
def test_two_text_files_with_zip_metadata(
    mock_get_unstructured_api_key: MagicMock,
    mock_db_session: MagicMock,
    mock_file_store: MagicMock,
) -> None:
    file1_content = io.BytesIO(b"File 1 content")
    file2_content = io.BytesIO(b"File 2 content")
    mock_get_filestore = MagicMock()
    mock_get_filestore.return_value = mock_file_store
    mock_file_store.read_file_record.side_effect = [
        MagicMock(file_id=str(uuid4()), display_name="file1.txt"),
        MagicMock(file_id=str(uuid4()), display_name="file2.txt"),
    ]
    mock_file_store.read_file.side_effect = [file1_content, file2_content]
    zip_metadata = {
        "file1.txt": {
            "filename": "file1.txt",
            "file_display_name": "display 1",
            "link": "https://onyx.app/1",
            "primary_owners": ["alice@onyx.app"],
            "secondary_owners": ["bob@onyx.app"],
            "doc_updated_at": "2022-02-02T00:00:00Z",
        },
        "file2.txt": {
            "filename": "file2.txt",
            "file_display_name": "display 2",
            "link": "https://onyx.app/2",
            "primary_owners": ["carol@onyx.app"],
            "secondary_owners": ["dave@onyx.app"],
            "doc_updated_at": "2023-03-03T00:00:00Z",
        },
    }

    with patch(
        "onyx.connectors.file.connector.get_default_file_store",
        return_value=mock_file_store,
    ):
        connector = LocalFileConnector(
            file_locations=["file1.txt", "file2.txt"],
            file_names=["file1.txt", "file2.txt"],
            zip_metadata=zip_metadata,
        )
        batches = list(connector.load_from_state())

    assert len(batches) == 1
    docs = batches[0]
    assert len(docs) == 2
    doc1, doc2 = docs

    assert doc1.sections[0].text == "File 1 content"
    assert doc1.sections[0].link == "https://onyx.app/1"
    assert doc1.semantic_identifier == "display 1"
    assert doc1.primary_owners[0].display_name == "alice@onyx.app"  # type: ignore
    assert doc1.secondary_owners[0].display_name == "bob@onyx.app"  # type: ignore
    assert doc1.doc_updated_at == datetime(2022, 2, 2, 0, 0, 0, tzinfo=timezone.utc)
    assert doc2.sections[0].text == "File 2 content"
    assert doc2.sections[0].link == "https://onyx.app/2"
    assert doc2.semantic_identifier == "display 2"
    assert doc2.primary_owners[0].display_name == "carol@onyx.app"  # type: ignore
    assert doc2.secondary_owners[0].display_name == "dave@onyx.app"  # type: ignore
    assert doc2.doc_updated_at == datetime(2023, 3, 3, 0, 0, 0, tzinfo=timezone.utc)
