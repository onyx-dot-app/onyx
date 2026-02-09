"""PostgreSQL-backed file store using Large Objects.

Stores file content directly in PostgreSQL via the Large Object facility,
eliminating the need for an external S3/MinIO service.
"""

import tempfile
import uuid
from io import BytesIO
from typing import Any
from typing import cast
from typing import IO

import puremagic
from psycopg2.extensions import connection as Psycopg2Connection
from sqlalchemy.orm import Session

from onyx.configs.constants import FileOrigin
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.engine.sql_engine import get_session_with_current_tenant_if_none
from onyx.db.file_content import delete_file_content_by_file_id
from onyx.db.file_content import get_file_content_by_file_id
from onyx.db.file_content import get_file_content_by_file_id_optional
from onyx.db.file_content import transfer_file_content_file_id
from onyx.db.file_content import upsert_file_content
from onyx.db.file_record import delete_filerecord_by_file_id
from onyx.db.file_record import get_filerecord_by_file_id
from onyx.db.file_record import get_filerecord_by_file_id_optional
from onyx.db.file_record import get_filerecord_by_prefix
from onyx.db.file_record import upsert_filerecord
from onyx.db.models import FileRecord
from onyx.db.models import FileRecord as FileStoreModel
from onyx.file_store.file_store import FileStore
from onyx.utils.file import FileWithMimeType
from onyx.utils.logger import setup_logger

logger = setup_logger()

POSTGRES_BUCKET_SENTINEL = "postgres"
STREAM_CHUNK_SIZE = 8 * 1024 * 1024  # 8 MB


def _get_raw_connection(db_session: Session) -> Psycopg2Connection:
    """Extract the raw psycopg2 connection from a SQLAlchemy session."""
    raw_conn = db_session.connection().connection.dbapi_connection
    if raw_conn is None:
        raise ValueError("Failed to get raw connection from session")
    return cast(Psycopg2Connection, raw_conn)


def _create_large_object(raw_conn: Psycopg2Connection, data: bytes) -> int:
    """Create a new Large Object, write data, and return the OID."""
    lobj = raw_conn.lobject(0, "wb")
    lobj.write(data)
    oid: int = lobj.oid
    lobj.close()
    return oid


def _read_large_object(raw_conn: Psycopg2Connection, oid: int) -> bytes:
    """Read all bytes from a Large Object."""
    lobj = raw_conn.lobject(oid, "rb")
    data: bytes = lobj.read()
    lobj.close()
    return data


def _read_large_object_to_tempfile(raw_conn: Psycopg2Connection, oid: int) -> IO[bytes]:
    """Stream a Large Object into a temporary file to avoid OOM on large files."""
    lobj = raw_conn.lobject(oid, "rb")
    temp = tempfile.NamedTemporaryFile(mode="w+b", delete=True)
    while True:
        chunk = lobj.read(STREAM_CHUNK_SIZE)
        if not chunk:
            break
        temp.write(chunk)
    lobj.close()
    temp.seek(0)
    return temp


def _delete_large_object(raw_conn: Any, oid: int) -> None:
    """Unlink (delete) a Large Object by OID."""
    lobj = raw_conn.lobject(oid, "n")
    lobj.unlink()


