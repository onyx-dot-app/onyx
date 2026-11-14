"""The conversion stage of indexing.

Docfetching lists a source and stores stub batches: documents that are
listed but not fetched. A conversion task takes one stub batch, fetches and
parses its documents with the connector, and stores a normal document batch
with the same number for docprocessing. So one stub batch becomes one document
batch, and the batch counts of the attempt stay as they are.

Sends are paced. ``dispatch_stub_batches`` claims stored stub batches while the
attempt has fewer than a window of batches sent and not converted. The lister
calls it after each store, and each conversion task calls it when it ends, so
the side that is behind gets the next send.
"""

import threading
import time
from typing import Any

from celery import Celery
from pydantic import BaseModel, ConfigDict

from onyx.access.access import source_should_fetch_permissions_during_indexing
from onyx.background.indexing.run_docfetching import (
    _get_run_config,
    cache_and_upsert_hierarchy_nodes,
    send_docprocessing_batch,
    set_document_parent_node_ids,
    strip_null_characters,
)
from onyx.configs.app_configs import DOCCONVERSION_WINDOW_BATCHES
from onyx.configs.constants import (
    DocumentSource,
    OnyxCeleryPriority,
    OnyxCeleryQueues,
    OnyxCeleryTask,
)
from onyx.connectors.factory import instantiate_connector
from onyx.connectors.interfaces import BaseConnector, Resolver
from onyx.connectors.models import (
    ConnectorFailure,
    Document,
    HierarchyNode,
    ResolveTarget,
)
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import AccessType, IndexModelStatus
from onyx.db.index_attempt import create_index_attempt_error, get_index_attempt
from onyx.db.index_attempt_metrics import safe_record_single_event, time_stage
from onyx.db.index_attempt_metrics_models import IndexAttemptStage
from onyx.db.indexing_coordination import IndexingCoordination
from onyx.db.models import Connector, Credential
from onyx.file_store.document_batch_storage import (
    get_document_batch_storage,
    get_stub_batch_storage,
)
from onyx.file_store.staging import build_raw_file_callback
from onyx.redis.redis_connector import RedisConnector
from onyx.redis.redis_docprocessing import BatchStage, RedisDocprocessing
from onyx.redis.redis_pool import get_redis_client
from onyx.utils.logger import setup_logger

logger = setup_logger()

# A conversion or docprocessing task that waits longer than this is dropped.
# The window keeps each attempt's queue short, so a task waits only when the
# workers are down. The stalled-chain check sends a dropped batch again.
DOCCONVERSION_TASK_EXPIRES_SECONDS = 4 * 60 * 60
# How long a worker process keeps the connector of an attempt. A build loads
# the credential and signs in, so one build for each task is too many.
_CONNECTOR_CACHE_SECONDS = 10 * 60
_CONNECTOR_CACHE_MAX_ENTRIES = 16


