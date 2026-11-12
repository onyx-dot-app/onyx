import time

from celery import Task, shared_task

from onyx.background.celery.apps.app_base import task_logger
from onyx.cache.factory import get_cache_backend
from onyx.configs.constants import OnyxCeleryTask, OnyxRedisLocks
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.plugin import get_orphan_skill_bundle_file_ids
from onyx.file_store.staging import delete_files_best_effort

_CLEANUP_BATCH_SIZE = 100
# Celery time limits do not apply in thread pools, so the loop enforces this.
_CLEANUP_TIME_BUDGET_S = 4 * 60
_CLEANUP_LOCK_TIMEOUT_S = _CLEANUP_TIME_BUDGET_S + 60


def delete_orphan_skill_bundles(time_budget_s: float = _CLEANUP_TIME_BUDGET_S) -> int:
    """Delete orphan skill bundle files until none is left or the time is up.
    A file that fails to delete, or that the time left no turn for, stays and
    is tried again on the next run. Returns how many it deleted."""
    deadline = time.monotonic() + time_budget_s
    deleted = 0
    after_file_id: str | None = None
    while time.monotonic() < deadline:
        with get_session_with_current_tenant() as db_session:
            file_ids = get_orphan_skill_bundle_file_ids(
                after_file_id=after_file_id,
                limit=_CLEANUP_BATCH_SIZE,
                db_session=db_session,
            )
        if not file_ids:
            break
        deleted += delete_files_best_effort(
            file_ids, context="orphan skill bundle cleanup", deadline=deadline
        )
        after_file_id = file_ids[-1]
    return deleted


@shared_task(  # ty: ignore[invalid-argument-type]
    name=OnyxCeleryTask.CHECK_FOR_ORPHAN_SKILL_BUNDLE_CLEANUP,
    bind=True,
    ignore_result=True,
)
def check_for_orphan_skill_bundle_cleanup(
    self: Task,  # noqa: ARG001
    *,
    tenant_id: str,
) -> None:
    """Delete skill bundle files that no plugin version or skill row uses, for
    example after a delete that failed when a version was pruned or a skill
    was deleted."""
    lock = get_cache_backend().lock(
        OnyxRedisLocks.ORPHAN_SKILL_BUNDLE_CLEANUP_BEAT_LOCK,
        timeout=_CLEANUP_LOCK_TIMEOUT_S,
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
