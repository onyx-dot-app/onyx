"""External dependency tests for PostgresBackedFileStore.

These tests interact with a real PostgreSQL database — no mocking.
They exercise Large Object creation, reading, streaming, deletion,
and verify consistency between the file_record / file_content tables
and the underlying pg_largeobject storage.
"""

import uuid
from collections.abc import Generator
from io import BytesIO
from io import StringIO
from typing import Any
from typing import Dict
from typing import List

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import FileOrigin
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.file_content import get_file_content_by_file_id
from onyx.db.file_content import get_file_content_by_file_id_optional
from onyx.file_store.postgres_file_store import _get_raw_connection
from onyx.file_store.postgres_file_store import _read_large_object
from onyx.file_store.postgres_file_store import POSTGRES_BUCKET_SENTINEL
from onyx.file_store.postgres_file_store import PostgresBackedFileStore
from onyx.utils.logger import setup_logger

logger = setup_logger()


# ------------------------------------------------------------------ fixtures --


@pytest.fixture(scope="function")
def pg_file_store(
    db_session: Session,  # noqa: ARG001 — ensures engine is ready
    tenant_context: None,  # noqa: ARG001
) -> Generator[PostgresBackedFileStore, None, None]:
    """Provide a PostgresBackedFileStore wired to the real test database."""
    store = PostgresBackedFileStore()
    store.initialize()

    # Track file IDs so we can clean up after each test
    created_ids: list[str] = []
    original_save = store.save_file

    def _tracking_save(*args: Any, **kwargs: Any) -> str:
        file_id = original_save(*args, **kwargs)
        created_ids.append(file_id)
        return file_id

    store.save_file = _tracking_save  # type: ignore[method-assign]

    yield store

    # Cleanup: delete every file we created (including Large Objects)
    for fid in created_ids:
        try:
            store.delete_file(fid)
        except Exception:
            pass


# -------------------------------------------------------------------- tests --


