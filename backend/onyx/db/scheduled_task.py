"""Database operations for scheduled tasks.

Mirrors the style of ``backend/onyx/db/persona.py`` — every function takes
``db_session: Session`` first, all queries live here (per CLAUDE.md), and
ownership / NOT_FOUND raising is consistent.

The dispatcher's hot path (``claim_due_scheduled_tasks``) is the only
function that uses ``FOR UPDATE SKIP LOCKED``. Callers MUST advance
``next_run_at`` and insert any associated run row in the same transaction
that claimed the task so concurrent beat ticks don't double-fire.
"""

from __future__ import annotations

from collections.abc import Collection
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import and_, case, desc, func, literal, select, update
from sqlalchemy.orm import Session, selectinload

from onyx.agents.models import RunFailureKind, RunStatus
from onyx.configs.constants import MessageType, NotificationType
from onyx.db.enums import (
    ScheduledTaskErrorClass,
    ScheduledTaskRunStatus,
    ScheduledTaskSkipReason,
    ScheduledTaskStatus,
    ScheduledTaskTriggerSource,
)
from onyx.db.models import (
    ChatMessage,
    ChatSession,
    ScheduledTask,
    ScheduledTaskRun,
    User,
)
from onyx.db.notification import (
    create_notification,
    dismiss_user_notifications_with_value,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.integrations.craft import replace_task_integrations__no_commit
from onyx.server.features.build.scheduled_tasks.schedule import (
    EditorMode,
    compute_next_dispatch_at,
)
from onyx.tools.models import IntegrationLinkConfiguration
from onyx.utils.logger import setup_logger

logger = setup_logger()

SUMMARY_MAX_CHARS = 120
ERROR_DETAIL_MAX_CHARS = 1000


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
    editor_mode: EditorMode,
    status: ScheduledTaskStatus = ScheduledTaskStatus.ACTIVE,
    integrations: list[IntegrationLinkConfiguration] | None = None,
    now: datetime | None = None,
) -> ScheduledTask:
    """Insert a new ``ScheduledTask``.

    Computes the initial ``next_run_at`` from ``cron_expression`` if
    ``status`` is ACTIVE; PAUSED tasks store NULL.

    Raises:
        OnyxError(INVALID_INPUT): if the cron is invalid.
    """
    now = now or datetime.now(tz=timezone.utc)
    task_id = uuid4()
    next_run_at: datetime | None = None
    if status == ScheduledTaskStatus.ACTIVE:
        next_run_at = compute_next_dispatch_at(cron_expression, now, task_id)

    task = ScheduledTask(
        id=task_id,
        user_id=user_id,
        name=name,
        prompt=prompt,
        cron_expression=cron_expression,
        editor_mode=editor_mode,
        status=status,
        next_run_at=next_run_at,
    )
    db_session.add(task)
    db_session.flush()
    user = db_session.get(User, user_id)
    if user is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "User not found")
    if integrations is not None:
        replace_task_integrations__no_commit(db_session, user, task.id, integrations)
    return task


