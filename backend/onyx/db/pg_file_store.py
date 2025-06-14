import tempfile
from io import BytesIO
from typing import IO

from psycopg2.extensions import connection
from sqlalchemy.orm import Session
from sqlalchemy.sql import and_
from sqlalchemy.sql import select

from onyx.background.task_utils import QUERY_REPORT_NAME_PREFIX
from onyx.configs.constants import FileOrigin
from onyx.configs.constants import FileType
from onyx.db.models import FileStore
from onyx.file_store.constants import MAX_IN_MEMORY_SIZE
from onyx.file_store.constants import STANDARD_CHUNK_SIZE
from onyx.utils.logger import setup_logger

logger = setup_logger()


def get_pg_conn_from_session(db_session: Session) -> connection:
    return db_session.connection().connection.connection  # type: ignore


def get_pgfilestore_by_file_name_optional(
    file_name: str,
    db_session: Session,
) -> FileStore | None:
    return db_session.query(FileStore).filter_by(file_name=file_name).first()


def get_pgfilestore_by_file_name(
    file_name: str,
    db_session: Session,
) -> FileStore:
    pgfilestore = db_session.query(FileStore).filter_by(file_name=file_name).first()

    if not pgfilestore:
        raise RuntimeError(f"File by name {file_name} does not exist or was deleted")

    return pgfilestore


def delete_pgfilestore_by_file_name(
    file_name: str,
    db_session: Session,
) -> None:
    db_session.query(FileStore).filter_by(file_name=file_name).delete()


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


def delete_lobj_by_name(
    lobj_name: str,
    db_session: Session,
) -> None:
    try:
        pgfilestore = get_pgfilestore_by_file_name(lobj_name, db_session)
    except RuntimeError:
        logger.info(f"no file with name {lobj_name} found")
        return

    pg_conn = get_pg_conn_from_session(db_session)
    pg_conn.lobject(pgfilestore.lobj_oid).unlink()

    delete_pgfilestore_by_file_name(lobj_name, db_session)
    db_session.commit()


def upsert_pgfilestore(
    file_name: str,
    display_name: str | None,
    file_origin: FileOrigin,
    file_type: str,
    lobj_oid: int,
    db_session: Session,
    commit: bool = False,
    file_metadata: dict | None = None,
) -> FileStore:
    pgfilestore = db_session.query(FileStore).filter_by(file_name=file_name).first()

    if pgfilestore:
        try:
            # This should not happen in normal execution
            delete_lobj_by_id(lobj_oid=pgfilestore.lobj_oid, db_session=db_session)
        except Exception:
            # If the delete fails as well, the large object doesn't exist anyway and even if it
            # fails to delete, it's not too terrible as most files sizes are insignificant
            logger.error(
                f"Failed to delete large object with oid {pgfilestore.lobj_oid}"
            )

        pgfilestore.lobj_oid = lobj_oid
    else:
        pgfilestore = FileStore(
            file_name=file_name,
            display_name=display_name,
            file_origin=file_origin,
            file_type=file_type,
            file_metadata=file_metadata,
            lobj_oid=lobj_oid,
        )
        db_session.add(pgfilestore)

    if commit:
        db_session.commit()

    return pgfilestore


def save_bytes_to_pgfilestore(
    db_session: Session,
    raw_bytes: bytes,
    media_type: str,
    identifier: str,
    display_name: str,
    file_origin: FileOrigin = FileOrigin.OTHER,
) -> FileStore:
    """
    Saves raw bytes to FileStore and returns the resulting record.
    """
    file_name = f"{file_origin.name.lower()}_{identifier}"
    lobj_oid = create_populate_lobj(BytesIO(raw_bytes), db_session)
    pgfilestore = upsert_pgfilestore(
        file_name=file_name,
        display_name=display_name,
        file_origin=file_origin,
        file_type=media_type,
        lobj_oid=lobj_oid,
        db_session=db_session,
        commit=True,
    )
    return pgfilestore


def get_query_history_export_files(
    db_session: Session,
) -> list[FileStore]:
    return list(
        db_session.scalars(
            select(FileStore).where(
                and_(
                    FileStore.file_name.like(f"{QUERY_REPORT_NAME_PREFIX}-%"),
                    FileStore.file_type == FileType.CSV,
                    FileStore.file_origin == FileOrigin.QUERY_HISTORY_CSV,
                )
            )
        )
    )


# New unified file store functions
def get_filestore_by_file_name_optional(
    file_name: str,
    db_session: Session,
) -> FileStore | None:
    return db_session.query(FileStore).filter_by(file_name=file_name).first()


def get_filestore_by_file_name(
    file_name: str,
    db_session: Session,
) -> FileStore:
    filestore = db_session.query(FileStore).filter_by(file_name=file_name).first()

    if not filestore:
        raise RuntimeError(f"File by name {file_name} does not exist or was deleted")

    return filestore


def delete_filestore_by_file_name(
    file_name: str,
    db_session: Session,
) -> None:
    db_session.query(FileStore).filter_by(file_name=file_name).delete()


def upsert_filestore_postgres(
    file_name: str,
    display_name: str,
    file_origin: FileOrigin,
    file_type: str,
    lobj_oid: int,
    db_session: Session,
    file_metadata: dict | None = None,
) -> FileStore:
    """Create or update a file store record for PostgreSQL large object storage"""
    filestore = db_session.query(FileStore).filter_by(file_name=file_name).first()

    if filestore:
        # If switching from external to PostgreSQL storage, clean up old values
        filestore.display_name = display_name
        filestore.file_origin = file_origin
        filestore.file_type = file_type
        filestore.file_metadata = file_metadata
        filestore.lobj_oid = lobj_oid
        filestore.bucket_name = None
        filestore.object_key = None
    else:
        filestore = FileStore(
            file_name=file_name,
            display_name=display_name,
            file_origin=file_origin,
            file_type=file_type,
            file_metadata=file_metadata,
            lobj_oid=lobj_oid,
            bucket_name=None,
            object_key=None,
        )
        db_session.add(filestore)

    return filestore


def upsert_filestore_external(
    file_name: str,
    display_name: str,
    file_origin: FileOrigin,
    file_type: str,
    bucket_name: str,
    object_key: str,
    db_session: Session,
    file_metadata: dict | None = None,
) -> FileStore:
    """Create or update a file store record for external storage (S3, MinIO, etc.)"""
    filestore = db_session.query(FileStore).filter_by(file_name=file_name).first()

    if filestore:
        # If switching from PostgreSQL to external storage, clean up old large object
        if filestore.lobj_oid is not None:
            try:
                delete_lobj_by_id(lobj_oid=filestore.lobj_oid, db_session=db_session)
            except Exception:
                logger.error(
                    f"Failed to delete large object with oid {filestore.lobj_oid}"
                )

        filestore.display_name = display_name
        filestore.file_origin = file_origin
        filestore.file_type = file_type
        filestore.file_metadata = file_metadata
        filestore.bucket_name = bucket_name
        filestore.object_key = object_key
        filestore.lobj_oid = None
    else:
        filestore = FileStore(
            file_name=file_name,
            display_name=display_name,
            file_origin=file_origin,
            file_type=file_type,
            file_metadata=file_metadata,
            bucket_name=bucket_name,
            object_key=object_key,
            lobj_oid=None,
        )
        db_session.add(filestore)

    return filestore
