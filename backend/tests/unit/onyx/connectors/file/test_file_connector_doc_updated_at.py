from datetime import datetime, timezone
from io import BytesIO
from typing import Any
from unittest.mock import MagicMock, patch

from onyx.connectors.file.connector import LocalFileConnector
from onyx.connectors.models import Document
from onyx.db.models import FileRecord
from onyx.indexing.indexing_pipeline import get_docs_to_update

MODULE = "onyx.connectors.file.connector"
UPLOADED_AT = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


def _record(created_at: datetime | None) -> FileRecord:
    return FileRecord(
        file_id="file-1",
        display_name="notes.txt",
        file_type="text/plain",
        file_size=11,
        created_at=created_at,
    )


def _load(
    file_record: FileRecord, zip_metadata: dict[str, Any] | None = None
) -> list[Document]:
    store = MagicMock()
    store.read_file_record.return_value = file_record
    store.read_file.return_value = BytesIO(b"hello notes")
    connector = LocalFileConnector(file_locations=[file_record.file_id])
    with (
        patch(f"{MODULE}.get_default_file_store", return_value=store),
        patch(f"{MODULE}.load_zip_metadata", return_value=zip_metadata or {}),
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


def _stored(doc: Document) -> MagicMock:
    db_doc = MagicMock()
    db_doc.id = doc.id
    db_doc.content_hash = doc.content_hash()
    db_doc.doc_updated_at = doc.doc_updated_at
    db_doc.source_mime_type = doc.source_mime_type
    db_doc.source_size_bytes = doc.source_size_bytes
    db_doc.external_user_emails = []
    db_doc.external_user_group_ids = []
    db_doc.is_public = False
    return db_doc


def test_rerun_over_unchanged_file_is_skipped() -> None:
    record = _record(UPLOADED_AT)

    (first,) = _load(record)
    (second,) = _load(record)

    assert first.doc_updated_at == UPLOADED_AT
    assert second.doc_updated_at == UPLOADED_AT
    to_update = get_docs_to_update(
        [second], db_docs=[_stored(first)], ignore_timestamp_gate=True
    )
    assert to_update.updatable_docs == []


def test_metadata_timestamp_takes_precedence() -> None:
    record = _record(UPLOADED_AT)
    metadata = {"notes.txt": {"doc_updated_at": "2025-06-01T00:00:00+00:00"}}

    (doc,) = _load(record, metadata)

    assert doc.doc_updated_at == datetime(2025, 6, 1, tzinfo=timezone.utc)


def test_record_without_upload_time_has_no_timestamp() -> None:
    (doc,) = _load(_record(None))

    assert doc.doc_updated_at is None
