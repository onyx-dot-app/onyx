from sqlalchemy import and_
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.background.task_utils import QUERY_REPORT_NAME_PREFIX
from onyx.configs.constants import FileOrigin
from onyx.configs.constants import FileType
from onyx.db.models import FileRecord


def get_query_history_export_files(
    db_session: Session,
) -> list[FileRecord]:
    return list(
        db_session.scalars(
            select(FileRecord).where(
                and_(
                    FileRecord.file_id.like(f"{QUERY_REPORT_NAME_PREFIX}-%"),
                    FileRecord.file_type == FileType.CSV,
                    FileRecord.file_origin == FileOrigin.QUERY_HISTORY_CSV,
                )
            )
        )
    )


def get_filerecord_by_file_id_optional(
    file_id: str,
    db_session: Session,
) -> FileRecord | None:
    return db_session.query(FileRecord).filter_by(file_id=file_id).first()


def get_filerecord_by_file_id(
    file_id: str,
    db_session: Session,
) -> FileRecord:
    filestore = db_session.query(FileRecord).filter_by(file_id=file_id).first()

    if not filestore:
        raise RuntimeError(f"File by id {file_id} does not exist or was deleted")

    return filestore


def get_filerecord_by_prefix(
    prefix: str,
    db_session: Session,
) -> list[FileRecord]:
    if not prefix:
        return db_session.query(FileRecord).all()
    return (
        db_session.query(FileRecord).filter(FileRecord.file_id.like(f"{prefix}%")).all()
    )


def delete_filerecord_by_file_id(
    file_id: str,
    db_session: Session,
) -> None:
    db_session.query(FileRecord).filter_by(file_id=file_id).delete()


def upsert_filerecord(
    file_id: str,
    display_name: str,
    file_origin: FileOrigin,
    file_type: str,
    bucket_name: str,
    object_key: str,
    db_session: Session,
    file_metadata: dict | None = None,
) -> FileRecord:
    """Create or update a file store record for external storage (S3, MinIO, etc.)"""
    filestore = db_session.query(FileRecord).filter_by(file_id=file_id).first()

    if filestore:
        filestore.display_name = display_name
        filestore.file_origin = file_origin
        filestore.file_type = file_type
        filestore.file_metadata = file_metadata
        filestore.bucket_name = bucket_name
        filestore.object_key = object_key
    else:
        filestore = FileRecord(
            file_id=file_id,
            display_name=display_name,
            file_origin=file_origin,
            file_type=file_type,
            file_metadata=file_metadata,
            bucket_name=bucket_name,
            object_key=object_key,
        )
        db_session.add(filestore)

    return filestore
