"""Tests for FileStore.delete_file error_on_missing behavior."""

from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

_S3_MODULE = "onyx.file_store.file_store"
_PG_MODULE = "onyx.file_store.postgres_file_store"


def _mock_db_session() -> MagicMock:
    session = MagicMock()
    session.__enter__ = MagicMock(return_value=session)
    session.__exit__ = MagicMock(return_value=False)
    return session


# ── S3BackedFileStore ────────────────────────────────────────────────


@patch(f"{_S3_MODULE}.get_session_with_current_tenant_if_none")
@patch(f"{_S3_MODULE}.get_filerecord_by_file_id_optional", return_value=None)
def test_s3_delete_missing_file_raises_by_default(
    _mock_get_record: MagicMock,
    mock_ctx: MagicMock,
) -> None:
    from onyx.file_store.file_store import S3BackedFileStore

    mock_ctx.return_value = _mock_db_session()
    store = S3BackedFileStore(bucket_name="b")

    with pytest.raises(RuntimeError, match="does not exist"):
        store.delete_file("nonexistent")


@patch(f"{_S3_MODULE}.get_session_with_current_tenant_if_none")
@patch(f"{_S3_MODULE}.get_filerecord_by_file_id_optional", return_value=None)
@patch(f"{_S3_MODULE}.delete_filerecord_by_file_id")
def test_s3_delete_missing_file_silent_when_error_on_missing_false(
    mock_delete_record: MagicMock,
    _mock_get_record: MagicMock,
    mock_ctx: MagicMock,
) -> None:
    from onyx.file_store.file_store import S3BackedFileStore

    mock_ctx.return_value = _mock_db_session()
    store = S3BackedFileStore(bucket_name="b")

    store.delete_file("nonexistent", error_on_missing=False)

    mock_delete_record.assert_not_called()


# ── PostgresBackedFileStore ──────────────────────────────────────────


@patch(f"{_PG_MODULE}.get_session_with_current_tenant_if_none")
@patch(f"{_PG_MODULE}.get_file_content_by_file_id_optional", return_value=None)
def test_pg_delete_missing_file_raises_by_default(
    _mock_get_content: MagicMock,
    mock_ctx: MagicMock,
) -> None:
    from onyx.file_store.postgres_file_store import PostgresBackedFileStore

    mock_ctx.return_value = _mock_db_session()
    store = PostgresBackedFileStore()

    with pytest.raises(RuntimeError, match="does not exist"):
        store.delete_file("nonexistent")


@patch(f"{_PG_MODULE}.get_session_with_current_tenant_if_none")
@patch(f"{_PG_MODULE}.get_file_content_by_file_id_optional", return_value=None)
@patch(f"{_PG_MODULE}.delete_file_content_by_file_id")
@patch(f"{_PG_MODULE}.delete_filerecord_by_file_id")
def test_pg_delete_missing_file_silent_when_error_on_missing_false(
    mock_delete_record: MagicMock,
    mock_delete_content: MagicMock,
    _mock_get_content: MagicMock,
    mock_ctx: MagicMock,
) -> None:
    from onyx.file_store.postgres_file_store import PostgresBackedFileStore

    mock_ctx.return_value = _mock_db_session()
    store = PostgresBackedFileStore()

    store.delete_file("nonexistent", error_on_missing=False)

    mock_delete_record.assert_not_called()
    mock_delete_content.assert_not_called()
