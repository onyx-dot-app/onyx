"""Database operations for Craft Scheduled Tasks.

Mirrors the style of ``backend/onyx/db/persona.py`` — every function takes
``db_session: Session`` first, all queries live here (per CLAUDE.md), and
ownership / NOT_FOUND raising is consistent.

The dispatcher's hot path (``claim_due_scheduled_tasks``) is the only
function that uses ``FOR UPDATE SKIP LOCKED``. Callers MUST advance
``next_run_at`` and insert any associated run row in the same transaction
that claimed the task so concurrent beat ticks don't double-fire.
"""

from __future__ import annotations

from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any
from uuid import UUID

from sqlalchemy import and_
from sqlalchemy import desc
from sqlalchemy import literal
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.enums import ScheduledTaskRunStatus
from onyx.db.enums import ScheduledTaskStatus
from onyx.db.enums import ScheduledTaskTriggerSource
from onyx.db.models import ScheduledTask
from onyx.db.models import ScheduledTaskRun
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.build.scheduled_tasks.schedule import compute_next_run_at
from onyx.server.features.build.scheduled_tasks.schedule import EditorMode
from onyx.server.features.build.scheduled_tasks.schedule import validate_timezone
from onyx.utils.logger import setup_logger

logger = setup_logger()


# ---------------------------------------------------------------------------
# Task CRUD
# ---------------------------------------------------------------------------


def create_scheduled_task(
    *,
    db_session: Session,
    user_id: UUID,
    name: str,
    prompt: str,
    cron_expression: str,
    timezone_name: str,
    editor_mode: EditorMode,
    status: ScheduledTaskStatus = ScheduledTaskStatus.ACTIVE,
    now: datetime | None = None,
) -> ScheduledTask:
    """Insert a new ``ScheduledTask``.

    Computes the initial ``next_run_at`` from ``cron_expression`` /
    ``timezone_name`` if ``status`` is ACTIVE; PAUSED tasks store NULL.

    Raises:
        OnyxError(INVALID_INPUT): if the cron or timezone is invalid.
    """
    validate_timezone(timezone_name)
    now = now or datetime.now(tz=timezone.utc)
    next_run_at: datetime | None = None
    if status == ScheduledTaskStatus.ACTIVE:
        next_run_at = compute_next_run_at(cron_expression, timezone_name, now)

    task = ScheduledTask(
        user_id=user_id,
        name=name,
        prompt=prompt,
        cron_expression=cron_expression,
        timezone=timezone_name,
        editor_mode=editor_mode,
        status=status,
        next_run_at=next_run_at,
    )
    db_session.add(task)
    db_session.flush()
    return task


def get_scheduled_task(
    *,
    db_session: Session,
    task_id: UUID,
    user_id: UUID,
) -> ScheduledTask:
    """Fetch a non-deleted task owned by ``user_id``.

    Raises ``OnyxError(NOT_FOUND)`` when the task is missing, soft-deleted,
    or belongs to a different user. Callers should never need to inspect
    ``deleted`` themselves.
    """
    task = db_session.execute(
        select(ScheduledTask).where(
            ScheduledTask.id == task_id,
            ScheduledTask.user_id == user_id,
            ScheduledTask.deleted.is_(False),
        )
    ).scalar_one_or_none()
    if task is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Scheduled task not found")
    return task


def list_scheduled_tasks_for_user(
    *,
    db_session: Session,
    user_id: UUID,
) -> list[ScheduledTask]:
    """Return all non-deleted tasks for a user, newest first."""
    return list(
        db_session.execute(
            select(ScheduledTask)
            .where(
                ScheduledTask.user_id == user_id,
                ScheduledTask.deleted.is_(False),
            )
            .order_by(desc(ScheduledTask.created_at))
        ).scalars()
    )


