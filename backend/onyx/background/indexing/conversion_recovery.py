"""Recovery for the conversion chain of an index attempt.

The chain feeds itself: the lister and each conversion task send the next
stub batches. If the task that must send next stops first, stub batches wait
and nothing runs. The watchdog calls ``check_conversion_chain`` to tell that
state from a dead attempt, and to start the chain again.
"""

from datetime import datetime, timedelta, timezone
from enum import Enum

from celery import Celery
from redis import Redis

from onyx.background.celery.celery_redis import (
    celery_find_task,
    celery_get_task_kwargs,
    celery_get_unacked_task_ids,
)
from onyx.background.indexing.run_docconversion import (
    DOCCONVERSION_TASK_EXPIRES_SECONDS,
    dispatch_stub_batches,
    send_docconversion_batch,
)
from onyx.background.indexing.run_docfetching import send_docprocessing_batch
from onyx.configs.app_configs import DOCCONVERSION_STALL_SECONDS
from onyx.configs.constants import OnyxCeleryPriority, OnyxCeleryQueues
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.index_attempt import get_index_attempt
from onyx.db.indexing_coordination import IndexingCoordination
from onyx.file_store.document_batch_storage import (
    get_document_batch_storage,
    get_stub_batch_storage,
)
from onyx.redis.redis_docprocessing import BatchStage, RedisDocprocessing
from onyx.redis.redis_pool import get_redis_client
from onyx.utils.logger import setup_logger

logger = setup_logger()

_STAGE_QUEUES = {
    BatchStage.DOCCONVERSION: OnyxCeleryQueues.DOCCONVERSION,
    BatchStage.DOCPROCESSING: OnyxCeleryQueues.DOCPROCESSING,
}


class ConversionChainState(str, Enum):
    # The attempt does not use the conversion stage, or no stub batch waits.
    IDLE = "idle"
    # A task dispatched a short time ago, or the last task that dispatched
    # is still in the queue.
    HEALTHY = "healthy"
    # Conversion tasks of the attempt exist. Each one dispatches when it ends.
    BUSY = "busy"
    # The chain was broken, and this check sent batches.
    RECOVERED = "recovered"
    # Stub batches wait, no task exists, and nothing could be sent.
    STUCK = "stuck"


def _stage_has_tasks(
    stage: BatchStage, index_attempt_id: int, tenant_id: str, broker: Redis
) -> bool:
    """True when a task of the stage can exist for the attempt. A task that
    expired in the queue leaves its pending count behind, so a pending count
    is checked against the attempt's tasks in the queue and the unacked hash.
    Tasks of other attempts do not count: a worker that was killed leaves its
    tasks unacked until the visibility timeout, hours later.

    A killed worker also leaves the in-flight count raised. A running
    conversion task keeps a live entry, so that stage checks the entries in
    place of the count."""
    counters = RedisDocprocessing(
        index_attempt_id, get_redis_client(tenant_id=tenant_id), stage
    )
    if stage == BatchStage.DOCCONVERSION:
        if counters.has_live_task():
            return True
    elif counters.in_flight() > 0:
        return True
    if counters.pending() == 0:
        return False
    # Attempt ids repeat across tenants, so the tenant must match too.
    return any(
        kwargs.get("index_attempt_id") == index_attempt_id
        and kwargs.get("tenant_id") == tenant_id
        for kwargs in celery_get_task_kwargs(_STAGE_QUEUES[stage], broker)
    )


def _task_is_queued(task_id: str, broker: Redis) -> bool:
    """True when the task waits in a queue or a worker holds it unacked. A
    task that runs after an ack on receipt is in neither place: the live entry
    covers a conversion task that runs."""
    for queue in (
        OnyxCeleryQueues.DOCCONVERSION,
        OnyxCeleryQueues.CONNECTOR_DOC_FETCHING,
    ):
        if celery_find_task(task_id, queue, broker):
            return True
        if task_id in celery_get_unacked_task_ids(queue, broker):
            return True
    return False


