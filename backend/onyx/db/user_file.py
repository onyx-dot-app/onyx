import datetime
from uuid import UUID

from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.models import UserFile


def fetch_chunk_counts_for_user_files(
    user_file_ids: list[str],
    db_session: Session,
) -> list[tuple[str, int]]:
    """
    Return a list of (user_file_id, chunk_count) tuples.
    If a user_file_id is not found in the database, it will be returned with a chunk_count of 0.
    """
    stmt = select(UserFile.id, UserFile.chunk_count).where(
        UserFile.id.in_(user_file_ids)
    )

    results = db_session.execute(stmt).all()

    # Create a dictionary of user_file_id to chunk_count
    chunk_counts = {str(row.id): row.chunk_count or 0 for row in results}

    # Return a list of tuples, preserving `None` for documents not found or with
    # an unknown chunk count. Callers should handle the `None` case and fall
    # back to an existence check against the vector DB if necessary.
    return [
        (user_file_id, chunk_counts.get(user_file_id, 0))
        for user_file_id in user_file_ids
    ]


def calculate_user_files_token_count(file_ids: list[UUID], db_session: Session) -> int:
    """Calculate total token count for specified files"""
    total_tokens = 0

    # Get tokens from individual files
    if file_ids:
        file_tokens = (
            db_session.query(func.sum(UserFile.token_count))
            .filter(UserFile.id.in_(file_ids))
            .scalar()
            or 0
        )
        total_tokens += file_tokens

    return total_tokens


def fetch_user_project_ids_for_user_files(
    user_file_ids: list[str],
    db_session: Session,
) -> dict[str, list[int]]:
    """Fetch user project ids for specified user files"""
    stmt = select(UserFile).where(UserFile.id.in_(user_file_ids))
    results = db_session.execute(stmt).scalars().all()
    return {
        str(user_file.id): [project.id for project in user_file.projects]
        for user_file in results
    }


def update_last_accessed_at_for_user_files(
    user_file_ids: list[UUID],
    db_session: Session,
) -> None:
    """Update `last_accessed_at` to now (UTC) for the given user files."""
    if not user_file_ids:
        return
    now = datetime.datetime.now(datetime.timezone.utc)
    (
        db_session.query(UserFile)
        .filter(UserFile.id.in_(user_file_ids))
        .update({UserFile.last_accessed_at: now}, synchronize_session=False)
    )
    db_session.commit()


def get_file_id_by_user_file_id(user_file_id: str, db_session: Session) -> str | None:
    user_file = db_session.query(UserFile).filter(UserFile.id == user_file_id).first()
    if user_file:
        return user_file.file_id
    return None
