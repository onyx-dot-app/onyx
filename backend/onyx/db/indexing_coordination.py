"""Database-based indexing coordination to replace Redis fencing."""

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from onyx.db.engine.time_utils import get_db_current_time
from onyx.db.enums import IndexingStatus
from onyx.db.index_attempt import count_error_rows_for_index_attempt
from onyx.db.index_attempt import create_index_attempt
from onyx.db.index_attempt import get_index_attempt
from onyx.db.models import IndexAttempt
from onyx.utils.logger import setup_logger

logger = setup_logger()

INDEXING_PROGRESS_TIMEOUT_HOURS = 6


class CoordinationStatus(BaseModel):
    """Status of an indexing attempt's coordination."""

    found: bool
    total_batches: int | None
    completed_batches: int
    total_failures: int
    total_docs: int
    total_chunks: int
    status: IndexingStatus | None = None
    cancellation_requested: bool = False


class IndexingCoordination:
    """Database-based coordination for indexing tasks, replacing Redis fencing."""

    @staticmethod
    def try_create_index_attempt(
        db_session: Session,
        cc_pair_id: int,
        search_settings_id: int,
        celery_task_id: str,
        from_beginning: bool = False,
    ) -> int | None:
        """
        Try to create a new index attempt for the given CC pair and search settings.
        Returns the index_attempt_id if successful, None if another attempt is already running.

        This replaces the Redis fencing mechanism by using database constraints
        and transactions to prevent duplicate attempts.
        """
        try:
            # Check for existing active attempts (this is the "fence" check)
            existing_attempt = db_session.execute(
                select(IndexAttempt)
                .where(
                    IndexAttempt.connector_credential_pair_id == cc_pair_id,
                    IndexAttempt.search_settings_id == search_settings_id,
                    IndexAttempt.status.in_(
                        [IndexingStatus.NOT_STARTED, IndexingStatus.IN_PROGRESS]
                    ),
                )
                .with_for_update(nowait=True)
            ).first()

            if existing_attempt:
                logger.info(
                    f"Indexing already in progress: "
                    f"cc_pair={cc_pair_id} "
                    f"search_settings={search_settings_id} "
                    f"existing_attempt={existing_attempt[0].id}"
                )
                return None

            # Create new index attempt (this is setting the "fence")
            attempt_id = create_index_attempt(
                connector_credential_pair_id=cc_pair_id,
                search_settings_id=search_settings_id,
                from_beginning=from_beginning,
                db_session=db_session,
                celery_task_id=celery_task_id,
            )

            logger.info(
                f"Created Index Attempt: "
                f"cc_pair={cc_pair_id} "
                f"search_settings={search_settings_id} "
                f"attempt_id={attempt_id} "
                f"celery_task_id={celery_task_id}"
            )

            return attempt_id

        except SQLAlchemyError as e:
            logger.info(
                f"Failed to create index attempt (likely race condition): "
                f"cc_pair={cc_pair_id} "
                f"search_settings={search_settings_id} "
                f"error={str(e)}"
            )
            db_session.rollback()
            return None

    @staticmethod
    def check_cancellation_requested(
        db_session: Session,
        index_attempt_id: int,
    ) -> bool:
        """
        Check if cancellation has been requested for this indexing attempt.
        This replaces Redis termination signals.
        """
        attempt = get_index_attempt(db_session, index_attempt_id)
        return attempt.cancellation_requested if attempt else False

    @staticmethod
    def request_cancellation(
        db_session: Session,
        index_attempt_id: int,
    ) -> None:
        """
        Request cancellation of an indexing attempt.
        This replaces Redis termination signals.
        """
        attempt = get_index_attempt(db_session, index_attempt_id)
        if attempt:
            attempt.cancellation_requested = True
            db_session.commit()

            logger.info(f"Requested cancellation for attempt {index_attempt_id}")

    @staticmethod
    def set_total_batches(
        db_session: Session,
        index_attempt_id: int,
        total_batches: int,
    ) -> None:
        """
        Set the total number of batches for this indexing attempt.
        Called by docfetching when extraction is complete.
        """
        attempt = get_index_attempt(db_session, index_attempt_id)
        if attempt:
            attempt.total_batches = total_batches
            db_session.commit()

            logger.info(
                f"Set total batches: attempt={index_attempt_id} total={total_batches}"
            )

    @staticmethod
    def update_batch_completion_and_docs(
        db_session: Session,
        index_attempt_id: int,
        total_docs_indexed: int,
        new_docs_indexed: int,
        total_chunks: int,
    ) -> tuple[int, int | None]:
        """
        Update batch completion and document counts atomically.
        Returns (completed_batches, total_batches).
        This extends the existing update_docs_indexed pattern.
        """
        try:
            attempt = db_session.execute(
                select(IndexAttempt)
                .where(IndexAttempt.id == index_attempt_id)
                .with_for_update()  # Same pattern as existing update_docs_indexed
            ).scalar_one()

            # Existing document count updates
            attempt.total_docs_indexed = (
                attempt.total_docs_indexed or 0
            ) + total_docs_indexed
            attempt.new_docs_indexed = (
                attempt.new_docs_indexed or 0
            ) + new_docs_indexed

            # New coordination updates
            attempt.completed_batches = (attempt.completed_batches or 0) + 1
            attempt.total_chunks = (attempt.total_chunks or 0) + total_chunks

            db_session.commit()

            logger.info(
                f"Updated batch completion: "
                f"attempt={index_attempt_id} "
                f"completed={attempt.completed_batches} "
                f"total={attempt.total_batches} "
                f"docs={total_docs_indexed} "
            )

            return attempt.completed_batches, attempt.total_batches

        except Exception:
            db_session.rollback()
            logger.exception(
                f"Failed to update batch completion for attempt {index_attempt_id}"
            )
            raise

    @staticmethod
    def get_coordination_status(
        db_session: Session,
        index_attempt_id: int,
    ) -> CoordinationStatus:
        """
        Get the current coordination status for an indexing attempt.
        This replaces reading FileStore state files.
        """
        attempt = get_index_attempt(db_session, index_attempt_id)
        if not attempt:
            return CoordinationStatus(
                found=False,
                total_batches=None,
                completed_batches=0,
                total_failures=0,
                total_docs=0,
                total_chunks=0,
                status=None,
                cancellation_requested=False,
            )

        return CoordinationStatus(
            found=True,
            total_batches=attempt.total_batches,
            completed_batches=attempt.completed_batches,
            total_failures=count_error_rows_for_index_attempt(
                index_attempt_id, db_session
            ),
            total_docs=attempt.total_docs_indexed or 0,
            total_chunks=attempt.total_chunks,
            status=attempt.status,
            cancellation_requested=attempt.cancellation_requested,
        )

    @staticmethod
    def get_orphaned_index_attempt_ids(db_session: Session) -> list[int]:
        """
        Gets a list of potentially orphaned index attempts.
        These are attempts in non-terminal state that have task IDs but may have died.

        This replaces the old get_unfenced_index_attempt_ids function.
        The actual orphan detection requires checking with Celery, which should be
        done by the caller.
        """
        # Find attempts that are active and have task IDs
        # The caller needs to check each one with Celery to confirm orphaned status
        active_attempts = (
            db_session.execute(
                select(IndexAttempt).where(
                    IndexAttempt.status.in_(
                        [IndexingStatus.NOT_STARTED, IndexingStatus.IN_PROGRESS]
                    ),
                    IndexAttempt.celery_task_id.isnot(None),
                )
            )
            .scalars()
            .all()
        )

        return [attempt.id for attempt in active_attempts]

    @staticmethod
    def update_progress_tracking(
        db_session: Session,
        index_attempt_id: int,
        current_batches_completed: int,
        timeout_hours: int = INDEXING_PROGRESS_TIMEOUT_HOURS,
        force_update_progress: bool = False,
    ) -> bool:
        """
        Update progress tracking for stall detection.
        Returns True if sufficient progress was made, False if stalled.
        """

        attempt = get_index_attempt(db_session, index_attempt_id)
        if not attempt:
            logger.error(f"Index attempt {index_attempt_id} not found in database")
            return False

        current_time = get_db_current_time(db_session)

        # No progress - check if this is the first time tracking
        # or if the caller wants to simulate guaranteed progress
        if attempt.last_progress_time is None or force_update_progress:
            # First time tracking - initialize
            attempt.last_progress_time = current_time
            attempt.last_batches_completed_count = current_batches_completed
            db_session.commit()
            return True

        time_elapsed = (current_time - attempt.last_progress_time).total_seconds()
        # only actually write to db every timeout_hours/2
        # this ensure thats at most timeout_hours will pass with no activity
        if time_elapsed < timeout_hours * 1800:
            return True

        # Check if progress has been made
        if current_batches_completed <= attempt.last_batches_completed_count:
            # if between timeout_hours/2 and timeout_hours has passed
            # without an update, we consider the attempt stalled
            return False

        # Progress made - update tracking
        attempt.last_progress_time = current_time
        attempt.last_batches_completed_count = current_batches_completed
        db_session.commit()
        return True
