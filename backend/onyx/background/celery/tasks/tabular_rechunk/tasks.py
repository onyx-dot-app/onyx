"""Beat task for the one-time tabular re-chunk migration.

`TABULAR_RECHUNK_ENABLED` arms it; the stored record stops it, so leaving the
variable set across restarts re-runs nothing. To run it again, delete the
record through the KV store, which clears the Redis copy a raw SQL delete
would leave behind.

Runs on the docprocessing queue, where the embedding belongs, and bounds
itself because Celery time limits do not fire in thread pools.
"""

from celery import Task, shared_task
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from onyx.background.celery.apps.app_base import task_logger
from onyx.background.indexing.run_tabular_rechunk import (
    TABULAR_RECHUNK_TIME_BUDGET_S,
    run_tabular_rechunk,
)
from onyx.cache.factory import get_cache_backend
from onyx.configs.app_configs import (
    DISABLE_VECTOR_DB,
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

# Outlives one run so a crashed worker's claim expires. Extended per batch,
# since one batch can outlast the budget under provider throttling.
_LOCK_TIMEOUT_S = TABULAR_RECHUNK_TIME_BUDGET_S + 5 * 60
# Bounded so a permanently broken document cannot rescan for ever.
_MAX_PASSES = 3


class TabularRechunkProgress(BaseModel):
    """How far the migration has got, per tenant. Durable in the KV store."""

    cursor: str | None = None
    completed: bool = False
    documents_indexed: int = 0
    documents_failed: int = 0
    failed_document_ids: list[str] = []
    passes: int = 0


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


def _blocked_reason(db_session: Session) -> str | None:
    """Why an armed migration still must not run, or None when it may."""
    if DISABLE_VECTOR_DB:
        return "the vector DB is disabled"

    search_settings = get_active_search_settings(db_session)
    if search_settings.secondary is not None:
        # The pipeline writes to the secondary whenever a FUTURE exists.
        return "a reindex is in flight"
    # Only while an INSTANT swap is backfilling, since the port copies chunks
    # boundary for boundary. The source-id check is load-bearing: "pending
    # work" alone means a cc_pair has no settled port attempt - the normal
    # state - so without it this blocks for ever.
    if search_settings.primary.port_backfill_source_id is not None and (
        port_backfill_has_pending_work(db_session, search_settings.primary.id)
    ):
        return "the reindex port has not finished"
    return None


def _finish_pass(progress: TabularRechunkProgress) -> None:
    """The scan reached the end of the table. Anything it could not re-chunk
    still carries its old chunk count, so another pass from the top finds it.
    """
    progress.passes += 1
    if not progress.failed_document_ids:
        progress.completed = True
        return
    if progress.passes >= _MAX_PASSES:
        task_logger.error(
            "tabular re-chunk: giving up on %s documents after %s passes: %s",
            len(progress.failed_document_ids),
            progress.passes,
            progress.failed_document_ids,
        )
        progress.completed = True
        return
    task_logger.info(
        "tabular re-chunk: %s documents failed, starting pass %s",
        len(progress.failed_document_ids),
        progress.passes + 1,
    )
    progress.cursor = None
    progress.failed_document_ids = []


def run_tabular_rechunk_tick(tenant_id: str) -> int | None:
    """Beat body. Re-chunks one batch and returns how many documents it
    indexed, or None when it did no work."""
    if not TABULAR_RECHUNK_ENABLED:
        return None
    # Before the lock, so a finished migration costs one cached read per tick.
    if load_progress().completed:
        return None

    lock = get_cache_backend().lock(
        OnyxRedisLocks.TABULAR_RECHUNK_LOCK, timeout=_LOCK_TIMEOUT_S
    )
    if not lock.acquire(blocking=False):
        return None  # a run is already in progress

    try:
        progress = load_progress()
        if progress.completed:
            return None

        with get_session_with_current_tenant() as db_session:
            blocked = _blocked_reason(db_session)
        if blocked is not None:
            task_logger.info("tabular re-chunk: waiting, %s", blocked)
            return None

        def extend_lock() -> None:
            lock.extend(_LOCK_TIMEOUT_S)

        result = run_tabular_rechunk(
            tenant_id=tenant_id,
            after_doc_id=progress.cursor,
            on_batch=extend_lock,
        )

        # The run took minutes; write onto current state, not a stale copy.
        progress = load_progress()
        progress.cursor = result.last_document_id
        progress.documents_indexed += result.documents_indexed
        progress.documents_failed += len(result.failed_document_ids)
        progress.failed_document_ids = sorted(
            set(progress.failed_document_ids) | set(result.failed_document_ids)
        )
        if result.finished:
            _finish_pass(progress)
        get_kv_store().store(KV_TABULAR_RECHUNK_PROGRESS_KEY, progress.model_dump())

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
