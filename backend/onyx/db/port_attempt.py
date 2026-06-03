"""DB helpers for the reindexing port-attempt lifecycle.

One PortAttempt per (cc_pair, FUTURE SearchSettings) drives the backlog port.
The partial-unique index `ix_port_attempt_active_unique` guarantees at most one
active (NOT_STARTED / IN_PROGRESS) attempt per pair; terminal rows accumulate as
history. Nothing here enqueues celery work — that is the caller's job.
"""

from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.enums import PortAttemptStatus
from onyx.db.models import PortAttempt
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
) -> PortAttempt:
    """Create a NOT_STARTED attempt. Raises IntegrityError (the active-unique
    index) if an active attempt already exists for the pair."""
    attempt = PortAttempt(
        cc_pair_id=cc_pair_id,
        search_settings_id=search_settings_id,
        status=PortAttemptStatus.NOT_STARTED,
        celery_task_id=celery_task_id,
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