def update_scheduled_task(
    *,
    db_session: Session,
    task_id: UUID,
    user_id: UUID,
    name: str | None = None,
    prompt: str | None = None,
    cron_expression: str | None = None,
    timezone_name: str | None = None,
    editor_mode: EditorMode | None = None,
    status: ScheduledTaskStatus | None = None,
    now: datetime | None = None,
) -> ScheduledTask:
    """Apply a partial update to a scheduled task.

    Recompute rules:
      - If ``cron_expression`` or ``timezone_name`` changed and the task is
        (or becomes) ACTIVE, ``next_run_at`` is recomputed from ``now``.
      - If ``status`` transitions to PAUSED, ``next_run_at`` is set to NULL.
      - If ``status`` transitions to ACTIVE, ``next_run_at`` is recomputed.

    Raises:
        OnyxError(NOT_FOUND): the task does not exist or is not owned by
            the caller.
        OnyxError(INVALID_INPUT): the new cron/timezone is invalid.
    """
    task = get_scheduled_task(db_session=db_session, task_id=task_id, user_id=user_id)
    now = now or datetime.now(tz=timezone.utc)

    schedule_changed = False
    if name is not None:
        task.name = name
    if prompt is not None:
        task.prompt = prompt
    if editor_mode is not None:
        task.editor_mode = editor_mode
    if cron_expression is not None and cron_expression != task.cron_expression:
        task.cron_expression = cron_expression
        schedule_changed = True
    if timezone_name is not None and timezone_name != task.timezone:
        validate_timezone(timezone_name)
        task.timezone = timezone_name
        schedule_changed = True

    if status is not None and status != task.status:
        task.status = status
        if status == ScheduledTaskStatus.PAUSED:
            task.next_run_at = None
        else:
            # Becoming ACTIVE — recompute from now regardless of schedule change.
            task.next_run_at = compute_next_run_at(
                task.cron_expression, task.timezone, now
            )
    elif schedule_changed and task.status == ScheduledTaskStatus.ACTIVE:
        task.next_run_at = compute_next_run_at(task.cron_expression, task.timezone, now)

    db_session.flush()
    return task


def soft_delete_scheduled_task(
    *,
    db_session: Session,
    task_id: UUID,
    user_id: UUID,
) -> None:
    """Mark a task as deleted. Idempotent.

    The row + its runs are retained so users can still open past runs from
    the task's run history; the dispatcher excludes deleted tasks from its
    claim query.
    """
    task = db_session.execute(
        select(ScheduledTask).where(
            ScheduledTask.id == task_id,
            ScheduledTask.user_id == user_id,
        )
    ).scalar_one_or_none()
    if task is None:
        # Idempotent — no-op if the row was never visible to this user.
        return
    if task.deleted:
        return
    task.deleted = True
    task.next_run_at = None
    db_session.flush()


# ---------------------------------------------------------------------------
# Dispatcher: claim, advance, insert run
# ---------------------------------------------------------------------------


def claim_due_scheduled_tasks(
    *,
    db_session: Session,
    now: datetime,
    batch_size: int,
) -> list[ScheduledTask]:
    """Atomically claim up to ``batch_size`` due tasks for dispatch.

    Implementation: ``SELECT FOR UPDATE SKIP LOCKED`` on
    ``scheduled_task`` filtered by ``status='active' AND deleted=false AND
    next_run_at IS NOT NULL AND next_run_at <= now``.

    The caller MUST, in the same transaction that called this function:
      1. Insert any run row(s) the dispatch logic produces.
      2. Call ``advance_next_run_at`` on each returned task.
      3. Commit.

    Otherwise, releasing the row locks before advancing will allow a
    concurrent beat tick to claim the same rows and double-fire.

    Args:
        db_session: An open SQLAlchemy session (must be a transactional
            session, not autocommit).
        now: Wall-clock time used for the ``next_run_at <= now`` comparison.
            Always pass ``datetime.now(tz=timezone.utc)`` from the caller —
            having the parameter explicit makes tests trivial.
        batch_size: Maximum number of tasks to claim in one tick.

    Returns:
        The claimed task rows, newest-due first.
    """
    if batch_size <= 0:
        return []
    stmt = (
        select(ScheduledTask)
        .where(
            ScheduledTask.status == ScheduledTaskStatus.ACTIVE,
            ScheduledTask.deleted.is_(False),
            ScheduledTask.next_run_at.is_not(None),
            ScheduledTask.next_run_at <= now,
        )
        .order_by(ScheduledTask.next_run_at)
        .limit(batch_size)
        .with_for_update(skip_locked=True)
    )
    return list(db_session.execute(stmt).scalars())


