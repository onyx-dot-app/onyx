from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from onyx.db.models import FileContent


def get_file_content_by_file_id(
    file_id: str,
    db_session: Session,
) -> FileContent:
    record = db_session.query(FileContent).filter_by(file_id=file_id).first()
    if not record:
        raise RuntimeError(
            f"File content for file_id {file_id} does not exist or was deleted"
        )
    return record


def get_file_content_by_file_id_optional(
    file_id: str,
    db_session: Session,
) -> FileContent | None:
    return db_session.query(FileContent).filter_by(file_id=file_id).first()


def upsert_file_content(
    file_id: str,
    lobj_oid: int,
    file_size: int,
    db_session: Session,
) -> FileContent:
    """Atomic upsert using INSERT ... ON CONFLICT DO UPDATE to avoid
    race conditions when concurrent calls target the same file_id."""
    stmt = insert(FileContent).values(
        file_id=file_id,
        lobj_oid=lobj_oid,
        file_size=file_size,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[FileContent.file_id],
        set_={
            "lobj_oid": stmt.excluded.lobj_oid,
            "file_size": stmt.excluded.file_size,
        },
    )
    db_session.execute(stmt)

    # Return the merged ORM instance so callers can inspect the result
    return db_session.get(FileContent, file_id)  # type: ignore[return-value]


def transfer_file_content_file_id(
    old_file_id: str,
    new_file_id: str,
    db_session: Session,
) -> None:
    """Move a file_content row from old_file_id to new_file_id in-place.

    This avoids creating a duplicate row that shares the same Large Object OID,
    keeping OID ownership unique at all times.  The caller must ensure that
    new_file_id already exists in file_record (FK target)."""
    rows = (
        db_session.query(FileContent)
        .filter_by(file_id=old_file_id)
        .update({"file_id": new_file_id})
    )
    if not rows:
        raise RuntimeError(
            f"File content for file_id {old_file_id} does not exist or was deleted"
        )


def delete_file_content_by_file_id(
    file_id: str,
    db_session: Session,
) -> None:
    db_session.query(FileContent).filter_by(file_id=file_id).delete()
