"""Kept around since it's used in the migration to move to S3/MinIO"""

import tempfile
from io import BytesIO
from typing import IO

from psycopg2.extensions import connection
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
    """Note, this does not commit the changes to the DB
    This is because the commit should happen with the FileStore row creation
    That step finalizes both the Large Object and the table tracking it
    """
    pg_conn = get_pg_conn_from_session(db_session)
    large_object = pg_conn.lobject()

    # write in multiple chunks to avoid loading the whole file into memory
    while True:
        chunk = content.read(STANDARD_CHUNK_SIZE)
        if not chunk:
            break
        large_object.write(chunk)

    large_object.close()

    return large_object.oid


def read_lobj(
    lobj_oid: int,
    db_session: Session,
    mode: str | None = None,
    use_tempfile: bool = False,
) -> IO:
    pg_conn = get_pg_conn_from_session(db_session)
    # Ensure we're using binary mode by default for large objects
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
        # Ensure we're getting raw bytes without text decoding
        return BytesIO(large_object.read())


def delete_lobj_by_id(
    lobj_oid: int,
    db_session: Session,
) -> None:
    pg_conn = get_pg_conn_from_session(db_session)
    pg_conn.lobject(lobj_oid).unlink()
