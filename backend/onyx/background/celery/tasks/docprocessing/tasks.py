import time
import traceback
from collections import defaultdict
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from http import HTTPStatus
from typing import Any

from celery import shared_task
from celery import Task
from celery.exceptions import SoftTimeLimitExceeded
from pydantic import BaseModel
from redis.lock import Lock as RedisLock
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.background.celery.apps.app_base import task_logger
from onyx.background.celery.celery_utils import httpx_init_vespa_pool
from onyx.background.celery.tasks.beat_schedule import CLOUD_BEAT_MULTIPLIER_DEFAULT
from onyx.background.celery.tasks.docprocessing.heartbeat import start_heartbeat
from onyx.background.celery.tasks.docprocessing.heartbeat import stop_heartbeat
from onyx.background.celery.tasks.docprocessing.utils import IndexingCallback
from onyx.background.celery.tasks.docprocessing.utils import is_in_repeated_error_state
from onyx.background.celery.tasks.docprocessing.utils import should_index
from onyx.background.celery.tasks.docprocessing.utils import (
    try_creating_docfetching_task,
)
from onyx.background.celery.tasks.models import DocProcessingContext
from onyx.background.indexing.checkpointing_utils import cleanup_checkpoint
from onyx.background.indexing.checkpointing_utils import (
    get_index_attempts_with_old_checkpoints,
)
from onyx.configs.app_configs import MANAGED_VESPA
from onyx.configs.app_configs import VESPA_CLOUD_CERT_PATH
from onyx.configs.app_configs import VESPA_CLOUD_KEY_PATH
from onyx.configs.constants import CELERY_GENERIC_BEAT_LOCK_TIMEOUT
from onyx.configs.constants import CELERY_INDEXING_LOCK_TIMEOUT
from onyx.configs.constants import OnyxCeleryPriority
from onyx.configs.constants import OnyxCeleryQueues
from onyx.configs.constants import OnyxCeleryTask
from onyx.configs.constants import OnyxRedisConstants
from onyx.configs.constants import OnyxRedisLocks
from onyx.configs.constants import OnyxRedisSignals
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import Document
from onyx.connectors.models import IndexAttemptMetadata
from onyx.db.connector import mark_ccpair_with_indexing_trigger
from onyx.db.connector_credential_pair import ConnectorType
from onyx.db.connector_credential_pair import (
    fetch_indexable_connector_credential_pair_ids,
)
from onyx.db.connector_credential_pair import get_connector_credential_pair_from_id
from onyx.db.connector_credential_pair import set_cc_pair_repeated_error_state
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.engine.time_utils import get_db_current_time
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.enums import IndexingMode
from onyx.db.enums import IndexingStatus
from onyx.db.index_attempt import create_index_attempt_error
from onyx.db.index_attempt import get_index_attempt
from onyx.db.index_attempt import get_index_attempt_errors_for_cc_pair
from onyx.db.index_attempt import IndexAttemptError
from onyx.db.index_attempt import mark_attempt_canceled
from onyx.db.index_attempt import mark_attempt_failed
from onyx.db.index_attempt import mark_attempt_partially_succeeded
from onyx.db.index_attempt import mark_attempt_succeeded
from onyx.db.indexing_coordination import CoordinationStatus
from onyx.db.indexing_coordination import IndexingCoordination
from onyx.db.models import IndexAttempt
from onyx.db.search_settings import get_active_search_settings_list
from onyx.db.search_settings import get_current_search_settings
from onyx.db.swap_index import check_and_perform_index_swap
from onyx.document_index.factory import get_default_document_index
from onyx.file_store.document_batch_storage import DocumentBatchStorage
from onyx.file_store.document_batch_storage import get_document_batch_storage
from onyx.httpx.httpx_pool import HttpxPool
from onyx.indexing.embedder import DefaultIndexingEmbedder
from onyx.indexing.indexing_pipeline import run_indexing_pipeline
from onyx.natural_language_processing.search_nlp_models import EmbeddingModel
from onyx.natural_language_processing.search_nlp_models import (
    InformationContentClassificationModel,
)
from onyx.natural_language_processing.search_nlp_models import warm_up_bi_encoder
from onyx.redis.redis_connector import RedisConnector
from onyx.redis.redis_pool import get_redis_client
from onyx.redis.redis_pool import get_redis_replica_client
from onyx.redis.redis_pool import redis_lock_dump
from onyx.redis.redis_pool import SCAN_ITER_COUNT_DEFAULT
from onyx.redis.redis_utils import is_fence
from onyx.server.runtime.onyx_runtime import OnyxRuntime
from onyx.utils.logger import setup_logger
from onyx.utils.logger import TaskAttemptSingleton
from onyx.utils.middleware import make_randomized_onyx_request_id
from onyx.utils.telemetry import optional_telemetry
from onyx.utils.telemetry import RecordType
from shared_configs.configs import INDEXING_MODEL_SERVER_HOST
from shared_configs.configs import INDEXING_MODEL_SERVER_PORT
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

logger = setup_logger()

USER_FILE_INDEXING_LIMIT = 100


def _get_fence_validation_block_expiration() -> int:
    """
    Compute the expiration time for the fence validation block signal.
    Base expiration is 60 seconds, multiplied by the beat multiplier only in MULTI_TENANT mode.
    """
    base_expiration = 60  # seconds

    if not MULTI_TENANT:
        return base_expiration

    try:
        beat_multiplier = OnyxRuntime.get_beat_multiplier()
    except Exception:
        beat_multiplier = CLOUD_BEAT_MULTIPLIER_DEFAULT

    return int(base_expiration * beat_multiplier)


