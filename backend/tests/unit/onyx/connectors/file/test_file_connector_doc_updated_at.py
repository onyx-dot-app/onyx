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
    file_record: FileRecord,
    zip_metadata: dict[str, Any] | None = None,
    metadata_record: FileRecord | None = None,
    inline_metadata: dict[str, Any] | None = None,
) -> list[Document]:
    records = {file_record.file_id: file_record}
    if metadata_record is not None:
        records[metadata_record.file_id] = metadata_record
    store = MagicMock()
    store.read_file_record.side_effect = lambda file_id: records[file_id]
    store.read_file.return_value = BytesIO(b"hello notes")
    connector = LocalFileConnector(
        file_locations=[file_record.file_id],
        zip_metadata_file_id=metadata_record.file_id if metadata_record else None,
        zip_metadata=inline_metadata,
    )
    with (
        patch(f"{MODULE}.get_default_file_store", return_value=store),
        patch(
            "onyx.connectors.file.metadata.get_default_file_store", return_value=store
        ),
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


def test_metadata_only_edit_is_indexed() -> None:
    record = _record(UPLOADED_AT)
    old_metadata = FileRecord(
        file_id="meta-1", created_at=datetime(2026, 2, 1, tzinfo=timezone.utc)
    )
    new_metadata = FileRecord(
        file_id="meta-2", created_at=datetime(2026, 3, 1, tzinfo=timezone.utc)
    )

    (first,) = _load(record, {"notes.txt": {"link": "https://a.example"}}, old_metadata)
    (second,) = _load(
        record, {"notes.txt": {"link": "https://b.example"}}, new_metadata
    )

    assert first.doc_updated_at == old_metadata.created_at
    assert second.doc_updated_at == new_metadata.created_at
    to_update = get_docs_to_update(
        [second], db_docs=[_stored(first)], ignore_timestamp_gate=True
    )
    assert to_update.updatable_docs == [second]


def test_inline_metadata_edit_is_indexed() -> None:
    record = _record(UPLOADED_AT)
    old_metadata = {"notes.txt": {"link": "https://a.example"}}
    new_metadata = {"notes.txt": {"link": "https://b.example"}}

    (first,) = _load(record, old_metadata, inline_metadata=old_metadata)
    (second,) = _load(record, new_metadata, inline_metadata=new_metadata)

    to_update = get_docs_to_update(
        [second], db_docs=[_stored(first)], ignore_timestamp_gate=True
    )
    assert to_update.updatable_docs == [second]


def test_metadata_timestamp_takes_precedence() -> None:
    record = _record(UPLOADED_AT)
    metadata = {"notes.txt": {"doc_updated_at": "2025-06-01T00:00:00+00:00"}}

    (doc,) = _load(record, metadata)

    assert doc.doc_updated_at == datetime(2025, 6, 1, tzinfo=timezone.utc)


def test_record_without_upload_time_has_no_timestamp() -> None:
    (doc,) = _load(_record(None))

    assert doc.doc_updated_at is None
