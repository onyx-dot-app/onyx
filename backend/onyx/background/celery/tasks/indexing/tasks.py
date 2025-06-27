import multiprocessing
import os
import time
import traceback
from collections import defaultdict
from datetime import datetime
from datetime import timezone
from enum import Enum
from http import HTTPStatus
from time import sleep
from typing import Any
from typing import cast

import sentry_sdk
from celery import Celery
from celery import shared_task
from celery import Task
from celery.exceptions import SoftTimeLimitExceeded
from celery.result import AsyncResult
from celery.states import READY_STATES
from pydantic import BaseModel
from redis import Redis
from redis.lock import Lock as RedisLock
from sqlalchemy.orm import Session

from onyx.background.celery.apps.app_base import task_logger
from onyx.background.celery.celery_utils import httpx_init_vespa_pool
from onyx.background.celery.memory_monitoring import emit_process_memory
from onyx.background.celery.tasks.beat_schedule import CLOUD_BEAT_MULTIPLIER_DEFAULT
from onyx.background.celery.tasks.indexing.utils import get_unfenced_index_attempt_ids
from onyx.background.celery.tasks.indexing.utils import IndexingCallback
from onyx.background.celery.tasks.indexing.utils import is_in_repeated_error_state
from onyx.background.celery.tasks.indexing.utils import should_index
from onyx.background.celery.tasks.indexing.utils import try_creating_indexing_task
from onyx.background.celery.tasks.indexing.utils import validate_indexing_fences
from onyx.background.indexing.checkpointing_utils import cleanup_checkpoint
from onyx.background.indexing.checkpointing_utils import (
    get_index_attempts_with_old_checkpoints,
)
from onyx.background.indexing.job_client import SimpleJob
from onyx.background.indexing.job_client import SimpleJobClient
from onyx.background.indexing.job_client import SimpleJobException
from onyx.background.indexing.run_indexing import run_indexing_entrypoint
from onyx.configs.app_configs import MANAGED_VESPA
from onyx.configs.app_configs import VESPA_CLOUD_CERT_PATH
from onyx.configs.app_configs import VESPA_CLOUD_KEY_PATH
from onyx.configs.constants import CELERY_GENERIC_BEAT_LOCK_TIMEOUT
from onyx.configs.constants import CELERY_INDEXING_LOCK_TIMEOUT
from onyx.configs.constants import CELERY_INDEXING_WATCHDOG_CONNECTOR_TIMEOUT
from onyx.configs.constants import CELERY_TASK_WAIT_FOR_FENCE_TIMEOUT
from onyx.configs.constants import OnyxCeleryPriority
from onyx.configs.constants import OnyxCeleryQueues
from onyx.configs.constants import OnyxCeleryTask
from onyx.configs.constants import OnyxRedisConstants
from onyx.configs.constants import OnyxRedisLocks
from onyx.configs.constants import OnyxRedisSignals
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import DocExtractionContext
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
from onyx.db.index_attempt import mark_attempt_canceled
from onyx.db.index_attempt import mark_attempt_failed
from onyx.db.index_attempt import mark_attempt_partially_succeeded
from onyx.db.index_attempt import mark_attempt_succeeded
from onyx.db.index_attempt import update_docs_indexed
from onyx.db.search_settings import get_active_search_settings_list
from onyx.db.search_settings import get_current_search_settings
from onyx.db.swap_index import check_and_perform_index_swap
from onyx.document_index.factory import get_default_document_index
from onyx.file_store.document_batch_storage import DocumentBatchStorage
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
from onyx.redis.redis_connector_index import RedisConnectorIndex
from onyx.redis.redis_pool import get_redis_client
from onyx.redis.redis_pool import get_redis_replica_client
from onyx.redis.redis_pool import redis_lock_dump
from onyx.redis.redis_pool import SCAN_ITER_COUNT_DEFAULT
from onyx.redis.redis_utils import is_fence
from onyx.server.runtime.onyx_runtime import OnyxRuntime
from onyx.utils.logger import setup_logger
from onyx.utils.middleware import make_randomized_onyx_request_id
from onyx.utils.telemetry import optional_telemetry
from onyx.utils.telemetry import RecordType
from onyx.utils.variable_functionality import global_version
from shared_configs.configs import INDEXING_MODEL_SERVER_HOST
from shared_configs.configs import INDEXING_MODEL_SERVER_PORT
from shared_configs.configs import MULTI_TENANT
from shared_configs.configs import SENTRY_DSN
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


