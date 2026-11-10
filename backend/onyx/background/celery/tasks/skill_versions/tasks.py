"""Resume metadata repair and reconcile legacy writers after the first pass."""

from time import monotonic
from uuid import UUID

from celery import shared_task

from onyx.cache.factory import get_cache_backend
from onyx.configs.constants import OnyxCeleryTask
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.skill_version import (
    delete_unreferenced_skill_bundles,
    repair_skill_version_metadata,
    skill_version_repair_batch,
)
from onyx.file_store.file_store import get_default_file_store
from onyx.key_value_store.factory import get_kv_store
from onyx.key_value_store.interface import KvKeyNotFoundError
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

logger = setup_logger()

PROGRESS_KEY = "skill_version_metadata_v2"
_DRIFT_CURSOR_KEY = "skill_version_metadata_v2_drift_cursor"
_COMPLETED = "completed"
_LOCK_TIMEOUT_SECONDS = 300
_TIME_BUDGET_SECONDS = 30


@shared_task(
    name=OnyxCeleryTask.REPAIR_SKILL_VERSIONS,
    soft_time_limit=300,
    ignore_result=True,
)
def repair_skill_versions(*, tenant_id: str) -> None:
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
    try:
        store = get_kv_store()
        lock = get_cache_backend().lock(PROGRESS_KEY, timeout=_LOCK_TIMEOUT_SECONDS)
        if not lock.acquire(blocking=False):
            return
        try:
            # Re-read after taking the lock; another pass may have just finished.
            try:
                progress = store.load(PROGRESS_KEY, refresh_cache=True)
            except KvKeyNotFoundError:
                progress = None
            completed = progress == _COMPLETED
            cursor = (
                UUID(str(progress)) if progress is not None and not completed else None
            )
            if completed:
                try:
                    drift_cursor = store.load(_DRIFT_CURSOR_KEY, refresh_cache=True)
                except KvKeyNotFoundError:
                    drift_cursor = None
                cursor = UUID(str(drift_cursor)) if drift_cursor is not None else None
            deadline = monotonic() + _TIME_BUDGET_SECONDS
            file_store = get_default_file_store()
            with get_session_with_current_tenant() as session:
                batch = skill_version_repair_batch(
                    session, cursor, drift_only=completed
                )
                if completed and not batch and cursor is not None:
                    batch = skill_version_repair_batch(session, None, drift_only=True)
                for skill in batch:
                    if monotonic() >= deadline:
                        return
                    lock.extend(_LOCK_TIMEOUT_SECONDS)
                    cursor = skill.id
                    try:
                        with session.begin_nested():
                            stale_file_ids = repair_skill_version_metadata(
                                skill, session, file_store, deadline=deadline
                            )
                    except Exception:
                        # Keep failed work selectable and allow later skills to progress.
                        logger.exception("Skill version repair failed for %s", cursor)
                        stale_file_ids = []
                    lock.extend(_LOCK_TIMEOUT_SECONDS)
                    session.commit()
                    lock.extend(_LOCK_TIMEOUT_SECONDS)
                    store.store(
                        _DRIFT_CURSOR_KEY if completed else PROGRESS_KEY, str(cursor)
                    )
                    try:
                        delete_unreferenced_skill_bundles(stale_file_ids, session)
                    except Exception:
                        session.rollback()
                        logger.exception("Skill bundle cleanup failed for %s", cursor)
                    lock.extend(_LOCK_TIMEOUT_SECONDS)
                if not batch:
                    lock.extend(_LOCK_TIMEOUT_SECONDS)
                    store.store(
                        _DRIFT_CURSOR_KEY if completed else PROGRESS_KEY,
                        None if completed else _COMPLETED,
                    )
        finally:
            if lock.owned():
                lock.release()
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
