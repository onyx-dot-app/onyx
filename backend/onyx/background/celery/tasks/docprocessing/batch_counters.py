"""Batch counter signal handlers for docprocessing tasks.

Maintains two per-attempt Redis counters (id = IndexAttempt.id):
  docprocessing_pending_{id}   - batches dispatched but not yet picked up
  docprocessing_in_flight_{id} - batches picked up but not yet completed

These counters let the monitor distinguish worker crashes (in_flight > 0)
from queue backlogs (in_flight = 0, pending > 0) when the heartbeat stops.
"""

from celery import Task
from sqlalchemy import update

from onyx.configs.constants import OnyxCeleryTask
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.models import IndexAttempt
from onyx.redis.redis_docprocessing import RedisDocprocessing
from onyx.redis.redis_pool import get_redis_client
from onyx.utils.logger import setup_logger
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA

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