class TestPostgresBackedFileStore:
    """Full integration tests against a real PostgreSQL instance."""

    # ── basic save / read ──────────────────────────────────────────

    def test_save_and_read_text_file(
        self, pg_file_store: PostgresBackedFileStore
    ) -> None:
        file_id = f"{uuid.uuid4()}.txt"
        content = "Hello, Postgres Large Objects!"

        returned_id = pg_file_store.save_file(
            content=BytesIO(content.encode()),
            display_name="greeting.txt",
            file_origin=FileOrigin.OTHER,
            file_type="text/plain",
            file_id=file_id,
        )

        assert returned_id == file_id

        result = pg_file_store.read_file(file_id)
        assert result.read().decode() == content

    def test_save_and_read_binary_file(
        self, pg_file_store: PostgresBackedFileStore
    ) -> None:
        file_id = f"{uuid.uuid4()}.bin"
        content = bytes(range(256))

        pg_file_store.save_file(
            content=BytesIO(content),
            display_name="binary.bin",
            file_origin=FileOrigin.CONNECTOR,
            file_type="application/octet-stream",
            file_id=file_id,
        )

        assert pg_file_store.read_file(file_id).read() == content

    def test_save_string_io(self, pg_file_store: PostgresBackedFileStore) -> None:
        """StringIO content should be transparently UTF-8 encoded."""
        file_id = f"{uuid.uuid4()}.txt"
        text = "StringIO content — including unicode: 测试 🚀"

        pg_file_store.save_file(
            content=StringIO(text),
            display_name="stringio.txt",
            file_origin=FileOrigin.OTHER,
            file_type="text/plain",
            file_id=file_id,
        )

        assert pg_file_store.read_file(file_id).read().decode() == text

    def test_auto_generated_file_id(
        self, pg_file_store: PostgresBackedFileStore
    ) -> None:
        """When no file_id is supplied, a UUID should be generated."""
        returned_id = pg_file_store.save_file(
            content=BytesIO(b"auto-id"),
            display_name="auto.txt",
            file_origin=FileOrigin.OTHER,
            file_type="text/plain",
        )

        # Should be a valid UUID
        uuid.UUID(returned_id)
        assert pg_file_store.read_file(returned_id).read() == b"auto-id"

    # ── read with tempfile (streaming) ─────────────────────────────

    def test_read_file_with_tempfile(
        self, pg_file_store: PostgresBackedFileStore
    ) -> None:
        file_id = f"{uuid.uuid4()}.txt"
        content = "Streamed via tempfile"

        pg_file_store.save_file(
            content=BytesIO(content.encode()),
            display_name="streamed.txt",
            file_origin=FileOrigin.OTHER,
            file_type="text/plain",
            file_id=file_id,
        )

        tmp = pg_file_store.read_file(file_id, use_tempfile=True)
        try:
            tmp.seek(0)
            assert tmp.read().decode() == content
        finally:
            tmp.close()

    # ── file record metadata ───────────────────────────────────────

    def test_file_record_fields(self, pg_file_store: PostgresBackedFileStore) -> None:
        file_id = f"{uuid.uuid4()}.json"
        metadata: Dict[str, Any] = {"source": "test", "version": 1}

        pg_file_store.save_file(
            content=BytesIO(b'{"k":"v"}'),
            display_name="meta.json",
            file_origin=FileOrigin.CHAT_UPLOAD,
            file_type="application/json",
            file_metadata=metadata,
            file_id=file_id,
        )

        record = pg_file_store.read_file_record(file_id)
        assert record.file_id == file_id
        assert record.display_name == "meta.json"
        assert record.file_origin == FileOrigin.CHAT_UPLOAD
        assert record.file_type == "application/json"
        assert record.file_metadata == metadata
        assert record.bucket_name == POSTGRES_BUCKET_SENTINEL

        # object_key should be the stringified Large Object OID
        oid = int(record.object_key)
        assert oid > 0

    def test_file_content_record(self, pg_file_store: PostgresBackedFileStore) -> None:
        """file_content row should track the OID and byte-size."""
        file_id = f"{uuid.uuid4()}.txt"
        payload = b"measure my size"

        pg_file_store.save_file(
            content=BytesIO(payload),
            display_name="sized.txt",
            file_origin=FileOrigin.OTHER,
            file_type="text/plain",
            file_id=file_id,
        )

        with get_session_with_current_tenant() as session:
            fc = get_file_content_by_file_id(file_id, session)
            assert fc.file_size == len(payload)
            assert fc.lobj_oid > 0

    # ── has_file ───────────────────────────────────────────────────

    def test_has_file(self, pg_file_store: PostgresBackedFileStore) -> None:
        file_id = f"{uuid.uuid4()}.txt"

        assert not pg_file_store.has_file(file_id, FileOrigin.OTHER, "text/plain")

        pg_file_store.save_file(
            content=BytesIO(b"exists"),
            display_name="exists.txt",
            file_origin=FileOrigin.OTHER,
            file_type="text/plain",
            file_id=file_id,
        )

        assert pg_file_store.has_file(file_id, FileOrigin.OTHER, "text/plain")
        # Wrong origin / type → False
        assert not pg_file_store.has_file(file_id, FileOrigin.CONNECTOR, "text/plain")
        assert not pg_file_store.has_file(file_id, FileOrigin.OTHER, "image/png")

    # ── get_file_size ──────────────────────────────────────────────

    def test_get_file_size(self, pg_file_store: PostgresBackedFileStore) -> None:
        file_id = f"{uuid.uuid4()}.txt"
        payload = b"exactly 24 bytes long!?!"

        pg_file_store.save_file(
            content=BytesIO(payload),
            display_name="sized.txt",
            file_origin=FileOrigin.OTHER,
            file_type="text/plain",
            file_id=file_id,
        )

        assert pg_file_store.get_file_size(file_id) == len(payload)

    def test_get_file_size_nonexistent(
        self, pg_file_store: PostgresBackedFileStore
    ) -> None:
        assert pg_file_store.get_file_size(f"{uuid.uuid4()}") is None

    # ── delete ─────────────────────────────────────────────────────

    def test_delete_file(self, pg_file_store: PostgresBackedFileStore) -> None:
        file_id = f"{uuid.uuid4()}.txt"

        pg_file_store.save_file(
            content=BytesIO(b"delete me"),
            display_name="doomed.txt",
            file_origin=FileOrigin.OTHER,
            file_type="text/plain",
            file_id=file_id,
        )

        pg_file_store.delete_file(file_id)

        assert not pg_file_store.has_file(file_id, FileOrigin.OTHER, "text/plain")

        with pytest.raises(RuntimeError, match="does not exist"):
            pg_file_store.read_file(file_id)

        # file_content row should also be gone
        with get_session_with_current_tenant() as session:
            assert get_file_content_by_file_id_optional(file_id, session) is None

    def test_delete_nonexistent_raises(
        self, pg_file_store: PostgresBackedFileStore
    ) -> None:
        with pytest.raises(RuntimeError, match="does not exist"):
            pg_file_store.delete_file(f"{uuid.uuid4()}")

    # ── overwrite (upsert) ─────────────────────────────────────────

    def test_overwrite_file(self, pg_file_store: PostgresBackedFileStore) -> None:
        file_id = f"{uuid.uuid4()}.txt"

        pg_file_store.save_file(
            content=BytesIO(b"original"),
            display_name="v1.txt",
            file_origin=FileOrigin.OTHER,
            file_type="text/plain",
            file_id=file_id,
        )

        assert pg_file_store.read_file(file_id).read() == b"original"

        # Capture the OID of the original Large Object
        with get_session_with_current_tenant() as session:
            old_oid = get_file_content_by_file_id(file_id, session).lobj_oid

        pg_file_store.save_file(
            content=BytesIO(b"overwritten"),
            display_name="v2.txt",
            file_origin=FileOrigin.OTHER,
            file_type="text/plain",
            file_id=file_id,
        )

        assert pg_file_store.read_file(file_id).read() == b"overwritten"

        # The old Large Object should have been unlinked
        with get_session_with_current_tenant() as session:
            new_oid = get_file_content_by_file_id(file_id, session).lobj_oid
            assert new_oid != old_oid

            raw_conn = _get_raw_connection(session)
            with pytest.raises(Exception):
                _read_large_object(raw_conn, old_oid)

    # ── change_file_id ─────────────────────────────────────────────

    def test_change_file_id(self, pg_file_store: PostgresBackedFileStore) -> None:
        old_id = f"{uuid.uuid4()}.txt"
        new_id = f"{uuid.uuid4()}.txt"
        content = b"portable content"

        pg_file_store.save_file(
            content=BytesIO(content),
            display_name="rename.txt",
            file_origin=FileOrigin.OTHER,
            file_type="text/plain",
            file_id=old_id,
        )

        pg_file_store.change_file_id(old_id, new_id)

        # Old ID should be gone
        assert not pg_file_store.has_file(old_id, FileOrigin.OTHER, "text/plain")

        # New ID should serve the same content
        assert pg_file_store.read_file(new_id).read() == content
        assert pg_file_store.get_file_size(new_id) == len(content)

        # Clean up the renamed file (fixture only tracks save_file calls)
        pg_file_store.delete_file(new_id)

    # ── list_files_by_prefix ───────────────────────────────────────

    def test_list_files_by_prefix(self, pg_file_store: PostgresBackedFileStore) -> None:
        prefix = f"batch-{uuid.uuid4().hex[:8]}-"

        # Create files with and without the prefix
        for i in range(3):
            pg_file_store.save_file(
                content=BytesIO(f"prefixed-{i}".encode()),
                display_name=f"p{i}.txt",
                file_origin=FileOrigin.OTHER,
                file_type="text/plain",
                file_id=f"{prefix}{i}.txt",
            )

        pg_file_store.save_file(
            content=BytesIO(b"unrelated"),
            display_name="other.txt",
            file_origin=FileOrigin.OTHER,
            file_type="text/plain",
            file_id=f"other-{uuid.uuid4()}.txt",
        )

        results = pg_file_store.list_files_by_prefix(prefix)
        returned_ids = [r.file_id for r in results]

        assert len(returned_ids) == 3
        for i in range(3):
            assert f"{prefix}{i}.txt" in returned_ids

    # ── get_file_with_mime_type ────────────────────────────────────

    def test_get_file_with_mime_type(
        self, pg_file_store: PostgresBackedFileStore
    ) -> None:
        file_id = f"{uuid.uuid4()}.txt"

        pg_file_store.save_file(
            content=BytesIO(b"plain text"),
            display_name="mime.txt",
            file_origin=FileOrigin.OTHER,
            file_type="text/plain",
            file_id=file_id,
        )

        result = pg_file_store.get_file_with_mime_type(file_id)
        assert result is not None
        assert result.data == b"plain text"
        assert result.mime_type is not None

    def test_get_file_with_mime_type_nonexistent(
        self, pg_file_store: PostgresBackedFileStore
    ) -> None:
        assert pg_file_store.get_file_with_mime_type(f"{uuid.uuid4()}") is None

    # ── error handling ─────────────────────────────────────────────

    def test_read_nonexistent_raises(
        self, pg_file_store: PostgresBackedFileStore
    ) -> None:
        with pytest.raises(RuntimeError, match="does not exist"):
            pg_file_store.read_file(f"{uuid.uuid4()}")

    def test_read_file_record_nonexistent_raises(
        self, pg_file_store: PostgresBackedFileStore
    ) -> None:
        with pytest.raises(RuntimeError, match="does not exist"):
            pg_file_store.read_file_record(f"{uuid.uuid4()}")

    # ── large file ─────────────────────────────────────────────────

    def test_large_file_roundtrip(self, pg_file_store: PostgresBackedFileStore) -> None:
        """Verify a 1 MB payload survives a full save / read cycle."""
        file_id = f"{uuid.uuid4()}.bin"
        content = b"X" * (1024 * 1024)

        pg_file_store.save_file(
            content=BytesIO(content),
            display_name="big.bin",
            file_origin=FileOrigin.CONNECTOR,
            file_type="application/octet-stream",
            file_id=file_id,
        )

        assert pg_file_store.read_file(file_id).read() == content
        assert pg_file_store.get_file_size(file_id) == len(content)

    # ── multiple files with different origins ──────────────────────

    def test_multiple_files_different_origins(
        self, pg_file_store: PostgresBackedFileStore
    ) -> None:
        files: List[Dict[str, Any]] = [
            {
                "id": f"{uuid.uuid4()}.txt",
                "content": b"chat upload",
                "origin": FileOrigin.CHAT_UPLOAD,
                "type": "text/plain",
            },
            {
                "id": f"{uuid.uuid4()}.json",
                "content": b'{"from":"connector"}',
                "origin": FileOrigin.CONNECTOR,
                "type": "application/json",
            },
            {
                "id": f"{uuid.uuid4()}.csv",
                "content": b"a,b\n1,2",
                "origin": FileOrigin.GENERATED_REPORT,
                "type": "text/csv",
            },
        ]

        for f in files:
            pg_file_store.save_file(
                content=BytesIO(f["content"]),
                display_name=f["id"],
                file_origin=f["origin"],
                file_type=f["type"],
                file_id=f["id"],
            )

        for f in files:
            assert pg_file_store.has_file(f["id"], f["origin"], f["type"])
            assert pg_file_store.read_file(f["id"]).read() == f["content"]

    # ── complex JSONB metadata ─────────────────────────────────────

    def test_complex_jsonb_metadata(
        self, pg_file_store: PostgresBackedFileStore
    ) -> None:
        file_id = f"{uuid.uuid4()}.json"
        metadata: Dict[str, Any] = {
            "nested": {"array": [1, 2, {"inner": True}], "null_val": None},
            "unicode": "测试 🚀",
            "large_text": "z" * 1000,
        }

        pg_file_store.save_file(
            content=BytesIO(b"{}"),
            display_name="meta.json",
            file_origin=FileOrigin.OTHER,
            file_type="application/json",
            file_metadata=metadata,
            file_id=file_id,
        )

        record = pg_file_store.read_file_record(file_id)
        assert record.file_metadata == metadata
