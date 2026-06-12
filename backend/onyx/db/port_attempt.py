"""DB helpers for the reindexing port-attempt lifecycle.

One PortAttempt per (cc_pair, FUTURE SearchSettings) drives the backlog port.
The partial-unique index `ix_port_attempt_active_unique` guarantees at most one
active (NOT_STARTED / IN_PROGRESS) attempt per pair; terminal rows accumulate as
history. Nothing here enqueues celery work — that is the caller's job.
"""

from datetime import datetime

from sqlalchemy import and_
from sqlalchemy import exists
from sqlalchemy import func
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.orm import Session

from onyx.db.enums import IndexModelStatus
from onyx.db.enums import PortAttemptStatus
from onyx.db.models import PortAttempt
from onyx.db.models import SearchSettings
from onyx.utils.logger import setup_logger

logger = setup_logger()

_ACTIVE_STATUSES = [PortAttemptStatus.NOT_STARTED, PortAttemptStatus.IN_PROGRESS]

# Reads enough recent attempts to reach the streak where retry backoff caps (9 at
# the current 30s base / 1h cap); 10 = small margin. Raise if that cap is raised.
_MAX_TRACKED_FAILED_RETRIES = 10


def _get_locked(db_session: Session, port_attempt_id: int) -> PortAttempt:
    """Row-locked fetch (SELECT ... FOR UPDATE) so status transitions serialize —
    the port task and the stall watchdog can race to close the same attempt.
    Mirrors the index_attempt.py transition helpers."""
    attempt = db_session.execute(
        select(PortAttempt).where(PortAttempt.id == port_attempt_id).with_for_update()
    ).scalar_one_or_none()
    if attempt is None:
        raise ValueError(f"PortAttempt {port_attempt_id} not found")
    return attempt


def create_port_attempt(
    db_session: Session,
    cc_pair_id: int,
    search_settings_id: int,
    celery_task_id: str | None = None,
    resume_from_doc_id: str | None = None,
    up_to_doc_id: str | None = None,
) -> PortAttempt:
    """Create a NOT_STARTED attempt. Raises IntegrityError (the active-unique
    index) if an active attempt already exists for the pair.

    `resume_from_doc_id` seeds the cursor so the run continues `WHERE
    document_id > resume_from_doc_id` — used when rescheduling a FAILED attempt.
    `up_to_doc_id` is the snapshot upper bound, carried across resumes.
    """
    attempt = PortAttempt(
        cc_pair_id=cc_pair_id,
        search_settings_id=search_settings_id,
        status=PortAttemptStatus.NOT_STARTED,
        celery_task_id=celery_task_id,
        last_processed_doc_id=resume_from_doc_id,
        up_to_doc_id=up_to_doc_id,
    )
    db_session.add(attempt)
    try:
        db_session.commit()
    except Exception:
        # The active-unique index violation (expected on a race) leaves the
        # session in a failed transaction; roll back so the caller's session is
        # usable, then re-raise.
        db_session.rollback()
        raise
    return attempt


def get_port_attempt(db_session: Session, port_attempt_id: int) -> PortAttempt | None:
    return db_session.get(PortAttempt, port_attempt_id)


def get_active_port_attempt(
    db_session: Session, cc_pair_id: int, search_settings_id: int
) -> PortAttempt | None:
    """The single active (NOT_STARTED / IN_PROGRESS) attempt for the pair, if any."""
    return db_session.execute(
        select(PortAttempt).where(
            PortAttempt.cc_pair_id == cc_pair_id,
            PortAttempt.search_settings_id == search_settings_id,
            PortAttempt.status.in_(_ACTIVE_STATUSES),
        )
    ).scalar_one_or_none()


def port_backfill_has_pending_work(
    db_session: Session, search_settings_id: int
) -> bool:
    """True while a post-swap (INSTANT) backfill still has work for this settings:
    no attempts yet (just promoted) or at least one not yet SUCCESS/CANCELED. Lets
    check_for_port stop targeting a promoted PRESENT once every cc_pair is ported."""
    any_attempt = db_session.execute(
        select(exists().where(PortAttempt.search_settings_id == search_settings_id))
    ).scalar()
    if not any_attempt:
        return True
    return bool(
        db_session.execute(
            select(
                exists().where(
                    PortAttempt.search_settings_id == search_settings_id,
                    PortAttempt.status.in_(
                        [
                            PortAttemptStatus.NOT_STARTED,
                            PortAttemptStatus.IN_PROGRESS,
                            PortAttemptStatus.FAILED,
                        ]
                    ),
                )
            )
        ).scalar()
    )


