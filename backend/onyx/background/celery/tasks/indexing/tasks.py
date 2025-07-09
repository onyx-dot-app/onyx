import os
import time
import traceback
from collections import defaultdict
from datetime import datetime
from datetime import timezone
from http import HTTPStatus
from typing import Any
from typing import cast

from celery import shared_task
from celery import Task
from celery.exceptions import SoftTimeLimitExceeded
from celery.result import AsyncResult
from celery.states import READY_STATES
from pydantic import BaseModel
from redis import Redis
from redis.lock import Lock as RedisLock
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.background.celery.apps.app_base import task_logger
from onyx.background.celery.tasks.beat_schedule import CLOUD_BEAT_MULTIPLIER_DEFAULT
from onyx.background.celery.tasks.indexing.utils import IndexingCallback
from onyx.background.celery.tasks.indexing.utils import is_in_repeated_error_state
from onyx.background.celery.tasks.indexing.utils import should_index
from onyx.background.celery.tasks.indexing.utils import try_creating_docfetching_task
from onyx.background.celery.tasks.models import DocProcessingContext
from onyx.background.celery.tasks.models import IndexingWatchdogTerminalStatus
from onyx.background.indexing.checkpointing_utils import cleanup_checkpoint
from onyx.background.indexing.checkpointing_utils import (
    get_index_attempts_with_old_checkpoints,
)
from onyx.background.indexing.job_client import SimpleJobException
from onyx.configs.constants import CELERY_GENERIC_BEAT_LOCK_TIMEOUT
from onyx.configs.constants import CELERY_INDEXING_LOCK_TIMEOUT
from onyx.configs.constants import OnyxCeleryPriority
from onyx.configs.constants import OnyxCeleryQueues
from onyx.configs.constants import OnyxCeleryTask
from onyx.configs.constants import OnyxRedisConstants
from onyx.configs.constants import OnyxRedisLocks
from onyx.configs.constants import OnyxRedisSignals
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import DocIndexingContext
from onyx.connectors.models import Document
from onyx.connectors.models import IndexAttemptMetadata
from onyx.db.connector import mark_ccpair_with_indexing_trigger
from onyx.db.connector_credential_pair import fetch_connector_credential_pairs
from onyx.db.connector_credential_pair import get_connector_credential_pair_from_id
from onyx.db.connector_credential_pair import set_cc_pair_repeated_error_state
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.enums import IndexingMode
from onyx.db.enums import IndexingStatus
from onyx.db.index_attempt import create_index_attempt_error
from onyx.db.index_attempt import get_index_attempt
from onyx.db.index_attempt import get_index_attempt_errors_for_cc_pair
from onyx.db.index_attempt import IndexAttemptError
from onyx.db.index_attempt import mark_attempt_failed
from onyx.db.index_attempt import mark_attempt_partially_succeeded
from onyx.db.index_attempt import mark_attempt_succeeded
from onyx.db.indexing_coordination import IndexingCoordination
from onyx.db.models import IndexAttempt
from onyx.db.search_settings import get_active_search_settings_list
from onyx.db.search_settings import get_current_search_settings
from onyx.db.swap_index import check_and_perform_index_swap
from onyx.document_index.factory import get_default_document_index
from onyx.file_store.document_batch_storage import get_document_batch_storage
from onyx.httpx.httpx_pool import HttpxPool
from onyx.indexing.embedder import DefaultIndexingEmbedder
from onyx.indexing.indexing_pipeline import build_indexing_pipeline
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
    tenant_id: str,
    r_celery: Redis,
    lock_beat: RedisLock,
) -> None:
    """
    Validates that active indexing attempts in the database have corresponding Celery tasks.
    If an attempt has a celery_task_id but the task doesn't exist, mark the attempt as failed.

    This replaces the Redis fence validation with database-based validation.
    Race condition handling:
    - We use a double-check pattern: check DB -> check Celery -> check DB again
    - Only mark attempts as failed if they consistently have missing tasks
    """
    with get_session_with_current_tenant() as db_session:
        # Find all active indexing attempts that have Celery task IDs
        # These should have corresponding tasks in Celery
        active_attempts = (
            db_session.execute(
                select(IndexAttempt).where(
                    IndexAttempt.status.in_(
                        [IndexingStatus.NOT_STARTED, IndexingStatus.IN_PROGRESS]
                    ),
                    IndexAttempt.celery_task_id.isnot(None),
                )
            )
            .scalars()
            .all()
        )

        for attempt in active_attempts:
            lock_beat.reacquire()

            # Double-check the attempt still exists and has the same status
            # This handles race conditions where the attempt might complete between queries
            fresh_attempt = get_index_attempt(db_session, attempt.id)
            if not fresh_attempt or fresh_attempt.status.is_terminal():
                continue

            celery_task_id = fresh_attempt.celery_task_id
            if not celery_task_id:
                continue

            # Check if the Celery task actually exists
            try:
                result: AsyncResult = AsyncResult(celery_task_id)

                # A task exists if it's not in PENDING state (which means unknown to Celery)
                # PENDING state means Celery has never seen this task ID
                if result.state != "PENDING":
                    continue

                # For PENDING tasks, we could also check Redis queues, but since we're being
                # conservative about cleanup, we'll only clean up tasks that are clearly orphaned
                # (i.e., definitely not known to Celery)

            except Exception:
                # If we can't check the task status, be conservative and continue
                task_logger.warning(
                    f"Could not check Celery task status for attempt {attempt.id}, "
                    f"task_id={celery_task_id}"
                )
                continue

            # Task doesn't exist - mark the attempt as failed
            task_logger.warning(
                f"Found orphaned index attempt without corresponding Celery task: "
                f"attempt={attempt.id} cc_pair={attempt.connector_credential_pair_id} "
                f"search_settings={attempt.search_settings_id} task_id={celery_task_id}"
            )

            try:
                mark_attempt_failed(
                    attempt.id,
                    db_session,
                    failure_reason=f"Orphaned attempt - Celery task {celery_task_id} not found",
                )
            except Exception:
                task_logger.exception(
                    f"Failed to mark orphaned attempt {attempt.id} as failed"
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
        )

    # Check task completion using Celery
    try:
        check_indexing_completion(attempt.id, tenant_id)
    except Exception:
        task_logger.exception(
            f"Error checking Celery task status for attempt {attempt.id}"
        )


