"""Backfill of cc_pair_ids onto OpenSearch chunks written before the field existed.

Beat runs the task per tenant. The first run stores the IDs of every cc-pair
that is not being deleted. Each run then takes the pending cc-pairs in order and
walks each one's documents in ID order from the stored cursor. It sets each
document's cc_pair_ids on its chunks with one update-by-query per batch (no
re-embedding), and stores the cursor after every batch. A cc-pair leaves the
pending list when all its documents are done, or when it is deleted or being
deleted. Documents indexed while the backfill runs already get the field at
index time, and metadata sync keeps it current afterwards.
"""

import time

from celery import Task, shared_task
from redis.lock import Lock as RedisLock
from sqlalchemy.orm import Session

from onyx.background.celery.apps.app_base import task_logger
from onyx.configs.app_configs import DISABLE_VECTOR_DB
from onyx.configs.constants import OnyxCeleryTask, OnyxRedisLocks
from onyx.db.connector_credential_pair import (
    get_connector_credential_pair_from_id,
    get_non_deleting_cc_pair_ids,
)
from onyx.db.document import (
    fetch_known_chunk_counts_for_documents,
    get_cc_pair_ids_for_documents,
    get_document_ids_for_cc_pair_batch,
    get_last_modified_for_documents,
    update_docs_last_modified__no_commit,
)
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.port_attempt import port_backfill_has_pending_work
from onyx.db.search_settings import get_current_search_settings
from onyx.document_index.factory import build_opensearch_document_index
from onyx.document_index.opensearch.cc_pair_ids_backfill import (
    load_cc_pair_ids_backfill_progress,
    store_cc_pair_ids_backfill_progress,
)
from onyx.document_index.opensearch.opensearch_document_index import (
    OpenSearchDocumentIndex,
)
from onyx.redis.redis_pool import get_redis_client

_BACKFILL_BATCH_SIZE = 500
# Bounds the chunks one update-by-query touches, so a batch of large documents
# stays well within the request timeout. A batch always takes one document.
_BACKFILL_MAX_CHUNKS_PER_BATCH = 5_000
# Celery time limits do not apply in thread pools, so the loop enforces this.
# Short, so a run holds a shared light-worker thread only briefly; the next beat
# resumes from the stored cursor.
_BACKFILL_TIME_BUDGET_S = 2 * 60
_BACKFILL_LOCK_TIMEOUT_S = _BACKFILL_TIME_BUDGET_S + 5 * 60


def _backfill_batch(index: OpenSearchDocumentIndex, document_ids: list[str]) -> None:
    """Sets cc_pair_ids for one batch of documents.

    A metadata sync that reads newer Postgres state before this write lands
    would be overwritten by it. To repair that, documents whose last_modified
    changed while the batch ran are marked modified again, so metadata sync
    writes them after this batch.
    """
    with get_session_with_current_tenant() as db_session:
        last_modified_before = get_last_modified_for_documents(db_session, document_ids)
        doc_id_to_cc_pair_ids = get_cc_pair_ids_for_documents(db_session, document_ids)

    index.set_cc_pair_ids(
        {
            document_id: doc_id_to_cc_pair_ids.get(document_id, [])
            for document_id in document_ids
        }
    )

    with get_session_with_current_tenant() as db_session:
        last_modified_after = get_last_modified_for_documents(db_session, document_ids)
        changed_document_ids = [
            document_id
            for document_id, last_modified in last_modified_after.items()
            if last_modified != last_modified_before.get(document_id)
        ]
        if changed_document_ids:
            update_docs_last_modified__no_commit(changed_document_ids, db_session)
            db_session.commit()