def validate_active_indexing_attempts(
    lock_beat: RedisLock,
) -> None:
    """
    Validates that active indexing attempts are still alive by checking heartbeat.
    If no heartbeat has been received for a certain amount of time, mark the attempt as failed.

    This uses the heartbeat_counter field which is incremented by active worker threads
    every INDEXING_WORKER_HEARTBEAT_INTERVAL seconds.
    """
    logger.info("Validating active indexing attempts")
    # Heartbeat timeout: if no heartbeat received for 5 minutes, consider it dead
    # This should be much longer than INDEXING_WORKER_HEARTBEAT_INTERVAL (30s)
    HEARTBEAT_TIMEOUT_SECONDS = 30 * 60  # 30 minutes

    with get_session_with_current_tenant() as db_session:
        cutoff_time = datetime.now(timezone.utc) - timedelta(
            seconds=HEARTBEAT_TIMEOUT_SECONDS
        )

        # Find all active indexing attempts
        active_attempts = (
            db_session.execute(
                select(IndexAttempt).where(
                    IndexAttempt.status.in_([IndexingStatus.IN_PROGRESS]),
                    IndexAttempt.celery_task_id.isnot(None),
                )
            )
            .scalars()
            .all()
        )

        for attempt in active_attempts:
            lock_beat.reacquire()

            # Double-check the attempt still exists and has the same status
            fresh_attempt = get_index_attempt(db_session, attempt.id)
            if not fresh_attempt or fresh_attempt.status.is_terminal():
                continue

            # Check if this attempt has been updated with heartbeat tracking
            if fresh_attempt.last_heartbeat_time is None:
                # First time seeing this attempt - initialize heartbeat tracking
                fresh_attempt.last_heartbeat_value = fresh_attempt.heartbeat_counter
                fresh_attempt.last_heartbeat_time = datetime.now(timezone.utc)
                db_session.commit()

                task_logger.info(
                    f"Initialized heartbeat tracking for attempt {fresh_attempt.id}: "
                    f"counter={fresh_attempt.heartbeat_counter}"
                )
                continue

            # Check if the heartbeat counter has advanced since last check
            current_counter = fresh_attempt.heartbeat_counter
            last_known_counter = fresh_attempt.last_heartbeat_value
            last_check_time = fresh_attempt.last_heartbeat_time

            task_logger.debug(
                f"Checking heartbeat for attempt {fresh_attempt.id}: "
                f"current_counter={current_counter} "
                f"last_known_counter={last_known_counter} "
                f"last_check_time={last_check_time}"
            )

            if current_counter > last_known_counter:
                # Heartbeat has advanced - worker is alive
                fresh_attempt.last_heartbeat_value = current_counter
                fresh_attempt.last_heartbeat_time = datetime.now(timezone.utc)
                db_session.commit()

                task_logger.debug(
                    f"Heartbeat advanced for attempt {fresh_attempt.id}: "
                    f"new_counter={current_counter}"
                )
                continue

            # Heartbeat hasn't advanced - check if it's been too long
            if last_check_time >= cutoff_time:
                task_logger.debug(
                    f"Heartbeat hasn't advanced for attempt {fresh_attempt.id} but still within timeout window"
                )
                continue

            # No heartbeat for too long - mark as failed
            failure_reason = (
                f"No heartbeat received for {HEARTBEAT_TIMEOUT_SECONDS} seconds"
            )

            task_logger.warning(
                f"Heartbeat timeout for attempt {fresh_attempt.id}: "
                f"last_heartbeat_time={last_check_time} "
                f"cutoff_time={cutoff_time} "
                f"counter={current_counter}"
            )

            try:
                mark_attempt_failed(
                    fresh_attempt.id,
                    db_session,
                    failure_reason=failure_reason,
                )

                task_logger.error(
                    f"Marked attempt {fresh_attempt.id} as failed due to heartbeat timeout"
                )

            except Exception:
                task_logger.exception(
                    f"Failed to mark attempt {fresh_attempt.id} as failed due to heartbeat timeout"
                )


class ConnectorIndexingLogBuilder:
    def __init__(self, ctx: DocProcessingContext):
        self.ctx = ctx

    def build(self, msg: str, **kwargs: Any) -> str:
        msg_final = (
            f"{msg}: "
            f"tenant_id={self.ctx.tenant_id} "
            f"attempt={self.ctx.index_attempt_id} "
            f"cc_pair={self.ctx.cc_pair_id} "
            f"search_settings={self.ctx.search_settings_id}"
        )

        # Append extra keyword arguments in logfmt style
        if kwargs:
            extra_logfmt = " ".join(f"{key}={value}" for key, value in kwargs.items())
            msg_final = f"{msg_final} {extra_logfmt}"

        return msg_final