def is_active_port_backfill_source(
    db_session: Session, source_settings_id: int
) -> bool:
    """True if a promoted settings is still backfilling its port FROM this index —
    i.e. the old index must not be deleted yet (the port still reads it)."""
    backfilling_ids = (
        db_session.execute(
            select(SearchSettings.id).where(
                SearchSettings.port_backfill_source_id == source_settings_id
            )
        )
        .scalars()
        .all()
    )
    return any(
        port_backfill_has_pending_work(db_session, sid) for sid in backfilling_ids
    )


def get_port_attempts_for_future(
    db_session: Session, search_settings_id: int
) -> list[PortAttempt]:
    """All attempts (any status) for a FUTURE, newest first."""
    return list(
        db_session.execute(
            select(PortAttempt)
            .where(PortAttempt.search_settings_id == search_settings_id)
            .order_by(PortAttempt.time_created.desc())
        )
        .scalars()
        .all()
    )


def get_latest_port_attempt(
    db_session: Session, cc_pair_id: int, search_settings_id: int
) -> PortAttempt | None:
    """The most recent attempt (any status) for a (cc_pair, FUTURE). The watchdog
    reads its status/cursor to decide whether to skip (SUCCESS/CANCELED) or
    reschedule resuming the cursor (FAILED)."""
    return (
        db_session.execute(
            select(PortAttempt)
            .where(
                PortAttempt.cc_pair_id == cc_pair_id,
                PortAttempt.search_settings_id == search_settings_id,
            )
            .order_by(PortAttempt.time_created.desc())
        )
        .scalars()
        .first()
    )


def count_consecutive_failed_port_attempts_no_progress(
    db_session: Session, cc_pair_id: int, search_settings_id: int
) -> int:
    """Length of the trailing run of FAILED attempts stuck at the SAME cursor (no
    docs ported since). A durably-erroring port fails repeatedly at one cursor, so
    this grows and drives retry backoff; a port that merely stall-yields advances
    the cursor each cycle, so the streak stays ~1 and it is not throttled."""
    recent = (
        db_session.execute(
            select(PortAttempt)
            .where(
                PortAttempt.cc_pair_id == cc_pair_id,
                PortAttempt.search_settings_id == search_settings_id,
            )
            .order_by(PortAttempt.time_created.desc())
            .limit(_MAX_TRACKED_FAILED_RETRIES)
        )
        .scalars()
        .all()
    )
    if not recent or recent[0].status != PortAttemptStatus.FAILED:
        return 0
    stuck_cursor = recent[0].last_processed_doc_id
    streak = 0
    for attempt in recent:
        if (
            attempt.status != PortAttemptStatus.FAILED
            or attempt.last_processed_doc_id != stuck_cursor
        ):
            break
        streak += 1
    return streak


def any_future_port_in_progress(db_session: Session) -> bool:
    """True if any PortAttempt against a FUTURE SearchSettings is active
    (NOT_STARTED / IN_PROGRESS). The vespa sync producer drops deferred-doc syncs
    to LOW priority while a port runs so they don't starve normal needs_sync work."""
    stmt = select(
        exists()
        .where(PortAttempt.search_settings_id == SearchSettings.id)
        .where(SearchSettings.status == IndexModelStatus.FUTURE)
        .where(PortAttempt.status.in_(_ACTIVE_STATUSES))
    )
    return bool(db_session.execute(stmt).scalar())


def get_stale_in_progress_port_attempts(
    db_session: Session, search_settings_id: int, stale_before: datetime
) -> list[PortAttempt]:
    """IN_PROGRESS attempts for a FUTURE with no progress since `stale_before`
    (last_progress_time older than that, or never set and started before it).
    The watchdog fails these so a fresh attempt can resume from the cursor."""
    return list(
        db_session.execute(
            select(PortAttempt).where(
                PortAttempt.search_settings_id == search_settings_id,
                PortAttempt.status == PortAttemptStatus.IN_PROGRESS,
                or_(
                    PortAttempt.last_progress_time < stale_before,
                    and_(
                        PortAttempt.last_progress_time.is_(None),
                        PortAttempt.time_started < stale_before,
                    ),
                ),
            )
        )
        .scalars()
        .all()
    )


