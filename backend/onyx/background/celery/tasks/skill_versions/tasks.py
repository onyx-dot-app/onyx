"""Resume metadata repair and reconcile legacy writers after the first pass."""

from time import monotonic
from uuid import UUID

from celery import shared_task

from onyx.cache.factory import get_cache_backend
from onyx.configs.constants import OnyxCeleryTask
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.skill_version import (
    repair_skill_version_metadata,
    skill_version_repair_batch,
)
from onyx.file_store.file_store import get_default_file_store
from onyx.key_value_store.factory import get_kv_store
from onyx.key_value_store.interface import KvKeyNotFoundError
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

PROGRESS_KEY = "skill_version_metadata_v2"
_COMPLETED = "completed"
_LOCK_TIMEOUT_SECONDS = 300
_TIME_BUDGET_SECONDS = 30


@shared_task(name=OnyxCeleryTask.REPAIR_SKILL_VERSIONS, ignore_result=True)
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
            deadline = monotonic() + _TIME_BUDGET_SECONDS
            file_store = get_default_file_store()
            with get_session_with_current_tenant() as session:
                batch = skill_version_repair_batch(
                    session, cursor, drift_only=completed
                )
                for skill in batch:
                    if monotonic() >= deadline:
                        return
                    lock.extend(_LOCK_TIMEOUT_SECONDS)
                    repair_skill_version_metadata(skill, session, file_store)
                    cursor = skill.id
                    lock.extend(_LOCK_TIMEOUT_SECONDS)
                    session.commit()
                    lock.extend(_LOCK_TIMEOUT_SECONDS)
                    if not completed:
                        store.store(PROGRESS_KEY, str(cursor))
                if not batch and not completed:
                    lock.extend(_LOCK_TIMEOUT_SECONDS)
                    store.store(PROGRESS_KEY, _COMPLETED)
        finally:
            if lock.owned():
                lock.release()
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