def _bound_by_chunk_count(db_session: Session, document_ids: list[str]) -> list[str]:
    """The leading documents whose chunks fit in one batch, at least one. A
    document with an unknown chunk count counts as a full batch."""
    bounded: list[str] = []
    total_chunks = 0
    for document_id, known_chunk_count in fetch_known_chunk_counts_for_documents(
        document_ids, db_session
    ):
        chunk_count = (
            _BACKFILL_MAX_CHUNKS_PER_BATCH
            if known_chunk_count is None
            else known_chunk_count
        )
        if bounded and total_chunks + chunk_count > _BACKFILL_MAX_CHUNKS_PER_BATCH:
            break
        bounded.append(document_id)
        total_chunks += chunk_count
    return bounded


def run_cc_pair_ids_backfill(lock: RedisLock) -> bool:
    """Backfills until done, out of time, or the lock is lost. Returns True if
    the backfill of the current primary index is complete."""
    start = time.monotonic()
    with get_session_with_current_tenant() as db_session:
        search_settings = get_current_search_settings(db_session)
        # After an INSTANT swap, the port keeps copying chunks from the old
        # index into this one, with the old chunks' cc_pair_ids. Wait for it,
        # so no copy lands behind the cursor.
        if search_settings.port_backfill_source_id is not None and (
            port_backfill_has_pending_work(db_session, search_settings.id)
        ):
            task_logger.info("cc_pair_ids backfill: waiting for the reindex port")
            return False
        progress = load_cc_pair_ids_backfill_progress(search_settings.index_name)
        if progress.pending_cc_pair_ids is None:
            progress.pending_cc_pair_ids = get_non_deleting_cc_pair_ids(db_session)
            store_cc_pair_ids_backfill_progress(progress)
        index = build_opensearch_document_index(search_settings)

    pending = progress.pending_cc_pair_ids
    batches = 0
    while (
        pending and time.monotonic() - start < _BACKFILL_TIME_BUDGET_S and lock.owned()
    ):
        cc_pair_id = pending[0]
        with get_session_with_current_tenant() as db_session:
            cc_pair = get_connector_credential_pair_from_id(
                db_session=db_session, cc_pair_id=cc_pair_id
            )
            document_ids = (
                []
                if cc_pair is None
                or cc_pair.status == ConnectorCredentialPairStatus.DELETING
                else _bound_by_chunk_count(
                    db_session,
                    get_document_ids_for_cc_pair_batch(
                        db_session,
                        cc_pair_id=cc_pair_id,
                        after_doc_id=progress.last_document_id,
                        limit=_BACKFILL_BATCH_SIZE,
                    ),
                )
            )
        if document_ids:
            _backfill_batch(index, document_ids)
            progress.last_document_id = document_ids[-1]
            batches += 1
        else:
            pending.pop(0)
            progress.last_document_id = None
            task_logger.info(
                f"cc_pair_ids backfill: cc_pair={cc_pair_id} done, "
                f"pending={len(pending)}"
            )
        store_cc_pair_ids_backfill_progress(progress)
        lock.reacquire()

    if not pending:
        task_logger.info(f"cc_pair_ids backfill complete: index={progress.index_name}")
        return True
    task_logger.info(
        f"cc_pair_ids backfill paused: index={progress.index_name} batches={batches} "
        f"cc_pair={pending[0]} cursor={progress.last_document_id} "
        f"pending={len(pending)}"
    )
    return False


@shared_task(  # ty: ignore[invalid-argument-type]
    name=OnyxCeleryTask.BACKFILL_CC_PAIR_IDS_TASK,
    bind=True,
    ignore_result=True,
)
def backfill_cc_pair_ids_task(
    self: Task,  # noqa: ARG001
    *,
    tenant_id: str,  # noqa: ARG001  # consumed by TenantAwareTask wrapper
) -> None:
    if DISABLE_VECTOR_DB:
        return

    lock: RedisLock = get_redis_client().lock(
        OnyxRedisLocks.CC_PAIR_IDS_BACKFILL_LOCK,
        timeout=_BACKFILL_LOCK_TIMEOUT_S,
    )
    # Another run for this tenant holds the lock and is making progress.
    if not lock.acquire(blocking=False):
        return
    try:
        run_cc_pair_ids_backfill(lock)
    finally:
        if lock.owned():
            lock.release()
