from datetime import timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from onyx.configs.constants import NUM_DAYS_TO_KEEP_INDEX_ATTEMPTS
from onyx.db.engine.time_utils import get_db_current_time
from onyx.db.models import IndexAttempt
from onyx.db.models import IndexAttemptError


# Always retain at least this many attempts per connector/search settings pair
NUM_RECENT_INDEX_ATTEMPTS_TO_KEEP = 10


def get_old_index_attempts(
    db_session: Session, days_to_keep: int = NUM_DAYS_TO_KEEP_INDEX_ATTEMPTS
) -> list[IndexAttempt]:
    """
    Get index attempts older than the specified number of days while retaining
    the latest NUM_RECENT_INDEX_ATTEMPTS_TO_KEEP per connector/search settings pair.
    """
    cutoff_date = get_db_current_time(db_session) - timedelta(days=days_to_keep)
    ranked_attempts = (
        db_session.query(
            IndexAttempt.id.label("attempt_id"),
            IndexAttempt.time_created.label("time_created"),
            func.row_number()
            .over(
                partition_by=(
                    IndexAttempt.connector_credential_pair_id,
                    IndexAttempt.search_settings_id,
                ),
                order_by=IndexAttempt.time_created.desc(),
            )
            .label("attempt_rank"),
        )
    ).subquery()

    return (
        db_session.query(IndexAttempt)
        .join(
            ranked_attempts,
            IndexAttempt.id == ranked_attempts.c.attempt_id,
        )
        .filter(
            ranked_attempts.c.time_created < cutoff_date,
            ranked_attempts.c.attempt_rank > NUM_RECENT_INDEX_ATTEMPTS_TO_KEEP,
        )
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
