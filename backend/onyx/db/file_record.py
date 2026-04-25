from sqlalchemy import and_
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
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


def update_filerecord_origin(
    file_id: str,
    from_origin: FileOrigin,
    to_origin: FileOrigin,
    db_session: Session,
) -> None:
    """Change a file_record's `file_origin`, filtered on the current origin
    so the update is idempotent. Caller owns the commit.
    """
    db_session.query(FileRecord).filter(
        FileRecord.file_id == file_id,
        FileRecord.file_origin == from_origin,
    ).update({FileRecord.file_origin: to_origin})


def get_staged_file_ids_by_index_attempt_id(
    index_attempt_id: int,
    db_session: Session,
) -> list[str]:
    """Return every `INDEXING_STAGING` file_id tagged with this attempt."""
    return list(
        db_session.scalars(
            select(FileRecord.file_id)
            .where(FileRecord.file_origin == FileOrigin.INDEXING_STAGING)
            .where(
                FileRecord.file_metadata["index_attempt_id"].as_string()
                == str(index_attempt_id)
            )
        ).all()
    )


def get_staged_file_ids_for_cc_pair_excluding_attempt(
    cc_pair_id: int,
    tenant_id: str,
    excluding_attempt_id: int,
    db_session: Session,
) -> list[str]:
    """Return `INDEXING_STAGING` file_ids for this cc_pair owned by any
    attempt OTHER than `excluding_attempt_id`. Used for the start-of-run
    orphan sweep — anything matching is by definition left over from a
    previous attempt on the same cc_pair."""
    return list(
        db_session.scalars(
            select(FileRecord.file_id)
            .where(FileRecord.file_origin == FileOrigin.INDEXING_STAGING)
            .where(
                FileRecord.file_metadata["cc_pair_id"].as_string() == str(cc_pair_id)
            )
            .where(FileRecord.file_metadata["tenant_id"].as_string() == tenant_id)
            .where(
                FileRecord.file_metadata["index_attempt_id"].as_string()
                != str(excluding_attempt_id)
            )
        ).all()
    )


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
    """Atomic upsert using INSERT ... ON CONFLICT DO UPDATE to avoid
    race conditions when concurrent calls target the same file_id."""
    stmt = insert(FileRecord).values(
        file_id=file_id,
        display_name=display_name,
        file_origin=file_origin,
        file_type=file_type,
        file_metadata=file_metadata,
        bucket_name=bucket_name,
        object_key=object_key,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[FileRecord.file_id],
        set_={
            "display_name": stmt.excluded.display_name,
            "file_origin": stmt.excluded.file_origin,
            "file_type": stmt.excluded.file_type,
            "file_metadata": stmt.excluded.file_metadata,
            "bucket_name": stmt.excluded.bucket_name,
            "object_key": stmt.excluded.object_key,
        },
    )
    db_session.execute(stmt)

    return db_session.get(FileRecord, file_id)  # ty: ignore[invalid-return-type]
