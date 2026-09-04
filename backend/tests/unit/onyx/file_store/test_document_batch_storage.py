"""Tests for FileStoreDocumentBatchStorage."""

import json
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

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
@patch(f"{_S3_MODULE}.get_filerecord_by_file_id_optional", return_value=None)
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


def _storage() -> FileStoreDocumentBatchStorage:
    return FileStoreDocumentBatchStorage(
        cc_pair_id=1, index_attempt_id=1, file_store=MagicMock()
    )


def _doc(**overrides: object) -> dict:
    doc: dict = {
        "id": "doc-1",
        "source": "github",
        "semantic_identifier": "a.py",
        "sections": [{"type": "text", "text": "hi", "link": "http://x"}],
        "metadata": {},
    }
    doc.update(overrides)
    return doc


def test_skips_only_the_known_rolling_deploy_shapes() -> None:
    """Both directions of version skew are skipped, and a doc this worker can
    validate still comes through."""
    legacy_tabular = _doc(id="legacy", sections=[{"type": "tabular", "text": "a,b"}])
    newer_type = _doc(id="newer", sections=[{"type": "quantum", "text": "?"}])

    documents = _storage()._deserialize_documents(
        json.dumps([legacy_tabular, newer_type, _doc()])
    )

    assert [d.id for d in documents] == ["doc-1"]


def test_a_real_validation_error_still_raises() -> None:
    """A model bug must not be swallowed as skew: dropping documents silently
    would leave a POLL connector permanently short with the attempt reported
    clean."""
    broken = _doc(sections=[{"type": "text", "link": "http://x"}])  # no text

    with pytest.raises(ValidationError):
        _storage()._deserialize_documents(json.dumps([broken]))