def monitor_indexing_attempt_progress(
    attempt: IndexAttempt, tenant_id: str, db_session: Session
) -> None:
    """
    TODO: rewrite this docstring
    Monitor the progress of an indexing attempt using database coordination.
    This replaces the Redis fence-based monitoring.

    Race condition handling:
    - Uses database coordination status to track progress
    - Only updates CC pair status based on confirmed database state
    - Handles concurrent completion gracefully
    """
    if not attempt.celery_task_id:
        # Attempt hasn't been assigned a task yet
        return

    cc_pair = get_connector_credential_pair_from_id(
        db_session, attempt.connector_credential_pair_id
    )
    if not cc_pair:
        task_logger.warning(f"CC pair not found for attempt {attempt.id}")
        return

    # Check if the CC Pair should be moved to INITIAL_INDEXING
    if cc_pair.status == ConnectorCredentialPairStatus.SCHEDULED:
        cc_pair.status = ConnectorCredentialPairStatus.INITIAL_INDEXING
        db_session.commit()

    # Get coordination status to track progress

    coordination_status = IndexingCoordination.get_coordination_status(
        db_session, attempt.id
    )

    current_db_time = get_db_current_time(db_session)
    if coordination_status.found:
        task_logger.info(
            f"Indexing attempt progress: "
            f"attempt={attempt.id} "
            f"cc_pair={attempt.connector_credential_pair_id} "
            f"search_settings={attempt.search_settings_id} "
            f"completed_batches={coordination_status.completed_batches} "
            f"total_batches={coordination_status.total_batches or '?'} "
            f"total_docs={coordination_status.total_docs} "
            f"total_failures={coordination_status.total_failures}"
            f"elapsed={(current_db_time - attempt.time_created).seconds}"
        )

    if coordination_status.cancellation_requested:
        task_logger.info(f"Indexing attempt {attempt.id} has been cancelled")
        mark_attempt_canceled(attempt.id, db_session)
        return

    storage = get_document_batch_storage(
        attempt.connector_credential_pair_id, attempt.id
    )

    # Check task completion using Celery
    try:
        check_indexing_completion(attempt.id, coordination_status, storage, tenant_id)
    except Exception as e:
        logger.exception(
            f"Failed to monitor document processing completion: "
            f"attempt={attempt.id} "
            f"error={str(e)}"
        )

        # Mark the attempt as failed if monitoring fails
        try:
            with get_session_with_current_tenant() as db_session:
                mark_attempt_failed(
                    attempt.id,
                    db_session,
                    failure_reason=f"Processing monitoring failed: {str(e)}",
                    full_exception_trace=traceback.format_exc(),
                )

        except Exception:
            logger.exception("Failed to mark attempt as failed")

        # Try to clean up storage
        try:
            logger.info(f"Cleaning up storage after monitoring failure: {storage}")
            storage.cleanup_all_batches()
        except Exception:
            logger.exception("Failed to cleanup storage after monitoring failure")


def check_indexing_completion(
    index_attempt_id: int,
    coordination_status: CoordinationStatus,
    storage: DocumentBatchStorage,
    tenant_id: str,
) -> None:

    logger.info(
        f"Checking for indexing completion: "
        f"attempt={index_attempt_id} "
        f"tenant={tenant_id}"
    )

    # Check if indexing is complete and all batches are processed
    batches_total = coordination_status.total_batches
    batches_processed = coordination_status.completed_batches
    indexing_completed = (
        batches_total is not None and batches_processed >= batches_total
    )

    logger.info(
        f"Indexing status: "
        f"indexing_completed={indexing_completed} "
        f"batches_processed={batches_processed}/{batches_total or '?'} "
        f"total_docs={coordination_status.total_docs} "
        f"total_chunks={coordination_status.total_chunks} "
        f"total_failures={coordination_status.total_failures}"
    )

    # Update progress tracking and check for stalls
    with get_session_with_current_tenant() as db_session:
        # Update progress tracking
        timed_out = not IndexingCoordination.update_progress_tracking(
            db_session, index_attempt_id, batches_processed
        )

        # Check for stalls (3-6 hour timeout). Only applies to in-progress attempts.
        attempt = get_index_attempt(db_session, index_attempt_id)
        if timed_out and attempt and attempt.status == IndexingStatus.IN_PROGRESS:
            logger.error(
                f"Indexing attempt {index_attempt_id} has been indexing for 3-6 hours without progress. "
                f"Marking it as failed."
            )
            mark_attempt_failed(
                index_attempt_id, db_session, failure_reason="Stalled indexing"
            )

    # check again on the next check_for_indexing task
    # TODO: on the cloud this is currently 25 minutes at most, which
    # is honestly too slow. We should either increase the frequency of
    # this task or change where we check for completion.
    if not indexing_completed:
        return

    # If processing is complete, handle completion
    logger.info(f"Connector indexing finished for index attempt {index_attempt_id}.")

    # All processing is complete
    total_failures = coordination_status.total_failures

    with get_session_with_current_tenant() as db_session:
        if total_failures == 0:
            attempt = mark_attempt_succeeded(index_attempt_id, db_session)
            logger.info(f"Index attempt {index_attempt_id} completed successfully")
        else:
            attempt = mark_attempt_partially_succeeded(index_attempt_id, db_session)
            logger.info(
                f"Index attempt {index_attempt_id} completed with {total_failures} failures"
            )

        # Update CC pair status if successful
        cc_pair = get_connector_credential_pair_from_id(
            db_session, attempt.connector_credential_pair_id
        )
        if cc_pair is None:
            raise RuntimeError(
                f"CC pair {attempt.connector_credential_pair_id} not found in database"
            )

        if attempt.status.is_successful():
            # NOTE: we define the last successful index time as the time the last successful
            # attempt finished. This is distinct from the poll_range_end of the last successful
            # attempt, which is the time up to which documents have been fetched.
            cc_pair.last_successful_index_time = attempt.time_updated
            if cc_pair.status in [
                ConnectorCredentialPairStatus.SCHEDULED,
                ConnectorCredentialPairStatus.INITIAL_INDEXING,
            ]:
                cc_pair.status = ConnectorCredentialPairStatus.ACTIVE
                db_session.commit()

            # Clear repeated error state on success
            if cc_pair.in_repeated_error_state:
                cc_pair.in_repeated_error_state = False
                db_session.commit()

            if attempt.status == IndexingStatus.SUCCESS:
                logger.info(
                    f"Resolving indexing entity errors for attempt {index_attempt_id}"
                )
                _resolve_indexing_entity_errors(
                    cc_pair_id=attempt.connector_credential_pair_id,
                    db_session=db_session,
                )

            # TODO: make it so we don't need this (might already be true)
            redis_connector = RedisConnector(
                tenant_id, attempt.connector_credential_pair_id
            )
            redis_connector_index = redis_connector.new_index(
                attempt.search_settings_id
            )
            redis_connector_index.set_generator_complete(HTTPStatus.OK.value)

    # Clean up FileStore storage (still needed for document batches during transition)
    try:
        logger.info(f"Cleaning up storage after indexing completion: {storage}")
        storage.cleanup_all_batches()
    except Exception:
        logger.exception("Failed to clean up document batches - continuing")

    logger.info(f"Database coordination completed for attempt {index_attempt_id}")


