from celery import Task, shared_task
from redis.lock import Lock as RedisLock

from onyx.background.celery.apps.app_base import task_logger
from onyx.configs.constants import (
    CELERY_GENERIC_BEAT_LOCK_TIMEOUT,
    OnyxCeleryTask,
    OnyxRedisLocks,
)
from onyx.connectors.file.edit_staging import delete_expired_staged_files
from onyx.redis.redis_pool import get_redis_client


@shared_task(  # ty: ignore[invalid-argument-type]
    name=OnyxCeleryTask.CHECK_FOR_STAGED_CONNECTOR_FILE_CLEANUP,
    soft_time_limit=300,
    bind=True,
    ignore_result=True,
)
def check_for_staged_connector_file_cleanup(
    self: Task,  # noqa: ARG001
    *,
    tenant_id: str,
) -> None:
    """Deletes files uploaded for connector edits that no applied plan
    claimed in time."""
    redis_client = get_redis_client(tenant_id=tenant_id)
    lock: RedisLock = redis_client.lock(
        OnyxRedisLocks.STAGED_CONNECTOR_FILE_CLEANUP_BEAT_LOCK,
        timeout=CELERY_GENERIC_BEAT_LOCK_TIMEOUT,
    )
    if not lock.acquire(blocking=False):
        return
    try:
        deleted = delete_expired_staged_files()
        if deleted:
            task_logger.info(
                f"Deleted {deleted} expired staged connector file(s) "
                f"(tenant {tenant_id})."
            )
    finally:
        if lock.owned():
            lock.release()