def advance_next_run_at(
    *,
    db_session: Session,
    task: ScheduledTask,
    now: datetime,
) -> datetime:
    """Recompute ``task.next_run_at`` from ``now`` and persist.

    Returns the new ``next_run_at`` (UTC).
    """
    next_run_at = compute_next_run_at(task.cron_expression, task.timezone, now)
    task.next_run_at = next_run_at
    db_session.flush()
    return next_run_at


# ---------------------------------------------------------------------------
# Run CRUD
# ---------------------------------------------------------------------------


def has_in_flight_run_for_task(
    *,
    db_session: Session,
    task_id: UUID,
) -> bool:
    """Return True if ``task_id`` has a run currently QUEUED or RUNNING.

    Used by the dispatcher to enforce SKIP_IF_RUNNING: when a prior fire is
    still in flight, the new claim writes a ``skipped`` run row instead of
    enqueuing the executor.
    """
    stmt = (
        select(literal(1))
        .where(
            ScheduledTaskRun.task_id == task_id,
            ScheduledTaskRun.status.in_(
                (
                    ScheduledTaskRunStatus.QUEUED,
                    ScheduledTaskRunStatus.RUNNING,
                )
            ),
        )
        .limit(1)
    )
    return db_session.execute(stmt).first() is not None


def insert_run(
    *,
    db_session: Session,
    task_id: UUID,
    trigger_source: ScheduledTaskTriggerSource,
    status: ScheduledTaskRunStatus = ScheduledTaskRunStatus.QUEUED,
    skip_reason: str | None = None,
) -> ScheduledTaskRun:
    """Insert a new run row. Returns the persisted row (with id)."""
    started_at = datetime.now(tz=timezone.utc)
    run = ScheduledTaskRun(
        task_id=task_id,
        status=status,
        trigger_source=trigger_source,
        skip_reason=skip_reason,
        started_at=started_at,
        # Skipped rows are terminal on insert — populate finished_at so the
        # UI doesn't have to special-case them.
        finished_at=(started_at if status == ScheduledTaskRunStatus.SKIPPED else None),
    )
    db_session.add(run)
    db_session.flush()
    return run


def mark_run_status(
    *,
    db_session: Session,
    run_id: UUID,
    status: ScheduledTaskRunStatus,
    session_id: UUID | None = None,
    skip_reason: str | None = None,
    error_class: str | None = None,
    error_detail: str | None = None,
    summary: str | None = None,
) -> ScheduledTaskRun:
    """Update a run row's status + optional fields.

    Terminal statuses (``succeeded``/``failed``/``skipped``) get a
    ``finished_at = now()`` written automatically; non-terminal statuses
    leave it NULL.
    """
    run = db_session.execute(
        select(ScheduledTaskRun).where(ScheduledTaskRun.id == run_id)
    ).scalar_one_or_none()
    if run is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Scheduled task run not found")
    run.status = status
    if session_id is not None:
        run.session_id = session_id
    if skip_reason is not None:
        run.skip_reason = skip_reason
    if error_class is not None:
        run.error_class = error_class
    if error_detail is not None:
        run.error_detail = error_detail
    if summary is not None:
        run.summary = summary
    if status.is_terminal():
        run.finished_at = datetime.now(tz=timezone.utc)
    db_session.flush()
    return run