class PostgresBackedFileStore(FileStore):
    """File store backed entirely by PostgreSQL.

    Metadata lives in `file_record`, content lives in PostgreSQL Large Objects
    with OID references tracked in `file_content`.
    """

    def initialize(self) -> None:
        # Nothing to do — tables are created by Alembic migrations.
        pass

    def has_file(
        self,
        file_id: str,
        file_origin: FileOrigin,
        file_type: str,
        db_session: Session | None = None,
    ) -> bool:
        with get_session_with_current_tenant_if_none(db_session) as session:
            record = get_filerecord_by_file_id_optional(
                file_id=file_id, db_session=session
            )
        return (
            record is not None
            and record.file_origin == file_origin
            and record.file_type == file_type
        )

    def save_file(
        self,
        content: IO,
        display_name: str | None,
        file_origin: FileOrigin,
        file_type: str,
        file_metadata: dict[str, Any] | None = None,
        file_id: str | None = None,
        db_session: Session | None = None,
    ) -> str:
        if file_id is None:
            file_id = str(uuid.uuid4())

        file_bytes = self._read_content_bytes(content)
        created_lo = False

        with get_session_with_current_tenant_if_none(db_session) as session:
            raw_conn, oid = None, None
            try:
                raw_conn = _get_raw_connection(session)

                # Look up existing content so we can unlink the old
                # Large Object after a successful overwrite.
                existing = get_file_content_by_file_id_optional(
                    file_id=file_id, db_session=session
                )
                old_oid = existing.lobj_oid if existing else None

                oid = _create_large_object(raw_conn, file_bytes)
                created_lo = True

                upsert_filerecord(
                    file_id=file_id,
                    display_name=display_name or file_id,
                    file_origin=file_origin,
                    file_type=file_type,
                    bucket_name=POSTGRES_BUCKET_SENTINEL,
                    object_key=str(oid),
                    db_session=session,
                    file_metadata=file_metadata,
                )
                upsert_file_content(
                    file_id=file_id,
                    lobj_oid=oid,
                    file_size=len(file_bytes),
                    db_session=session,
                )

                # Unlink the previous Large Object to avoid orphans
                if old_oid is not None and old_oid != oid:
                    try:
                        _delete_large_object(raw_conn, old_oid)
                    except Exception:
                        logger.warning(
                            f"Failed to unlink old large object {old_oid} "
                            f"for file {file_id}"
                        )

                session.commit()
            except Exception as e:
                session.rollback()
                try:
                    if created_lo and raw_conn is not None and oid is not None:
                        _delete_large_object(raw_conn, oid)
                except Exception:
                    logger.exception(
                        f"Failed to delete large object {oid} for file {file_id}"
                    )
                raise e

        return file_id

    def read_file(
        self,
        file_id: str,
        mode: str | None = None,  # noqa: ARG002
        use_tempfile: bool = False,
        db_session: Session | None = None,
    ) -> IO[bytes]:
        with get_session_with_current_tenant_if_none(db_session) as session:
            file_content = get_file_content_by_file_id(
                file_id=file_id, db_session=session
            )
            raw_conn = _get_raw_connection(session)

            if use_tempfile:
                return _read_large_object_to_tempfile(raw_conn, file_content.lobj_oid)

            data = _read_large_object(raw_conn, file_content.lobj_oid)
            return BytesIO(data)

    def read_file_record(
        self, file_id: str, db_session: Session | None = None
    ) -> FileStoreModel:
        with get_session_with_current_tenant_if_none(db_session) as session:
            return get_filerecord_by_file_id(file_id=file_id, db_session=session)

    def get_file_size(
        self, file_id: str, db_session: Session | None = None
    ) -> int | None:
        try:
            with get_session_with_current_tenant_if_none(db_session) as session:
                record = get_file_content_by_file_id(
                    file_id=file_id, db_session=session
                )
                return record.file_size
        except Exception as e:
            logger.warning(f"Error getting file size for {file_id}: {e}")
            return None

    def delete_file(self, file_id: str, db_session: Session | None = None) -> None:
        with get_session_with_current_tenant_if_none(db_session) as session:
            try:
                file_content = get_file_content_by_file_id(
                    file_id=file_id, db_session=session
                )
                raw_conn = _get_raw_connection(session)

                try:
                    _delete_large_object(raw_conn, file_content.lobj_oid)
                except Exception:
                    logger.warning(
                        f"Large object {file_content.lobj_oid} for file {file_id} "
                        "not found, cleaning up records only."
                    )

                delete_file_content_by_file_id(file_id=file_id, db_session=session)
                delete_filerecord_by_file_id(file_id=file_id, db_session=session)
                session.commit()
            except Exception:
                session.rollback()
                raise

    def get_file_with_mime_type(self, file_id: str) -> FileWithMimeType | None:
        mime_type = "application/octet-stream"
        try:
            file_io = self.read_file(file_id, mode="b")
        except Exception:
            return None

        file_content = file_io.read()
        try:
            matches = puremagic.magic_string(file_content)
            if matches:
                mime_type = cast(str, matches[0].mime_type)
        except puremagic.PureError:
            pass

        return FileWithMimeType(data=file_content, mime_type=mime_type)

    def change_file_id(
        self, old_file_id: str, new_file_id: str, db_session: Session | None = None
    ) -> None:
        with get_session_with_current_tenant_if_none(db_session) as session:
            try:
                old_record = get_filerecord_by_file_id(
                    file_id=old_file_id, db_session=session
                )
                file_metadata = cast(dict[Any, Any] | None, old_record.file_metadata)

                # 1. Create the new file_record so the FK target exists
                upsert_filerecord(
                    file_id=new_file_id,
                    display_name=old_record.display_name,
                    file_origin=old_record.file_origin,
                    file_type=old_record.file_type,
                    bucket_name=POSTGRES_BUCKET_SENTINEL,
                    object_key=old_record.object_key,
                    db_session=session,
                    file_metadata=file_metadata,
                )

                # 2. Move file_content in-place — the LO OID is never
                #    shared between two rows.
                transfer_file_content_file_id(
                    old_file_id=old_file_id,
                    new_file_id=new_file_id,
                    db_session=session,
                )

                # 3. Remove the now-orphaned old file_record
                delete_filerecord_by_file_id(file_id=old_file_id, db_session=session)

                session.commit()
            except Exception as e:
                session.rollback()
                logger.exception(
                    f"Failed to change file ID from {old_file_id} to {new_file_id}: {e}"
                )
                raise

    def list_files_by_prefix(self, prefix: str) -> list[FileRecord]:
        with get_session_with_current_tenant() as session:
            return get_filerecord_by_prefix(prefix=prefix, db_session=session)

    @staticmethod
    def _read_content_bytes(content: IO) -> bytes:
        """Normalize an IO object into raw bytes."""
        if hasattr(content, "read"):
            raw = content.read()
        else:
            raw = content

        if isinstance(raw, str):
            return raw.encode("utf-8")
        return raw
