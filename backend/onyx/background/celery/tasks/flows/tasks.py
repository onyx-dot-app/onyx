"""Celery tasks for flow automations.

Four tasks across two queues, mirroring the Craft scheduled-task split that
already works in production:

- ``dispatch_due_flows`` (primary, every 30 s) claims due schedule triggers
  with ``FOR UPDATE SKIP LOCKED``, advances ``next_run_at``, and writes either
  a QUEUED run (enqueuing the executor) or a SKIPPED one when the previous run
  is still going. DB-only work, so it stays off the executor queue where a
  saturated pool would stall dispatch.
- ``run_flow`` (``scheduled_tasks`` queue) delegates to ``run_flow_logic``.
  It shares that queue rather than claiming a new one because both are
  long-running user-triggered background work, and a new queue would mean new
  workers in every deployment target for no behavioural gain.
- ``cleanup_stuck_flow_runs`` (primary, hourly) fails runs whose worker died.
- ``purge_old_flow_runs`` (primary, daily) trims run history.

Repo conventions: ``@shared_task`` everywhere, ``expires=`` on every enqueue so a
dead consumer cannot grow the backlog, and time limits enforced inside the
task body because the thread-pool worker silently ignores ``soft_time_limit``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from celery import Task, shared_task

from onyx.background.celery.apps.app_base import task_logger
from onyx.configs.constants import OnyxCeleryPriority, OnyxCeleryQueues, OnyxCeleryTask
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import (
    FlowErrorClass,
    FlowRunStatus,
    FlowSkipReason,
    FlowTriggerSource,
)
from onyx.db.flow import (
    advance_next_run_at,
    claim_due_triggers,
    find_stuck_runs,
    get_flow_version,
    has_in_flight_run,
    insert_run,
    mark_run_status,
    purge_old_runs,
)
from onyx.flows.runner import RUN_BUDGET_SECONDS, run_flow_logic
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Larger than typical per-tenant load so the tick stays infrequent and the
# batch healthy. SKIP LOCKED makes over-sizing free: a concurrent tick just
# sees no rows.
DISPATCH_BATCH_SIZE = 50

# How long a queued run may sit before the sweep reclaims it unexecuted. The
# Celery expiry and the stuck-QUEUED threshold are one policy, so they share
# a value rather than drifting apart.
QUEUE_RESIDENCY_SECONDS = 15 * 60

# Slack on top of the run budget, so a run that hits its own ceiling always
# writes FAILED itself before the sweeper would call it stuck.
RUN_RECLAIM_SLACK_SECONDS = 5 * 60

STUCK_QUEUED_OLDER_THAN = timedelta(seconds=QUEUE_RESIDENCY_SECONDS)
STUCK_RUNNING_OLDER_THAN = timedelta(
    seconds=RUN_BUDGET_SECONDS + RUN_RECLAIM_SLACK_SECONDS
)

# Run history retention. Both bounds apply — see `purge_old_runs`.
RUN_HISTORY_MAX_AGE = timedelta(days=30)
RUN_HISTORY_KEEP_PER_FLOW = 100


@shared_task(  # ty: ignore[invalid-argument-type]
    name=OnyxCeleryTask.FLOWS_DISPATCH_DUE,
    ignore_result=True,
    bind=True,
)
def dispatch_due_flows(self: Task, *, tenant_id: str) -> int | None:
    """Claim due schedule triggers and queue a run for each.

    Returns the number of runs enqueued, which is what the beat log shows.
    """
    now = datetime.now(tz=timezone.utc)
    enqueued = 0

    try:
        with get_session_with_current_tenant() as db_session:
            triggers = claim_due_triggers(
                db_session=db_session, now=now, batch_size=DISPATCH_BATCH_SIZE
            )
            if not triggers:
                return 0

            to_enqueue: list[UUID] = []
            for trigger in triggers:
                flow = trigger.flow

                if has_in_flight_run(db_session=db_session, flow_id=flow.id):
                    insert_run(
                        db_session=db_session,
                        flow_id=flow.id,
                        trigger_id=trigger.id,
                        trigger_source=FlowTriggerSource.SCHEDULE,
                        status=FlowRunStatus.SKIPPED,
                        skip_reason=FlowSkipReason.PREVIOUS_RUN_IN_FLIGHT.value,
                    )
                    task_logger.info(
                        "flow still running, skipping this fire flow_id=%s", flow.id
                    )
                elif flow.published_version is None:
                    # set_flow_status refuses to activate without one, so this
                    # only happens if a version was deleted underneath us.
                    insert_run(
                        db_session=db_session,
                        flow_id=flow.id,
                        trigger_id=trigger.id,
                        trigger_source=FlowTriggerSource.SCHEDULE,
                        status=FlowRunStatus.FAILED,
                        skip_reason=None,
                    )
                    task_logger.error(
                        "active flow has no published version flow_id=%s", flow.id
                    )
                else:
                    version = get_flow_version(
                        db_session=db_session,
                        flow_id=flow.id,
                        version=flow.published_version,
                    )
                    run = insert_run(
                        db_session=db_session,
                        flow_id=flow.id,
                        flow_version_id=version.id,
                        trigger_id=trigger.id,
                        trigger_source=FlowTriggerSource.SCHEDULE,
                    )
                    to_enqueue.append(run.id)

                # Must happen before the transaction releases its row locks,
                # or the next tick claims the same trigger and fires twice.
                advance_next_run_at(db_session=db_session, trigger=trigger, now=now)

            db_session.commit()

        for run_id in to_enqueue:
            self.app.send_task(
                OnyxCeleryTask.FLOWS_RUN,
                kwargs={"run_id": str(run_id), "tenant_id": tenant_id},
                queue=OnyxCeleryQueues.SCHEDULED_TASKS,
                priority=OnyxCeleryPriority.MEDIUM,
                expires=QUEUE_RESIDENCY_SECONDS,
            )
            enqueued += 1

    except Exception:
        task_logger.exception("dispatch_due_flows failed tenant=%s", tenant_id)
        return None

    if enqueued:
        task_logger.info("queued %d flow run(s) tenant=%s", enqueued, tenant_id)
    return enqueued


@shared_task(  # ty: ignore[invalid-argument-type]
    name=OnyxCeleryTask.FLOWS_RUN,
    ignore_result=True,
    # Ack on delivery. A redelivered run would be safe — every node row is
    # keyed on (run, node, item), so completed work is reused rather than
    # repeated — but the stuck-run sweeper is the deliberate recovery path
    # and a silent Celery replay would race it.
    acks_late=False,
    bind=True,
    track_started=True,
)
def run_flow(self: Task, *, run_id: str, tenant_id: str) -> None:
    """Execute one queued run.

    ``tenant_id`` is consumed by ``TenantAwareTask`` before this body runs;
    it is accepted here only so Celery's argument unpacking succeeds.

    Exceptions are swallowed inside ``run_flow_logic``; anything escaping to
    here is a bug in this wrapper, and a retry would re-enter a run that is
    no longer QUEUED and immediately return.
    """
    _ = self
    _ = tenant_id
    try:
        run_flow_logic(UUID(run_id))
    except Exception:
        task_logger.exception("run_flow wrapper failed run_id=%s", run_id)


@shared_task(  # ty: ignore[invalid-argument-type]
    name=OnyxCeleryTask.FLOWS_CLEANUP_STUCK,
    ignore_result=True,
    bind=True,
)
def cleanup_stuck_flow_runs(self: Task, *, tenant_id: str) -> int | None:
    """Fail runs whose worker died without writing a terminal status."""
    _ = self
    now = datetime.now(tz=timezone.utc)

    try:
        with get_session_with_current_tenant() as db_session:
            stuck = find_stuck_runs(
                db_session=db_session,
                queued_before=now - STUCK_QUEUED_OLDER_THAN,
                running_before=now - STUCK_RUNNING_OLDER_THAN,
            )
            for run in stuck:
                mark_run_status(
                    db_session=db_session,
                    run=run,
                    status=FlowRunStatus.FAILED,
                    error_class=FlowErrorClass.STUCK,
                    error_detail=(
                        f"run was left in {run.status.value} with no worker; "
                        "reclaimed by the stuck-run sweep"
                    ),
                )
            db_session.commit()
    except Exception:
        task_logger.exception("cleanup_stuck_flow_runs failed tenant=%s", tenant_id)
        return None

    if stuck:
        task_logger.warning("reclaimed %d stuck flow run(s)", len(stuck))
    return len(stuck)


@shared_task(  # ty: ignore[invalid-argument-type]
    name=OnyxCeleryTask.FLOWS_PURGE_OLD_RUNS,
    ignore_result=True,
    bind=True,
)
def purge_old_flow_runs(self: Task, *, tenant_id: str) -> int | None:
    """Trim run history so a chatty flow cannot fill the table."""
    _ = self
    try:
        with get_session_with_current_tenant() as db_session:
            removed = purge_old_runs(
                db_session=db_session,
                older_than=RUN_HISTORY_MAX_AGE,
                keep_per_flow=RUN_HISTORY_KEEP_PER_FLOW,
            )
            db_session.commit()
    except Exception:
        task_logger.exception("purge_old_flow_runs failed tenant=%s", tenant_id)
        return None

    if removed:
        task_logger.info("purged %d old flow run(s)", removed)
    return removed
