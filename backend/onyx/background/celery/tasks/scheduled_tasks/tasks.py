"""Celery tasks for Craft Scheduled Tasks.

Three @shared_task wrappers, split across two queues:

- ``dispatch_due_scheduled_tasks`` (primary queue, per tenant, every
  30 s): claims due rows via ``FOR UPDATE SKIP LOCKED``, advances
  ``next_run_at``, writes either a QUEUED run row (and enqueues the
  executor onto ``scheduled_tasks``) or a SKIPPED row (when a prior run
  is still in flight). Lightweight DB-only work, so it lives on primary
  rather than competing with long-running executor slots.
- ``run_scheduled_task(run_id)`` (``scheduled_tasks`` queue): thin
  delegation to ``run_scheduled_task_logic`` in the executor module.
  The dedicated worker exists for this task.
- ``cleanup_stuck_scheduled_runs`` (primary queue, hourly): marks runs
  that have been QUEUED >15 min or RUNNING >45 min as
  ``failed (stuck)``.

Per CLAUDE.md:

- All tasks use ``@shared_task`` (never ``@celery_app.task``).
- Every enqueue passes ``expires=`` so a dead consumer can't grow the
  backlog without bound.
- Time limits are implemented inside the task body (the executor's
  budget). Celery's thread-pool worker pool silently ignores
  ``soft_time_limit`` and ``time_limit``.
"""

from __future__ import annotations

import time
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from uuid import UUID

from celery import shared_task
from celery import Task

from onyx.background.celery.apps.app_base import task_logger
from onyx.configs.constants import OnyxCeleryPriority
from onyx.configs.constants import OnyxCeleryQueues
from onyx.configs.constants import OnyxCeleryTask
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import ScheduledTaskRunStatus
from onyx.db.enums import ScheduledTaskTriggerSource
from onyx.db.scheduled_task import advance_next_run_at
from onyx.db.scheduled_task import claim_due_scheduled_tasks
from onyx.db.scheduled_task import find_stuck_runs
from onyx.db.scheduled_task import has_in_flight_run_for_task
from onyx.db.scheduled_task import insert_run
from onyx.db.scheduled_task import mark_run_status
from onyx.server.features.build.scheduled_tasks.executor import (
    DEFAULT_EXECUTOR_BUDGET_SECONDS,
)
from onyx.server.features.build.scheduled_tasks.executor import run_scheduled_task_logic

# --- Tunables -----------------------------------------------------------------

# Max tasks claimed per beat tick. Larger than typical per-tenant load to
# keep the dispatcher tick infrequent and the batch size healthy. The
# query is `FOR UPDATE SKIP LOCKED` so over-sizing the batch is safe —
# concurrent ticks just see "no rows" and exit.
DISPATCH_BATCH_SIZE = 50

# How long the executor message can sit on the `scheduled_tasks` queue
# before Celery drops it. After 15 min we'd rather let the next beat tick
# re-dispatch a new run row than execute a stale one.
RUN_EXPIRES_SECONDS = 15 * 60

# Stuck-run sweeper thresholds. The QUEUED threshold needs to comfortably
# exceed the longest plausible queue wait + executor startup. The RUNNING
# threshold should exceed the executor budget by enough margin that a
# well-behaved run that hits its own budget gets there first and marks
# itself FAILED (rather than the sweeper). Budget is 30 min by default;
# 45 min gives 50% slack.
STUCK_QUEUED_OLDER_THAN = timedelta(minutes=15)
STUCK_RUNNING_OLDER_THAN = timedelta(seconds=DEFAULT_EXECUTOR_BUDGET_SECONDS + 15 * 60)


# --- Dispatch ----------------------------------------------------------------