def get_scheduled_task(
    *,
    db_session: Session,
    task_id: UUID,
    user_id: UUID,
    lock: bool = False,
) -> ScheduledTask:
    """Fetch a non-deleted task owned by ``user_id``.

    Raises ``OnyxError(NOT_FOUND)`` when the task is missing, soft-deleted,
    or belongs to a different user. Callers should never need to inspect
    ``deleted`` themselves.
    """
    query = select(ScheduledTask).where(
        ScheduledTask.id == task_id,
        ScheduledTask.user_id == user_id,
        ScheduledTask.deleted.is_(False),
    )
    if lock:
        query = query.with_for_update()
    task = db_session.scalar(query)
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
    editor_mode: EditorMode | None = None,
    status: ScheduledTaskStatus | None = None,
    integrations: list[IntegrationLinkConfiguration] | None = None,
    now: datetime | None = None,
) -> ScheduledTask:
    """Apply a partial update to a scheduled task.

    Recompute rules:
      - If ``cron_expression`` changed and the task is (or becomes) ACTIVE,
        ``next_run_at`` is recomputed from ``now``.
      - If ``status`` transitions to PAUSED, ``next_run_at`` is set to NULL.
      - If ``status`` transitions to ACTIVE, ``next_run_at`` is recomputed.

    Raises:
        OnyxError(NOT_FOUND): the task does not exist or is not owned by
            the caller.
        OnyxError(INVALID_INPUT): the new cron is invalid.
    """
    task = get_scheduled_task(
        db_session=db_session, task_id=task_id, user_id=user_id, lock=True
    )
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

    if status is not None and status != task.status:
        task.status = status
        if status == ScheduledTaskStatus.PAUSED:
            task.next_run_at = None
        else:
            # Becoming ACTIVE — recompute from now regardless of schedule change.
            task.next_run_at = compute_next_dispatch_at(
                task.cron_expression, now, task.id
            )
    elif schedule_changed and task.status == ScheduledTaskStatus.ACTIVE:
        task.next_run_at = compute_next_dispatch_at(task.cron_expression, now, task.id)

    if integrations is not None:
        user = db_session.get(User, user_id)
        if user is None:
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "User not found")
        replace_task_integrations__no_commit(db_session, user, task.id, integrations)
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
        # The dispatcher gates each task on its owner's Craft access.
        .options(selectinload(ScheduledTask.user))
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
    next_run_at = compute_next_dispatch_at(
        task.cron_expression, now, task.id, handled_dispatch_at=task.next_run_at
    )
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

    The dispatcher writes a ``skipped`` run row for a fire while a prior run
    is RUNNING. A QUEUED prior run takes the fire instead
    (``requeue_queued_run__no_commit``).
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


def requeue_queued_run__no_commit(
    db_session: Session, task_id: UUID, now: datetime
) -> UUID | None:
    """Give a new fire to the task's QUEUED run, if it has one: its queue age
    starts again at ``now``. Returns the run id to send again."""
    run = db_session.scalars(
        select(ScheduledTaskRun)
        .where(
            ScheduledTaskRun.task_id == task_id,
            ScheduledTaskRun.status == ScheduledTaskRunStatus.QUEUED,
        )
        .order_by(desc(ScheduledTaskRun.started_at))
        .limit(1)
        .with_for_update()
    ).first()
    if run is None:
        return None
    run.started_at = now
    db_session.flush()
    return run.id


