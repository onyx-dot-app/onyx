"""Database-based indexing coordination to replace Redis fencing."""

from pydantic import BaseModel
from sqlalchemy import select, text, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from onyx.db.backfill_models import BackfillSpec
from onyx.db.enums import IndexingStatus
from onyx.db.index_attempt import (
    count_error_rows_for_index_attempt,
    create_index_attempt,
    get_index_attempt,
)
from onyx.db.models import IndexAttempt
from onyx.utils.logger import setup_logger

logger = setup_logger()


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
        # None creates the attempt without its docfetching task, to send later.
        celery_task_id: str | None,
        from_beginning: bool = False,
        backfill: BackfillSpec | None = None,
    ) -> int | None:
        """
        Try to create a new index attempt for the given CC pair and search settings.
        Returns the index_attempt_id if successful, None if another attempt is already running.

        This replaces the Redis fencing mechanism by using database constraints
        and transactions to prevent duplicate attempts.
        """
        try:
            # Check for existing active full-run attempts (the "fence" check).
            # Targeted reindex attempts are allowed to overlap with a full crawl
            # by design (per-doc row-locks handle write conflicts), so they're
            # excluded here. A backfill runs the connector like a full run, so
            # it fences and is fenced.
            existing_attempt = db_session.execute(
                select(IndexAttempt)
                .where(
                    IndexAttempt.connector_credential_pair_id == cc_pair_id,
                    IndexAttempt.search_settings_id == search_settings_id,
                    IndexAttempt.status.in_(
                        [IndexingStatus.NOT_STARTED, IndexingStatus.IN_PROGRESS]
                    ),
                    IndexAttempt.targeted_reindex_job_id.is_(None),
                )
                .with_for_update(nowait=True)
            ).first()

            if existing_attempt:
                logger.info(
                    "Indexing already in progress: cc_pair=%s search_settings=%s existing_attempt=%s",
                    cc_pair_id,
                    search_settings_id,
                    existing_attempt[0].id,
                )
                return None

            # Create new index attempt (this is setting the "fence")
            attempt_id = create_index_attempt(
                connector_credential_pair_id=cc_pair_id,
                search_settings_id=search_settings_id,
                from_beginning=from_beginning,
                db_session=db_session,
                celery_task_id=celery_task_id,
                backfill=backfill,
            )

            logger.info(
                "Created Index Attempt: cc_pair=%s search_settings=%s attempt_id=%s celery_task_id=%s is_backfill=%s",
                cc_pair_id,
                search_settings_id,
                attempt_id,
                celery_task_id,
                backfill is not None,
            )

            return attempt_id

        except SQLAlchemyError as e:
            logger.info(
                "Failed to create index attempt (likely race condition): cc_pair=%s search_settings=%s error=%s",
                cc_pair_id,
                search_settings_id,
                str(e),
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
    def request_cancellation__no_commit(
        db_session: Session,
        index_attempt_id: int,
    ) -> None:
        """Flags the attempt for cancellation; its task reads the flag. The
        caller commits."""
        attempt = get_index_attempt(db_session, index_attempt_id)
        if attempt:
            attempt.cancellation_requested = True
            logger.info("Requested cancellation for attempt %s", index_attempt_id)

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
                "Set total batches: attempt=%s total=%s",
                index_attempt_id,
                total_batches,
            )

    @staticmethod
    def get_completed_batches(db_session: Session, index_attempt_id: int) -> int:
        """Reads the count from the database. A column query skips the
        session's identity map, so an attempt loaded earlier cannot make it stale."""
        completed = db_session.scalar(
            select(IndexAttempt.completed_batches).where(
                IndexAttempt.id == index_attempt_id
            )
        )
        return completed or 0

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
                "Updated batch completion: attempt=%s completed=%s total=%s docs=%s ",
                index_attempt_id,
                attempt.completed_batches,
                attempt.total_batches,
                total_docs_indexed,
            )

            return attempt.completed_batches, attempt.total_batches

        except Exception:
            db_session.rollback()
            logger.exception(
                "Failed to update batch completion for attempt %s", index_attempt_id
            )
            raise

    @staticmethod
    def record_stub_batch_stored(
        db_session: Session, index_attempt_id: int, batch_num: int
    ) -> int:
        """Counts stub batch `batch_num` as stored and returns the new count.
        One lister stores batches in order, so `batch_num` must equal the
        current count. A gap would let a claim hand out a missing batch."""
        stored = db_session.execute(
            update(IndexAttempt)
            .where(
                IndexAttempt.id == index_attempt_id,
                IndexAttempt.stub_batches_stored == batch_num,
            )
            .values(stub_batches_stored=IndexAttempt.stub_batches_stored + 1)
            .returning(IndexAttempt.stub_batches_stored)
        ).scalar_one_or_none()
        if stored is None:
            db_session.rollback()
            raise RuntimeError(
                f"Stub batch {batch_num} of attempt {index_attempt_id} is out of order"
            )
        db_session.commit()
        return stored

    @staticmethod
    def start_stub_batches(
        db_session: Session,
        index_attempt_id: int,
        first_batch_num: int,
        stored_batches: int,
    ) -> None:
        """Marks the attempt as one that lists stub batches, and sets its
        counters before the listing starts. `first_batch_num` is the
        attempt's first stub batch number. `stored_batches` stub batches,
        taken over from an earlier attempt, have the numbers from there up."""
        db_session.execute(
            update(IndexAttempt)
            .where(IndexAttempt.id == index_attempt_id)
            .values(
                uses_conversion_stage=True,
                stub_batches_stored=first_batch_num + stored_batches,
                stub_batches_sent=first_batch_num,
                stub_batches_converted=first_batch_num,
            )
        )
        db_session.commit()

    @staticmethod
    def record_stubs_listed(
        db_session: Session, index_attempt_id: int, listed: int, skipped: int
    ) -> None:
        """Adds to the attempt's counts of listed documents and of those
        dropped as unchanged."""
        db_session.execute(
            update(IndexAttempt)
            .where(IndexAttempt.id == index_attempt_id)
            .values(
                stubs_listed=IndexAttempt.stubs_listed + listed,
                stubs_skipped=IndexAttempt.stubs_skipped + skipped,
            )
        )
        db_session.commit()

    @staticmethod
    def claim_stub_batches(
        db_session: Session,
        index_attempt_id: int,
        window: int,
        task_id: str | None = None,
    ) -> list[int]:
        """Claims the next stored stub batches for conversion and returns their
        numbers. It claims no more than are stored and not sent, and keeps
        the batches sent but not converted at or under `window`.

        One statement: the CTE locks the row and reads `sent` before the
        update, so concurrent callers never get the same number. The same
        statement records the caller as the last task that dispatched. A
        caller with no task of its own (the watchdog) keeps the task id and
        moves the time."""
        claim = text(
            """
            WITH before AS (
                SELECT stub_batches_sent AS sent
                FROM index_attempt
                WHERE id = :index_attempt_id
                FOR UPDATE
            )
            UPDATE index_attempt
            SET stub_batches_sent = stub_batches_sent + GREATEST(
                0,
                LEAST(
                    stub_batches_stored - stub_batches_sent,
                    :window - (stub_batches_sent - stub_batches_converted)
                )
            ),
            last_dispatch_task_id = COALESCE(:task_id, last_dispatch_task_id),
            last_dispatch_at = now()
            FROM before
            WHERE index_attempt.id = :index_attempt_id
            RETURNING before.sent, index_attempt.stub_batches_sent
            """
        )
        row = db_session.execute(
            claim,
            {
                "index_attempt_id": index_attempt_id,
                "window": window,
                "task_id": task_id,
            },
        ).one_or_none()
        db_session.commit()
        if row is None:
            return []
        sent_before, sent_after = row
        return list(range(sent_before, sent_after))

    @staticmethod
    def record_stub_batch_converted(db_session: Session, index_attempt_id: int) -> int:
        """Counts one sent stub batch as converted and returns the new count.
        The count never passes `sent`, so a redelivered task cannot open the
        window past its size."""
        converted = db_session.execute(
            update(IndexAttempt)
            .where(
                IndexAttempt.id == index_attempt_id,
                IndexAttempt.stub_batches_converted < IndexAttempt.stub_batches_sent,
            )
            .values(stub_batches_converted=IndexAttempt.stub_batches_converted + 1)
            .returning(IndexAttempt.stub_batches_converted)
        ).scalar_one_or_none()
        if converted is None:
            db_session.rollback()
            logger.warning(
                "Stub batch conversion not counted: attempt=%s has none in flight",
                index_attempt_id,
            )
            return IndexingCoordination._get_stub_batches_converted(
                db_session, index_attempt_id
            )
        db_session.commit()
        return converted

    @staticmethod
    def settle_stub_batches_converted(
        db_session: Session, index_attempt_id: int
    ) -> int:
        """Counts every sent stub batch as converted and returns how many
        that added. Call it only when no conversion task of the attempt exists
        and no sent stub batch is in the store: a task that stopped after it
        deleted its stub batch never counted it."""
        settle = text(
            """
            WITH before AS (
                SELECT stub_batches_converted AS converted
                FROM index_attempt
                WHERE id = :index_attempt_id
                FOR UPDATE
            )
            UPDATE index_attempt
            SET stub_batches_converted = stub_batches_sent
            FROM before
            WHERE index_attempt.id = :index_attempt_id
            RETURNING index_attempt.stub_batches_sent - before.converted
            """
        )
        added = db_session.execute(
            settle, {"index_attempt_id": index_attempt_id}
        ).scalar_one_or_none()
        db_session.commit()
        return max(0, added or 0)

    @staticmethod
    def record_heartbeat(db_session: Session, index_attempt_id: int) -> None:
        """Counts progress that no worker heartbeat shows, for example a
        send by the watchdog."""
        db_session.execute(
            update(IndexAttempt)
            .where(IndexAttempt.id == index_attempt_id)
            .values(heartbeat_counter=IndexAttempt.heartbeat_counter + 1)
        )
        db_session.commit()

    @staticmethod
    def _get_stub_batches_converted(db_session: Session, index_attempt_id: int) -> int:
        converted = db_session.scalar(
            select(IndexAttempt.stub_batches_converted).where(
                IndexAttempt.id == index_attempt_id
            )
        )
        return converted or 0

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
