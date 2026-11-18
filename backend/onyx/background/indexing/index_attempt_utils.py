from datetime import timedelta

from sqlalchemy.orm import Session

from onyx.configs.constants import NUM_DAYS_TO_KEEP_INDEX_ATTEMPTS
from onyx.db.engine.time_utils import get_db_current_time
from onyx.db.index_attempt import (
    delete_index_attempts_by_ids__no_commit,
    get_index_attempt_ids_past_retention,
    get_oldest_index_attempt_time_created,
)

# Always retain at least this many attempts per connector/search settings pair
NUM_RECENT_INDEX_ATTEMPTS_TO_KEEP = 10


def get_old_index_attempt_ids(
    db_session: Session, days_to_keep: int = NUM_DAYS_TO_KEEP_INDEX_ATTEMPTS
) -> list[int]:
    """
    Get IDs of index attempts older than the specified number of days while retaining
    the latest NUM_RECENT_INDEX_ATTEMPTS_TO_KEEP per connector/search settings pair.
    """
    cutoff_date = get_db_current_time(db_session) - timedelta(days=days_to_keep)

    # Short-circuit using the index on time_created. The window query below
    # cannot use an index (ROW_NUMBER must rank every row before WHERE can
    # filter), so when nothing is old enough to clean we skip it entirely.
    oldest = get_oldest_index_attempt_time_created(db_session)
    if oldest is None or oldest >= cutoff_date:
        return []

    return get_index_attempt_ids_past_retention(
        db_session=db_session,
        cutoff_date=cutoff_date,
        num_recent_to_keep=NUM_RECENT_INDEX_ATTEMPTS_TO_KEEP,
    )


def cleanup_index_attempts(db_session: Session, index_attempt_ids: list[int]) -> None:
    """Clean up multiple index attempts"""
    delete_index_attempts_by_ids__no_commit(db_session, index_attempt_ids)
    db_session.commit()
