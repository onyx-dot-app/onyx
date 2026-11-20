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
from uuid import uuid4

from celery import Celery
from pydantic import BaseModel, ConfigDict

from onyx.access.access import source_should_fetch_permissions_during_indexing
from onyx.background.indexing.run_docfetching import (
    _get_run_config,
    cache_and_upsert_hierarchy_nodes,
    select_docprocessing_priority,
    send_docprocessing_batch,
    set_document_parent_node_ids,
    strip_null_characters,
)
from onyx.configs.app_configs import (
    DOCCONVERSION_WINDOW_BATCHES,
    PERSISTENT_INDEXING,
)
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
    DocumentFailure,
    HierarchyNode,
    ResolveTarget,
    SlimDocumentStub,
)
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import AccessType, IndexModelStatus
from onyx.db.index_attempt import create_index_attempt_error, get_index_attempt
from onyx.db.index_attempt_metrics import safe_record_single_event, time_stage
from onyx.db.index_attempt_metrics_models import IndexAttemptStage
from onyx.db.indexing_coordination import IndexingCoordination
from onyx.db.models import Connector, Credential
from onyx.db.port_attempt import reindex_finalizing
from onyx.db.search_settings import get_search_settings_by_id
from onyx.file_store.document_batch_storage import (
    get_document_batch_storage,
    get_stub_batch_storage,
)
from onyx.file_store.staging import build_raw_file_callback
from onyx.redis.redis_connector import RedisConnector
from onyx.redis.redis_docprocessing import (
    BatchStage,
    RedisDocprocessing,
    claim_conversion_batch,
    release_conversion_batch_claim,
)
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
# The attempt fails when more than this many stub batches failed, and they are
# more than this share of the converted batches. A batch failed when it
# failed as a whole, or when more than this share of its documents failed.
# Docfetching and docprocessing use the same limits for failed documents.
_FAILED_BATCH_THRESHOLD = 3
_FAILED_BATCH_RATIO_THRESHOLD = 0.1


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
    # A FUTURE attempt below HIGH checks again for each batch: the priority
    # rises when its port-flow reindex starts to finalize.
    recheck_finalizing: bool
    search_settings_id: int | None
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
            # Many conversion threads share the budget: their calls wait after
            # listing and permission sync.
            bulk_source_api_calls=True,
            cc_pair_id=cc_pair_id,
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
        # The same rule as docfetching.
        docprocessing_priority = select_docprocessing_priority(
            db_session,
            is_primary=is_primary,
            has_successful_attempt=has_successful_attempt,
            search_settings=attempt.search_settings,
        )
        context = ConversionContext(
            connector=connector,
            db_connector=db_connector,
            db_credential=db_credential,
            source=db_connector.source,
            is_connector_public=cc_pair.access_type == AccessType.PUBLIC,
            include_permissions=include_permissions,
            docprocessing_priority=docprocessing_priority,
            recheck_finalizing=(
                not is_primary and docprocessing_priority != OnyxCeleryPriority.HIGH
            ),
            search_settings_id=attempt.search_settings_id,
            is_backfill=attempt.is_backfill,
            built_at=time.monotonic(),
        )
        # The rows are read after the session closes.
        db_session.expunge_all()
    return context