class IndexingWatchdogTerminalStatus(str, Enum):
    """The different statuses the watchdog can finish with.

    TODO: create broader success/failure/abort categories
    """

    UNDEFINED = "undefined"

    SUCCEEDED = "succeeded"

    SPAWN_FAILED = "spawn_failed"  # connector spawn failed
    SPAWN_NOT_ALIVE = (
        "spawn_not_alive"  # spawn succeeded but process did not come alive
    )

    BLOCKED_BY_DELETION = "blocked_by_deletion"
    BLOCKED_BY_STOP_SIGNAL = "blocked_by_stop_signal"
    FENCE_NOT_FOUND = "fence_not_found"  # fence does not exist
    FENCE_READINESS_TIMEOUT = (
        "fence_readiness_timeout"  # fence exists but wasn't ready within the timeout
    )
    FENCE_MISMATCH = "fence_mismatch"  # task and fence metadata mismatch
    TASK_ALREADY_RUNNING = "task_already_running"  # task appears to be running already
    INDEX_ATTEMPT_MISMATCH = (
        "index_attempt_mismatch"  # expected index attempt metadata not found in db
    )

    CONNECTOR_VALIDATION_ERROR = (
        "connector_validation_error"  # the connector validation failed
    )
    CONNECTOR_EXCEPTIONED = "connector_exceptioned"  # the connector itself exceptioned
    WATCHDOG_EXCEPTIONED = "watchdog_exceptioned"  # the watchdog exceptioned

    # the watchdog received a termination signal
    TERMINATED_BY_SIGNAL = "terminated_by_signal"

    # the watchdog terminated the task due to no activity
    TERMINATED_BY_ACTIVITY_TIMEOUT = "terminated_by_activity_timeout"

    # NOTE: this may actually be the same as SIGKILL, but parsed differently by python
    # consolidate once we know more
    OUT_OF_MEMORY = "out_of_memory"

    PROCESS_SIGNAL_SIGKILL = "process_signal_sigkill"

    @property
    def code(self) -> int:
        _ENUM_TO_CODE: dict[IndexingWatchdogTerminalStatus, int] = {
            IndexingWatchdogTerminalStatus.PROCESS_SIGNAL_SIGKILL: -9,
            IndexingWatchdogTerminalStatus.OUT_OF_MEMORY: 137,
            IndexingWatchdogTerminalStatus.CONNECTOR_VALIDATION_ERROR: 247,
            IndexingWatchdogTerminalStatus.BLOCKED_BY_DELETION: 248,
            IndexingWatchdogTerminalStatus.BLOCKED_BY_STOP_SIGNAL: 249,
            IndexingWatchdogTerminalStatus.FENCE_NOT_FOUND: 250,
            IndexingWatchdogTerminalStatus.FENCE_READINESS_TIMEOUT: 251,
            IndexingWatchdogTerminalStatus.FENCE_MISMATCH: 252,
            IndexingWatchdogTerminalStatus.TASK_ALREADY_RUNNING: 253,
            IndexingWatchdogTerminalStatus.INDEX_ATTEMPT_MISMATCH: 254,
            IndexingWatchdogTerminalStatus.CONNECTOR_EXCEPTIONED: 255,
        }

        return _ENUM_TO_CODE[self]

    @classmethod
    def from_code(cls, code: int) -> "IndexingWatchdogTerminalStatus":
        _CODE_TO_ENUM: dict[int, IndexingWatchdogTerminalStatus] = {
            -9: IndexingWatchdogTerminalStatus.PROCESS_SIGNAL_SIGKILL,
            137: IndexingWatchdogTerminalStatus.OUT_OF_MEMORY,
            247: IndexingWatchdogTerminalStatus.CONNECTOR_VALIDATION_ERROR,
            248: IndexingWatchdogTerminalStatus.BLOCKED_BY_DELETION,
            249: IndexingWatchdogTerminalStatus.BLOCKED_BY_STOP_SIGNAL,
            250: IndexingWatchdogTerminalStatus.FENCE_NOT_FOUND,
            251: IndexingWatchdogTerminalStatus.FENCE_READINESS_TIMEOUT,
            252: IndexingWatchdogTerminalStatus.FENCE_MISMATCH,
            253: IndexingWatchdogTerminalStatus.TASK_ALREADY_RUNNING,
            254: IndexingWatchdogTerminalStatus.INDEX_ATTEMPT_MISMATCH,
            255: IndexingWatchdogTerminalStatus.CONNECTOR_EXCEPTIONED,
        }

        if code in _CODE_TO_ENUM:
            return _CODE_TO_ENUM[code]

        return IndexingWatchdogTerminalStatus.UNDEFINED


class SimpleJobResult:
    """The data we want to have when the watchdog finishes"""

    def __init__(self) -> None:
        self.status = IndexingWatchdogTerminalStatus.UNDEFINED
        self.connector_source = None
        self.exit_code = None
        self.exception_str = None

    status: IndexingWatchdogTerminalStatus
    connector_source: str | None
    exit_code: int | None
    exception_str: str | None


class ConnectorIndexingContext(BaseModel):
    tenant_id: str
    cc_pair_id: int
    search_settings_id: int
    index_attempt_id: int