def check_indexing_completion(
    index_attempt_id: int,
    tenant_id: str,
) -> None:

    logger.info(
        f"Checking for indexing completion: "
        f"attempt={index_attempt_id} "
        f"tenant={tenant_id}"
    )

    storage = get_document_batch_storage(tenant_id, index_attempt_id)

    try:
        # Get current state from database instead of FileStore
        with get_session_with_current_tenant() as db_session:
            coordination_status = IndexingCoordination.get_coordination_status(
                db_session, index_attempt_id
            )

        if not coordination_status.found:
            raise RuntimeError(
                f"Index attempt {index_attempt_id} not found in database"
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

            # Check for stalls (6 hour timeout)
            if timed_out:
                raise RuntimeError(
                    f"Indexing attempt {index_attempt_id} has been indexing for 6 hours without progress. "
                    f"Marking it as failed."
                )

        # If processing is complete, handle completion
        if indexing_completed:
            logger.info(
                f"All batches for index attempt {index_attempt_id} have been processed."
            )

            # All processing is complete
            total_failures = coordination_status.total_failures

            with get_session_with_current_tenant() as db_session:
                if total_failures == 0:
                    mark_attempt_succeeded(index_attempt_id, db_session)
                    logger.info(
                        f"Index attempt {index_attempt_id} completed successfully"
                    )
                else:
                    mark_attempt_partially_succeeded(index_attempt_id, db_session)
                    logger.info(
                        f"Index attempt {index_attempt_id} completed with {total_failures} failures"
                    )

                # Clean up database coordination
                IndexingCoordination.cleanup_attempt_coordination(
                    db_session, index_attempt_id
                )

                # Update CC pair status if successful
                attempt = get_index_attempt(db_session, index_attempt_id)
                if attempt is None:
                    raise RuntimeError(
                        f"Index attempt {index_attempt_id} not found in database"
                    )

                cc_pair = get_connector_credential_pair_from_id(
                    db_session, attempt.connector_credential_pair_id
                )
                if cc_pair is None:
                    raise RuntimeError(
                        f"CC pair {attempt.connector_credential_pair_id} not found in database"
                    )

                if attempt.status.is_successful():
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

            # Clean up FileStore storage (still needed for document batches during transition)
            try:
                storage.cleanup_all_batches()
            except Exception:
                logger.exception("Failed to clean up document batches - continuing")

            logger.info(
                f"Database coordination completed for attempt {index_attempt_id}"
            )

    except Exception as e:
        logger.exception(
            f"Failed to monitor document processing completion: "
            f"attempt={index_attempt_id} "
            f"error={str(e)}"
        )

        # Mark the attempt as failed if monitoring fails
        try:
            with get_session_with_current_tenant() as db_session:
                mark_attempt_failed(
                    index_attempt_id,
                    db_session,
                    failure_reason=f"Processing monitoring failed: {str(e)}",
                    full_exception_trace=traceback.format_exc(),
                )

                # Clean up coordination on failure
                try:
                    IndexingCoordination.cleanup_attempt_coordination(
                        db_session, index_attempt_id
                    )
                except Exception:
                    logger.exception(
                        "Failed to cleanup attempt coordination during failure cleanup"
                    )
        except Exception:
            logger.exception("Failed to mark attempt as failed")

        # Try to clean up storage
        try:
            storage.cleanup_all_batches()
        except Exception:
            logger.exception("Failed to cleanup storage after monitoring failure")


def monitor_ccpair_indexing_taskset(
    tenant_id: str, fence_key: str, r: Redis, db_session: Session
) -> None:
    # if the fence doesn't exist, there's nothing to do
    composite_id = RedisConnector.get_id_from_fence_key(fence_key)
    if composite_id is None:
        task_logger.warning(
            f"Connector indexing: could not parse composite_id from {fence_key}"
        )
        return

    # parse out metadata and initialize the helper class with it
    parts = composite_id.split("/")
    if len(parts) != 2:
        return

    cc_pair_id = int(parts[0])
    search_settings_id = int(parts[1])

    redis_connector = RedisConnector(tenant_id, cc_pair_id)
    redis_connector_index = redis_connector.new_index(search_settings_id)
    if not redis_connector_index.fenced:
        return

    payload = redis_connector_index.payload
    if not payload:
        return

    # if the CC Pair is `SCHEDULED`, moved it to `INITIAL_INDEXING`. A CC Pair
    # should only ever be `SCHEDULED` if it's a new connector.
    cc_pair = get_connector_credential_pair_from_id(db_session, cc_pair_id)
    if cc_pair is None:
        raise RuntimeError(f"CC Pair {cc_pair_id} not found")

    if cc_pair.status == ConnectorCredentialPairStatus.SCHEDULED:
        cc_pair.status = ConnectorCredentialPairStatus.INITIAL_INDEXING
        db_session.commit()

    elapsed_started_str = None
    if payload.started:
        elapsed_started = datetime.now(timezone.utc) - payload.started
        elapsed_started_str = f"{elapsed_started.total_seconds():.2f}"

    elapsed_submitted = datetime.now(timezone.utc) - payload.submitted

    progress = redis_connector_index.get_progress()
    if progress is not None:
        task_logger.info(
            f"Connector indexing progress: "
            f"attempt={payload.index_attempt_id} "
            f"cc_pair={cc_pair_id} "
            f"search_settings={search_settings_id} "
            f"progress={progress} "
            f"elapsed_submitted={elapsed_submitted.total_seconds():.2f} "
            f"elapsed_started={elapsed_started_str}"
        )

    if payload.index_attempt_id is None or payload.celery_task_id is None:
        # the task is still setting up
        return

    # never use any blocking methods on the result from inside a task!
    result: AsyncResult = AsyncResult(payload.celery_task_id)

    # inner/outer/inner double check pattern to avoid race conditions when checking for
    # bad state

    # Verify: if the generator isn't complete, the task must not be in READY state
    # inner = get_completion / generator_complete not signaled
    # outer = result.state in READY state
    status_int = redis_connector_index.get_completion()
    if status_int is None:  # inner signal not set ... possible error
        task_state = result.state
        if (
            task_state in READY_STATES
        ):  # outer signal in terminal state ... possible error
            # Now double check!
            if redis_connector_index.get_completion() is None:
                # inner signal still not set (and cannot change when outer result_state is READY)
                # Task is finished but generator complete isn't set.
                # We have a problem! Worker may have crashed.
                task_result = str(result.result)
                task_traceback = str(result.traceback)

                msg = (
                    f"Connector indexing aborted or exceptioned: "
                    f"attempt={payload.index_attempt_id} "
                    f"celery_task={payload.celery_task_id} "
                    f"cc_pair={cc_pair_id} "
                    f"search_settings={search_settings_id} "
                    f"elapsed_submitted={elapsed_submitted.total_seconds():.2f} "
                    f"result.state={task_state} "
                    f"result.result={task_result} "
                    f"result.traceback={task_traceback}"
                )
                task_logger.warning(msg)

                try:
                    index_attempt = get_index_attempt(
                        db_session=db_session,
                        index_attempt_id=payload.index_attempt_id,
                    )
                    if index_attempt:
                        if (
                            index_attempt.status != IndexingStatus.CANCELED
                            and index_attempt.status != IndexingStatus.FAILED
                        ):
                            mark_attempt_failed(
                                index_attempt_id=payload.index_attempt_id,
                                db_session=db_session,
                                failure_reason=msg,
                            )
                except Exception:
                    task_logger.exception(
                        "Connector indexing - Transient exception marking index attempt as failed: "
                        f"attempt={payload.index_attempt_id} "
                        f"tenant={tenant_id} "
                        f"cc_pair={cc_pair_id} "
                        f"search_settings={search_settings_id}"
                    )

                redis_connector_index.reset()
        return

    if redis_connector_index.watchdog_signaled():
        # if the generator is complete, don't clean up until the watchdog has exited
        task_logger.info(
            f"Connector indexing - Delaying finalization until watchdog has exited: "
            f"attempt={payload.index_attempt_id} "
            f"cc_pair={cc_pair_id} "
            f"search_settings={search_settings_id} "
            f"progress={progress} "
            f"elapsed_submitted={elapsed_submitted.total_seconds():.2f} "
            f"elapsed_started={elapsed_started_str}"
        )

        return

    status_enum = HTTPStatus(status_int)

    task_logger.info(
        f"Connector indexing finished: "
        f"attempt={payload.index_attempt_id} "
        f"cc_pair={cc_pair_id} "
        f"search_settings={search_settings_id} "
        f"progress={progress} "
        f"status={status_enum.name} "
        f"elapsed_submitted={elapsed_submitted.total_seconds():.2f} "
        f"elapsed_started={elapsed_started_str}"
    )

    redis_connector_index.reset()

    # mark the CC Pair as `ACTIVE` if the attempt was a success and the
    # CC Pair is not active not already
    # This should never technically be in this state, but we'll handle it anyway
    index_attempt = get_index_attempt(db_session, payload.index_attempt_id)
    index_attempt_is_successful = index_attempt and index_attempt.status.is_successful()
    if (
        index_attempt_is_successful
        and cc_pair.status == ConnectorCredentialPairStatus.SCHEDULED
        or cc_pair.status == ConnectorCredentialPairStatus.INITIAL_INDEXING
    ):
        cc_pair.status = ConnectorCredentialPairStatus.ACTIVE
        db_session.commit()

    # if the index attempt is successful, clear the repeated error state
    if cc_pair.in_repeated_error_state and index_attempt_is_successful:
        cc_pair.in_repeated_error_state = False
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
    redis_client_celery: Redis = self.app.broker_connection().channel().client  # type: ignore

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

        # gather cc_pair_ids
        lock_beat.reacquire()
        cc_pair_ids: list[int] = []
        with get_session_with_current_tenant() as db_session:
            cc_pairs = fetch_connector_credential_pairs(
                db_session, include_user_files=True
            )
            for cc_pair_entry in cc_pairs:
                cc_pair_ids.append(cc_pair_entry.id)

        # mark CC Pairs that are repeatedly failing as in repeated error state
        with get_session_with_current_tenant() as db_session:
            current_search_settings = get_current_search_settings(db_session)
            for cc_pair_id in cc_pair_ids:
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
                search_settings_list = get_active_search_settings_list(db_session)
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
                validate_active_indexing_attempts(
                    tenant_id, redis_client_celery, lock_beat
                )
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


def _update_indexing_state(
    index_attempt_id: int,
    tenant_id: str,
    failures: int,
    new_docs: int,
    total_chunks: int,
) -> DocIndexingContext:
    storage = get_document_batch_storage(tenant_id, index_attempt_id)

    current_state = storage.ensure_indexing_state()
    current_state.batches_done += 1

    current_state.total_failures += failures
    current_state.net_doc_change += new_docs
    current_state.total_chunks += total_chunks
    storage.store_indexing_state(current_state)
    return current_state


def _resolve_indexing_errors(
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
    batch_id: str,
    index_attempt_id: int,
    cc_pair_id: int,
    tenant_id: str,
    batch_num: int,
) -> None:
    """Process a batch of documents through the indexing pipeline.

    This task retrieves documents from storage and processes them through
    the indexing pipeline (embedding + vector store indexing).
    """

    start_time = time.monotonic()

    # set the indexing attempt ID so that all log messages from this process
    # will have it added as a prefix
    TaskAttemptSingleton.set_cc_and_index_id(index_attempt_id, cc_pair_id)
    if tenant_id:
        CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)

    task_logger.info(
        f"Processing document batch: "
        f"batch_id={batch_id} "
        f"attempt={index_attempt_id} "
        f"batch_num={batch_num} "
    )

    # Get the document batch storage
    storage = get_document_batch_storage(tenant_id, index_attempt_id)

    redis_connector = RedisConnector(tenant_id, cc_pair_id)
    r = get_redis_client(tenant_id=tenant_id)

    # dummy lock to satisfy linter
    per_batch_lock: RedisLock | None = None
    try:
        # Retrieve documents from storage
        documents = storage.get_batch(batch_id)
        if not documents:
            task_logger.error(f"No documents found for batch {batch_id}")
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

            redis_connector_index = redis_connector.new_index(
                index_attempt.search_settings.id
            )

            cross_batch_db_lock: RedisLock = r.lock(
                redis_connector_index.db_lock_key,
                timeout=CELERY_INDEXING_LOCK_TIMEOUT,
                thread_local=False,
            )
            # set thread_local=False since we don't control what thread the indexing/pruning
            # might run our callback with
            per_batch_lock = cast(
                RedisLock,
                r.lock(
                    redis_connector_index.lock_key_by_batch(batch_num),
                    timeout=CELERY_INDEXING_LOCK_TIMEOUT,
                    thread_local=False,
                ),
            )

            acquired = per_batch_lock.acquire(blocking=False)
            if not acquired:
                logger.warning(
                    f"Indexing batch task already running, exiting...: "
                    f"index_attempt={index_attempt_id} "
                    f"cc_pair={cc_pair_id} "
                    f"search_settings={index_attempt.search_settings.id} "
                    f"batch_num={batch_num}"
                )

                raise SimpleJobException(
                    f"Indexing batch task already running, exiting...: "
                    f"index_attempt={index_attempt_id} "
                    f"cc_pair={cc_pair_id} "
                    f"search_settings={index_attempt.search_settings.id} "
                    f"batch_num={batch_num}",
                    code=IndexingWatchdogTerminalStatus.TASK_ALREADY_RUNNING.code,
                )

            storage.ensure_indexing_state()

            callback = IndexingCallback(
                os.getppid(),
                redis_connector,
                per_batch_lock,
                r,
                redis_connector_index,
            )
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

            indexing_pipeline = build_indexing_pipeline(
                embedder=embedding_model,
                information_content_classification_model=information_content_classification_model,
                document_index=document_index,
                ignore_time_skip=True,  # Documents are already filtered during extraction
                db_session=db_session,
                tenant_id=tenant_id,
                callback=callback,
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

            per_batch_lock.reacquire()
            # real work happens here!
            index_pipeline_result = indexing_pipeline(
                document_batch=documents,
                index_attempt_metadata=index_attempt_metadata,
            )
            per_batch_lock.reacquire()

        # Update batch completion and document counts atomically using database coordination
        from onyx.db.indexing_coordination import IndexingCoordination

        with get_session_with_current_tenant() as db_session, cross_batch_db_lock:
            IndexingCoordination.update_batch_completion_and_docs(
                db_session=db_session,
                index_attempt_id=index_attempt_id,
                total_docs_indexed=index_pipeline_result.total_docs,
                new_docs_indexed=index_pipeline_result.new_docs,
                failures=len(index_pipeline_result.failures),
                total_chunks=index_pipeline_result.total_chunks,
            )

        with cross_batch_db_lock:
            _resolve_indexing_errors(
                cc_pair_id,
                index_pipeline_result.failures,
                documents,
            )

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

        if callback:
            # _run_indexing for legacy reasons
            callback.progress("_run_indexing", len(documents))

        # redis_connector_index.set_generator_complete(HTTPStatus.OK.value)
        # Add telemetry for indexing progress using database coordination status
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
        storage.delete_batch(batch_id)

        elapsed_time = time.monotonic() - start_time
        task_logger.info(
            f"Completed document batch processing: "
            f"batch_id={batch_id} "
            f"docs={len(documents)} "
            f"chunks={index_pipeline_result.total_chunks} "
            f"failures={len(index_pipeline_result.failures)} "
            f"elapsed={elapsed_time:.2f}s"
        )

    except Exception:
        task_logger.exception(
            f"Document batch processing failed: "
            f"batch_id={batch_id} "
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
