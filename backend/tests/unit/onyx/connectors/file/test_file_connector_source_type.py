from io import BytesIO
from unittest.mock import MagicMock, patch

from onyx.connectors.file.connector import LocalFileConnector
from onyx.connectors.models import Document
from onyx.db.models import FileRecord

MODULE = "onyx.connectors.file.connector"


def _load(file_record: FileRecord, content: bytes) -> list[Document]:
    store = MagicMock()
    store.read_file_record.return_value = file_record
    store.read_file.return_value = BytesIO(content)
    connector = LocalFileConnector(file_locations=[file_record.file_id])
    with (
        patch(f"{MODULE}.get_default_file_store", return_value=store),
        patch(f"{MODULE}.load_zip_metadata", return_value={}),
        patch(
            "onyx.file_processing.extract_file_text.get_unstructured_api_key",
            return_value=None,
        ),
    ):
        return [
            doc
            for batch in connector.load_from_state()
            for doc in batch
            if isinstance(doc, Document)
        ]


def test_document_reports_the_file_record_type_and_size() -> None:
    record = FileRecord(
        file_id="file-1",
        display_name="notes.txt",
        file_type="text/plain",
        file_size=11,
    )

    documents = _load(record, b"hello notes")

    assert len(documents) == 1
    assert documents[0].source_mime_type == "text/plain"
    assert documents[0].source_size_bytes == 11


def test_unknown_record_size_stays_null() -> None:
    record = FileRecord(
        file_id="file-2",
        display_name="notes.txt",
        file_type="text/plain",
        file_size=None,
    )

    documents = _load(record, b"hello notes")

    assert len(documents) == 1
    assert documents[0].source_mime_type == "text/plain"
    assert documents[0].source_size_bytes is None
