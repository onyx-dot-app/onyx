"""Tests for FileStoreDocumentBatchStorage."""

from unittest.mock import MagicMock, patch

from onyx.db.models import FileRecord
from onyx.file_store.document_batch_storage import FileStoreDocumentBatchStorage
from onyx.file_store.file_store import FileStore, S3BackedFileStore

_S3_MODULE = "onyx.file_store.file_store"


def _mock_db_session() -> MagicMock:
    session = MagicMock()
    session.__enter__ = MagicMock(return_value=session)
    session.__exit__ = MagicMock(return_value=False)
    return session


@patch(f"{_S3_MODULE}.get_session_with_current_tenant")
@patch(f"{_S3_MODULE}.get_session_with_current_tenant_if_none")
@patch(f"{_S3_MODULE}.get_filerecord_by_file_id_for_update", return_value=None)
@patch(f"{_S3_MODULE}.get_filerecord_by_prefix")
def test_cleanup_all_batches_completes_when_files_already_deleted(
    mock_list: MagicMock,
    _mock_get_record: MagicMock,
    mock_ctx: MagicMock,
    mock_session_ctx: MagicMock,
) -> None:
    """cleanup_all_batches must complete without raising even if every batch
    file is already gone — e.g. from a partial cleanup or a batch that was
    never written due to an earlier failure."""
    mock_ctx.return_value = _mock_db_session()
    mock_session_ctx.return_value = _mock_db_session()
    mock_list.return_value = [
        MagicMock(file_id="iab/1/42/0.json"),
        MagicMock(file_id="iab/1/42/1.json"),
        MagicMock(file_id="iab/1/42/2.json"),
    ]

    file_store = S3BackedFileStore(bucket_name="test-bucket")
    storage = FileStoreDocumentBatchStorage(
        cc_pair_id=1, index_attempt_id=42, file_store=file_store
    )
    storage.cleanup_all_batches()  # must not raise


def test_batch_cleanup_does_not_match_another_connection_prefix() -> None:
    file_store = MagicMock(spec=FileStore)
    records = [
        FileRecord(file_id="iab/2/3/0.json"),
        FileRecord(file_id="iab/20/3/0.json"),
        FileRecord(file_id="iab/200/3/0.json"),
    ]
    file_store.list_files_by_prefix.side_effect = lambda prefix: [
        record for record in records if record.file_id.startswith(prefix)
    ]
    storage = FileStoreDocumentBatchStorage(2, 3, file_store)

    storage.cleanup_all_batches()

    file_store.delete_file.assert_called_once_with(
        "iab/2/3/0.json", error_on_missing=False
    )


def test_batch_recovery_rejects_another_connection() -> None:
    file_store = MagicMock(spec=FileStore)
    storage = FileStoreDocumentBatchStorage(2, 4, file_store)

    storage.update_old_batches_to_new_index_attempt(
        ["iab/20/3/0.json", "iab/2/3/1.json"]
    )

    file_store.change_file_id.assert_called_once_with(
        "iab/2/3/1.json", "iab/2/4/1.json"
    )
