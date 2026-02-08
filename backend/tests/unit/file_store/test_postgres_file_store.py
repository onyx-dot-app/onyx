"""Unit tests for PostgresBackedFileStore.

These tests mock the database layer (sessions, raw connections, large objects)
so they run without any external services.
"""

from io import BytesIO
from io import StringIO
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.configs.constants import FileOrigin
from onyx.file_store.postgres_file_store import POSTGRES_BUCKET_SENTINEL
from onyx.file_store.postgres_file_store import PostgresBackedFileStore


@pytest.fixture
def store() -> PostgresBackedFileStore:
    return PostgresBackedFileStore()


def _make_session_ctx(
    mock_session: MagicMock,
) -> Any:
    """Build a context-manager mock that yields mock_session."""
    from contextlib import contextmanager

    @contextmanager
    def _ctx(session: Any = None):  # type: ignore
        yield session if session is not None else mock_session

    return _ctx


def _mock_lobject(oid: int = 42, data: bytes = b"hello") -> MagicMock:
    """Return a mock lobject factory that the raw connection exposes."""
    lobj = MagicMock()
    lobj.oid = oid
    lobj.read = MagicMock(side_effect=[data, b""])
    lobj.write = MagicMock()
    lobj.close = MagicMock()
    lobj.unlink = MagicMock()
    return lobj


class TestInitialize:
    def test_initialize_is_noop(self, store: PostgresBackedFileStore) -> None:
        # Should not raise
        store.initialize()


class TestSaveFile:
    @patch(
        "onyx.file_store.postgres_file_store.get_session_with_current_tenant_if_none"
    )
    def test_save_bytes_content(
        self,
        mock_get_session: MagicMock,
        store: PostgresBackedFileStore,
    ) -> None:
        mock_session = MagicMock()
        mock_get_session.return_value = _make_session_ctx(mock_session)(None)

        raw_conn = MagicMock()
        lobj = _mock_lobject(oid=99)
        raw_conn.lobject.return_value = lobj
        mock_session.connection.return_value.connection.dbapi_connection = raw_conn

        with (
            patch(
                "onyx.file_store.postgres_file_store.upsert_filerecord"
            ) as mock_upsert_fr,
            patch(
                "onyx.file_store.postgres_file_store.upsert_file_content"
            ) as mock_upsert_fc,
        ):
            content = BytesIO(b"test data")
            file_id = store.save_file(
                content=content,
                display_name="test.txt",
                file_origin=FileOrigin.OTHER,
                file_type="text/plain",
                file_id="my-file-id",
                db_session=mock_session,
            )

        assert file_id == "my-file-id"
        lobj.write.assert_called_once_with(b"test data")

        mock_upsert_fr.assert_called_once()
        fr_kwargs = mock_upsert_fr.call_args[1]
        assert fr_kwargs["file_id"] == "my-file-id"
        assert fr_kwargs["bucket_name"] == POSTGRES_BUCKET_SENTINEL
        assert fr_kwargs["object_key"] == "99"

        mock_upsert_fc.assert_called_once()
        fc_kwargs = mock_upsert_fc.call_args[1]
        assert fc_kwargs["lobj_oid"] == 99
        assert fc_kwargs["file_size"] == len(b"test data")

    @patch(
        "onyx.file_store.postgres_file_store.get_session_with_current_tenant_if_none"
    )
    def test_save_string_io_content(
        self,
        mock_get_session: MagicMock,
        store: PostgresBackedFileStore,
    ) -> None:
        """StringIO content should be encoded to UTF-8 bytes."""
        mock_session = MagicMock()
        mock_get_session.return_value = _make_session_ctx(mock_session)(None)

        raw_conn = MagicMock()
        lobj = _mock_lobject(oid=50)
        raw_conn.lobject.return_value = lobj
        mock_session.connection.return_value.connection.dbapi_connection = raw_conn

        with (
            patch("onyx.file_store.postgres_file_store.upsert_filerecord"),
            patch("onyx.file_store.postgres_file_store.upsert_file_content"),
        ):
            content = StringIO("text content")
            file_id = store.save_file(
                content=content,
                display_name="doc.txt",
                file_origin=FileOrigin.OTHER,
                file_type="text/plain",
                db_session=mock_session,
            )

        # Should have generated a UUID file_id
        assert file_id is not None
        lobj.write.assert_called_once_with(b"text content")

    @patch(
        "onyx.file_store.postgres_file_store.get_session_with_current_tenant_if_none"
    )
    def test_save_rolls_back_on_error(
        self,
        mock_get_session: MagicMock,
        store: PostgresBackedFileStore,
    ) -> None:
        mock_session = MagicMock()
        mock_get_session.return_value = _make_session_ctx(mock_session)(None)

        raw_conn = MagicMock()
        raw_conn.lobject.side_effect = RuntimeError("pg error")
        mock_session.connection.return_value.connection.dbapi_connection = raw_conn

        with pytest.raises(RuntimeError, match="pg error"):
            store.save_file(
                content=BytesIO(b"data"),
                display_name="fail.txt",
                file_origin=FileOrigin.OTHER,
                file_type="text/plain",
                db_session=mock_session,
            )
        mock_session.rollback.assert_called_once()


