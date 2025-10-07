from datetime import timedelta

from sqlalchemy.orm import Session

from onyx.configs.constants import NUM_DAYS_TO_KEEP_INDEX_ATTEMPTS
from onyx.db.engine.time_utils import get_db_current_time
from onyx.db.models import IndexAttempt
from onyx.db.models import IndexAttemptError


def get_old_index_attempts(
    db_session: Session, days_to_keep: int = NUM_DAYS_TO_KEEP_INDEX_ATTEMPTS
) -> list[IndexAttempt]:
    """Get all index attempts older than the specified number of days."""
    cutoff_date = get_db_current_time(db_session) - timedelta(days=days_to_keep)
    return (
        db_session.query(IndexAttempt)
        .filter(IndexAttempt.time_created < cutoff_date)
        .all()
    )


def cleanup_index_attempts(db_session: Session, index_attempt_ids: list[int]) -> None:
    """Clean up multiple index attempts"""
    db_session.query(IndexAttemptError).filter(
        IndexAttemptError.index_attempt_id.in_(index_attempt_ids)
    ).delete(synchronize_session=False)

    db_session.query(IndexAttempt).filter(
        IndexAttempt.id.in_(index_attempt_ids)
    ).delete(synchronize_session=False)
    db_session.commit()
