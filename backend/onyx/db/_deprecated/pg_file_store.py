"""Kept around since it's used in the migration to move to S3/MinIO"""

import tempfile
from io import BytesIO
from typing import IO

from psycopg2.extensions import connection
from sqlalchemy import text  # NEW: for SQL large-object helpers
from sqlalchemy.orm import Session

from onyx.file_store.constants import MAX_IN_MEMORY_SIZE
from onyx.file_store.constants import STANDARD_CHUNK_SIZE
from onyx.utils.logger import setup_logger

logger = setup_logger()


def get_pg_conn_from_session(db_session: Session) -> connection:
    return db_session.connection().connection.connection  # type: ignore


def create_populate_lobj(
    content: IO,
    db_session: Session,
) -> int:
    """Create a PostgreSQL large object from *content* and return its OID.

    Preferred approach is to use the psycopg2 ``lobject`` API, but if that is
    unavailable (e.g. when the underlying connection is an asyncpg adapter)
    we fall back to PostgreSQL helper functions such as ``lo_from_bytea``.

    NOTE: this function intentionally *does not* commit the surrounding
    transaction – that is handled by the caller so all work stays atomic.
    """

    pg_conn = None
    try:
        pg_conn = get_pg_conn_from_session(db_session)
        # ``AsyncAdapt_asyncpg_connection`` (asyncpg) has no ``lobject``
        if not hasattr(pg_conn, "lobject"):
            raise AttributeError  # will be handled by fallback below

        large_object = pg_conn.lobject()

        # write in multiple chunks to avoid loading the whole file into memory
        while True:
            chunk = content.read(STANDARD_CHUNK_SIZE)
            if not chunk:
                break
            large_object.write(chunk)

        large_object.close()

        return large_object.oid

    except AttributeError:
        # Fall back to SQL helper functions – read the full content into memory
        # (acceptable for the limited number and size of files handled during
        # migrations).  ``lo_from_bytea`` returns the new OID.
        byte_data = content.read()
        result = db_session.execute(
            text("SELECT lo_from_bytea(0, :data) AS oid"),
            {"data": byte_data},
        )
        # ``scalar_one`` is 2.0-style; ``scalar`` works on both 1.4/2.0.
        lobj_oid = result.scalar()
        if lobj_oid is None:
            raise RuntimeError("Failed to create large object")
        return int(lobj_oid)


def read_lobj(
    lobj_oid: int,
    db_session: Session,
    mode: str | None = None,
    use_tempfile: bool = False,
) -> IO:
    """Read a PostgreSQL large object identified by *lobj_oid*.

    Attempts to use the native ``lobject`` API first; if unavailable falls back
    to ``lo_get`` which returns the large object's contents as *bytea*.
    """

    pg_conn = None
    try:
        pg_conn = get_pg_conn_from_session(db_session)
        if not hasattr(pg_conn, "lobject"):
            raise AttributeError

        # Ensure binary mode by default
        if mode is None:
            mode = "rb"
        large_object = (
            pg_conn.lobject(lobj_oid, mode=mode) if mode else pg_conn.lobject(lobj_oid)
        )

        if use_tempfile:
            temp_file = tempfile.SpooledTemporaryFile(max_size=MAX_IN_MEMORY_SIZE)
            while True:
                chunk = large_object.read(STANDARD_CHUNK_SIZE)
                if not chunk:
                    break
                temp_file.write(chunk)
            temp_file.seek(0)
            return temp_file
        else:
            return BytesIO(large_object.read())

    except AttributeError:
        # Fallback path using ``lo_get``
        result = db_session.execute(
            text("SELECT lo_get(:oid) AS data"),
            {"oid": lobj_oid},
        )
        byte_data = result.scalar()
        if byte_data is None:
            raise RuntimeError("Failed to read large object")

        if use_tempfile:
            temp_file = tempfile.SpooledTemporaryFile(max_size=MAX_IN_MEMORY_SIZE)
            temp_file.write(byte_data)
            temp_file.seek(0)
            return temp_file
        return BytesIO(byte_data)


def delete_lobj_by_id(
    lobj_oid: int,
    db_session: Session,
) -> None:
    """Remove a large object by OID, regardless of driver implementation."""

    try:
        pg_conn = get_pg_conn_from_session(db_session)
        if hasattr(pg_conn, "lobject"):
            pg_conn.lobject(lobj_oid).unlink()
            return
        raise AttributeError
    except AttributeError:
        # Fallback for drivers without ``lobject`` support
        db_session.execute(text("SELECT lo_unlink(:oid)"), {"oid": lobj_oid})
        # No explicit result expected