def get_run(
    *,
    db_session: Session,
    run_id: UUID,
) -> ScheduledTaskRun:
    """Fetch a single run by id.

    Returns the run row. Ownership checks are the caller's responsibility —
    ``list_runs_for_task`` covers the user-scoped case.

    Raises ``OnyxError(NOT_FOUND)`` if the run does not exist.
    """
    run = db_session.execute(
        select(ScheduledTaskRun).where(ScheduledTaskRun.id == run_id)
    ).scalar_one_or_none()
    if run is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Scheduled task run not found")
    return run


def list_runs_for_task(
    *,
    db_session: Session,
    task_id: UUID,
    user_id: UUID,
    cursor: datetime | None = None,
    limit: int = 50,
) -> list[ScheduledTaskRun]:
    """List runs for a task, newest first, optionally paginated by ``started_at``.

    ``cursor`` is the ``started_at`` of the last seen row in the previous
    page; only runs with ``started_at < cursor`` are returned. This matches
    the ``ix_scheduled_task_run_task_started`` index, which is
    ``(task_id, started_at DESC)``.

    Raises:
        OnyxError(NOT_FOUND): the task does not exist or is not owned by
            this user. (We do this check rather than returning [] so the UI
            can distinguish "no runs yet" from "wrong user / deleted task".)
    """
    # Ownership check up front — raises NOT_FOUND if invalid.
    get_scheduled_task(db_session=db_session, task_id=task_id, user_id=user_id)

    conditions = [ScheduledTaskRun.task_id == task_id]
    if cursor is not None:
        conditions.append(ScheduledTaskRun.started_at < cursor)

    stmt = (
        select(ScheduledTaskRun)
        .where(and_(*conditions))
        .order_by(desc(ScheduledTaskRun.started_at))
        .limit(limit)
    )
    return list(db_session.execute(stmt).scalars())


def find_stuck_runs(
    *,
    db_session: Session,
    queued_older_than: timedelta,
    running_older_than: timedelta,
    now: datetime | None = None,
) -> list[ScheduledTaskRun]:
    """Find runs the stuck-run sweeper should mark ``failed (stuck)``.

    A run is "stuck" when:
      - its status is QUEUED and ``started_at`` is older than
        ``queued_older_than`` (worker presumably died between dispatch and
        pick-up); or
      - its status is RUNNING and ``started_at`` is older than
        ``running_older_than`` (worker died mid-execution or the run blew
        past its budget without crashing).
    """
    now = now or datetime.now(tz=timezone.utc)
    queued_cutoff = now - queued_older_than
    running_cutoff = now - running_older_than

    stmt = select(ScheduledTaskRun).where(
        (
            (ScheduledTaskRun.status == ScheduledTaskRunStatus.QUEUED)
            & (ScheduledTaskRun.started_at < queued_cutoff)
        )
        | (
            (ScheduledTaskRun.status == ScheduledTaskRunStatus.RUNNING)
            & (ScheduledTaskRun.started_at < running_cutoff)
        )
    )
    return list(db_session.execute(stmt).scalars())


# ---------------------------------------------------------------------------
# Session-view banner helper
# ---------------------------------------------------------------------------


def get_scheduled_run_context(
    *,
    db_session: Session,
    session_id: UUID,
    user_id: UUID,
) -> dict[str, Any] | None:
    """Return scheduled-run context for the session-view banner, or ``None``.

    Result shape::

        {"task_id": UUID, "task_name": str, "started_at": datetime}

    Returns ``None`` when the session was not produced by a scheduled run,
    or when the owning task is not accessible to ``user_id``.
    """
    row = db_session.execute(
        select(ScheduledTaskRun, ScheduledTask)
        .join(ScheduledTask, ScheduledTaskRun.task_id == ScheduledTask.id)
        .where(
            ScheduledTaskRun.session_id == session_id,
            ScheduledTask.user_id == user_id,
        )
        .order_by(desc(ScheduledTaskRun.started_at))
    ).first()
    if row is None:
        return None
    run, task = row
    return {
        "task_id": task.id,
        "task_name": task.name,
        "started_at": run.started_at,
    }
