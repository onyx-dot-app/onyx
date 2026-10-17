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

from onyx.background.celery.apps.app_base import task_logger
from onyx.background.indexing.run_tabular_rechunk import (
    TABULAR_RECHUNK_TIME_BUDGET_S,
    run_tabular_rechunk,
)
from onyx.cache.factory import get_cache_backend
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

# Outlives one run so a crashed worker's claim expires; extended after each
# batch, since one batch can outlast the budget under provider throttling.
_LOCK_TIMEOUT_S = TABULAR_RECHUNK_TIME_BUDGET_S + 5 * 60
# Bounded so a permanently broken document cannot rescan for ever.
_MAX_RETRY_PASSES = 3


class TabularRechunkProgress(BaseModel):
    """How far the migration has got, per tenant. Durable in the KV store."""

    cursor: str | None = None
    completed: bool = False
    documents_indexed: int = 0
    documents_failed: int = 0
    # Everything the current pass could not re-chunk.
    failed_document_ids: list[str] = []
    # The snapshot a retry pass works through. Held apart from
    # `failed_document_ids` so that pass can record its own failures without
    # changing what it still has to visit. Empty while the forward scan runs.
    retrying_document_ids: list[str] = []
    retry_passes: int = 0


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


def _blocked_reason() -> str | None:
    """Why an armed migration still must not run, or None when it may."""
    if DISABLE_VECTOR_DB:
        return "the vector DB is disabled"
    if SKIP_SPREADSHEET_CONTENT:
        # Tabular files index as a title plus a placeholder; nothing to chunk.
        return "SKIP_SPREADSHEET_CONTENT is set"
    return None


def _start_next_pass(progress: TabularRechunkProgress) -> None:
    """Called when a pass reaches the end of its work. Queues the documents it
    could not re-chunk for another pass, or ends the migration."""
    if not progress.failed_document_ids:
        progress.completed = True
        progress.retrying_document_ids = []
        return

    if progress.retry_passes >= _MAX_RETRY_PASSES:
        task_logger.error(
            "tabular re-chunk: giving up on %s documents after %s passes: %s",
            len(progress.failed_document_ids),
            progress.retry_passes,
            progress.failed_document_ids,
        )
        progress.completed = True
        progress.retrying_document_ids = []
        return

    progress.retry_passes += 1
    # By id, not by chunk_count: a failure that got as far as chunking has
    # already committed the smaller count and no longer looks oversized.
    progress.retrying_document_ids = progress.failed_document_ids
    progress.failed_document_ids = []
    progress.cursor = None
    task_logger.info(
        "tabular re-chunk: retrying %s documents, pass %s",
        len(progress.retrying_document_ids),
        progress.retry_passes,
    )


def run_tabular_rechunk_tick(tenant_id: str) -> int | None:
    """Beat body. Re-chunks one batch and returns how many documents it
    indexed, or None when it did no work."""
    if not TABULAR_RECHUNK_ENABLED:
        return None
    blocked = _blocked_reason()
    if blocked is not None:
        task_logger.info("tabular re-chunk: not running, %s", blocked)
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
            active_search_settings = get_active_search_settings(db_session)
            if active_search_settings.secondary is not None:
                # The pipeline writes to the secondary whenever a FUTURE
                # exists, leaving the live index on the old chunks.
                task_logger.info("tabular re-chunk: a reindex is in flight, waiting")
                return None
            # Only while an INSTANT swap is still backfilling: the port copies
            # chunks boundary for boundary over finished work. Without the
            # source-id check this blocks for ever, because "pending work"
            # means a cc_pair has no settled port attempt - the normal state.
            if active_search_settings.primary.port_backfill_source_id is not None and (
                port_backfill_has_pending_work(
                    db_session, active_search_settings.primary.id
                )
            ):
                task_logger.info("tabular re-chunk: waiting for the reindex port")
                return None

        result = run_tabular_rechunk(
            tenant_id=tenant_id,
            after_doc_id=progress.cursor,
            retry_document_ids=progress.retrying_document_ids or None,
            on_batch=lambda: lock.extend(_LOCK_TIMEOUT_S),
        )

        # Re-read: the run took minutes, so write onto current state rather
        # than a stale copy.
        progress = load_progress()
        progress.cursor = result.last_document_id
        progress.documents_indexed += result.documents_indexed
        progress.documents_failed += len(result.failed_document_ids)
        progress.failed_document_ids = sorted(
            set(progress.failed_document_ids) | set(result.failed_document_ids)
        )
        if result.finished:
            _start_next_pass(progress)
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