def restart_conversion_chain(
    app: Celery,
    broker: Redis,
    *,
    index_attempt_id: int,
    cc_pair_id: int,
    tenant_id: str,
    is_backfill: bool,
) -> int:
    """Sends what a broken chain left behind and returns the number of sends.
    Call it only when no conversion task of the attempt exists.

    A sent stub batch that is still in the store was never converted: send it
    again. A sent stub batch that is not in the store was converted, so the
    count is corrected for a task that stopped before it counted. A document
    batch in the store with no docprocessing task was never sent on: send it.
    Then dispatch the stub batches that were never sent."""
    # No conversion task runs, so the in-flight count is from killed workers.
    RedisDocprocessing(
        index_attempt_id,
        get_redis_client(tenant_id=tenant_id),
        BatchStage.DOCCONVERSION,
    ).reset_in_flight()
    with get_session_with_current_tenant() as db_session:
        attempt = get_index_attempt(db_session, index_attempt_id)
        if attempt is None:
            return 0
        sent = attempt.stub_batches_sent

    stub_storage = get_stub_batch_storage(
        cc_pair_id, index_attempt_id, is_backfill=is_backfill
    )
    lost = sorted(n for n in stub_storage.stored_batch_nums() if n < sent)
    for batch_num in lost:
        send_docconversion_batch(
            app,
            index_attempt_id=index_attempt_id,
            cc_pair_id=cc_pair_id,
            tenant_id=tenant_id,
            batch_num=batch_num,
            is_backfill=is_backfill,
        )
    sends = len(lost)

    if not lost:
        # Not a send: it only lets the dispatch below claim again.
        with get_session_with_current_tenant() as db_session:
            IndexingCoordination.settle_stub_batches_converted(
                db_session, index_attempt_id
            )

    if not _stage_has_tasks(
        BatchStage.DOCPROCESSING, index_attempt_id, tenant_id, broker
    ):
        doc_storage = get_document_batch_storage(
            cc_pair_id, index_attempt_id, is_backfill=is_backfill
        )
        for batch_file_name in doc_storage.get_all_batches_for_cc_pair():
            path_info = doc_storage.extract_path_info(batch_file_name)
            if path_info is None or path_info.index_attempt_id != index_attempt_id:
                continue
            send_docprocessing_batch(
                app,
                index_attempt_id=index_attempt_id,
                cc_pair_id=cc_pair_id,
                tenant_id=tenant_id,
                batch_num=path_info.batch_num,
                priority=OnyxCeleryPriority.MEDIUM,
                is_backfill=is_backfill,
                expires=DOCCONVERSION_TASK_EXPIRES_SECONDS,
            )
            sends += 1

    sends += len(
        dispatch_stub_batches(
            app,
            index_attempt_id=index_attempt_id,
            cc_pair_id=cc_pair_id,
            tenant_id=tenant_id,
            is_backfill=is_backfill,
        )
    )
    return sends


def check_conversion_chain(
    app: Celery,
    broker: Redis,
    *,
    index_attempt_id: int,
    tenant_id: str,
) -> ConversionChainState:
    """Checks the conversion chain of an attempt and starts it again if it is
    broken. The sends of a restart are atomic claims, so a restart that races
    with a live task sends no batch twice."""
    with get_session_with_current_tenant() as db_session:
        attempt = get_index_attempt(db_session, index_attempt_id)
        if attempt is None or not attempt.uses_conversion_stage:
            return ConversionChainState.IDLE
        waiting = (
            attempt.stub_batches_stored > attempt.stub_batches_sent
            or attempt.stub_batches_sent > attempt.stub_batches_converted
        )
        if not waiting:
            return ConversionChainState.IDLE
        last_dispatch_at = attempt.last_dispatch_at
        last_dispatch_task_id = attempt.last_dispatch_task_id
        cc_pair_id = attempt.connector_credential_pair_id
        is_backfill = attempt.is_backfill

    stall_cutoff = datetime.now(timezone.utc) - timedelta(
        seconds=DOCCONVERSION_STALL_SECONDS
    )
    if last_dispatch_at is not None and last_dispatch_at >= stall_cutoff:
        return ConversionChainState.HEALTHY
    if _stage_has_tasks(BatchStage.DOCCONVERSION, index_attempt_id, tenant_id, broker):
        return ConversionChainState.BUSY
    if last_dispatch_task_id is not None and _task_is_queued(
        last_dispatch_task_id, broker
    ):
        return ConversionChainState.HEALTHY

    sends = restart_conversion_chain(
        app,
        broker,
        index_attempt_id=index_attempt_id,
        cc_pair_id=cc_pair_id,
        tenant_id=tenant_id,
        is_backfill=is_backfill,
    )
    if sends == 0:
        logger.warning(
            "Conversion chain of attempt %s is stuck: nothing could be sent",
            index_attempt_id,
        )
        return ConversionChainState.STUCK
    with get_session_with_current_tenant() as db_session:
        IndexingCoordination.record_heartbeat(db_session, index_attempt_id)
    logger.warning(
        "Restarted the conversion chain of attempt %s: %s sends",
        index_attempt_id,
        sends,
    )
    return ConversionChainState.RECOVERED