def _resolve_indexing_entity_errors(
    cc_pair_id: int,
    db_session: Session,
) -> None:
    unresolved_errors = get_index_attempt_errors_for_cc_pair(
        cc_pair_id=cc_pair_id,
        unresolved_only=True,
        db_session=db_session,
    )
    for error in unresolved_errors:
        if error.entity_id:
            error.is_resolved = True
            db_session.add(error)
    db_session.commit()


@shared_task(
    name=OnyxCeleryTask.CHECK_FOR_INDEXING,
    soft_time_limit=300,
    bind=True,
)
def check_for_indexing(self: Task, *, tenant_id: str) -> int | None:
    """a lightweight task used to kick off the pipeline of indexing tasks.
    Occcasionally does some validation of existing state to clear up error conditions.

    This task is the entrypoint for the full "indexing pipeline", which is composed
    of two tasks: "docfetching" and "docprocessing". More details in
    the docfetching task (OnyxCeleryTask.CONNECTOR_DOC_FETCHING_TASK).

    For cc pairs that should be indexed (see should_index()), this task
    calls try_creating_docfetching_task, which creates a docfetching task.
    All the logic for determining what state the indexing pipeline is in
    w.r.t previous failed attempt, checkpointing, etc is handled in the docfetching task.
    """

    time_start = time.monotonic()
    task_logger.warning("check_for_indexing - Starting")

    tasks_created = 0
    locked = False
    redis_client = get_redis_client()
    redis_client_replica = get_redis_replica_client()

    # we need to use celery's redis client to access its redis data
    # (which lives on a different db number)
    # redis_client_celery: Redis = self.app.broker_connection().channel().client  # type: ignore

    lock_beat: RedisLock = redis_client.lock(
        OnyxRedisLocks.CHECK_INDEXING_BEAT_LOCK,
        timeout=CELERY_GENERIC_BEAT_LOCK_TIMEOUT,
    )

    # these tasks should never overlap
    if not lock_beat.acquire(blocking=False):
        return None

    try:
        locked = True

        # SPECIAL 0/3: sync lookup table for active fences
        # we want to run this less frequently than the overall task
        if not redis_client.exists(OnyxRedisSignals.BLOCK_BUILD_FENCE_LOOKUP_TABLE):
            # build a lookup table of existing fences
            # this is just a migration concern and should be unnecessary once
            # lookup tables are rolled out
            for key_bytes in redis_client_replica.scan_iter(
                count=SCAN_ITER_COUNT_DEFAULT
            ):
                if is_fence(key_bytes) and not redis_client.sismember(
                    OnyxRedisConstants.ACTIVE_FENCES, key_bytes
                ):
                    logger.warning(f"Adding {key_bytes} to the lookup table.")
                    redis_client.sadd(OnyxRedisConstants.ACTIVE_FENCES, key_bytes)

            redis_client.set(
                OnyxRedisSignals.BLOCK_BUILD_FENCE_LOOKUP_TABLE,
                1,
                ex=OnyxRuntime.get_build_fence_lookup_table_interval(),
            )

        # 1/3: KICKOFF

        # check for search settings swap
        with get_session_with_current_tenant() as db_session:
            old_search_settings = check_and_perform_index_swap(db_session=db_session)
            current_search_settings = get_current_search_settings(db_session)
            # So that the first time users aren't surprised by really slow speed of first
            # batch of documents indexed
            if current_search_settings.provider_type is None and not MULTI_TENANT:
                if old_search_settings:
                    embedding_model = EmbeddingModel.from_db_model(
                        search_settings=current_search_settings,
                        server_host=INDEXING_MODEL_SERVER_HOST,
                        server_port=INDEXING_MODEL_SERVER_PORT,
                    )

                    # only warm up if search settings were changed
                    warm_up_bi_encoder(
                        embedding_model=embedding_model,
                    )

        # gather cc_pair_ids + current search settings
        lock_beat.reacquire()
        with get_session_with_current_tenant() as db_session:
            standard_cc_pair_ids = fetch_indexable_connector_credential_pair_ids(
                db_session, connector_type=ConnectorType.STANDARD
            )
            # only index 50 user files at a time. This makes sense since user files are
            # indexed only once, and then they are done. In practice, we would rarely
            # have more than `USER_FILE_INDEXING_LIMIT` user files to index.
            user_file_cc_pair_ids = fetch_indexable_connector_credential_pair_ids(
                db_session,
                connector_type=ConnectorType.USER_FILE,
                limit=USER_FILE_INDEXING_LIMIT,
            )
            cc_pair_ids = standard_cc_pair_ids + user_file_cc_pair_ids

            # NOTE: some potential race conditions here, but the worse case is
            # kicking off some "invalid" indexing tasks which will just fail
            search_settings_list = get_active_search_settings_list(db_session)

        current_search_settings = next(
            search_settings_instance
            for search_settings_instance in search_settings_list
            if search_settings_instance.status.is_current()
        )

        # mark CC Pairs that are repeatedly failing as in repeated error state
        with get_session_with_current_tenant() as db_session:
            for cc_pair_id in cc_pair_ids:
                lock_beat.reacquire()

                if is_in_repeated_error_state(
                    cc_pair_id=cc_pair_id,
                    search_settings_id=current_search_settings.id,
                    db_session=db_session,
                ):
                    set_cc_pair_repeated_error_state(
                        db_session=db_session,
                        cc_pair_id=cc_pair_id,
                        in_repeated_error_state=True,
                    )

        # kick off index attempts
        for cc_pair_id in cc_pair_ids:
            lock_beat.reacquire()

            with get_session_with_current_tenant() as db_session:
                for search_settings_instance in search_settings_list:
                    # skip non-live search settings that don't have background reindex enabled
                    # those should just auto-change to live shortly after creation without
                    # requiring any indexing till that point
                    if (
                        not search_settings_instance.status.is_current()
                        and not search_settings_instance.background_reindex_enabled
                    ):
                        task_logger.warning("SKIPPING DUE TO NON-LIVE SEARCH SETTINGS")

                        continue

                    # Check if there's already an active indexing attempt for this CC pair + search settings
                    # This prevents race conditions where multiple indexing attempts could be created
                    # We check for any non-terminal status (NOT_STARTED, IN_PROGRESS)
                    existing_attempts = (
                        db_session.execute(
                            select(IndexAttempt).where(
                                IndexAttempt.connector_credential_pair_id == cc_pair_id,
                                IndexAttempt.search_settings_id
                                == search_settings_instance.id,
                                IndexAttempt.status.in_(
                                    [
                                        IndexingStatus.NOT_STARTED,
                                        IndexingStatus.IN_PROGRESS,
                                    ]
                                ),
                            )
                        )
                        .scalars()
                        .all()
                    )

                    if existing_attempts:
                        task_logger.debug(
                            f"check_for_indexing - Skipping due to active indexing attempt: "
                            f"cc_pair={cc_pair_id} search_settings={search_settings_instance.id} "
                            f"active_attempts={[a.id for a in existing_attempts]}"
                        )
                        continue

                    cc_pair = get_connector_credential_pair_from_id(
                        db_session=db_session,
                        cc_pair_id=cc_pair_id,
                    )
                    if not cc_pair:
                        task_logger.warning(
                            f"check_for_indexing - CC pair not found: cc_pair={cc_pair_id}"
                        )
                        continue

                    if not should_index(
                        cc_pair=cc_pair,
                        search_settings_instance=search_settings_instance,
                        secondary_index_building=len(search_settings_list) > 1,
                        db_session=db_session,
                    ):
                        task_logger.debug(
                            f"check_for_indexing - Not indexing cc_pair_id: {cc_pair_id} "
                            f"search_settings={search_settings_instance.id}, "
                            f"secondary_index_building={len(search_settings_list) > 1}"
                        )
                        continue

                    task_logger.debug(
                        f"check_for_indexing - Will index cc_pair_id: {cc_pair_id} "
                        f"search_settings={search_settings_instance.id}, "
                        f"secondary_index_building={len(search_settings_list) > 1}"
                    )

                    reindex = False
                    if search_settings_instance.status.is_current():
                        # the indexing trigger is only checked and cleared with the current search settings
                        if cc_pair.indexing_trigger is not None:
                            if cc_pair.indexing_trigger == IndexingMode.REINDEX:
                                reindex = True

                            task_logger.info(
                                f"Connector indexing manual trigger detected: "
                                f"cc_pair={cc_pair.id} "
                                f"search_settings={search_settings_instance.id} "
                                f"indexing_mode={cc_pair.indexing_trigger}"
                            )

                            mark_ccpair_with_indexing_trigger(
                                cc_pair.id, None, db_session
                            )

                    # using a task queue and only allowing one task per cc_pair/search_setting
                    # prevents us from starving out certain attempts
                    attempt_id = try_creating_docfetching_task(
                        self.app,
                        cc_pair,
                        search_settings_instance,
                        reindex,
                        db_session,
                        redis_client,
                        tenant_id,
                    )
                    if attempt_id:
                        task_logger.info(
                            f"Connector indexing queued: "
                            f"index_attempt={attempt_id} "
                            f"cc_pair={cc_pair.id} "
                            f"search_settings={search_settings_instance.id}"
                        )
                        tasks_created += 1
                    else:
                        task_logger.info(
                            f"Failed to create indexing task: "
                            f"cc_pair={cc_pair.id} "
                            f"search_settings={search_settings_instance.id}"
                        )

        lock_beat.reacquire()

        # 2/3: VALIDATE

        # Check for inconsistent index attempts - active attempts without task IDs
        # This can happen if attempt creation fails partway through
        with get_session_with_current_tenant() as db_session:
            inconsistent_attempts = (
                db_session.execute(
                    select(IndexAttempt).where(
                        IndexAttempt.status.in_(
                            [IndexingStatus.NOT_STARTED, IndexingStatus.IN_PROGRESS]
                        ),
                        IndexAttempt.celery_task_id.is_(None),
                    )
                )
                .scalars()
                .all()
            )

            for attempt in inconsistent_attempts:
                lock_beat.reacquire()

                # Double-check the attempt still has the inconsistent state
                fresh_attempt = get_index_attempt(db_session, attempt.id)
                if (
                    not fresh_attempt
                    or fresh_attempt.celery_task_id
                    or fresh_attempt.status.is_terminal()
                ):
                    continue

                failure_reason = (
                    f"Inconsistent index attempt found - active status without Celery task: "
                    f"index_attempt={attempt.id} "
                    f"cc_pair={attempt.connector_credential_pair_id} "
                    f"search_settings={attempt.search_settings_id}"
                )
                task_logger.error(failure_reason)
                mark_attempt_failed(
                    attempt.id, db_session, failure_reason=failure_reason
                )

        lock_beat.reacquire()
        # we want to run this less frequently than the overall task
        if not redis_client.exists(OnyxRedisSignals.BLOCK_VALIDATE_INDEXING_FENCES):
            # Check for orphaned index attempts that have Celery task IDs but no actual running tasks
            # This can happen if workers crash or tasks are terminated unexpectedly
            # We reuse the same Redis signal name for backwards compatibility
            try:
                validate_active_indexing_attempts(lock_beat)
            except Exception:
                task_logger.exception(
                    "Exception while validating active indexing attempts"
                )

            redis_client.set(
                OnyxRedisSignals.BLOCK_VALIDATE_INDEXING_FENCES,
                1,
                ex=_get_fence_validation_block_expiration(),
            )

        # 3/3: FINALIZE - Monitor active indexing attempts using database
        lock_beat.reacquire()
        with get_session_with_current_tenant() as db_session:
            # Monitor all active indexing attempts directly from the database
            # This replaces the Redis fence-based monitoring
            active_attempts = (
                db_session.execute(
                    select(IndexAttempt).where(
                        IndexAttempt.status.in_(
                            [IndexingStatus.NOT_STARTED, IndexingStatus.IN_PROGRESS]
                        )
                    )
                )
                .scalars()
                .all()
            )

            for attempt in active_attempts:
                try:
                    monitor_indexing_attempt_progress(attempt, tenant_id, db_session)
                except Exception:
                    task_logger.exception(f"Error monitoring attempt {attempt.id}")

                lock_beat.reacquire()

    except SoftTimeLimitExceeded:
        task_logger.info(
            "Soft time limit exceeded, task is being terminated gracefully."
        )
    except Exception:
        task_logger.exception("Unexpected exception during indexing check")
    finally:
        if locked:
            if lock_beat.owned():
                lock_beat.release()
            else:
                task_logger.error(
                    "check_for_indexing - Lock not owned on completion: "
                    f"tenant={tenant_id}"
                )
                redis_lock_dump(lock_beat, redis_client)

    time_elapsed = time.monotonic() - time_start
    task_logger.info(f"check_for_indexing finished: elapsed={time_elapsed:.2f}")
    return tasks_created


