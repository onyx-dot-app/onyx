from celery import shared_task

from onyx.background.celery.apps.app_base import task_logger
from onyx.cache.factory import get_cache_backend
from onyx.configs.constants import (
    CELERY_GENERIC_BEAT_LOCK_TIMEOUT,
    OnyxCeleryTask,
    OnyxRedisLocks,
)
from onyx.db.skill_version import delete_orphan_skill_bundles
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR


@shared_task(
    name=OnyxCeleryTask.CHECK_FOR_ORPHAN_SKILL_BUNDLE_CLEANUP,
    ignore_result=True,
)
def check_for_orphan_skill_bundle_cleanup(*, tenant_id: str) -> None:
    """Retry deletion of orphan skill bundles in the specified tenant."""
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
    try:
        lock = get_cache_backend().lock(
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
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