@shared_task(
    name=OnyxCeleryTask.SCHEDULED_TASKS_DISPATCH_DUE,
    ignore_result=True,
    bind=True,
)
def dispatch_due_scheduled_tasks(self: Task, *, tenant_id: str) -> int:
    """Claim due ``ScheduledTask`` rows and dispatch executor tasks.

    Returns the number of run rows inserted (QUEUED + SKIPPED) — useful
    for tests and metrics.
    """
    now = datetime.now(tz=timezone.utc)
    dispatched_count = 0
    skipped_count = 0

    with get_session_with_current_tenant() as db_session:
        # FOR UPDATE SKIP LOCKED: concurrent ticks see the rest of the
        # rows; we don't double-fire. The locks release on commit at the
        # end of this `with` block.
        claimed_tasks = claim_due_scheduled_tasks(
            db_session=db_session,
            now=now,
            batch_size=DISPATCH_BATCH_SIZE,
        )

        if not claimed_tasks:
            return 0

        # We need to know the run id of every QUEUED insert so we can
        # enqueue the executor. Collect them inside the txn; only enqueue
        # AFTER commit so the executor doesn't see a phantom QUEUED row
        # if our transaction rolls back for some reason.
        to_enqueue: list[UUID] = []

        for task in claimed_tasks:
            try:
                if has_in_flight_run_for_task(db_session=db_session, task_id=task.id):
                    # SKIP_IF_RUNNING: a prior fire is still in flight.
                    # Write a skipped row so the user can see the miss,
                    # then advance next_run_at as if it had fired.
                    insert_run(
                        db_session=db_session,
                        task_id=task.id,
                        trigger_source=ScheduledTaskTriggerSource.SCHEDULED,
                        status=ScheduledTaskRunStatus.SKIPPED,
                        skip_reason="prior_in_flight",
                    )
                    skipped_count += 1
                else:
                    run = insert_run(
                        db_session=db_session,
                        task_id=task.id,
                        trigger_source=ScheduledTaskTriggerSource.SCHEDULED,
                        status=ScheduledTaskRunStatus.QUEUED,
                    )
                    to_enqueue.append(run.id)
                    dispatched_count += 1

                # Always advance next_run_at; otherwise the next tick
                # would re-claim the same row.
                advance_next_run_at(db_session=db_session, task=task, now=now)
            except Exception:
                task_logger.exception(
                    "Error dispatching scheduled task %s (skipping)", task.id
                )

        db_session.commit()

    # Post-commit enqueues. If we crash between commit and enqueue, the
    # stuck-run sweeper picks the QUEUED rows up after ~15 min.
    for run_id in to_enqueue:
        try:
            self.app.send_task(
                OnyxCeleryTask.SCHEDULED_TASKS_RUN,
                kwargs={
                    "run_id": str(run_id),
                    "tenant_id": tenant_id,
                },
                queue=OnyxCeleryQueues.SCHEDULED_TASKS,
                priority=OnyxCeleryPriority.MEDIUM,
                expires=RUN_EXPIRES_SECONDS,
                headers={"enqueued_at": time.time()},
            )
        except Exception:
            task_logger.exception(
                "Failed to enqueue scheduled run %s; "
                "sweeper will reclaim if it stays QUEUED.",
                run_id,
            )

    if dispatched_count or skipped_count:
        task_logger.info(
            "dispatch_due_scheduled_tasks tenant=%s dispatched=%d skipped=%d",
            tenant_id,
            dispatched_count,
            skipped_count,
        )

    return dispatched_count + skipped_count


# --- Run executor wrapper ----------------------------------------------------


@shared_task(
    name=OnyxCeleryTask.SCHEDULED_TASKS_RUN,
    ignore_result=True,
    # acks_late=False so a worker crash doesn't cause Celery to retry the
    # message — V1 has no retries, and the stuck-run sweeper handles dead
    # workers separately.
    acks_late=False,
    bind=True,
    track_started=True,
)
def run_scheduled_task(self: Task, *, run_id: str, tenant_id: str) -> None:
    """Thin Celery wrapper around :func:`run_scheduled_task_logic`.

    ``tenant_id`` is consumed by ``TenantAwareTask`` before this body
    runs (it sets ``CURRENT_TENANT_ID_CONTEXTVAR``); we accept it here
    only so Celery's argument unpacking succeeds.

    Swallows exceptions so Celery doesn't reschedule. The executor logic
    is responsible for translating failures into a ``FAILED`` row +
    notification.
    """
    _ = self  # bound only for symmetry with other shared_task wrappers
    _ = tenant_id
    try:
        run_scheduled_task_logic(UUID(run_id))
    except Exception:
        task_logger.exception(
            "Unhandled exception escaped run_scheduled_task_logic for run %s",
            run_id,
        )


# --- Stuck-run sweeper -------------------------------------------------------


@shared_task(
    name=OnyxCeleryTask.SCHEDULED_TASKS_CLEANUP_STUCK,
    ignore_result=True,
    bind=True,
)
def cleanup_stuck_scheduled_runs(self: Task, *, tenant_id: str) -> int:
    """Mark abandoned runs as ``FAILED (stuck)``.

    A run is "stuck" when either:
    - it has been ``QUEUED`` for longer than ``STUCK_QUEUED_OLDER_THAN``
      (the worker presumably died between dispatch and pickup), or
    - it has been ``RUNNING`` for longer than ``STUCK_RUNNING_OLDER_THAN``
      (the worker died mid-execution or blew past its budget without
      crashing — the latter shouldn't happen because the executor self-
      enforces a budget, but the sweeper is a belt-and-braces backstop).

    Returns the number of rows marked failed (for tests / metrics).
    """
    _ = self
    marked = 0
    with get_session_with_current_tenant() as db_session:
        stuck = find_stuck_runs(
            db_session=db_session,
            queued_older_than=STUCK_QUEUED_OLDER_THAN,
            running_older_than=STUCK_RUNNING_OLDER_THAN,
        )
        for run in stuck:
            detail = (
                f"queued > {int(STUCK_QUEUED_OLDER_THAN.total_seconds() // 60)} min"
                if run.status == ScheduledTaskRunStatus.QUEUED
                else "running > "
                f"{int(STUCK_RUNNING_OLDER_THAN.total_seconds() // 60)} min"
            )
            try:
                mark_run_status(
                    db_session=db_session,
                    run_id=run.id,
                    status=ScheduledTaskRunStatus.FAILED,
                    error_class="stuck",
                    error_detail=detail,
                )
                marked += 1
            except Exception:
                task_logger.exception("Error marking stuck run %s as failed", run.id)
        db_session.commit()

    if marked:
        task_logger.info(
            "cleanup_stuck_scheduled_runs tenant=%s marked=%d", tenant_id, marked
        )
    return marked
