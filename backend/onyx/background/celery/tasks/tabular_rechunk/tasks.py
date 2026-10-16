"""Beat task for the one-time tabular re-chunk migration.

`TABULAR_RECHUNK_ENABLED` arms the migration, so an operator turns it on by
deploying with the variable set and nothing else.

What stops it is the stored record. The scan walks the document table by
primary key, re-chunking only documents that hold more chunks than the current
chunker could produce; once it reaches the end the record says so, and every
later tick costs one cached read. Leaving the variable set therefore re-runs
nothing. Delete the record through the KV store - which clears the Redis copy
too, unlike a raw SQL delete - to run it again.

One batch of documents runs per tick, on the docprocessing queue where the
embedding belongs. The run is bounded by its own time budget because Celery
time limits do not fire in thread pools.
"""

from celery import Task, shared_task
from pydantic import BaseModel, ValidationError
from redis.lock import Lock as RedisLock

from onyx.background.celery.apps.app_base import task_logger
from onyx.background.indexing.run_tabular_rechunk import (
    TABULAR_RECHUNK_TIME_BUDGET_S,
    run_tabular_rechunk,
)
from onyx.configs.app_configs import (
    DISABLE_VECTOR_DB,
    SKIP_SPREADSHEET_CONTENT,
    TABULAR_RECHUNK_ENABLED,
)
from onyx.configs.constants import (
    KV_TABULAR_RECHUNK_PROGRESS_KEY,
    OnyxCeleryTask,
    OnyxRedisLocks,
)
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.port_attempt import port_backfill_has_pending_work
from onyx.db.search_settings import get_active_search_settings
from onyx.key_value_store.factory import get_kv_store
from onyx.key_value_store.interface import KvKeyNotFoundError
from onyx.redis.redis_pool import get_redis_client

# Outlives one run, so a crashed worker's claim still expires.
_LOCK_TIMEOUT_S = TABULAR_RECHUNK_TIME_BUDGET_S + 5 * 60


class TabularRechunkProgress(BaseModel):
    """How far the migration has got, per tenant. Durable in the KV store."""

    # Last document id scanned. The scan resumes past it.
    cursor: str | None = None
    completed: bool = False
    documents_indexed: int = 0
    documents_failed: int = 0


def load_progress() -> TabularRechunkProgress:
    """The stored record, or a fresh one when none is stored."""
    try:
        stored = get_kv_store().load(KV_TABULAR_RECHUNK_PROGRESS_KEY)
    except KvKeyNotFoundError:
        return TabularRechunkProgress()
    try:
        return TabularRechunkProgress.model_validate(stored)
    except ValidationError as e:
        task_logger.warning(
            "tabular re-chunk: stored progress does not validate, restarting: %s", e
        )
        return TabularRechunkProgress()


def store_progress(progress: TabularRechunkProgress) -> None:
    get_kv_store().store(KV_TABULAR_RECHUNK_PROGRESS_KEY, progress.model_dump())


def _blocked_reason() -> str | None:
    """Why an armed migration still must not run, or None when it may."""
    if DISABLE_VECTOR_DB:
        return "the vector DB is disabled"
    if SKIP_SPREADSHEET_CONTENT:
        # Connectors index tabular files as a title plus a placeholder, so
        # there is no tabular content to re-chunk.
        return "SKIP_SPREADSHEET_CONTENT is set"
    return None


def run_tabular_rechunk_tick(tenant_id: str) -> int | None:
    """Beat body. Re-chunks one batch and returns how many documents it
    indexed, or None when it did no work."""
    if not TABULAR_RECHUNK_ENABLED:
        return None
    blocked = _blocked_reason()
    if blocked is not None:
        task_logger.info("tabular re-chunk: not running, %s", blocked)
        return None

    lock: RedisLock = get_redis_client().lock(
        OnyxRedisLocks.TABULAR_RECHUNK_LOCK, timeout=_LOCK_TIMEOUT_S
    )
    if not lock.acquire(blocking=False):
        return None  # a run is already in progress

    try:
        progress = load_progress()
        if progress.completed:
            return None

        with get_session_with_current_tenant() as db_session:
            active_search_settings = get_active_search_settings(db_session)
            if active_search_settings.secondary is not None:
                # run_indexing_pipeline writes to the secondary whenever a
                # FUTURE exists, which would fill the new index and leave the
                # live one on the old chunks.
                task_logger.info("tabular re-chunk: a reindex is in flight, waiting")
                return None
            if port_backfill_has_pending_work(
                db_session, active_search_settings.primary.id
            ):
                # The port copies chunks boundary for boundary and would carry
                # the old chunks back over finished work.
                task_logger.info("tabular re-chunk: waiting for the reindex port")
                return None

        result = run_tabular_rechunk(tenant_id=tenant_id, after_doc_id=progress.cursor)

        # Re-read: the run took minutes, so write onto current state rather
        # than a stale copy.
        progress = load_progress()
        progress.cursor = result.last_document_id
        progress.completed = result.finished
        progress.documents_indexed += result.documents_indexed
        progress.documents_failed += result.documents_failed
        store_progress(progress)

        return result.documents_indexed or None
    finally:
        if lock.owned():
            lock.release()


@shared_task(  # ty: ignore[invalid-argument-type]
    name=OnyxCeleryTask.TABULAR_RECHUNK_TASK,
    bind=True,
    ignore_result=True,
)
def tabular_rechunk_task(
    self: Task,  # noqa: ARG001
    *,
    tenant_id: str,
) -> int | None:
    return run_tabular_rechunk_tick(tenant_id)
