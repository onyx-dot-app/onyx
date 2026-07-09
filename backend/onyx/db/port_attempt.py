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

from onyx.db.connector_credential_pair import (
    fetch_indexable_standard_connector_credential_pair_ids,
)
from onyx.db.enums import IndexModelStatus
from onyx.db.enums import PortAttemptStatus
from onyx.db.enums import SwitchoverType
from onyx.db.models import PortAttempt
from onyx.db.models import SearchSettings
from onyx.utils.logger import setup_logger

logger = setup_logger()

_ACTIVE_STATUSES = [PortAttemptStatus.NOT_STARTED, PortAttemptStatus.IN_PROGRESS]

# States check_for_port won't create a further attempt for; anything else
# (none / active / FAILED) is still pending work.
_SETTLED_STATUSES = frozenset({PortAttemptStatus.SUCCESS, PortAttemptStatus.CANCELED})

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


def count_active_port_attempts(db_session: Session, search_settings_id: int) -> int:
    """Active (NOT_STARTED / IN_PROGRESS) attempts across all cc_pairs for a settings.
    check_for_port caps new attempt creation on this so the port doesn't fill every
    docprocessing slot and starve live indexing."""
    return db_session.execute(
        select(func.count())
        .select_from(PortAttempt)
        .where(
            PortAttempt.search_settings_id == search_settings_id,
            PortAttempt.status.in_(_ACTIVE_STATUSES),
        )
    ).scalar_one()