def insert_run(
    *,
    db_session: Session,
    task_id: UUID,
    trigger_source: ScheduledTaskTriggerSource,
    status: ScheduledTaskRunStatus = ScheduledTaskRunStatus.QUEUED,
    skip_reason: ScheduledTaskSkipReason | None = None,
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
    chat_session_id: UUID | None = None,
    skip_reason: ScheduledTaskSkipReason | None = None,
    error_class: ScheduledTaskErrorClass | None = None,
    error_detail: str | None = None,
    summary: str | None = None,
    started_at: datetime | None = None,
) -> ScheduledTaskRun:
    """Update a run row's status + optional fields.

    A QUEUED run's ``started_at`` is its queue clock; the move to RUNNING
    passes ``started_at`` so it becomes the real start.

    Terminal statuses get ``finished_at = now()``. A move into a status
    with results (``has_results``) advances ``version``.
    """
    run = db_session.execute(
        select(ScheduledTaskRun)
        .where(ScheduledTaskRun.id == run_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if run is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Scheduled task run not found")
    if status.has_results() and run.status != status:
        run.version += 1
    if (
        run.status == ScheduledTaskRunStatus.AWAITING_APPROVAL
        and status != ScheduledTaskRunStatus.AWAITING_APPROVAL
    ):
        # The run no longer waits, so its approval notification is stale.
        dismiss_user_notifications_with_value(
            user_id=run.task.user_id,
            notif_type=NotificationType.SCHEDULED_TASK_AWAITING_APPROVAL,
            key="run_id",
            value=str(run.id),
            db_session=db_session,
        )
    run.status = status
    if chat_session_id is not None:
        run.chat_session_id = chat_session_id
    if skip_reason is not None:
        run.skip_reason = skip_reason
    if error_class is not None:
        run.error_class = error_class
    if error_detail is not None:
        run.error_detail = error_detail
    if summary is not None:
        run.summary = summary
    if started_at is not None:
        run.started_at = started_at
    if status.is_terminal():
        run.finished_at = datetime.now(tz=timezone.utc)
    db_session.flush()
    return run


def get_run(
    *,
    db_session: Session,
    run_id: UUID,
    for_update: bool = False,
) -> ScheduledTaskRun:
    """Fetch a single run by id. ``for_update`` locks the row until commit.

    Returns the run row. Ownership checks are the caller's responsibility —
    ``list_runs_for_task`` covers the user-scoped case.

    Raises ``OnyxError(NOT_FOUND)`` if the run does not exist.
    """
    stmt = select(ScheduledTaskRun).where(ScheduledTaskRun.id == run_id)
    if for_update:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    run = db_session.execute(stmt).scalar_one_or_none()
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
    unviewed_only: bool = False,
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
    if unviewed_only:
        conditions.append(
            func.coalesce(ScheduledTaskRun.viewed_revision, 0)
            < ScheduledTaskRun.version
        )

    stmt = (
        select(ScheduledTaskRun)
        .where(and_(*conditions))
        .order_by(desc(ScheduledTaskRun.started_at))
        .limit(limit)
    )
    return list(db_session.execute(stmt).scalars())


def unread_run_counts_for_user(
    *,
    db_session: Session,
    user_id: UUID,
) -> dict[UUID, int]:
    """Count runs with unviewed results per non-deleted task of ``user_id``."""
    rows = db_session.execute(
        select(ScheduledTaskRun.task_id, func.count())
        .join(ScheduledTask, ScheduledTaskRun.task_id == ScheduledTask.id)
        .where(
            ScheduledTask.user_id == user_id,
            ScheduledTask.deleted.is_(False),
            func.coalesce(ScheduledTaskRun.viewed_revision, 0)
            < ScheduledTaskRun.version,
        )
        .group_by(ScheduledTaskRun.task_id)
    ).tuples()
    return dict(rows.all())


def mark_runs_viewed(
    *,
    db_session: Session,
    task_id: UUID,
    user_id: UUID,
    revisions: dict[UUID, int],
) -> list[ScheduledTaskRun]:
    """Acknowledge only supplied revisions; newer results stay unread.

    Raises ``OnyxError(NOT_FOUND)`` for a task the user cannot see and
    ``ValueError`` when a revision is newer than the run's current version.
    """
    get_scheduled_task(db_session=db_session, task_id=task_id, user_id=user_id)
    if not revisions:
        return []
    # Lock before validating so the complete request succeeds or fails together.
    rows = db_session.execute(
        select(ScheduledTaskRun.id, ScheduledTaskRun.version)
        .where(
            ScheduledTaskRun.task_id == task_id,
            ScheduledTaskRun.id.in_(revisions),
        )
        .order_by(ScheduledTaskRun.id)
        .with_for_update()
    ).all()
    if any(revisions[run_id] > version for run_id, version in rows):
        raise ValueError("Run revision is newer than the current run")
    if not rows:
        return []
    viewed = case(revisions, value=ScheduledTaskRun.id)
    return list(
        db_session.scalars(
            update(ScheduledTaskRun)
            .where(ScheduledTaskRun.id.in_([run_id for run_id, _ in rows]))
            .values(
                viewed_revision=func.greatest(ScheduledTaskRun.viewed_revision, viewed)
            )
            .returning(ScheduledTaskRun)
            .execution_options(populate_existing=True, synchronize_session=False)
        )
    )


def find_stuck_runs(
    *,
    db_session: Session,
    queued_older_than: timedelta,
    now: datetime | None = None,
) -> list[ScheduledTaskRun]:
    """QUEUED runs older than ``queued_older_than``: the worker died between
    dispatch and pick-up, or the message expired. Locked, so a dispatch tick
    cannot requeue a run between this read and its failure; a run that a tick
    holds is left for the next sweep."""
    cutoff = (now or datetime.now(tz=timezone.utc)) - queued_older_than
    return list(
        db_session.scalars(
            select(ScheduledTaskRun)
            .where(
                ScheduledTaskRun.status == ScheduledTaskRunStatus.QUEUED,
                ScheduledTaskRun.started_at < cutoff,
            )
            .with_for_update(skip_locked=True)
        )
    )


def list_chat_runs_in_flight(
    *,
    db_session: Session,
    task_id: UUID | None = None,
    status: ScheduledTaskRunStatus | None = None,
    started_before: datetime | None = None,
) -> list[ScheduledTaskRun]:
    """Runs whose chat response has not ended."""
    stmt = select(ScheduledTaskRun).where(
        ScheduledTaskRun.chat_session_id.is_not(None),
        ScheduledTaskRun.status.in_(_CHAT_IN_FLIGHT),
    )
    if task_id is not None:
        stmt = stmt.where(ScheduledTaskRun.task_id == task_id)
    if status is not None:
        stmt = stmt.where(ScheduledTaskRun.status == status)
    if started_before is not None:
        stmt = stmt.where(ScheduledTaskRun.started_at < started_before)
    return list(db_session.scalars(stmt))


_CHAT_IN_FLIGHT = (
    ScheduledTaskRunStatus.RUNNING,
    ScheduledTaskRunStatus.AWAITING_APPROVAL,
)

_RUN_STATUS_BY_RESPONSE_STATUS = {
    RunStatus.RUNNING: ScheduledTaskRunStatus.RUNNING,
    RunStatus.SUSPENDED: ScheduledTaskRunStatus.AWAITING_APPROVAL,
    RunStatus.COMPLETE: ScheduledTaskRunStatus.SUCCEEDED,
    RunStatus.LIMIT: ScheduledTaskRunStatus.SUCCEEDED,
    RunStatus.CANCELLED: ScheduledTaskRunStatus.CANCELLED,
    RunStatus.ERROR: ScheduledTaskRunStatus.FAILED,
}

_NOTIFICATION_BY_RUN_STATUS = {
    ScheduledTaskRunStatus.FAILED: NotificationType.SCHEDULED_TASK_FAILED,
    ScheduledTaskRunStatus.AWAITING_APPROVAL: (
        NotificationType.SCHEDULED_TASK_AWAITING_APPROVAL
    ),
}


def missing_chat_session_ids(
    db_session: Session, chat_session_ids: Collection[UUID]
) -> set[UUID]:
    """The ids with no chat session row: chats that were hard-deleted."""
    if not chat_session_ids:
        return set()
    present = set(
        db_session.scalars(
            select(ChatSession.id).where(ChatSession.id.in_(chat_session_ids))
        )
    )
    return set(chat_session_ids) - present


def get_run_response(db_session: Session, chat_session_id: UUID) -> ChatMessage | None:
    """The response to the task prompt: the first response of the run's chat.
    Follow-up messages of the owner come after it."""
    return db_session.scalar(
        select(ChatMessage)
        .where(
            ChatMessage.chat_session_id == chat_session_id,
            ChatMessage.message_type == MessageType.ASSISTANT,
            ChatMessage.response_status.is_not(None),
        )
        .order_by(ChatMessage.id)
        .limit(1)
        # The response changes in other sessions; never decide on a stale copy.
        .execution_options(populate_existing=True)
    )


def clip_summary(text: str) -> str:
    if len(text) <= SUMMARY_MAX_CHARS:
        return text
    clipped = text[:SUMMARY_MAX_CHARS]
    last_space = clipped.rfind(" ")
    if last_space > SUMMARY_MAX_CHARS // 2:
        clipped = clipped[:last_space]
    return clipped.rstrip() + "…"


def notify_run_owner__no_commit(
    db_session: Session, run: ScheduledTaskRun, notif_type: NotificationType
) -> None:
    """Best effort: a notification error must not undo the status change."""
    task = run.task
    title = (
        f'Scheduled task "{task.name}" failed'
        if notif_type == NotificationType.SCHEDULED_TASK_FAILED
        else f'Scheduled task "{task.name}" needs approval'
    )
    try:
        with db_session.begin_nested():
            create_notification(
                user_id=task.user_id,
                notif_type=notif_type,
                db_session=db_session,
                title=title,
                additional_data={
                    "task_id": str(task.id),
                    "run_id": str(run.id),
                    "chat_session_id": (
                        str(run.chat_session_id) if run.chat_session_id else None
                    ),
                    # A run that failed before its chat opens its task.
                    "link": (
                        f"/app?chatId={run.chat_session_id}"
                        if run.chat_session_id
                        else f"/app/scheduled-tasks/{task.id}"
                    ),
                },
                autocommit=False,
            )
    except Exception:
        logger.exception(
            "Failed to create scheduled-task notification (task=%s run=%s)",
            task.id,
            run.id,
        )


def sync_chat_run__no_commit(
    db_session: Session, run: ScheduledTaskRun
) -> ScheduledTaskRunStatus | None:
    """Give an in-flight run the status of its chat response, and notify the
    owner when it fails or waits for approval. The response is the source of
    truth; this converges whenever and however often it runs. Returns the new
    status, or None when nothing changed."""
    # Lock and refresh the run first: the executor or another tick may have
    # moved it since the caller read it.
    run = get_run(db_session=db_session, run_id=run.id, for_update=True)
    if (
        run.chat_session_id is None
        or run.status not in _CHAT_IN_FLIGHT
        or (response := get_run_response(db_session, run.chat_session_id)) is None
        or response.response_status is None
    ):
        return None
    failure = response.response_failure
    # A turn stopped at the chat deadline is a failed run, not a user Stop.
    timed_out = failure is not None and failure.kind is RunFailureKind.DEADLINE
    status = (
        ScheduledTaskRunStatus.FAILED
        if timed_out
        else _RUN_STATUS_BY_RESPONSE_STATUS[response.response_status]
    )
    if status == run.status:
        return None
    mark_run_status(
        db_session=db_session,
        run_id=run.id,
        status=status,
        summary=(
            clip_summary(response.message.strip())
            if status == ScheduledTaskRunStatus.SUCCEEDED and response.message
            else None
        ),
        error_class=(
            ScheduledTaskErrorClass.TIMEOUT
            if timed_out
            else ScheduledTaskErrorClass.AGENT_EXCEPTION
            if status == ScheduledTaskRunStatus.FAILED
            else ScheduledTaskErrorClass.USER_CANCELLED
            if status == ScheduledTaskRunStatus.CANCELLED
            else None
        ),
        error_detail=(
            failure.message[:ERROR_DETAIL_MAX_CHARS]
            if failure is not None and status == ScheduledTaskRunStatus.FAILED
            else None
        ),
    )
    if notif_type := _NOTIFICATION_BY_RUN_STATUS.get(status):
        notify_run_owner__no_commit(db_session, run, notif_type)
    return status


def get_run_of_chat_session(
    db_session: Session, chat_session_id: UUID, user_id: UUID
) -> ScheduledTaskRun | None:
    """The run that made the chat, if ``user_id`` owns its task."""
    return db_session.scalar(
        select(ScheduledTaskRun)
        .join(ScheduledTask, ScheduledTaskRun.task_id == ScheduledTask.id)
        .where(
            ScheduledTaskRun.chat_session_id == chat_session_id,
            ScheduledTask.user_id == user_id,
        )
        .options(selectinload(ScheduledTaskRun.task))
    )