class ConnectorIndexingLogBuilder:
    def __init__(self, ctx: ConnectorIndexingContext):
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
    """a lightweight task used to kick off indexing tasks.
    Occcasionally does some validation of existing state to clear up error conditions"""

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

            redis_connector = RedisConnector(tenant_id, cc_pair_id)
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

                    redis_connector_index = redis_connector.new_index(
                        search_settings_instance.id
                    )
                    if redis_connector_index.fenced:
                        task_logger.debug(
                            f"check_for_indexing - Skipping fenced connector: "
                            f"cc_pair={cc_pair_id} search_settings={search_settings_instance.id}"
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
                    else:
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
                    attempt_id = try_creating_indexing_task(
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

        # Fail any index attempts in the DB that don't have fences
        # This shouldn't ever happen!
        with get_session_with_current_tenant() as db_session:
            unfenced_attempt_ids = get_unfenced_index_attempt_ids(
                db_session, redis_client
            )

            for attempt_id in unfenced_attempt_ids:
                lock_beat.reacquire()

                attempt = get_index_attempt(db_session, attempt_id)
                if not attempt:
                    continue

                failure_reason = (
                    f"Unfenced index attempt found in DB: "
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
            # clear any indexing fences that don't have associated celery tasks in progress
            # tasks can be in the queue in redis, in reserved tasks (prefetched by the worker),
            # or be currently executing
            try:
                validate_indexing_fences(
                    tenant_id, redis_client_replica, redis_client_celery, lock_beat
                )
            except Exception:
                task_logger.exception("Exception while validating indexing fences")

            redis_client.set(
                OnyxRedisSignals.BLOCK_VALIDATE_INDEXING_FENCES,
                1,
                ex=_get_fence_validation_block_expiration(),
            )

        # 3/3: FINALIZE
        lock_beat.reacquire()
        keys = cast(
            set[bytes], redis_client_replica.smembers(OnyxRedisConstants.ACTIVE_FENCES)
        )
        for key_bytes in keys:

            if not redis_client.exists(key_bytes):
                redis_client.srem(OnyxRedisConstants.ACTIVE_FENCES, key_bytes)
                continue

            key_str = key_bytes.decode("utf-8")
            if key_str.startswith(RedisConnectorIndex.FENCE_PREFIX):
                with get_session_with_current_tenant() as db_session:
                    monitor_ccpair_indexing_taskset(
                        tenant_id, key_str, redis_client_replica, db_session
                    )

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


def docfetching_task(
    app: Celery,
    index_attempt_id: int,
    cc_pair_id: int,
    search_settings_id: int,
    is_ee: bool,
    tenant_id: str,
) -> int | None:
    """
    TODO: update docstring to reflect docfetching
    Indexing task. For a cc pair, this task pulls all document IDs from the source
    and compares those IDs to locally stored documents and deletes all locally stored IDs missing
    from the most recently pulled document ID list

    acks_late must be set to False. Otherwise, celery's visibility timeout will
    cause any task that runs longer than the timeout to be redispatched by the broker.
    There appears to be no good workaround for this, so we need to handle redispatching
    manually.

    Returns None if the task did not run (possibly due to a conflict).
    Otherwise, returns an int >= 0 representing the number of indexed docs.

    NOTE: if an exception is raised out of this task, the primary worker will detect
    that the task transitioned to a "READY" state but the generator_complete_key doesn't exist.
    This will cause the primary worker to abort the indexing attempt and clean up.
    """

    # Since connector_indexing_proxy_task spawns a new process using this function as
    # the entrypoint, we init Sentry here.
    if SENTRY_DSN:
        sentry_sdk.init(
            dsn=SENTRY_DSN,
            traces_sample_rate=0.1,
        )
        logger.info("Sentry initialized")
    else:
        logger.debug("Sentry DSN not provided, skipping Sentry initialization")

    logger.info(
        f"Indexing spawned task starting: "
        f"attempt={index_attempt_id} "
        f"tenant={tenant_id} "
        f"cc_pair={cc_pair_id} "
        f"search_settings={search_settings_id}"
    )

    n_final_progress: int | None = None

    # 20 is the documented default for httpx max_keepalive_connections
    if MANAGED_VESPA:
        httpx_init_vespa_pool(
            20, ssl_cert=VESPA_CLOUD_CERT_PATH, ssl_key=VESPA_CLOUD_KEY_PATH
        )
    else:
        httpx_init_vespa_pool(20)

    redis_connector = RedisConnector(tenant_id, cc_pair_id)
    redis_connector_index = redis_connector.new_index(search_settings_id)

    r = get_redis_client()

    if redis_connector.delete.fenced:
        raise SimpleJobException(
            f"Indexing will not start because connector deletion is in progress: "
            f"attempt={index_attempt_id} "
            f"cc_pair={cc_pair_id} "
            f"fence={redis_connector.delete.fence_key}",
            code=IndexingWatchdogTerminalStatus.BLOCKED_BY_DELETION.code,
        )

    if redis_connector.stop.fenced:
        raise SimpleJobException(
            f"Indexing will not start because a connector stop signal was detected: "
            f"attempt={index_attempt_id} "
            f"cc_pair={cc_pair_id} "
            f"fence={redis_connector.stop.fence_key}",
            code=IndexingWatchdogTerminalStatus.BLOCKED_BY_STOP_SIGNAL.code,
        )

    # this wait is needed to avoid a race condition where
    # the primary worker sends the task and it is immediately executed
    # before the primary worker can finalize the fence
    start = time.monotonic()
    while True:
        if time.monotonic() - start > CELERY_TASK_WAIT_FOR_FENCE_TIMEOUT:
            raise SimpleJobException(
                f"connector_indexing_task - timed out waiting for fence to be ready: "
                f"fence={redis_connector.permissions.fence_key}",
                code=IndexingWatchdogTerminalStatus.FENCE_READINESS_TIMEOUT.code,
            )

        if not redis_connector_index.fenced:  # The fence must exist
            raise SimpleJobException(
                f"connector_indexing_task - fence not found: fence={redis_connector_index.fence_key}",
                code=IndexingWatchdogTerminalStatus.FENCE_NOT_FOUND.code,
            )

        payload = redis_connector_index.payload  # The payload must exist
        if not payload:
            raise SimpleJobException(
                "connector_indexing_task: payload invalid or not found",
                code=IndexingWatchdogTerminalStatus.FENCE_NOT_FOUND.code,
            )

        if payload.index_attempt_id is None or payload.celery_task_id is None:
            logger.info(
                f"connector_indexing_task - Waiting for fence: fence={redis_connector_index.fence_key}"
            )
            sleep(1)
            continue

        if payload.index_attempt_id != index_attempt_id:
            raise SimpleJobException(
                f"connector_indexing_task - id mismatch. Task may be left over from previous run.: "
                f"task_index_attempt={index_attempt_id} "
                f"payload_index_attempt={payload.index_attempt_id}",
                code=IndexingWatchdogTerminalStatus.FENCE_MISMATCH.code,
            )

        logger.info(
            f"connector_indexing_task - Fence found, continuing...: fence={redis_connector_index.fence_key}"
        )
        break

    # set thread_local=False since we don't control what thread the indexing/pruning
    # might run our callback with
    lock: RedisLock = r.lock(
        redis_connector_index.generator_lock_key,
        timeout=CELERY_INDEXING_LOCK_TIMEOUT,
        thread_local=False,
    )

    acquired = lock.acquire(blocking=False)
    if not acquired:
        logger.warning(
            f"Indexing task already running, exiting...: "
            f"index_attempt={index_attempt_id} "
            f"cc_pair={cc_pair_id} "
            f"search_settings={search_settings_id}"
        )

        raise SimpleJobException(
            f"Indexing task already running, exiting...: "
            f"index_attempt={index_attempt_id} "
            f"cc_pair={cc_pair_id} "
            f"search_settings={search_settings_id}",
            code=IndexingWatchdogTerminalStatus.TASK_ALREADY_RUNNING.code,
        )

    payload.started = datetime.now(timezone.utc)
    redis_connector_index.set_fence(payload)

    try:
        with get_session_with_current_tenant() as db_session:
            attempt = get_index_attempt(db_session, index_attempt_id)
            if not attempt:
                raise SimpleJobException(
                    f"Index attempt not found: index_attempt={index_attempt_id}",
                    code=IndexingWatchdogTerminalStatus.INDEX_ATTEMPT_MISMATCH.code,
                )

            cc_pair = get_connector_credential_pair_from_id(
                db_session=db_session,
                cc_pair_id=cc_pair_id,
            )

            if not cc_pair:
                raise SimpleJobException(
                    f"cc_pair not found: cc_pair={cc_pair_id}",
                    code=IndexingWatchdogTerminalStatus.INDEX_ATTEMPT_MISMATCH.code,
                )

            if not cc_pair.connector:
                raise SimpleJobException(
                    f"Connector not found: cc_pair={cc_pair_id} connector={cc_pair.connector_id}",
                    code=IndexingWatchdogTerminalStatus.INDEX_ATTEMPT_MISMATCH.code,
                )

            if not cc_pair.credential:
                raise SimpleJobException(
                    f"Credential not found: cc_pair={cc_pair_id} credential={cc_pair.credential_id}",
                    code=IndexingWatchdogTerminalStatus.INDEX_ATTEMPT_MISMATCH.code,
                )

        # define a callback class
        callback = IndexingCallback(
            os.getppid(),
            redis_connector,
            lock,
            r,
            redis_connector_index,
        )

        logger.info(
            f"Indexing spawned task running entrypoint: attempt={index_attempt_id} "
            f"tenant={tenant_id} "
            f"cc_pair={cc_pair_id} "
            f"search_settings={search_settings_id}"
        )

        # This is where the heavy/real work happens
        run_indexing_entrypoint(
            app,
            index_attempt_id,
            tenant_id,
            cc_pair_id,
            is_ee,
            callback=callback,
        )

        # get back the total number of indexed docs and return it
        n_final_progress = redis_connector_index.get_progress()
        redis_connector_index.set_generator_complete(HTTPStatus.OK.value)
    except ConnectorValidationError:
        raise SimpleJobException(
            f"Indexing task failed: attempt={index_attempt_id} "
            f"tenant={tenant_id} "
            f"cc_pair={cc_pair_id} "
            f"search_settings={search_settings_id}",
            code=IndexingWatchdogTerminalStatus.CONNECTOR_VALIDATION_ERROR.code,
        )

    except Exception as e:
        logger.exception(
            f"Indexing spawned task failed: attempt={index_attempt_id} "
            f"tenant={tenant_id} "
            f"cc_pair={cc_pair_id} "
            f"search_settings={search_settings_id}"
        )

        # special bulletproofing ... truncate long exception messages
        # for exception types that require more args, this will fail
        # thus the try/except
        try:
            sanitized_e = type(e)(str(e)[:1024])
            sanitized_e.__traceback__ = e.__traceback__
            raise sanitized_e
        except Exception:
            raise e

    finally:
        if lock.owned():
            lock.release()

    logger.info(
        f"Indexing spawned task finished: attempt={index_attempt_id} "
        f"cc_pair={cc_pair_id} "
        f"search_settings={search_settings_id}"
    )
    return n_final_progress


def process_job_result(
    job: SimpleJob,
    connector_source: str | None,
    redis_connector_index: RedisConnectorIndex,
    log_builder: ConnectorIndexingLogBuilder,
) -> SimpleJobResult:
    result = SimpleJobResult()
    result.connector_source = connector_source

    if job.process:
        result.exit_code = job.process.exitcode

    if job.status != "error":
        result.status = IndexingWatchdogTerminalStatus.SUCCEEDED
        return result

    ignore_exitcode = False

    # In EKS, there is an edge case where successful tasks return exit
    # code 1 in the cloud due to the set_spawn_method not sticking.
    # We've since worked around this, but the following is a safe way to
    # work around this issue. Basically, we ignore the job error state
    # if the completion signal is OK.
    status_int = redis_connector_index.get_completion()
    if status_int:
        status_enum = HTTPStatus(status_int)
        if status_enum == HTTPStatus.OK:
            ignore_exitcode = True

    if ignore_exitcode:
        result.status = IndexingWatchdogTerminalStatus.SUCCEEDED
        task_logger.warning(
            log_builder.build(
                "Indexing watchdog - spawned task has non-zero exit code "
                "but completion signal is OK. Continuing...",
                exit_code=str(result.exit_code),
            )
        )
    else:
        if result.exit_code is not None:
            result.status = IndexingWatchdogTerminalStatus.from_code(result.exit_code)

        result.exception_str = job.exception()

    return result


@shared_task(
    name=OnyxCeleryTask.CONNECTOR_DOC_FETCHING_TASK,
    bind=True,
    acks_late=False,
    track_started=True,
)
def connector_indexing_proxy_task(
    self: Task,
    index_attempt_id: int,
    cc_pair_id: int,
    search_settings_id: int,
    tenant_id: str,
) -> None:
    """celery out of process task execution strategy is pool=prefork, but it uses fork,
    and forking is inherently unstable.

    To work around this, we use pool=threads and proxy our work to a spawned task.

    TODO(rkuo): refactor this so that there is a single return path where we canonically
    log the result of running this function.

    NOTE: we try/except all db access in this function because as a watchdog, this function
    needs to be extremely stable.
    """
    start = time.monotonic()

    result = SimpleJobResult()

    ctx = ConnectorIndexingContext(
        tenant_id=tenant_id,
        cc_pair_id=cc_pair_id,
        search_settings_id=search_settings_id,
        index_attempt_id=index_attempt_id,
    )

    log_builder = ConnectorIndexingLogBuilder(ctx)

    task_logger.info(
        log_builder.build(
            "Indexing watchdog - starting",
            mp_start_method=str(multiprocessing.get_start_method()),
        )
    )

    if not self.request.id:
        task_logger.error("self.request.id is None!")

    client = SimpleJobClient()
    task_logger.info(f"submitting connector_indexing_task with tenant_id={tenant_id}")

    job = client.submit(
        docfetching_task,
        self.app,
        index_attempt_id,
        cc_pair_id,
        search_settings_id,
        global_version.is_ee_version(),
        tenant_id,
    )

    if not job or not job.process:
        result.status = IndexingWatchdogTerminalStatus.SPAWN_FAILED
        task_logger.info(
            log_builder.build(
                "Indexing watchdog - finished",
                status=str(result.status.value),
                exit_code=str(result.exit_code),
            )
        )
        return

    # Ensure the process has moved out of the starting state
    num_waits = 0
    while True:
        if num_waits > 15:
            result.status = IndexingWatchdogTerminalStatus.SPAWN_NOT_ALIVE
            task_logger.info(
                log_builder.build(
                    "Indexing watchdog - finished",
                    status=str(result.status.value),
                    exit_code=str(result.exit_code),
                )
            )
            job.release()
            return

        if job.process.is_alive() or job.process.exitcode is not None:
            break

        sleep(1)
        num_waits += 1

    task_logger.info(
        log_builder.build(
            "Indexing watchdog - spawn succeeded",
            pid=str(job.process.pid),
        )
    )

    redis_connector = RedisConnector(tenant_id, cc_pair_id)
    redis_connector_index = redis_connector.new_index(search_settings_id)

    # Track the last time memory info was emitted
    last_memory_emit_time = 0.0

    # track the last ttl and the time it was observed
    last_activity_ttl_observed: float = time.monotonic()
    last_activity_ttl: int = 0

    try:
        with get_session_with_current_tenant() as db_session:
            index_attempt = get_index_attempt(
                db_session=db_session,
                index_attempt_id=index_attempt_id,
                eager_load_cc_pair=True,
            )
            if not index_attempt:
                raise RuntimeError("Index attempt not found")

            result.connector_source = (
                index_attempt.connector_credential_pair.connector.source.value
            )

        redis_connector_index.set_active()  # renew active signal

        # prime the connector active signal (renewed inside the connector)
        redis_connector_index.set_connector_active()

        while True:
            sleep(5)

            now = time.monotonic()

            # renew watchdog signal (this has a shorter timeout than set_active)
            redis_connector_index.set_watchdog(True)

            # renew active signal
            redis_connector_index.set_active()

            # if the job is done, clean up and break
            if job.done():
                try:
                    result = process_job_result(
                        job, result.connector_source, redis_connector_index, log_builder
                    )
                except Exception:
                    task_logger.exception(
                        log_builder.build(
                            "Indexing watchdog - spawned task exceptioned"
                        )
                    )
                finally:
                    job.release()
                    break

            # log the memory usage for tracking down memory leaks / connector-specific memory issues
            pid = job.process.pid
            if pid is not None:
                # Only emit memory info once per minute (60 seconds)
                current_time = time.monotonic()
                if current_time - last_memory_emit_time >= 60.0:
                    emit_process_memory(
                        pid,
                        "indexing_worker",
                        {
                            "cc_pair_id": cc_pair_id,
                            "search_settings_id": search_settings_id,
                            "index_attempt_id": index_attempt_id,
                        },
                    )
                    last_memory_emit_time = current_time

            # if a termination signal is detected, break (exit point will clean up)
            if self.request.id and redis_connector_index.terminating(self.request.id):
                task_logger.warning(
                    log_builder.build("Indexing watchdog - termination signal detected")
                )

                result.status = IndexingWatchdogTerminalStatus.TERMINATED_BY_SIGNAL
                break

            # if activity timeout is detected, break (exit point will clean up)
            ttl = redis_connector_index.connector_active_ttl()
            if ttl < 0:
                # verify expectations around ttl
                last_observed = last_activity_ttl_observed - now
                if now > last_activity_ttl_observed + last_activity_ttl:
                    task_logger.warning(
                        log_builder.build(
                            "Indexing watchdog - activity timeout exceeded",
                            last_observed=f"{last_observed:.2f}s",
                            last_ttl=f"{last_activity_ttl}",
                            timeout=f"{CELERY_INDEXING_WATCHDOG_CONNECTOR_TIMEOUT}s",
                        )
                    )

                    result.status = (
                        IndexingWatchdogTerminalStatus.TERMINATED_BY_ACTIVITY_TIMEOUT
                    )
                    break
                else:
                    task_logger.warning(
                        log_builder.build(
                            "Indexing watchdog - activity timeout expired unexpectedly, "
                            "waiting for last observed TTL before exiting",
                            last_observed=f"{last_observed:.2f}s",
                            last_ttl=f"{last_activity_ttl}",
                            timeout=f"{CELERY_INDEXING_WATCHDOG_CONNECTOR_TIMEOUT}s",
                        )
                    )
            else:
                last_activity_ttl_observed = now
                last_activity_ttl = ttl

            # if the spawned task is still running, restart the check once again
            # if the index attempt is not in a finished status
            try:
                with get_session_with_current_tenant() as db_session:
                    index_attempt = get_index_attempt(
                        db_session=db_session, index_attempt_id=index_attempt_id
                    )

                    if not index_attempt:
                        continue

                    if not index_attempt.is_finished():
                        continue

            except Exception:
                task_logger.exception(
                    log_builder.build(
                        "Indexing watchdog - transient exception looking up index attempt"
                    )
                )
                continue

    except Exception as e:
        result.status = IndexingWatchdogTerminalStatus.WATCHDOG_EXCEPTIONED
        if isinstance(e, ConnectorValidationError):
            # No need to expose full stack trace for validation errors
            result.exception_str = str(e)
        else:
            result.exception_str = traceback.format_exc()

    # handle exit and reporting
    elapsed = time.monotonic() - start
    if result.exception_str is not None:
        # print with exception
        try:
            with get_session_with_current_tenant() as db_session:
                failure_reason = (
                    f"Spawned task exceptioned: exit_code={result.exit_code}"
                )
                mark_attempt_failed(
                    ctx.index_attempt_id,
                    db_session,
                    failure_reason=failure_reason,
                    full_exception_trace=result.exception_str,
                )
        except Exception:
            task_logger.exception(
                log_builder.build(
                    "Indexing watchdog - transient exception marking index attempt as failed"
                )
            )

        normalized_exception_str = "None"
        if result.exception_str:
            normalized_exception_str = result.exception_str.replace(
                "\n", "\\n"
            ).replace('"', '\\"')

        task_logger.warning(
            log_builder.build(
                "Indexing watchdog - finished",
                source=result.connector_source,
                status=result.status.value,
                exit_code=str(result.exit_code),
                exception=f'"{normalized_exception_str}"',
                elapsed=f"{elapsed:.2f}s",
            )
        )

        redis_connector_index.set_watchdog(False)
        raise RuntimeError(f"Exception encountered: traceback={result.exception_str}")

    # print without exception
    if result.status == IndexingWatchdogTerminalStatus.TERMINATED_BY_SIGNAL:
        try:
            with get_session_with_current_tenant() as db_session:
                logger.exception(
                    f"Marking attempt {index_attempt_id} as canceled due to termination signal"
                )
                mark_attempt_canceled(
                    index_attempt_id,
                    db_session,
                    "Connector termination signal detected",
                )
        except Exception:
            task_logger.exception(
                log_builder.build(
                    "Indexing watchdog - transient exception marking index attempt as canceled"
                )
            )

        job.cancel()
    elif result.status == IndexingWatchdogTerminalStatus.TERMINATED_BY_ACTIVITY_TIMEOUT:
        try:
            with get_session_with_current_tenant() as db_session:
                mark_attempt_failed(
                    index_attempt_id,
                    db_session,
                    "Indexing watchdog - activity timeout exceeded: "
                    f"attempt={index_attempt_id} "
                    f"timeout={CELERY_INDEXING_WATCHDOG_CONNECTOR_TIMEOUT}s",
                )
        except Exception:
            logger.exception(
                log_builder.build(
                    "Indexing watchdog - transient exception marking index attempt as failed"
                )
            )
        job.cancel()
    else:
        pass

    task_logger.info(
        log_builder.build(
            "Indexing watchdog - finished",
            source=result.connector_source,
            status=str(result.status.value),
            exit_code=str(result.exit_code),
            elapsed=f"{elapsed:.2f}s",
        )
    )

    redis_connector_index.set_watchdog(False)


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


def _initialize_indexing_state(
    storage: DocumentBatchStorage,
) -> DocIndexingContext:
    curr_state = storage.get_indexing_state()
    if curr_state:
        return curr_state

    current_state = DocIndexingContext(
        batches_done=0,
        unfinished_batches=set(),
        total_failures=0,
        net_doc_change=0,
        total_chunks=0,
    )
    storage.store_indexing_state(current_state)
    return current_state


def _ensure_indexing_state(
    storage: DocumentBatchStorage,
) -> DocIndexingContext:
    current_state = storage.get_indexing_state()
    if not current_state:
        raise ValueError("No indexing state found")
    return current_state


def _ensure_extraction_state(
    storage: DocumentBatchStorage,
) -> DocExtractionContext:
    current_state = storage.get_extraction_state()
    if not current_state:
        raise ValueError("No extraction state found")
    return current_state


def _update_indexing_state(
    index_attempt_id: int,
    tenant_id: str,
    failures: int,
    new_docs: int,
    total_chunks: int,
) -> DocIndexingContext:
    with get_session_with_current_tenant() as db_session:
        storage = get_document_batch_storage(tenant_id, index_attempt_id, db_session)

        current_state = _ensure_indexing_state(storage)
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
    name=OnyxCeleryTask.DOCUMENT_INDEXING_PIPELINE_TASK,
    bind=True,
)
def document_indexing_pipeline_task(
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

    if tenant_id:
        CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)

    task_logger.info(
        f"Processing document batch: "
        f"batch_id={batch_id} "
        f"attempt={index_attempt_id} "
        f"batch_num={batch_num} "
    )

    # Get the document batch storage
    with get_session_with_current_tenant() as db_session:
        storage = get_document_batch_storage(tenant_id, index_attempt_id, db_session)

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

            cross_batch_state_lock: RedisLock = r.lock(
                redis_connector_index.filestore_lock_key,
                timeout=CELERY_INDEXING_LOCK_TIMEOUT,
                thread_local=False,
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

            with cross_batch_state_lock:
                current_indexing_state = _initialize_indexing_state(storage)

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

        # Update extraction state with batch results using atomic Redis operation
        with cross_batch_state_lock:
            current_indexing_state = _update_indexing_state(
                index_attempt_id,
                tenant_id,
                len(index_pipeline_result.failures),
                index_pipeline_result.new_docs,
                index_pipeline_result.total_chunks,
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
            _check_failure_threshold(
                current_indexing_state.total_failures,
                current_indexing_state.net_doc_change,
                batch_num,
                index_pipeline_result.failures[-1],
            )

        with get_session_with_current_tenant() as db_session:
            update_docs_indexed(
                db_session=db_session,
                index_attempt_id=index_attempt_id,
                total_docs_indexed=index_pipeline_result.total_docs,
                new_docs_indexed=index_pipeline_result.new_docs,
                docs_removed_from_index=0,
            )

        if callback:
            # _run_indexing for legacy reasons
            callback.progress("_run_indexing", len(documents))
        # Check if all batches are complete and signal completion if so
        with get_session_with_current_tenant() as db_session:
            # Use the same Redis lock for consistency
            with cross_batch_state_lock:
                current_extraction_state = _ensure_extraction_state(storage)
                check_indexing_completion(index_attempt_id, tenant_id)

                # redis_connector_index.set_generator_complete(HTTPStatus.OK.value)
        # Add telemetry for indexing progress
        optional_telemetry(
            record_type=RecordType.INDEXING_PROGRESS,
            data={
                "index_attempt_id": index_attempt_id,
                "cc_pair_id": cc_pair_id,
                "current_docs_indexed": current_indexing_state.net_doc_change,
                "current_chunks_indexed": current_indexing_state.total_chunks,
                "source": current_extraction_state.source.value,
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

    except Exception as e:
        task_logger.exception(
            f"Document batch processing failed: "
            f"batch_id={batch_id} "
            f"attempt={index_attempt_id} "
            f"error={str(e)}"
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


def check_indexing_completion(
    index_attempt_id: int,
    tenant_id: str,
) -> None:

    task_logger.info(
        f"Checking for document processing completion: "
        f"attempt={index_attempt_id} "
        f"tenant={tenant_id}"
    )

    with get_session_with_current_tenant() as db_session:
        storage = get_document_batch_storage(tenant_id, index_attempt_id, db_session)

    try:
        # Get current state
        extraction_state = _ensure_extraction_state(storage)
        indexing_state = _ensure_indexing_state(storage)

        # Check if extraction is complete and all batches are processed
        batches_total = extraction_state.doc_extraction_complete_batch_num
        batches_processed = indexing_state.batches_done
        extraction_completed = batches_total is not None and (
            batches_processed >= batches_total
        )

        task_logger.info(
            f"Processing status: "
            f"extraction_completed={extraction_completed} "
            f"batches_processed={batches_processed}/{batches_total or '?'}"  # probably off by 1
        )

        if not extraction_completed:
            return

        task_logger.info(
            f"All batches for index attempt {index_attempt_id} have been processed."
        )

        # All processing is complete
        total_failures = indexing_state.total_failures

        with get_session_with_current_tenant() as db_session:
            if total_failures == 0:
                mark_attempt_succeeded(index_attempt_id, db_session)
                task_logger.info(
                    f"Index attempt {index_attempt_id} completed successfully"
                )
            else:
                mark_attempt_partially_succeeded(index_attempt_id, db_session)
                task_logger.info(
                    f"Index attempt {index_attempt_id} completed with {total_failures} failures"
                )

            # Clear the indexing trigger if it was set, to prevent duplicate indexing attempts
            index_attempt = get_index_attempt(db_session, index_attempt_id)
            if (
                index_attempt
                and index_attempt.connector_credential_pair.indexing_trigger is not None
            ):
                task_logger.info(
                    "Clearing indexing trigger after completion: "
                    f"cc_pair={index_attempt.connector_credential_pair.id} "
                    f"trigger={index_attempt.connector_credential_pair.indexing_trigger}"
                )
                mark_ccpair_with_indexing_trigger(
                    index_attempt.connector_credential_pair.id, None, db_session
                )

        # Clean up all remaining storage
        storage.cleanup_all_batches()

        # Clean up the fence to allow the next run to start
        with get_session_with_current_tenant() as db_session:
            index_attempt = get_index_attempt(db_session, index_attempt_id)
            if index_attempt and index_attempt.search_settings:
                redis_connector = RedisConnector(
                    tenant_id, index_attempt.connector_credential_pair_id
                )
                redis_connector_index = redis_connector.new_index(
                    index_attempt.search_settings.id
                )
                redis_connector_index.reset()
                task_logger.info(
                    f"Resetting indexing fence for attempt {index_attempt_id}"
                )

    except Exception as e:
        task_logger.exception(
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
        except Exception:
            task_logger.exception("Failed to mark attempt as failed")

        # Try to clean up storage
        try:
            storage.cleanup_all_batches()
        except Exception:
            task_logger.exception("Failed to cleanup storage after monitoring failure")