def _docprocessing_priority(
    context: ConversionContext, index_attempt_id: int
) -> OnyxCeleryPriority:
    """The priority of the batch's docprocessing task. A cached context keeps
    a FUTURE attempt's priority for minutes, so it checks again here."""
    if not context.recheck_finalizing:
        return context.docprocessing_priority
    with get_session_with_current_tenant() as db_session:
        search_settings = (
            get_search_settings_by_id(db_session, context.search_settings_id)
            if context.search_settings_id is not None
            else None
        )
        if reindex_finalizing(db_session, search_settings):
            logger.info(
                "Reindex finalizing: attempt=%s sends its batches at HIGH",
                index_attempt_id,
            )
            return OnyxCeleryPriority.HIGH
    return context.docprocessing_priority


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
    task_id: str | None = None,
) -> list[int]:
    """Claims the stub batches that can go to conversion now and sends a
    task for each. Returns their numbers. The claim is one atomic update, so
    callers that run at the same time never send one batch twice.

    `task_id` is the caller's Celery task. The attempt keeps it as the last
    task that dispatched, for the watchdog."""
    with get_session_with_current_tenant() as db_session:
        batch_nums = IndexingCoordination.claim_stub_batches(
            db_session, index_attempt_id, DOCCONVERSION_WINDOW_BATCHES, task_id
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


def _unconverted_stub_failures(
    stubs: list[SlimDocumentStub],
    documents: list[Document],
    failures: list[ConnectorFailure],
    error: Exception,
) -> list[ConnectorFailure]:
    """A failure for each stub that the failed conversion gave no document
    and no failure. Each names its document, so the attempt can still end
    with errors, and a later attempt converts the document again."""
    done = {document.id for document in documents} | {
        failure.failed_document.document_id
        for failure in failures
        if failure.failed_document is not None
    }
    return [
        ConnectorFailure(
            failed_document=DocumentFailure(document_id=stub.id),
            failure_message=f"The conversion of its stub batch failed: {error}",
            exception=error,
        )
        for stub in stubs
        if stub.id not in done
    ]


def _batch_failure(
    stubs: list[SlimDocumentStub],
    failures: list[ConnectorFailure],
    batch_error: Exception | None,
) -> Exception | None:
    """The error that counts the batch as failed, or None. A source that
    reports a failure for each document, and raises nothing, must also end
    the attempt."""
    if batch_error is not None:
        return batch_error
    if not failures or len(failures) / max(len(stubs), 1) <= (
        _FAILED_BATCH_RATIO_THRESHOLD
    ):
        return None
    last_failure = failures[-1]
    return last_failure.exception or RuntimeError(last_failure.failure_message)


def _check_failed_batch_threshold(
    failed_batches: int, converted_batches: int, error: Exception
) -> None:
    """Fails the attempt when the source fails for many of its batches, not
    for one of them."""
    if PERSISTENT_INDEXING:
        return
    if (
        failed_batches > _FAILED_BATCH_THRESHOLD
        and failed_batches / max(converted_batches, 1) > _FAILED_BATCH_RATIO_THRESHOLD
    ):
        raise RuntimeError(
            f"The conversion failed for {failed_batches} of {converted_batches} "
            f"stub batches. Last error: {error}"
        ) from error


def convert_stub_batch(
    app: Celery,
    *,
    index_attempt_id: int,
    cc_pair_id: int,
    tenant_id: str,
    batch_num: int,
    enqueue_time_ms: int | None = None,
    is_backfill: bool = False,
    task_id: str | None = None,
) -> None:
    """Converts one stub batch into a document batch and sends it to
    docprocessing.

    The order of the last steps makes a second run of the task safe. The
    stub batch is deleted when the document batch is stored, before the
    docprocessing send. So a stub batch that exists was never sent on, and a
    second run can convert it again. A second run that finds no stub batch
    does nothing. A claim keeps two runs from converting one batch at the
    same time: a recovery resend can overlap a run that still converts."""
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

    redis_client = get_redis_client(tenant_id=tenant_id)
    claim_owner = task_id or uuid4().hex
    if not claim_conversion_batch(
        redis_client, index_attempt_id, batch_num, claim_owner
    ):
        logger.info(
            "Conversion skipped: attempt=%s batch_num=%s converts in another run",
            index_attempt_id,
            batch_num,
        )
        return
    try:
        _convert_claimed_stub_batch(
            app,
            index_attempt_id=index_attempt_id,
            cc_pair_id=cc_pair_id,
            tenant_id=tenant_id,
            batch_num=batch_num,
            is_backfill=is_backfill,
            task_id=task_id,
        )
    finally:
        release_conversion_batch_claim(
            redis_client, index_attempt_id, batch_num, claim_owner
        )


def _convert_claimed_stub_batch(
    app: Celery,
    *,
    index_attempt_id: int,
    cc_pair_id: int,
    tenant_id: str,
    batch_num: int,
    is_backfill: bool,
    task_id: str | None,
) -> None:
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
            task_id=task_id,
        )
        return

    documents: list[Document] = []
    hierarchy_nodes: list[HierarchyNode] = []
    failures: list[ConnectorFailure] = []
    batch_error: Exception | None = None
    with time_stage(IndexAttemptStage.CONVERSION, index_attempt_id):
        try:
            for item in connector.resolve_targets(
                [
                    ResolveTarget(
                        document_id=stub.id, listing_payload=stub.listing_payload
                    )
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
        except Exception as e:
            # One batch's error does not end the attempt: the documents it did
            # not convert become failures. The threshold below ends an
            # attempt whose source fails for many batches.
            logger.exception(
                "Conversion failed: attempt=%s batch_num=%s",
                index_attempt_id,
                batch_num,
            )
            batch_error = e
            failures.extend(
                _unconverted_stub_failures(stubs, documents, failures, batch_error)
            )

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
        # Left by a run that stopped before it deleted the stub batch. It goes
        # also when this run gives no document, so it is not sent twice.
        doc_storage.delete_batch_by_num(batch_num)
        # A batch with no document is stored empty. It is the durable record
        # of the batch until docprocessing counts it complete, so a worker
        # that stops after the stub delete loses no completion.
        doc_storage.store_batch(batch_num, documents)

    stub_storage.delete_batch_by_num(batch_num)
    with get_session_with_current_tenant() as db_session:
        IndexingCoordination.record_stub_batch_converted(db_session, index_attempt_id)
    send_docprocessing_batch(
        app,
        index_attempt_id=index_attempt_id,
        cc_pair_id=cc_pair_id,
        tenant_id=tenant_id,
        batch_num=batch_num,
        priority=_docprocessing_priority(context, index_attempt_id),
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
    batch_failure = _batch_failure(stubs, failures, batch_error)
    if batch_failure is not None:
        with get_session_with_current_tenant() as db_session:
            failed_batches, converted_batches = (
                IndexingCoordination.record_stub_batch_conversion_failed(
                    db_session, index_attempt_id
                )
            )
        _check_failed_batch_threshold(failed_batches, converted_batches, batch_failure)

    with time_stage(IndexAttemptStage.CONVERSION_DISPATCH, index_attempt_id):
        dispatch_stub_batches(
            app,
            index_attempt_id=index_attempt_id,
            cc_pair_id=cc_pair_id,
            tenant_id=tenant_id,
            is_backfill=is_backfill,
            task_id=task_id,
        )
