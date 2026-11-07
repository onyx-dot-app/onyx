"""One completed pass per tenant; incomplete passes resume after worker restarts."""

import time
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


@shared_task(name=OnyxCeleryTask.REPAIR_SKILL_VERSIONS, ignore_result=True)
def repair_skill_versions(*, tenant_id: str) -> None:
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
    try:
        store = get_kv_store()
        try:
            progress = store.load(PROGRESS_KEY)
        except KvKeyNotFoundError:
            progress = None
        if progress == _COMPLETED:
            return
        lock = get_cache_backend().lock(PROGRESS_KEY, timeout=300)
        if not lock.acquire(blocking=False):
            return
        try:
            # Re-read after taking the lock; another pass may have just finished.
            try:
                progress = store.load(PROGRESS_KEY)
            except KvKeyNotFoundError:
                progress = None
            if progress == _COMPLETED:
                return
            cursor = UUID(str(progress)) if progress is not None else None
            deadline = time.monotonic() + 30
            file_store = get_default_file_store()
            with get_session_with_current_tenant() as session:
                batch = skill_version_repair_batch(session, cursor)
                for skill in batch:
                    repair_skill_version_metadata(skill, session, file_store)
                    cursor = skill.id
                    session.commit()
                    store.store(PROGRESS_KEY, str(cursor))
                    lock.extend(300)
                    if time.monotonic() >= deadline:
                        return
                if not batch:
                    store.store(PROGRESS_KEY, _COMPLETED)
        finally:
            if lock.owned():
                lock.release()
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
