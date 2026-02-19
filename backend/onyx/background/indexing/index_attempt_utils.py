from datetime import timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from onyx.configs.constants import NUM_DAYS_TO_KEEP_INDEX_ATTEMPTS
from onyx.db.engine.time_utils import get_db_current_time
from onyx.db.enums import IndexingStatus
from onyx.db.models import IndexAttempt
from onyx.db.models import IndexAttemptError


# Always retain at least this many attempts per connector/search settings pair
NUM_RECENT_INDEX_ATTEMPTS_TO_KEEP = 10
TERMINAL_INDEX_ATTEMPT_STATUSES = (
    IndexingStatus.SUCCESS,
    IndexingStatus.COMPLETED_WITH_ERRORS,
    IndexingStatus.CANCELED,
    IndexingStatus.FAILED,
)


def get_old_index_attempts(
    db_session: Session,
    days_to_keep: int = NUM_DAYS_TO_KEEP_INDEX_ATTEMPTS,
    limit: int | None = None,
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

    query = (
        db_session.query(IndexAttempt)
        .join(
            ranked_attempts,
            IndexAttempt.id == ranked_attempts.c.attempt_id,
        )
        .filter(
            ranked_attempts.c.time_created < cutoff_date,
            ranked_attempts.c.attempt_rank > NUM_RECENT_INDEX_ATTEMPTS_TO_KEEP,
            IndexAttempt.status.in_(TERMINAL_INDEX_ATTEMPT_STATUSES),
        )
        .order_by(ranked_attempts.c.time_created.asc())
    )

    if limit is not None:
        query = query.limit(limit)

    return query.all()


def cleanup_index_attempts(db_session: Session, index_attempt_ids: list[int]) -> None:
    """Clean up multiple index attempts"""
    if not index_attempt_ids:
        return

    # Keep each transaction smaller to reduce lock duration and WAL bursts.
    sub_batch_size = 100
    for i in range(0, len(index_attempt_ids), sub_batch_size):
        sub_batch = index_attempt_ids[i : i + sub_batch_size]

        db_session.query(IndexAttemptError).filter(
            IndexAttemptError.index_attempt_id.in_(sub_batch)
        ).delete(synchronize_session=False)

        db_session.query(IndexAttempt).filter(IndexAttempt.id.in_(sub_batch)).delete(
            synchronize_session=False
        )
        db_session.commit()