# primary
@shared_task(
    name=OnyxCeleryTask.CHECK_FOR_CHECKPOINT_CLEANUP,
    soft_time_limit=300,
    bind=True,
)
def check_for_checkpoint_cleanup(self: Task, *, tenant_id: str) -> None:
    """Clean up old checkpoints that are older than 7 days."""
    locked = False
    redis_client = get_redis_client(tenant_id=tenant_id)
    lock: RedisLock = redis_client.lock(
        OnyxRedisLocks.CHECK_CHECKPOINT_CLEANUP_BEAT_LOCK,
        timeout=CELERY_GENERIC_BEAT_LOCK_TIMEOUT,
    )

    # these tasks should never overlap
    if not lock.acquire(blocking=False):
        return None

    try:
        locked = True
        with get_session_with_current_tenant() as db_session:
            old_attempts = get_index_attempts_with_old_checkpoints(db_session)
            for attempt in old_attempts:
                task_logger.info(
                    f"Cleaning up checkpoint for index attempt {attempt.id}"
                )
                self.app.send_task(
                    OnyxCeleryTask.CLEANUP_CHECKPOINT,
                    kwargs={
                        "index_attempt_id": attempt.id,
                        "tenant_id": tenant_id,
                    },
                    queue=OnyxCeleryQueues.CHECKPOINT_CLEANUP,
                    priority=OnyxCeleryPriority.MEDIUM,
                )
    except Exception:
        task_logger.exception("Unexpected exception during checkpoint cleanup")
        return None
    finally:
        if locked:
            if lock.owned():
                lock.release()
            else:
                task_logger.error(
                    "check_for_checkpoint_cleanup - Lock not owned on completion: "
                    f"tenant={tenant_id}"
                )


