"""Batch counter signal handlers for docprocessing tasks.

Maintains two per-attempt Redis counters:
  docprocessing_pending_{id}   - batches dispatched but not yet picked up
  docprocessing_in_flight_{id} - batches picked up but not yet completed

These counters let the monitor distinguish worker crashes (in_flight > 0)
from queue backlogs (in_flight = 0, pending > 0) when the heartbeat stops.
"""

from celery import Task

from onyx.configs.constants import OnyxCeleryTask
from onyx.redis.redis_docprocessing import RedisDocprocessing
from onyx.redis.redis_pool import get_redis_client
from onyx.utils.logger import setup_logger

logger = setup_logger()

_TRACKED_TASK = OnyxCeleryTask.DOCPROCESSING_TASK


def on_docprocessing_task_prerun(
    task_id: str | None,
    task: Task | None,
    kwargs: dict | None,
) -> None:
    if task is None or task_id is None or kwargs is None:
        return
    if (task.name or "") != _TRACKED_TASK:
        return

    index_attempt_id = kwargs.get("index_attempt_id")
    tenant_id = kwargs.get("tenant_id")
    if index_attempt_id is None:
        return

    try:
        r = get_redis_client(tenant_id=tenant_id)
        RedisDocprocessing(index_attempt_id, r).decr_pending_incr_in_flight()
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
    if (task.name or "") != _TRACKED_TASK:
        return

    index_attempt_id = kwargs.get("index_attempt_id")
    tenant_id = kwargs.get("tenant_id")
    if index_attempt_id is None:
        return

    try:
        r = get_redis_client(tenant_id=tenant_id)
        RedisDocprocessing(index_attempt_id, r).decr_in_flight()
    except Exception:
        logger.debug(
            "Failed to update docprocessing counters on postrun for attempt %s",
            index_attempt_id,
            exc_info=True,
        )