def port_backfill_has_pending_work(
    db_session: Session, search_settings_id: int
) -> bool:
    """True while some in-scope cc_pair lacks a settled port attempt, so check_for_port
    keeps targeting a promoted (INSTANT) PRESENT until every cc_pair is ported.

    Cc_pair-aware, not existing-row-aware: MAX_CONCURRENT_PORT_ATTEMPTS defers cc_pairs to
    later ticks, so all-terminal *existing* rows != done — un-attempted cc_pairs still
    need one. Checking only existing rows let the first fast batch's SUCCESS strand the
    rest, leaving the live index incomplete. Scope + _SETTLED_STATUSES match check_for_port
    so this never reports pending for a cc_pair it won't act on.
    """
    settings = db_session.get(SearchSettings, search_settings_id)
    active_only = (
        settings is not None and settings.switchover_type == SwitchoverType.ACTIVE_ONLY
    )
    in_scope_cc_pair_ids = fetch_indexable_standard_connector_credential_pair_ids(
        db_session, active_cc_pairs_only=active_only
    )
    if not in_scope_cc_pair_ids:
        return False
    # Latest attempt per cc_pair in one DISTINCT ON pass (avoids an N+1 over cc_pairs).
    settled_cc_pairs = {
        cc_pair_id
        for cc_pair_id, status in db_session.execute(
            select(PortAttempt.cc_pair_id, PortAttempt.status)
            .where(
                PortAttempt.search_settings_id == search_settings_id,
                PortAttempt.cc_pair_id.in_(in_scope_cc_pair_ids),
            )
            .distinct(PortAttempt.cc_pair_id)
            .order_by(
                PortAttempt.cc_pair_id,
                PortAttempt.time_created.desc(),
                PortAttempt.id.desc(),
            )
        )
        if status in _SETTLED_STATUSES
    }
    # Pending if any in-scope cc_pair has no settled latest attempt (incl. none at all).
    return bool(set(in_scope_cc_pair_ids) - settled_cc_pairs)


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
    db_session: Session, stale_before: datetime
) -> list[PortAttempt]:
    """All IN_PROGRESS attempts (any FUTURE) with no progress since `stale_before`
    (last_progress_time older, or unset and started before it) — a dead/self-yielded
    worker. Not scoped to a settings id: superseded/promoted FUTUREs drop out of the
    current port target but keep dead attempts the watchdog must still fail."""
    return list(
        db_session.execute(
            select(PortAttempt).where(
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
    """Flip NOT_STARTED -> IN_PROGRESS, returning True. Returns False (no change) for
    any other status under the row lock: a terminal row (a supersede/cancel that
    landed during startup), or an already-IN_PROGRESS row (a re-dispatched duplicate —
    a second concurrent writer would let one worker's cancel-ack unblock deletion
    while the other writes). A resume is always a fresh attempt id, so requiring
    NOT_STARTED rejects nothing valid."""
    try:
        attempt = _get_locked(db_session, port_attempt_id)
        if attempt.status != PortAttemptStatus.NOT_STARTED:
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
) -> bool:
    """Per-batch durability point: advance the resume cursor + progress clock.
    `docs_ported` is the cumulative count so far. Returns False without writing if
    the attempt already terminalized under the lock (a cancel/stall-FAIL that landed
    mid-batch) so the caller stops rather than writing behind cleanup's back."""
    try:
        attempt = _get_locked(db_session, port_attempt_id)
        if attempt.status.is_terminal():
            db_session.rollback()
            return False
        attempt.last_processed_doc_id = last_processed_doc_id
        attempt.docs_ported = docs_ported
        attempt.last_progress_time = func.now()
        db_session.commit()
        return True
    except Exception:
        db_session.rollback()
        raise


def touch_port_progress(db_session: Session, port_attempt_id: int) -> None:
    """Per-page heartbeat: bump last_progress_time (no cursor change) so the stall
    watchdog can tell an active port from a dead/yielded one. Unlocked — a racing
    terminal write just costs a redundant bump."""
    try:
        db_session.execute(
            update(PortAttempt)
            .where(PortAttempt.id == port_attempt_id)
            .values(last_progress_time=func.now())
        )
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


def request_port_cancel(db_session: Session, port_attempt_id: int) -> None:
    """Ask a port to stop so a waiter (connector deletion) can be the last writer.
    Under the row lock (serializes vs mark_port_in_progress):
      - NOT_STARTED: cancel outright. Must terminalize, not just flag: a NOT_STARTED
        attempt is invisible to the stall watchdog and isn't re-enqueued once the
        cc_pair is DELETING, so a flag alone would wedge the waiter forever.
      - IN_PROGRESS: flag only; the task acks (-> CANCELED) after its last write.
      - terminal: no-op.
    Idempotent."""
    try:
        attempt = _get_locked(db_session, port_attempt_id)
        if attempt.status.is_terminal():
            db_session.rollback()
            return
        if attempt.status == PortAttemptStatus.NOT_STARTED:
            attempt.status = PortAttemptStatus.CANCELED
            attempt.time_completed = func.now()
        else:  # IN_PROGRESS
            attempt.cancel_requested = True
        db_session.commit()
    except Exception:
        db_session.rollback()
        raise


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
    """Stop all active port attempts for a FUTURE (superseded/promoted by a swap),
    via the same two-phase cancel as request_port_cancel so a concurrently-waiting
    deletion stays the last writer: NOT_STARTED -> CANCELED, IN_PROGRESS -> flag (the
    task acks after its last write, rather than being terminalized mid-write here).
    Two scoped UPDATEs: an attempt flipping NOT_STARTED -> IN_PROGRESS between them is
    still caught by the second. Returns the number affected."""
    not_started = db_session.execute(
        update(PortAttempt)
        .where(
            PortAttempt.search_settings_id == search_settings_id,
            PortAttempt.status == PortAttemptStatus.NOT_STARTED,
        )
        .values(
            status=PortAttemptStatus.CANCELED,
            time_completed=func.now(),
            error_msg=reason,
        )
    )
    in_progress = db_session.execute(
        update(PortAttempt)
        .where(
            PortAttempt.search_settings_id == search_settings_id,
            PortAttempt.status == PortAttemptStatus.IN_PROGRESS,
        )
        .values(cancel_requested=True)
    )
    db_session.commit()
    ns_count = not_started.rowcount  # ty: ignore[unresolved-attribute]
    ip_count = in_progress.rowcount  # ty: ignore[unresolved-attribute]
    return (ns_count or 0) + (ip_count or 0)
