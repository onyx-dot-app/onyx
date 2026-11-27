"""Celery tasks for scheduled tasks.

- ``dispatch_due_scheduled_tasks`` (primary queue, per tenant, every 30 s):
  brings in-flight runs up to the status of their chat response, then claims
  due tasks with ``FOR UPDATE SKIP LOCKED``, advances ``next_run_at``, and
  writes a QUEUED run (enqueued after commit) or a SKIPPED run. A fire
  cancels a prior run that still waits for approval, and a still-QUEUED prior
  run takes the fire and is sent again.
- ``run_scheduled_task(run_id)`` (``scheduled_tasks`` queue): runs the task
  as a chat turn.
- ``cleanup_stuck_scheduled_runs`` (primary queue, hourly): fails runs that
  stayed QUEUED, and cancels runs that waited for approval for 24 hours.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from uuid import UUID

from celery import Task, shared_task
from sqlalchemy.orm import Session

from onyx.agents.models import RunFailure, RunFailureKind, RunStatus
from onyx.background.celery.apps.app_base import task_logger
from onyx.cache.factory import get_cache_backend
from onyx.chat.run_store import (
    cancel_parked_response,
    interrupt_ownerless_responses,
)
from onyx.configs.constants import OnyxCeleryPriority, OnyxCeleryQueues, OnyxCeleryTask
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import (
    ScheduledTaskErrorClass,
    ScheduledTaskRunStatus,
    ScheduledTaskSkipReason,
    ScheduledTaskTriggerSource,
)
from onyx.db.models import ScheduledTaskRun
from onyx.db.scheduled_task import (
    advance_next_run_at,
    claim_due_scheduled_tasks,
    find_stuck_runs,
    get_run_response,
    has_in_flight_run_for_task,
    insert_run,
    list_chat_runs_in_flight,
    mark_run_status,
    missing_chat_session_ids,
    requeue_queued_run__no_commit,
    sync_chat_run__no_commit,
)
from onyx.server.features.build.timeouts import SCHEDULED_RUN_QUEUE_RESIDENCY_SECONDS

# --- Tunables -----------------------------------------------------------------

# Max tasks claimed per beat tick. Larger than typical per-tenant load to
# keep the dispatcher tick infrequent and the batch size healthy. The
# query is `FOR UPDATE SKIP LOCKED` so over-sizing the batch is safe —
# concurrent ticks just see "no rows" and exit.
DISPATCH_BATCH_SIZE = 50

# Celery expiry and the stuck-QUEUED sweep are one policy: a run that sat
# queued past the residency limit is dropped unexecuted and its row reclaimed
# by the same threshold.
RUN_EXPIRES_SECONDS = SCHEDULED_RUN_QUEUE_RESIDENCY_SECONDS
STUCK_QUEUED_OLDER_THAN = timedelta(seconds=SCHEDULED_RUN_QUEUE_RESIDENCY_SECONDS)
# A started run makes its chat response within seconds; counted from the start.
NO_RESPONSE_OLDER_THAN = timedelta(minutes=15)
APPROVAL_WAIT_LIMIT = timedelta(hours=24)


def _sync_chat_runs(db_session: Session, tenant_id: str, now: datetime) -> None:
    """Bring each in-flight chat run up to the status of its response. A
    response that lost its worker is interrupted first, so it fails."""
    runs = list_chat_runs_in_flight(db_session=db_session)
    responses = {
        run.id: get_run_response(db_session, run.chat_session_id)
        for run in runs
        if run.chat_session_id is not None
    }
    running_ids = [
        response.id
        for response in responses.values()
        if response is not None and response.response_status == RunStatus.RUNNING
    ]
    if running_ids and interrupt_ownerless_responses(
        get_cache_backend(), tenant_id, running_ids
    ):
        db_session.expire_all()
    deleted_chats = missing_chat_session_ids(
        db_session,
        [run.chat_session_id for run in runs if run.chat_session_id is not None],
    )
    for run in runs:
        try:
            if run.chat_session_id in deleted_chats:
                # The owner hard-deleted the run's chat.
                mark_run_status(
                    db_session=db_session,
                    run_id=run.id,
                    status=ScheduledTaskRunStatus.CANCELLED,
                    error_class=ScheduledTaskErrorClass.USER_CANCELLED,
                    error_detail="chat deleted",
                )
            elif (
                responses.get(run.id) is None
                and run.started_at < now - NO_RESPONSE_OLDER_THAN
            ):
                mark_run_status(
                    db_session=db_session,
                    run_id=run.id,
                    status=ScheduledTaskRunStatus.FAILED,
                    error_class=ScheduledTaskErrorClass.STUCK,
                    error_detail="no chat response",
                )
            else:
                sync_chat_run__no_commit(db_session, run)
        except Exception:
            task_logger.exception("Error syncing scheduled run %s", run.id)


_EXPIRED_APPROVAL_MESSAGES = {
    ScheduledTaskErrorClass.SUPERSEDED_BY_NEXT_FIRE: (
        "The next scheduled run started before anyone answered the approval "
        "request, so this run stopped."
    ),
    ScheduledTaskErrorClass.APPROVAL_TIMEOUT: (
        "Nobody answered the approval request in time, so this run stopped."
    ),
}


def _cancel_parked_runs(
    db_session: Session,
    tenant_id: str,
    runs: list[ScheduledTaskRun],
    error_class: ScheduledTaskErrorClass,
) -> None:
    """Cancel runs that wait for approval. An approval can resume a response
    before its run status follows; such a run is synced instead, so it counts
    as in flight."""
    cache = get_cache_backend()
    for run in runs:
        response = (
            get_run_response(db_session, run.chat_session_id)
            if run.chat_session_id is not None
            else None
        )
        if response is not None and cancel_parked_response(
            cache,
            tenant_id,
            response.id,
            RunFailure(
                kind=RunFailureKind.APPROVAL_EXPIRED,
                message=_EXPIRED_APPROVAL_MESSAGES[error_class],
            ),
        ):
            mark_run_status(
                db_session=db_session,
                run_id=run.id,
                status=ScheduledTaskRunStatus.CANCELLED,
                error_class=error_class,
            )
        else:
            if response is not None:
                db_session.refresh(response)
            sync_chat_run__no_commit(db_session, run)


# --- Dispatch ----------------------------------------------------------------


@shared_task(  # ty: ignore[invalid-argument-type]
    name=OnyxCeleryTask.SCHEDULED_TASKS_DISPATCH_DUE,
    ignore_result=True,
    bind=True,
)
def dispatch_due_scheduled_tasks(self: Task, *, tenant_id: str) -> int:
    """Claim due ``ScheduledTask`` rows and dispatch executor tasks.

    Returns the number of fires handled (queued, sent again, or skipped).
    """
    now = datetime.now(tz=timezone.utc)
    dispatched_count = 0
    requeued_count = 0
    skipped_count = 0

    with get_session_with_current_tenant() as db_session:
        _sync_chat_runs(db_session, tenant_id, now)
        db_session.commit()

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
                # A fire replaces a run that still waits for approval.
                parked = list_chat_runs_in_flight(
                    db_session=db_session,
                    task_id=task.id,
                    status=ScheduledTaskRunStatus.AWAITING_APPROVAL,
                )
                _cancel_parked_runs(
                    db_session,
                    tenant_id,
                    parked,
                    ScheduledTaskErrorClass.SUPERSEDED_BY_NEXT_FIRE,
                )
                # A QUEUED prior run takes this fire: it restarts its queue
                # age and is sent again. Duplicate sends are safe, because
                # _start_run only starts a QUEUED run, under its row lock.
                requeued_run_id = requeue_queued_run__no_commit(
                    db_session, task.id, now
                )
                if requeued_run_id is not None:
                    to_enqueue.append(requeued_run_id)
                    requeued_count += 1
                # A parked run that did not cancel (its response is still
                # parking) stays in flight; the next fire tries again.
                elif has_in_flight_run_for_task(
                    db_session=db_session, task_id=task.id
                ) or any(
                    run.status == ScheduledTaskRunStatus.AWAITING_APPROVAL
                    for run in parked
                ):
                    # A prior run is still running. Write a skipped row so the
                    # user can see the miss, then advance next_run_at.
                    insert_run(
                        db_session=db_session,
                        task_id=task.id,
                        trigger_source=ScheduledTaskTriggerSource.SCHEDULED,
                        status=ScheduledTaskRunStatus.SKIPPED,
                        skip_reason=ScheduledTaskSkipReason.PRIOR_IN_FLIGHT,
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
    # next fire sends the QUEUED run again, or the stuck-run sweeper fails it
    # after the residency limit.
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

    if dispatched_count or requeued_count or skipped_count:
        task_logger.info(
            "dispatch_due_scheduled_tasks tenant=%s dispatched=%d requeued=%d "
            "skipped=%d",
            tenant_id,
            dispatched_count,
            requeued_count,
            skipped_count,
        )

    return dispatched_count + requeued_count + skipped_count


# --- Run executor wrapper ----------------------------------------------------


@shared_task(  # ty: ignore[invalid-argument-type]
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
        from onyx.scheduled_tasks.executor import run_scheduled_task_logic

        run_scheduled_task_logic(UUID(run_id))
    except Exception:
        task_logger.exception(
            "Unhandled exception escaped run_scheduled_task_logic for run %s",
            run_id,
        )


# --- Stuck-run sweeper -------------------------------------------------------


@shared_task(  # ty: ignore[invalid-argument-type]
    name=OnyxCeleryTask.SCHEDULED_TASKS_CLEANUP_STUCK,
    ignore_result=True,
    bind=True,
)
def cleanup_stuck_scheduled_runs(self: Task, *, tenant_id: str) -> int:
    """Fail runs that stayed QUEUED too long, and cancel runs that waited
    for approval for ``APPROVAL_WAIT_LIMIT``.
    Returns the number of runs ended."""
    _ = self
    marked = 0
    with get_session_with_current_tenant() as db_session:
        stuck = find_stuck_runs(
            db_session=db_session, queued_older_than=STUCK_QUEUED_OLDER_THAN
        )
        detail = f"queued > {int(STUCK_QUEUED_OLDER_THAN.total_seconds() // 60)} min"
        for run in stuck:
            try:
                mark_run_status(
                    db_session=db_session,
                    run_id=run.id,
                    status=ScheduledTaskRunStatus.FAILED,
                    error_class=ScheduledTaskErrorClass.STUCK,
                    error_detail=detail,
                )
                marked += 1
            except Exception:
                task_logger.exception("Error marking stuck run %s as failed", run.id)
        expired = list_chat_runs_in_flight(
            db_session=db_session,
            status=ScheduledTaskRunStatus.AWAITING_APPROVAL,
            started_before=datetime.now(tz=timezone.utc) - APPROVAL_WAIT_LIMIT,
        )
        _cancel_parked_runs(
            db_session, tenant_id, expired, ScheduledTaskErrorClass.APPROVAL_TIMEOUT
        )
        marked += sum(run.status == ScheduledTaskRunStatus.CANCELLED for run in expired)
        db_session.commit()

    if marked:
        task_logger.info(
            "cleanup_stuck_scheduled_runs tenant=%s marked=%d", tenant_id, marked
        )
    return marked