# light worker
@shared_task(
    name=OnyxCeleryTask.CLEANUP_CHECKPOINT,
    bind=True,
)
def cleanup_checkpoint_task(
    self: Task, *, index_attempt_id: int, tenant_id: str | None
) -> None:
    """Clean up a checkpoint for a given index attempt"""

    start = time.monotonic()

    try:
        with get_session_with_current_tenant() as db_session:
            cleanup_checkpoint(db_session, index_attempt_id)
    finally:
        elapsed = time.monotonic() - start

        task_logger.info(
            f"cleanup_checkpoint_task completed: tenant_id={tenant_id} "
            f"index_attempt_id={index_attempt_id} "
            f"elapsed={elapsed:.2f}"
        )


class DocumentProcessingBatch(BaseModel):
    """Data structure for a document processing batch."""

    batch_id: str
    index_attempt_id: int
    cc_pair_id: int
    tenant_id: str
    batch_num: int


def _check_failure_threshold(
    total_failures: int,
    document_count: int,
    batch_num: int,
    last_failure: ConnectorFailure | None,
) -> None:
    """Check if we've hit the failure threshold and raise an appropriate exception if so.

    We consider the threshold hit if:
    1. We have more than 3 failures AND
    2. Failures account for more than 10% of processed documents
    """
    failure_ratio = total_failures / (document_count or 1)

    FAILURE_THRESHOLD = 3
    FAILURE_RATIO_THRESHOLD = 0.1
    if total_failures > FAILURE_THRESHOLD and failure_ratio > FAILURE_RATIO_THRESHOLD:
        logger.error(
            f"Connector run failed with '{total_failures}' errors "
            f"after '{batch_num}' batches."
        )
        if last_failure and last_failure.exception:
            raise last_failure.exception from last_failure.exception

        raise RuntimeError(
            f"Connector run encountered too many errors, aborting. "
            f"Last error: {last_failure}"
        )