class TestReadFile:
    @patch(
        "onyx.file_store.postgres_file_store.get_session_with_current_tenant_if_none"
    )
    def test_read_file_in_memory(
        self,
        mock_get_session: MagicMock,
        store: PostgresBackedFileStore,
    ) -> None:
        mock_session = MagicMock()
        mock_get_session.return_value = _make_session_ctx(mock_session)(None)

        mock_record = MagicMock()
        mock_record.lobj_oid = 42

        raw_conn = MagicMock()
        lobj = _mock_lobject(oid=42, data=b"file contents")
        raw_conn.lobject.return_value = lobj
        mock_session.connection.return_value.connection.dbapi_connection = raw_conn

        with patch(
            "onyx.file_store.postgres_file_store.get_file_content_by_file_id",
            return_value=mock_record,
        ):
            result = store.read_file("my-file", db_session=mock_session)

        assert result.read() == b"file contents"


class TestDeleteFile:
    @patch(
        "onyx.file_store.postgres_file_store.get_session_with_current_tenant_if_none"
    )
    def test_delete_removes_lobject_and_records(
        self,
        mock_get_session: MagicMock,
        store: PostgresBackedFileStore,
    ) -> None:
        mock_session = MagicMock()
        mock_get_session.return_value = _make_session_ctx(mock_session)(None)

        mock_record = MagicMock()
        mock_record.lobj_oid = 77

        raw_conn = MagicMock()
        lobj = _mock_lobject(oid=77)
        raw_conn.lobject.return_value = lobj
        mock_session.connection.return_value.connection.dbapi_connection = raw_conn

        with (
            patch(
                "onyx.file_store.postgres_file_store.get_file_content_by_file_id",
                return_value=mock_record,
            ),
            patch(
                "onyx.file_store.postgres_file_store.delete_file_content_by_file_id"
            ) as mock_del_fc,
            patch(
                "onyx.file_store.postgres_file_store.delete_filerecord_by_file_id"
            ) as mock_del_fr,
        ):
            store.delete_file("file-77", db_session=mock_session)

        lobj.unlink.assert_called_once()
        mock_del_fc.assert_called_once()
        mock_del_fr.assert_called_once()
        mock_session.commit.assert_called_once()


class TestGetFileSize:
    @patch(
        "onyx.file_store.postgres_file_store.get_session_with_current_tenant_if_none"
    )
    def test_returns_stored_size(
        self,
        mock_get_session: MagicMock,
        store: PostgresBackedFileStore,
    ) -> None:
        mock_session = MagicMock()
        mock_get_session.return_value = _make_session_ctx(mock_session)(None)

        mock_record = MagicMock()
        mock_record.file_size = 1024

        with patch(
            "onyx.file_store.postgres_file_store.get_file_content_by_file_id",
            return_value=mock_record,
        ):
            size = store.get_file_size("file-1", db_session=mock_session)

        assert size == 1024

    @patch(
        "onyx.file_store.postgres_file_store.get_session_with_current_tenant_if_none"
    )
    def test_returns_none_on_error(
        self,
        mock_get_session: MagicMock,
        store: PostgresBackedFileStore,
    ) -> None:
        mock_session = MagicMock()
        mock_get_session.return_value = _make_session_ctx(mock_session)(None)

        with patch(
            "onyx.file_store.postgres_file_store.get_file_content_by_file_id",
            side_effect=RuntimeError("not found"),
        ):
            size = store.get_file_size("missing", db_session=mock_session)

        assert size is None


