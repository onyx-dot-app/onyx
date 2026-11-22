"""Tests for FileStoreDocumentBatchStorage."""

from io import BytesIO, StringIO
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from onyx.access.models import ExternalAccess
from onyx.configs.constants import DocumentSource
from onyx.connectors.models import Document
from onyx.file_store.document_batch_storage import FileStoreDocumentBatchStorage
from onyx.file_store.file_store import S3BackedFileStore

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


def test_backfill_batches_live_apart_from_normal_batches() -> None:
    """A backfill's batch listing (used by cleanup and reissue) never sees a
    normal attempt's leftover batches, and vice versa."""
    file_store = MagicMock()
    normal = FileStoreDocumentBatchStorage(
        cc_pair_id=1, index_attempt_id=42, file_store=file_store
    )
    backfill = FileStoreDocumentBatchStorage(
        cc_pair_id=1, index_attempt_id=43, file_store=file_store, is_backfill=True
    )

    normal.get_all_batches_for_cc_pair()
    backfill.get_all_batches_for_cc_pair()

    assert [c.args[0] for c in file_store.list_files_by_prefix.call_args_list] == [
        "iab/1/",
        "iab_backfill/1/",
    ]
    assert backfill.extract_path_info("iab_backfill/1/43/0.json") is not None


def test_document_batch_round_trips_external_access() -> None:
    files: dict[str, bytes] = {}

    def save_file(*, file_id: str, content: StringIO, **_: object) -> None:
        files[file_id] = content.read().encode("utf-8")

    file_store = MagicMock()
    file_store.has_file.side_effect = lambda *, file_id, **_: file_id in files
    file_store.save_file.side_effect = save_file
    file_store.read_file.side_effect = lambda file_id: BytesIO(files[file_id])
    storage = FileStoreDocumentBatchStorage(
        cc_pair_id=1, index_attempt_id=42, file_store=file_store
    )
    documents = [
        Document(
            id="restricted",
            source=DocumentSource.FILE,
            sections=[],
            metadata={},
            semantic_identifier="Restricted document",
            external_access=ExternalAccess(
                external_user_emails={"reader@example.com"},
                external_user_group_ids={"group-1"},
                is_public=False,
            ),
        ),
        Document(
            id="private",
            source=DocumentSource.FILE,
            sections=[],
            metadata={},
            semantic_identifier="Private document",
            external_access=ExternalAccess.empty(),
        ),
    ]

    storage.store_batch(0, documents)

    assert storage.get_batch(0) == documents


@pytest.mark.parametrize("field", ["external_user_emails", "external_user_group_ids"])
def test_external_access_rejects_non_string_members(field: str) -> None:
    payload = {
        "external_user_emails": [],
        "external_user_group_ids": [],
        "is_public": False,
    }
    payload[field] = [42]

    with pytest.raises(ValidationError, match="Input should be a valid string"):
        ExternalAccess.model_validate(payload)