class ConversionContext(BaseModel):
    """What a conversion task needs to know about its attempt. It stays the
    same for the life of the attempt, so a worker process keeps it with the
    connector."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    connector: BaseConnector
    db_connector: Connector
    db_credential: Credential
    source: DocumentSource
    is_connector_public: bool
    include_permissions: bool
    docprocessing_priority: OnyxCeleryPriority
    is_backfill: bool
    built_at: float


_context_cache: dict[tuple[str, int], ConversionContext] = {}
_context_cache_lock = threading.Lock()


def _build_context(
    index_attempt_id: int, cc_pair_id: int, tenant_id: str
) -> ConversionContext:
    with get_session_with_current_tenant() as db_session:
        attempt = get_index_attempt(
            db_session,
            index_attempt_id,
            eager_load_cc_pair=True,
            eager_load_search_settings=True,
        )
        if attempt is None:
            raise RuntimeError(f"Index attempt {index_attempt_id} not found")
        cc_pair = attempt.connector_credential_pair
        db_connector = cc_pair.connector
        db_credential = cc_pair.credential
        is_primary = (
            attempt.search_settings is not None
            and attempt.search_settings.status == IndexModelStatus.PRESENT
        )
        has_successful_attempt = cc_pair.last_successful_index_time is not None
        redis_connector = RedisConnector(tenant_id, cc_pair_id)
        connector = instantiate_connector(
            db_session=db_session,
            source=db_connector.source,
            input_type=db_connector.input_type,
            connector_specific_config=_get_run_config(attempt),
            credential=db_credential,
            raw_file_callback=build_raw_file_callback(
                index_attempt_id=index_attempt_id,
                cc_pair_id=cc_pair_id,
                tenant_id=tenant_id,
            ),
            should_stop=lambda: bool(redis_connector.stop.fenced),
        )
        # The same rules as docfetching, which makes these choices for the
        # documents it fetches itself.
        include_permissions = (
            cc_pair.access_type.is_perm_synced()
            and source_should_fetch_permissions_during_indexing(db_connector.source)
            and (
                db_connector.source == DocumentSource.ZOOM
                or (
                    is_primary
                    and (attempt.from_beginning or not has_successful_attempt)
                )
            )
        )
        context = ConversionContext(
            connector=connector,
            db_connector=db_connector,
            db_credential=db_credential,
            source=db_connector.source,
            is_connector_public=cc_pair.access_type == AccessType.PUBLIC,
            include_permissions=include_permissions,
            docprocessing_priority=(
                OnyxCeleryPriority.MEDIUM
                if has_successful_attempt
                else OnyxCeleryPriority.HIGH
            ),
            is_backfill=attempt.is_backfill,
            built_at=time.monotonic(),
        )
        # The rows are read after the session closes.
        db_session.expunge_all()
    return context


def get_conversion_context(
    index_attempt_id: int, cc_pair_id: int, tenant_id: str
) -> ConversionContext:
    """The attempt's connector and settings, built once for each worker
    process and kept for a few minutes."""
    key = (tenant_id, index_attempt_id)
    now = time.monotonic()
    with _context_cache_lock:
        context = _context_cache.get(key)
        if context is not None and now - context.built_at < _CONNECTOR_CACHE_SECONDS:
            return context
    # Built outside the lock: a build signs in to the source. Two threads can
    # build at the same time, and the last one stays.
    context = _build_context(index_attempt_id, cc_pair_id, tenant_id)
    with _context_cache_lock:
        for stale in [
            k
            for k, c in _context_cache.items()
            if now - c.built_at >= _CONNECTOR_CACHE_SECONDS
        ]:
            del _context_cache[stale]
        if len(_context_cache) >= _CONNECTOR_CACHE_MAX_ENTRIES:
            oldest = min(_context_cache, key=lambda k: _context_cache[k].built_at)
            del _context_cache[oldest]
        _context_cache[key] = context
    return context


def clear_conversion_context_cache() -> None:
    """For tests."""
    with _context_cache_lock:
        _context_cache.clear()


def attempt_should_stop(index_attempt_id: int, cc_pair_id: int, tenant_id: str) -> bool:
    """True when the attempt was canceled or paused, or it ended. Conversion
    then does no more work for it."""
    if RedisConnector(tenant_id, cc_pair_id).stop.fenced:
        return True
    with get_session_with_current_tenant() as db_session:
        attempt = get_index_attempt(db_session, index_attempt_id)
        return (
            attempt is None
            or attempt.cancellation_requested
            or attempt.status.is_terminal()
        )


def dispatch_stub_batches(
    app: Celery,
    *,
    index_attempt_id: int,
    cc_pair_id: int,
    tenant_id: str,
    is_backfill: bool,
) -> list[int]:
    """Claims the stub batches that can go to conversion now and sends a
    task for each. Returns their numbers. The claim is one atomic update, so
    callers that run at the same time never send one batch twice."""
    with get_session_with_current_tenant() as db_session:
        batch_nums = IndexingCoordination.claim_stub_batches(
            db_session, index_attempt_id, DOCCONVERSION_WINDOW_BATCHES
        )
    for batch_num in batch_nums:
        send_docconversion_batch(
            app,
            index_attempt_id=index_attempt_id,
            cc_pair_id=cc_pair_id,
            tenant_id=tenant_id,
            batch_num=batch_num,
            is_backfill=is_backfill,
        )
    return batch_nums


def send_docconversion_batch(
    app: Celery,
    *,
    index_attempt_id: int,
    cc_pair_id: int,
    tenant_id: str,
    batch_num: int,
    is_backfill: bool,
) -> None:
    kwargs: dict[str, Any] = {
        "index_attempt_id": index_attempt_id,
        "cc_pair_id": cc_pair_id,
        "tenant_id": tenant_id,
        "batch_num": batch_num,
        "enqueue_time_ms": int(time.time() * 1000),
    }
    if is_backfill:
        kwargs["is_backfill"] = True
    try:
        RedisDocprocessing(
            index_attempt_id,
            get_redis_client(tenant_id=tenant_id),
            BatchStage.DOCCONVERSION,
        ).incr_pending()
    except Exception:
        logger.debug(
            "Failed to increment the conversion pending counter for attempt %s",
            index_attempt_id,
            exc_info=True,
        )
    app.send_task(
        OnyxCeleryTask.DOCCONVERSION_TASK,
        kwargs=kwargs,
        queue=OnyxCeleryQueues.DOCCONVERSION,
        priority=OnyxCeleryPriority.MEDIUM,
        expires=DOCCONVERSION_TASK_EXPIRES_SECONDS,
    )


def convert_stub_batch(
    app: Celery,
    *,
    index_attempt_id: int,
    cc_pair_id: int,
    tenant_id: str,
    batch_num: int,
    enqueue_time_ms: int | None = None,
    is_backfill: bool = False,
) -> None:
    """Converts one stub batch into a document batch and sends it to
    docprocessing.

    The order of the last steps makes a second run of the task safe. The
    stub batch is deleted when the document batch is stored, before the
    docprocessing send. So a stub batch that exists was never sent on, and a
    second run can convert it again. A second run that finds no stub batch
    does nothing."""
    if enqueue_time_ms is not None:
        safe_record_single_event(
            IndexAttemptStage.CONVERSION_QUEUE_WAIT,
            index_attempt_id,
            max(0, int(time.time() * 1000) - enqueue_time_ms),
        )
    if attempt_should_stop(index_attempt_id, cc_pair_id, tenant_id):
        logger.info(
            "Conversion skipped: attempt=%s batch_num=%s is stopped",
            index_attempt_id,
            batch_num,
        )
        return

    context = get_conversion_context(index_attempt_id, cc_pair_id, tenant_id)
    connector = context.connector
    if not isinstance(connector, Resolver):
        raise RuntimeError(
            f"Connector of source {context.source} cannot convert listed documents"
        )
    stub_storage = get_stub_batch_storage(
        cc_pair_id, index_attempt_id, is_backfill=is_backfill
    )
    with time_stage(IndexAttemptStage.STUB_BATCH_LOAD, index_attempt_id):
        stubs = stub_storage.get_batch(batch_num, connector.listing_payload_type)
    if stubs is None:
        # An earlier run of this task converted the batch.
        logger.info(
            "Conversion skipped: attempt=%s batch_num=%s has no stub batch",
            index_attempt_id,
            batch_num,
        )
        dispatch_stub_batches(
            app,
            index_attempt_id=index_attempt_id,
            cc_pair_id=cc_pair_id,
            tenant_id=tenant_id,
            is_backfill=is_backfill,
        )
        return

    documents: list[Document] = []
    hierarchy_nodes: list[HierarchyNode] = []
    failures: list[ConnectorFailure] = []
    with time_stage(IndexAttemptStage.CONVERSION, index_attempt_id):
        for item in connector.resolve_targets(
            [
                ResolveTarget(document_id=stub.id, listing_payload=stub.listing_payload)
                for stub in stubs
            ],
            context.include_permissions,
        ):
            if isinstance(item, Document):
                documents.append(item)
            elif isinstance(item, HierarchyNode):
                hierarchy_nodes.append(item)
            else:
                failures.append(item)

    # The conversion can take minutes. Do not store work for a stopped attempt.
    if attempt_should_stop(index_attempt_id, cc_pair_id, tenant_id):
        logger.info(
            "Conversion dropped: attempt=%s batch_num=%s stopped during the batch",
            index_attempt_id,
            batch_num,
        )
        return

    if failures:
        with get_session_with_current_tenant() as db_session:
            for failure in failures:
                create_index_attempt_error(
                    index_attempt_id, cc_pair_id, failure, db_session
                )
    if hierarchy_nodes:
        cache_and_upsert_hierarchy_nodes(
            context.db_connector,
            context.db_credential,
            context.is_connector_public,
            hierarchy_nodes,
        )

    documents = strip_null_characters(documents)
    if documents:
        set_document_parent_node_ids(
            get_redis_client(tenant_id=tenant_id),
            documents,
            source=context.source,
            connector_id=context.db_connector.id,
            credential_id=context.db_credential.id,
        )
        doc_storage = get_document_batch_storage(
            cc_pair_id, index_attempt_id, is_backfill=is_backfill
        )
        with time_stage(IndexAttemptStage.CONVERSION_DOC_BATCH_STORE, index_attempt_id):
            # Left by a run that stopped before it deleted the stub batch.
            doc_storage.delete_batch_by_num(batch_num)
            doc_storage.store_batch(batch_num, documents)

    stub_storage.delete_batch_by_num(batch_num)
    with get_session_with_current_tenant() as db_session:
        IndexingCoordination.record_stub_batch_converted(db_session, index_attempt_id)
        if not documents:
            # No document is left, so no docprocessing task will count the
            # batch. Count it as complete here.
            IndexingCoordination.update_batch_completion_and_docs(
                db_session=db_session,
                index_attempt_id=index_attempt_id,
                total_docs_indexed=0,
                new_docs_indexed=0,
                total_chunks=0,
            )
    if documents:
        send_docprocessing_batch(
            app,
            index_attempt_id=index_attempt_id,
            cc_pair_id=cc_pair_id,
            tenant_id=tenant_id,
            batch_num=batch_num,
            priority=context.docprocessing_priority,
            is_backfill=is_backfill,
            expires=DOCCONVERSION_TASK_EXPIRES_SECONDS,
        )
    logger.info(
        "Converted stub batch: attempt=%s batch_num=%s stubs=%s docs=%s failures=%s",
        index_attempt_id,
        batch_num,
        len(stubs),
        len(documents),
        len(failures),
    )

    with time_stage(IndexAttemptStage.CONVERSION_DISPATCH, index_attempt_id):
        dispatch_stub_batches(
            app,
            index_attempt_id=index_attempt_id,
            cc_pair_id=cc_pair_id,
            tenant_id=tenant_id,
            is_backfill=is_backfill,
        )
