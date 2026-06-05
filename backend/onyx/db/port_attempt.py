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
from sqlalchemy.orm import Session

from onyx.db.enums import IndexModelStatus
from onyx.db.enums import PortAttemptStatus
from onyx.db.models import PortAttempt
from onyx.db.models import SearchSettings
from onyx.utils.logger import setup_logger

logger = setup_logger()

_ACTIVE_STATUSES = [PortAttemptStatus.NOT_STARTED, PortAttemptStatus.IN_PROGRESS]


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
) -> PortAttempt:
    """Create a NOT_STARTED attempt. Raises IntegrityError (the active-unique
    index) if an active attempt already exists for the pair.

    `resume_from_doc_id` seeds the cursor so the run continues `WHERE
    document_id > resume_from_doc_id` — used when rescheduling a FAILED attempt.
    """
    attempt = PortAttempt(
        cc_pair_id=cc_pair_id,
        search_settings_id=search_settings_id,
        status=PortAttemptStatus.NOT_STARTED,
        celery_task_id=celery_task_id,
        last_processed_doc_id=resume_from_doc_id,
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
) -> None:
    try:
        attempt = _get_locked(db_session, port_attempt_id)
        attempt.status = PortAttemptStatus.IN_PROGRESS
        attempt.time_started = func.now()
        attempt.last_progress_time = func.now()
        if celery_task_id is not None:
            attempt.celery_task_id = celery_task_id
        db_session.commit()
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