def _resolve_indexing_document_errors(
    cc_pair_id: int,
    failures: list[ConnectorFailure],
    document_batch: list[Document],
) -> None:
    with get_session_with_current_tenant() as db_session_temp:
        # get previously unresolved errors
        unresolved_errors = get_index_attempt_errors_for_cc_pair(
            cc_pair_id=cc_pair_id,
            unresolved_only=True,
            db_session=db_session_temp,
        )
        doc_id_to_unresolved_errors: dict[str, list[IndexAttemptError]] = defaultdict(
            list
        )
        for error in unresolved_errors:
            if error.document_id:
                doc_id_to_unresolved_errors[error.document_id].append(error)

        # resolve errors for documents that were successfully indexed
        failed_document_ids = [
            failure.failed_document.document_id
            for failure in failures
            if failure.failed_document
        ]
        successful_document_ids = [
            document.id
            for document in document_batch
            if document.id not in failed_document_ids
        ]
        for document_id in successful_document_ids:
            if document_id not in doc_id_to_unresolved_errors:
                continue

            logger.info(f"Resolving IndexAttemptError for document '{document_id}'")
            for error in doc_id_to_unresolved_errors[document_id]:
                error.is_resolved = True
                db_session_temp.add(error)

        db_session_temp.commit()


@shared_task(
    name=OnyxCeleryTask.DOCPROCESSING_TASK,
    bind=True,
)
def docprocessing_task(
    self: Task,
    index_attempt_id: int,
    cc_pair_id: int,
    tenant_id: str,
    batch_num: int,
) -> None:
    """Process a batch of documents through the indexing pipeline.

    This task retrieves documents from storage and processes them through
    the indexing pipeline (embedding + vector store indexing).
    """
    # Start heartbeat for this indexing attempt
    heartbeat_thread, stop_event = start_heartbeat(index_attempt_id)
    try:
        _docprocessing_task(index_attempt_id, cc_pair_id, tenant_id, batch_num)
    finally:
        stop_heartbeat(heartbeat_thread, stop_event)  # Stop heartbeat before exiting