class TestChangeFileId:
    @patch(
        "onyx.file_store.postgres_file_store.get_session_with_current_tenant_if_none"
    )
    def test_reuses_same_lobject(
        self,
        mock_get_session: MagicMock,
        store: PostgresBackedFileStore,
    ) -> None:
        """Changing file ID should reuse the same large object (no copy)."""
        mock_session = MagicMock()
        mock_get_session.return_value = _make_session_ctx(mock_session)(None)

        old_fr = MagicMock()
        old_fr.display_name = "doc.pdf"
        old_fr.file_origin = FileOrigin.OTHER
        old_fr.file_type = "application/pdf"
        old_fr.file_metadata = None
        old_fr.object_key = "55"

        with (
            patch(
                "onyx.file_store.postgres_file_store.get_filerecord_by_file_id",
                return_value=old_fr,
            ),
            patch(
                "onyx.file_store.postgres_file_store.upsert_filerecord"
            ) as mock_upsert_fr,
            patch(
                "onyx.file_store.postgres_file_store.transfer_file_content_file_id"
            ) as mock_transfer,
            patch("onyx.file_store.postgres_file_store.delete_filerecord_by_file_id"),
        ):
            store.change_file_id("old-id", "new-id", db_session=mock_session)

        # file_content row should be moved in-place via transfer
        transfer_kwargs = mock_transfer.call_args[1]
        assert transfer_kwargs["old_file_id"] == "old-id"
        assert transfer_kwargs["new_file_id"] == "new-id"

        # New file_record should preserve the same object_key (LO OID)
        fr_kwargs = mock_upsert_fr.call_args[1]
        assert fr_kwargs["file_id"] == "new-id"
        assert fr_kwargs["object_key"] == "55"


class TestHasFile:
    @patch(
        "onyx.file_store.postgres_file_store.get_session_with_current_tenant_if_none"
    )
    def test_returns_true_when_present(
        self,
        mock_get_session: MagicMock,
        store: PostgresBackedFileStore,
    ) -> None:
        mock_session = MagicMock()
        mock_get_session.return_value = _make_session_ctx(mock_session)(None)

        record = MagicMock()
        record.file_origin = FileOrigin.OTHER
        record.file_type = "text/plain"

        with patch(
            "onyx.file_store.postgres_file_store.get_filerecord_by_file_id_optional",
            return_value=record,
        ):
            assert store.has_file(
                "f1", FileOrigin.OTHER, "text/plain", db_session=mock_session
            )

    @patch(
        "onyx.file_store.postgres_file_store.get_session_with_current_tenant_if_none"
    )
    def test_returns_false_when_absent(
        self,
        mock_get_session: MagicMock,
        store: PostgresBackedFileStore,
    ) -> None:
        mock_session = MagicMock()
        mock_get_session.return_value = _make_session_ctx(mock_session)(None)

        with patch(
            "onyx.file_store.postgres_file_store.get_filerecord_by_file_id_optional",
            return_value=None,
        ):
            assert not store.has_file(
                "missing", FileOrigin.OTHER, "text/plain", db_session=mock_session
            )


class TestReadContentBytes:
    def test_bytes_passthrough(self) -> None:
        result = PostgresBackedFileStore._read_content_bytes(BytesIO(b"raw"))
        assert result == b"raw"

    def test_string_encoded_to_utf8(self) -> None:
        result = PostgresBackedFileStore._read_content_bytes(StringIO("hello"))
        assert result == b"hello"
