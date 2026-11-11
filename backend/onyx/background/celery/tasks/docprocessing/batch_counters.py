"""Batch counter signal handlers for docprocessing and docconversion tasks.

Maintains two per-attempt Redis counters for each stage (id = IndexAttempt.id):
  {stage}_pending_{id}   - batches dispatched but not yet picked up
  {stage}_in_flight_{id} - batches picked up but not yet completed

These counters let the monitor distinguish worker crashes (in_flight > 0)
from queue backlogs (in_flight = 0, pending > 0) when the heartbeat stops.
"""

from celery import Task
from sqlalchemy import update

from onyx.configs.constants import OnyxCeleryTask
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.models import IndexAttempt
from onyx.redis.redis_docprocessing import BatchStage, RedisDocprocessing
from onyx.redis.redis_pool import get_redis_client
from onyx.utils.logger import setup_logger
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA

logger = setup_logger()

_TRACKED_TASK_STAGES: dict[str, BatchStage] = {
    OnyxCeleryTask.DOCPROCESSING_TASK: BatchStage.DOCPROCESSING,
    OnyxCeleryTask.DOCCONVERSION_TASK: BatchStage.DOCCONVERSION,
}

# Stages whose tasks refresh a live entry while they run (see
# docconversion_task), so the watchdog can tell a killed worker's in-flight
# count from a running task.
_LIVE_TASK_STAGES = frozenset({BatchStage.DOCCONVERSION})


def on_docprocessing_task_prerun(
    task_id: str | None,
    task: Task | None,
    kwargs: dict | None,
) -> None:
    if task is None or task_id is None or kwargs is None:
        return
    stage = _TRACKED_TASK_STAGES.get(task.name or "")
    if stage is None:
        return

    index_attempt_id = kwargs.get("index_attempt_id")
    tenant_id = kwargs.get("tenant_id")
    if index_attempt_id is None:
        return

    # Emit a heartbeat before moving the counter to in_flight. This ensures
    # the monitor never sees in_flight > 0 with a stale heartbeat for a live
    # worker — picking up a batch is proof of life.
    # Use get_session_with_tenant() with the explicit tenant_id from kwargs
    # because task_prerun fires before TenantAwareTask.__call__ sets the
    # tenant context var, so get_session_with_current_tenant() would use the
    # wrong tenant.
    resolved_tenant_id = tenant_id or POSTGRES_DEFAULT_SCHEMA
    try:
        with get_session_with_tenant(tenant_id=resolved_tenant_id) as db_session:
            db_session.execute(
                update(IndexAttempt)
                .where(IndexAttempt.id == index_attempt_id)
                .values(heartbeat_counter=IndexAttempt.heartbeat_counter + 1)
            )
            db_session.commit()
    except Exception:
        logger.debug(
            "Failed to emit heartbeat on prerun for attempt %s",
            index_attempt_id,
            exc_info=True,
        )

    try:
        r = get_redis_client(tenant_id=tenant_id)
        counters = RedisDocprocessing(index_attempt_id, r, stage)
        if stage in _LIVE_TASK_STAGES:
            # Before the count, so a counted task that runs has an entry.
            counters.mark_task_live(task_id)
        counters.decr_pending_incr_in_flight()
    except Exception:
        logger.debug(
            "Failed to update docprocessing counters on prerun for attempt %s",
            index_attempt_id,
            exc_info=True,
        )


def on_docprocessing_task_postrun(
    task_id: str | None,
    task: Task | None,
    kwargs: dict | None,
    state: str | None,  # noqa: ARG001
) -> None:
    if task is None or task_id is None or kwargs is None:
        return
    stage = _TRACKED_TASK_STAGES.get(task.name or "")
    if stage is None:
        return

    index_attempt_id = kwargs.get("index_attempt_id")
    tenant_id = kwargs.get("tenant_id")
    if index_attempt_id is None:
        return

    try:
        r = get_redis_client(tenant_id=tenant_id)
        counters = RedisDocprocessing(index_attempt_id, r, stage)
        counters.decr_in_flight()
        if stage in _LIVE_TASK_STAGES:
            counters.clear_task_live(task_id)
    except Exception:
        logger.debug(
            "Failed to update docprocessing counters on postrun for attempt %s",
            index_attempt_id,
            exc_info=True,
        )
