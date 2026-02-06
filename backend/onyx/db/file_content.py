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
    record = db_session.query(FileContent).filter_by(file_id=file_id).first()
    if record:
        record.lobj_oid = lobj_oid
        record.file_size = file_size
    else:
        record = FileContent(
            file_id=file_id,
            lobj_oid=lobj_oid,
            file_size=file_size,
        )
        db_session.add(record)
    return record


def delete_file_content_by_file_id(
    file_id: str,
    db_session: Session,
) -> None:
    db_session.query(FileContent).filter_by(file_id=file_id).delete()
