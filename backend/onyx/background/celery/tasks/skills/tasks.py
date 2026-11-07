from celery import Task, shared_task
from redis.lock import Lock as RedisLock

from onyx.background.celery.apps.app_base import task_logger
from onyx.configs.constants import (
    CELERY_GENERIC_BEAT_LOCK_TIMEOUT,
    OnyxCeleryTask,
    OnyxRedisLocks,
)
from onyx.db.skill_version import delete_orphan_skill_bundles
from onyx.redis.redis_pool import get_redis_client


@shared_task(  # ty: ignore[invalid-argument-type]
    name=OnyxCeleryTask.CHECK_FOR_ORPHAN_SKILL_BUNDLE_CLEANUP,
    soft_time_limit=300,
    bind=True,
    ignore_result=True,
)
def check_for_orphan_skill_bundle_cleanup(
    self: Task,  # noqa: ARG001
    *,
    tenant_id: str,
) -> None:
    """Deletes skill bundle files that no skill or version uses, such as
    files whose delete after commit failed."""
    redis_client = get_redis_client(tenant_id=tenant_id)
    lock: RedisLock = redis_client.lock(
        OnyxRedisLocks.ORPHAN_SKILL_BUNDLE_CLEANUP_BEAT_LOCK,
        timeout=CELERY_GENERIC_BEAT_LOCK_TIMEOUT,
    )
    if not lock.acquire(blocking=False):
        return
    try:
        deleted = delete_orphan_skill_bundles()
        if deleted:
            task_logger.info(
                f"Deleted {deleted} orphan skill bundle file(s) (tenant {tenant_id})."
            )
    finally:
        if lock.owned():
            lock.release()
