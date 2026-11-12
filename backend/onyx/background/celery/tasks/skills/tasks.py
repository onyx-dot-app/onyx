import time
from uuid import UUID

from celery import Task, shared_task
from pydantic import BaseModel, ValidationError

from onyx.background.celery.apps.app_base import task_logger
from onyx.cache.factory import get_cache_backend
from onyx.configs.constants import (
    KV_PLUGIN_VERSION_REPAIR_OVER_LIMITS_KEY,
    OnyxCeleryTask,
    OnyxRedisLocks,
)
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.plugin import (
    get_orphan_skill_bundle_file_ids,
    get_plugin_versions_to_repair,
    mark_plugin_version_invalid__no_commit,
    repair_plugin_version__no_commit,
)
from onyx.file_store.file_store import get_default_file_store
from onyx.file_store.staging import delete_files_best_effort
from onyx.key_value_store.factory import get_kv_store
from onyx.key_value_store.interface import KvKeyNotFoundError
from onyx.skills import bundle
from onyx.skills.repair import read_stored_version_content

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


_REPAIR_BATCH_SIZE = 50
_REPAIR_TIME_BUDGET_S = 4 * 60
_REPAIR_LOCK_TIMEOUT_S = _REPAIR_TIME_BUDGET_S + 60
# The limits a stored bundle is read under. A version over one of them is
# tried again only after one of them changes.
STORED_BUNDLE_LIMITS = [
    bundle.DEFAULT_PER_FILE_MAX_BYTES,
    bundle.DEFAULT_TOTAL_MAX_BYTES,
    bundle.STORED_ZIP_MAX_BYTES,
    bundle.STORED_ZIP_DIRECTORY_MAX_BYTES,
]


class _OverLimitVersions(BaseModel):
    limits: list[int]
    version_ids: list[UUID]


def _load_over_limit_version_ids() -> set[UUID]:
    try:
        stored = get_kv_store().load(KV_PLUGIN_VERSION_REPAIR_OVER_LIMITS_KEY)
        over_limits = _OverLimitVersions.model_validate(stored)
    except (KvKeyNotFoundError, ValidationError):
        return set()
    if over_limits.limits != STORED_BUNDLE_LIMITS:
        return set()
    return set(over_limits.version_ids)


def repair_backfilled_plugin_versions(
    time_budget_s: float = _REPAIR_TIME_BUDGET_S,
) -> int:
    """Fill the file list, sizes, SKILL.md text and frontmatter of plugin
    versions copied from legacy skill rows, from their bundles, until none is
    left or the time is up. A corrupt bundle makes its version invalid. A
    bundle over a size limit stays unclassified. Returns how many versions it
    filled."""
    start = time.monotonic()
    over_limit_ids = _load_over_limit_version_ids()
    over_limits_changed = False
    file_store = get_default_file_store()
    repaired = 0
    after_version_id: UUID | None = None
    while time.monotonic() - start < time_budget_s:
        with get_session_with_current_tenant() as db_session:
            versions = get_plugin_versions_to_repair(
                after_version_id=after_version_id,
                skip_version_ids=over_limit_ids,
                limit=_REPAIR_BATCH_SIZE,
                db_session=db_session,
            )
        if not versions:
            break
        for version in versions:
            if time.monotonic() - start >= time_budget_s:
                break
            after_version_id = version.version_id
            result = read_stored_version_content(
                version.name, version.bundle_file_id, file_store
            )
            with get_session_with_current_tenant() as db_session:
                if result.content is not None:
                    repaired += repair_plugin_version__no_commit(
                        version_id=version.version_id,
                        bundle_file_id=version.bundle_file_id,
                        content=result.content,
                        db_session=db_session,
                    )
                elif result.is_valid is False:
                    task_logger.warning(
                        f"Plugin version {version.version_id} is invalid: "
                        f"{result.detail}"
                    )
                    mark_plugin_version_invalid__no_commit(
                        version_id=version.version_id,
                        bundle_file_id=version.bundle_file_id,
                        db_session=db_session,
                    )
                elif result.over_limits:
                    over_limit_ids.add(version.version_id)
                    over_limits_changed = True
                else:
                    task_logger.warning(
                        f"Plugin version {version.version_id} was not repaired, "
                        f"will retry: {result.detail}"
                    )
                db_session.commit()
    if over_limits_changed:
        get_kv_store().store(
            KV_PLUGIN_VERSION_REPAIR_OVER_LIMITS_KEY,
            _OverLimitVersions(
                limits=STORED_BUNDLE_LIMITS, version_ids=sorted(over_limit_ids)
            ).model_dump(mode="json"),
        )
    return repaired


@shared_task(  # ty: ignore[invalid-argument-type]
    name=OnyxCeleryTask.REPAIR_BACKFILLED_PLUGIN_VERSIONS,
    bind=True,
    ignore_result=True,
)
def repair_backfilled_plugin_versions_task(
    self: Task,  # noqa: ARG001
    *,
    tenant_id: str,
) -> None:
    """Beat runs this for each tenant. It has work after a deploy that copied
    skill rows to plugin versions, and when a size limit changes; otherwise
    one query finds nothing to do."""
    lock = get_cache_backend().lock(
        OnyxRedisLocks.PLUGIN_VERSION_REPAIR_LOCK,
        timeout=_REPAIR_LOCK_TIMEOUT_S,
    )
    if not lock.acquire(blocking=False):
        return
    try:
        repaired = repair_backfilled_plugin_versions()
        if repaired:
            task_logger.info(
                f"Repaired {repaired} backfilled plugin version(s) (tenant {tenant_id})."
            )
    finally:
        if lock.owned():
            lock.release()