def _docprocessing_task(
    index_attempt_id: int,
    cc_pair_id: int,
    tenant_id: str,
    batch_num: int,
) -> None:
    start_time = time.monotonic()

    # set the indexing attempt ID so that all log messages from this process
    # will have it added as a prefix
    TaskAttemptSingleton.set_cc_and_index_id(index_attempt_id, cc_pair_id)
    if tenant_id:
        CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)

    task_logger.info(
        f"Processing document batch: "
        f"attempt={index_attempt_id} "
        f"batch_num={batch_num} "
    )

    # Get the document batch storage
    storage = get_document_batch_storage(cc_pair_id, index_attempt_id)

    redis_connector = RedisConnector(tenant_id, cc_pair_id)
    r = get_redis_client(tenant_id=tenant_id)

    # 20 is the documented default for httpx max_keepalive_connections
    if MANAGED_VESPA:
        httpx_init_vespa_pool(
            20, ssl_cert=VESPA_CLOUD_CERT_PATH, ssl_key=VESPA_CLOUD_KEY_PATH
        )
    else:
        httpx_init_vespa_pool(20)

    # dummy lock to satisfy linter
    per_batch_lock: RedisLock | None = None
    try:
        # Retrieve documents from storage
        documents = storage.get_batch(batch_num)
        if not documents:
            task_logger.error(f"No documents found for batch {batch_num}")
            return

        with get_session_with_current_tenant() as db_session:
            # matches parts of _run_indexing
            index_attempt = get_index_attempt(
                db_session,
                index_attempt_id,
                eager_load_cc_pair=True,
                eager_load_search_settings=True,
            )
            if not index_attempt:
                raise RuntimeError(f"Index attempt {index_attempt_id} not found")

            if index_attempt.search_settings is None:
                raise ValueError("Search settings must be set for indexing")

            if (
                index_attempt.celery_task_id is None
                or index_attempt.status.is_terminal()
            ):
                raise RuntimeError(
                    f"Index attempt {index_attempt_id} is not running, status {index_attempt.status}"
                )

            redis_connector_index = redis_connector.new_index(
                index_attempt.search_settings.id
            )

            cross_batch_db_lock: RedisLock = r.lock(
                redis_connector_index.db_lock_key,
                timeout=CELERY_INDEXING_LOCK_TIMEOUT,
                thread_local=False,
            )

            callback = IndexingCallback(
                redis_connector,
            )
            # TODO: right now this is the only thing the callback is used for,
            # probably there is a simpler way to handle pausing
            if callback.should_stop():
                raise RuntimeError("Docprocessing cancelled by connector pausing")

            # Set up indexing pipeline components
            embedding_model = DefaultIndexingEmbedder.from_db_search_settings(
                search_settings=index_attempt.search_settings,
                callback=callback,
            )

            information_content_classification_model = (
                InformationContentClassificationModel()
            )

            document_index = get_default_document_index(
                index_attempt.search_settings,
                None,
                httpx_client=HttpxPool.get("vespa"),
            )

            # Set up metadata for this batch
            index_attempt_metadata = IndexAttemptMetadata(
                attempt_id=index_attempt_id,
                connector_id=index_attempt.connector_credential_pair.connector.id,
                credential_id=index_attempt.connector_credential_pair.credential.id,
                request_id=make_randomized_onyx_request_id("DIP"),
                structured_id=f"{tenant_id}:{cc_pair_id}:{index_attempt_id}:{batch_num}",
                batch_num=batch_num,
            )

            # Process documents through indexing pipeline
            task_logger.info(
                f"Processing {len(documents)} documents through indexing pipeline"
            )

            # real work happens here!
            index_pipeline_result = run_indexing_pipeline(
                embedder=embedding_model,
                information_content_classification_model=information_content_classification_model,
                document_index=document_index,
                ignore_time_skip=True,  # Documents are already filtered during extraction
                db_session=db_session,
                tenant_id=tenant_id,
                document_batch=documents,
                index_attempt_metadata=index_attempt_metadata,
            )

        # Update batch completion and document counts atomically using database coordination

        with get_session_with_current_tenant() as db_session, cross_batch_db_lock:
            IndexingCoordination.update_batch_completion_and_docs(
                db_session=db_session,
                index_attempt_id=index_attempt_id,
                total_docs_indexed=index_pipeline_result.total_docs,
                new_docs_indexed=index_pipeline_result.new_docs,
                total_chunks=index_pipeline_result.total_chunks,
            )

            _resolve_indexing_document_errors(
                cc_pair_id,
                index_pipeline_result.failures,
                documents,
            )

        coordination_status = None
        # Record failures in the database
        if index_pipeline_result.failures:
            with get_session_with_current_tenant() as db_session:
                for failure in index_pipeline_result.failures:
                    create_index_attempt_error(
                        index_attempt_id,
                        cc_pair_id,
                        failure,
                        db_session,
                    )
            # Use database state instead of FileStore for failure checking
            with get_session_with_current_tenant() as db_session:
                coordination_status = IndexingCoordination.get_coordination_status(
                    db_session, index_attempt_id
                )
                _check_failure_threshold(
                    coordination_status.total_failures,
                    coordination_status.total_docs,
                    batch_num,
                    index_pipeline_result.failures[-1],
                )

        # Add telemetry for indexing progress using database coordination status
        # only re-fetch coordination status if necessary
        if coordination_status is None:
            with get_session_with_current_tenant() as db_session:
                coordination_status = IndexingCoordination.get_coordination_status(
                    db_session, index_attempt_id
                )

        optional_telemetry(
            record_type=RecordType.INDEXING_PROGRESS,
            data={
                "index_attempt_id": index_attempt_id,
                "cc_pair_id": cc_pair_id,
                "current_docs_indexed": coordination_status.total_docs,
                "current_chunks_indexed": coordination_status.total_chunks,
                "source": index_attempt.connector_credential_pair.connector.source.value,
                "completed_batches": coordination_status.completed_batches,
                "total_batches": coordination_status.total_batches,
            },
            tenant_id=tenant_id,
        )
        # Clean up this batch after successful processing
        storage.delete_batch_by_num(batch_num)

        elapsed_time = time.monotonic() - start_time
        task_logger.info(
            f"Completed document batch processing: "
            f"index_attempt={index_attempt_id} "
            f"cc_pair={cc_pair_id} "
            f"search_settings={index_attempt.search_settings.id} "
            f"batch_num={batch_num} "
            f"docs={len(documents)} "
            f"chunks={index_pipeline_result.total_chunks} "
            f"failures={len(index_pipeline_result.failures)} "
            f"elapsed={elapsed_time:.2f}s"
        )

    except Exception:
        task_logger.exception(
            f"Document batch processing failed: "
            f"batch_num={batch_num} "
            f"attempt={index_attempt_id} "
        )

        # on failure, signal completion with an error to unblock the watchdog
        with get_session_with_current_tenant() as db_session:
            index_attempt = get_index_attempt(db_session, index_attempt_id)
            if index_attempt and index_attempt.search_settings:
                redis_connector_index = redis_connector.new_index(
                    index_attempt.search_settings.id
                )
                redis_connector_index.set_generator_complete(
                    HTTPStatus.INTERNAL_SERVER_ERROR.value
                )

        raise
    finally:
        if per_batch_lock and per_batch_lock.owned():
            per_batch_lock.release()