def mark_port_in_progress(
    db_session: Session, port_attempt_id: int, celery_task_id: str | None = None
) -> bool:
    """Flip the attempt to IN_PROGRESS, returning True. Returns False without
    changing anything if it's already terminal — a supersede/cancel that landed
    during the task's startup must not be flipped back to IN_PROGRESS. The row lock
    serializes this against the cancel, so first-terminal-write-wins holds."""
    try:
        attempt = _get_locked(db_session, port_attempt_id)
        if attempt.status.is_terminal():
            db_session.rollback()
            return False
        attempt.status = PortAttemptStatus.IN_PROGRESS
        attempt.time_started = func.now()
        attempt.last_progress_time = func.now()
        if celery_task_id is not None:
            attempt.celery_task_id = celery_task_id
        db_session.commit()
        return True
    except Exception:
        db_session.rollback()
        raise


def commit_port_cursor(
    db_session: Session,
    port_attempt_id: int,
    last_processed_doc_id: str,
    docs_ported: int,
) -> None:
    """Per-batch durability point: advance the resume cursor + progress clock.
    `docs_ported` is the cumulative count so far."""
    try:
        attempt = _get_locked(db_session, port_attempt_id)
        attempt.last_processed_doc_id = last_processed_doc_id
        attempt.docs_ported = docs_ported
        attempt.last_progress_time = func.now()
        db_session.commit()
    except Exception:
        db_session.rollback()
        raise


def touch_port_progress(db_session: Session, port_attempt_id: int) -> None:
    """Per-page heartbeat: bump last_progress_time (no cursor change) so the stall
    watchdog can tell an active port from a dead/yielded one. Unlocked — a racing
    terminal write just costs a redundant bump."""
    db_session.execute(
        update(PortAttempt)
        .where(PortAttempt.id == port_attempt_id)
        .values(last_progress_time=func.now())
    )
    db_session.commit()


def mark_port_succeeded(db_session: Session, port_attempt_id: int) -> None:
    _mark_terminal(db_session, port_attempt_id, PortAttemptStatus.SUCCESS)


def mark_port_failed(
    db_session: Session, port_attempt_id: int, error_msg: str | None = None
) -> None:
    _mark_terminal(db_session, port_attempt_id, PortAttemptStatus.FAILED, error_msg)


def mark_port_canceled(db_session: Session, port_attempt_id: int) -> None:
    _mark_terminal(db_session, port_attempt_id, PortAttemptStatus.CANCELED)


def _mark_terminal(
    db_session: Session,
    port_attempt_id: int,
    status: PortAttemptStatus,
    error_msg: str | None = None,
) -> None:
    try:
        attempt = _get_locked(db_session, port_attempt_id)
        if attempt.status.is_terminal():
            # First terminal write wins: the row lock makes the watchdog-vs-task
            # race deterministic, so a late SUCCESS can't clobber a watchdog FAILED.
            logger.debug(
                "PortAttempt %s already terminal (%s); ignoring %s",
                port_attempt_id,
                attempt.status.value,
                status.value,
            )
            db_session.rollback()
            return
        attempt.status = status
        attempt.time_completed = func.now()
        if error_msg is not None:
            attempt.error_msg = error_msg
        db_session.commit()
    except Exception:
        db_session.rollback()
        raise


def cancel_active_port_attempts(
    db_session: Session,
    search_settings_id: int,
    reason: str = "Canceled: superseded by a newer reindex",
) -> int:
    """Cancel all active (NOT_STARTED / IN_PROGRESS) port attempts for a FUTURE
    (superseded by a newer reindex, or promoted by a swap). A running port re-reads
    its row each batch/page and stops on CANCELED; only active rows are touched, so
    first-terminal-write-wins holds. Returns the number canceled."""
    result = db_session.execute(
        update(PortAttempt)
        .where(
            PortAttempt.search_settings_id == search_settings_id,
            PortAttempt.status.in_(_ACTIVE_STATUSES),
        )
        .values(
            status=PortAttemptStatus.CANCELED,
            time_completed=func.now(),
            error_msg=reason,
        )
    )
    db_session.commit()
    return result.rowcount  # ty: ignore[unresolved-attribute]
