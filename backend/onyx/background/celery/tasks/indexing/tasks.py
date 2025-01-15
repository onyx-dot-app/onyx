import multiprocessing
import os
import sys
import time
from datetime import datetime
from datetime import timezone
from http import HTTPStatus
from time import sleep

import redis
import sentry_sdk
from celery import Celery
from celery import shared_task
from celery import Task
from celery.exceptions import SoftTimeLimitExceeded
from redis import Redis
from redis.exceptions import LockError
from redis.lock import Lock as RedisLock
from sqlalchemy.orm import Session

from onyx.background.celery.apps.app_base import task_logger
from onyx.background.celery.celery_redis import celery_find_task
from onyx.background.celery.celery_redis import celery_get_unacked_task_ids
from onyx.background.indexing.job_client import SimpleJobClient
from onyx.background.indexing.run_indexing import run_indexing_entrypoint
from onyx.configs.app_configs import DISABLE_INDEX_UPDATE_ON_SWAP
from onyx.configs.constants import CELERY_INDEXING_LOCK_TIMEOUT
from onyx.configs.constants import CELERY_TASK_WAIT_FOR_FENCE_TIMEOUT
from onyx.configs.constants import CELERY_VESPA_SYNC_BEAT_LOCK_TIMEOUT
from onyx.configs.constants import DANSWER_REDIS_FUNCTION_LOCK_PREFIX
from onyx.configs.constants import DocumentSource
from onyx.configs.constants import OnyxCeleryPriority
from onyx.configs.constants import OnyxCeleryQueues
from onyx.configs.constants import OnyxCeleryTask
from onyx.configs.constants import OnyxRedisLocks
from onyx.configs.constants import OnyxRedisSignals
from onyx.db.connector import mark_ccpair_with_indexing_trigger
from onyx.db.connector_credential_pair import fetch_connector_credential_pairs
from onyx.db.connector_credential_pair import get_connector_credential_pair_from_id
from onyx.db.engine import get_db_current_time
from onyx.db.engine import get_session_with_tenant
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.enums import IndexingMode
from onyx.db.enums import IndexingStatus
from onyx.db.enums import IndexModelStatus
from onyx.db.index_attempt import create_index_attempt
from onyx.db.index_attempt import delete_index_attempt
from onyx.db.index_attempt import get_all_index_attempts_by_status
from onyx.db.index_attempt import get_index_attempt
from onyx.db.index_attempt import get_last_attempt_for_cc_pair
from onyx.db.index_attempt import mark_attempt_canceled
from onyx.db.index_attempt import mark_attempt_failed
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import IndexAttempt
from onyx.db.models import SearchSettings
from onyx.db.search_settings import get_active_search_settings
from onyx.db.search_settings import get_current_search_settings
from onyx.db.swap_index import check_index_swap
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.natural_language_processing.search_nlp_models import EmbeddingModel
from onyx.natural_language_processing.search_nlp_models import warm_up_bi_encoder
from onyx.redis.redis_connector import RedisConnector
from onyx.redis.redis_connector_index import RedisConnectorIndex
from onyx.redis.redis_connector_index import RedisConnectorIndexPayload
from onyx.redis.redis_pool import get_redis_client
from onyx.redis.redis_pool import redis_lock_dump
from onyx.redis.redis_pool import SCAN_ITER_COUNT_DEFAULT
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import global_version
from shared_configs.configs import INDEXING_MODEL_SERVER_HOST
from shared_configs.configs import INDEXING_MODEL_SERVER_PORT
from shared_configs.configs import MULTI_TENANT
from shared_configs.configs import SENTRY_DSN

logger = setup_logger()


class IndexingCallback(IndexingHeartbeatInterface):
    PARENT_CHECK_INTERVAL = 60

    def __init__(
        self,
        parent_pid: int,
        stop_key: str,
        generator_progress_key: str,
        redis_lock: RedisLock,
        redis_client: Redis,
    ):
        super().__init__()
        self.parent_pid = parent_pid
        self.redis_lock: RedisLock = redis_lock
        self.stop_key: str = stop_key
        self.generator_progress_key: str = generator_progress_key
        self.redis_client = redis_client
        self.started: datetime = datetime.now(timezone.utc)
        self.redis_lock.reacquire()

        self.last_tag: str = "IndexingCallback.__init__"
        self.last_lock_reacquire: datetime = datetime.now(timezone.utc)
        self.last_lock_monotonic = time.monotonic()

        self.last_parent_check = time.monotonic()

    def should_stop(self) -> bool:
        if self.redis_client.exists(self.stop_key):
            return True

        return False

    def progress(self, tag: str, amount: int) -> None:
        # rkuo: this shouldn't be necessary yet because we spawn the process this runs inside
        # with daemon = True. It seems likely some indexing tasks will need to spawn other processes eventually
        # so leave this code in until we're ready to test it.

        # if self.parent_pid:
        #     # check if the parent pid is alive so we aren't running as a zombie
        #     now = time.monotonic()
        #     if now - self.last_parent_check > IndexingCallback.PARENT_CHECK_INTERVAL:
        #         try:
        #             # this is unintuitive, but it checks if the parent pid is still running
        #             os.kill(self.parent_pid, 0)
        #         except Exception:
        #             logger.exception("IndexingCallback - parent pid check exceptioned")
        #             raise
        #         self.last_parent_check = now

        try:
            current_time = time.monotonic()
            if current_time - self.last_lock_monotonic >= (
                CELERY_VESPA_SYNC_BEAT_LOCK_TIMEOUT / 4
            ):
                self.redis_lock.reacquire()
                self.last_lock_reacquire = datetime.now(timezone.utc)
                self.last_lock_monotonic = time.monotonic()

            self.last_tag = tag
        except LockError:
            logger.exception(
                f"IndexingCallback - lock.reacquire exceptioned: "
                f"lock_timeout={self.redis_lock.timeout} "
                f"start={self.started} "
                f"last_tag={self.last_tag} "
                f"last_reacquired={self.last_lock_reacquire} "
                f"now={datetime.now(timezone.utc)}"
            )

            redis_lock_dump(self.redis_lock, self.redis_client)
            raise

        self.redis_client.incrby(self.generator_progress_key, amount)


def get_unfenced_index_attempt_ids(db_session: Session, r: redis.Redis) -> list[int]:
    """Gets a list of unfenced index attempts. Should not be possible, so we'd typically
    want to clean them up.

    Unfenced = attempt not in terminal state and fence does not exist.
    """
    unfenced_attempts: list[int] = []

    # inner/outer/inner double check pattern to avoid race conditions when checking for
    # bad state
    # inner = index_attempt in non terminal state
    # outer = r.fence_key down

    # check the db for index attempts in a non terminal state
    attempts: list[IndexAttempt] = []
    attempts.extend(
        get_all_index_attempts_by_status(IndexingStatus.NOT_STARTED, db_session)
    )
    attempts.extend(
        get_all_index_attempts_by_status(IndexingStatus.IN_PROGRESS, db_session)
    )

    for attempt in attempts:
        fence_key = RedisConnectorIndex.fence_key_with_ids(
            attempt.connector_credential_pair_id, attempt.search_settings_id
        )

        # if the fence is down / doesn't exist, possible error but not confirmed
        if r.exists(fence_key):
            continue

        # Between the time the attempts are first looked up and the time we see the fence down,
        # the attempt may have completed and taken down the fence normally.

        # We need to double check that the index attempt is still in a non terminal state
        # and matches the original state, which confirms we are really in a bad state.
        attempt_2 = get_index_attempt(db_session, attempt.id)
        if not attempt_2:
            continue

        if attempt.status != attempt_2.status:
            continue

        unfenced_attempts.append(attempt.id)

    return unfenced_attempts


@shared_task(
    name=OnyxCeleryTask.CHECK_FOR_INDEXING,
    soft_time_limit=300,
    bind=True,
)
def check_for_indexing(self: Task, *, tenant_id: str | None) -> int | None:
    """a lightweight task used to kick off indexing tasks.
    Occcasionally does some validation of existing state to clear up error conditions"""
    debug_tenants = {
        "tenant_i-043470d740845ec56",
        "tenant_82b497ce-88aa-4fbd-841a-92cae43529c8",
    }
    time_start = time.monotonic()

    tasks_created = 0
    locked = False
    redis_client = get_redis_client(tenant_id=tenant_id)

    # we need to use celery's redis client to access its redis data
    # (which lives on a different db number)
    redis_client_celery: Redis = self.app.broker_connection().channel().client  # type: ignore

    lock_beat: RedisLock = redis_client.lock(
        OnyxRedisLocks.CHECK_INDEXING_BEAT_LOCK,
        timeout=CELERY_VESPA_SYNC_BEAT_LOCK_TIMEOUT,
    )

    # these tasks should never overlap
    if not lock_beat.acquire(blocking=False):
        return None

    try:
        locked = True

        # check for search settings swap
        with get_session_with_tenant(tenant_id=tenant_id) as db_session:
            old_search_settings = check_index_swap(db_session=db_session)
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
        with get_session_with_tenant(tenant_id) as db_session:
            cc_pairs = fetch_connector_credential_pairs(db_session)
            for cc_pair_entry in cc_pairs:
                cc_pair_ids.append(cc_pair_entry.id)

        # kick off index attempts
        for cc_pair_id in cc_pair_ids:
            # debugging logic - remove after we're done
            if tenant_id in debug_tenants:
                ttl = redis_client.ttl(OnyxRedisLocks.CHECK_INDEXING_BEAT_LOCK)
                task_logger.info(
                    f"check_for_indexing cc_pair lock: "
                    f"tenant={tenant_id} "
                    f"cc_pair={cc_pair_id} "
                    f"ttl={ttl}"
                )

            lock_beat.reacquire()

            redis_connector = RedisConnector(tenant_id, cc_pair_id)
            with get_session_with_tenant(tenant_id) as db_session:
                search_settings_list: list[SearchSettings] = get_active_search_settings(
                    db_session
                )
                for search_settings_instance in search_settings_list:
                    if tenant_id in debug_tenants:
                        ttl = redis_client.ttl(OnyxRedisLocks.CHECK_INDEXING_BEAT_LOCK)
                        task_logger.info(
                            f"check_for_indexing cc_pair search settings lock: "
                            f"tenant={tenant_id} "
                            f"cc_pair={cc_pair_id} "
                            f"ttl={ttl}"
                        )

                    redis_connector_index = redis_connector.new_index(
                        search_settings_instance.id
                    )
                    if redis_connector_index.fenced:
                        continue

                    if tenant_id in debug_tenants:
                        ttl = redis_client.ttl(OnyxRedisLocks.CHECK_INDEXING_BEAT_LOCK)
                        task_logger.info(
                            f"check_for_indexing get_connector_credential_pair_from_id: "
                            f"tenant={tenant_id} "
                            f"cc_pair={cc_pair_id} "
                            f"ttl={ttl}"
                        )

                    cc_pair = get_connector_credential_pair_from_id(
                        db_session=db_session,
                        cc_pair_id=cc_pair_id,
                    )
                    if not cc_pair:
                        continue

                    if tenant_id in debug_tenants:
                        ttl = redis_client.ttl(OnyxRedisLocks.CHECK_INDEXING_BEAT_LOCK)
                        task_logger.info(
                            f"check_for_indexing get_last_attempt_for_cc_pair: "
                            f"tenant={tenant_id} "
                            f"cc_pair={cc_pair_id} "
                            f"ttl={ttl}"
                        )

                    last_attempt = get_last_attempt_for_cc_pair(
                        cc_pair.id, search_settings_instance.id, db_session
                    )

                    if tenant_id in debug_tenants:
                        ttl = redis_client.ttl(OnyxRedisLocks.CHECK_INDEXING_BEAT_LOCK)
                        task_logger.info(
                            f"check_for_indexing cc_pair should index: "
                            f"tenant={tenant_id} "
                            f"cc_pair={cc_pair_id} "
                            f"ttl={ttl}"
                        )

                    search_settings_primary = False
                    if search_settings_instance.id == search_settings_list[0].id:
                        search_settings_primary = True

                    if not _should_index(
                        cc_pair=cc_pair,
                        last_index=last_attempt,
                        search_settings_instance=search_settings_instance,
                        search_settings_primary=search_settings_primary,
                        secondary_index_building=len(search_settings_list) > 1,
                        db_session=db_session,
                    ):
                        continue

                    reindex = False
                    if search_settings_instance.id == search_settings_list[0].id:
                        # the indexing trigger is only checked and cleared with the primary search settings
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

                    if tenant_id in debug_tenants:
                        ttl = redis_client.ttl(OnyxRedisLocks.CHECK_INDEXING_BEAT_LOCK)
                        task_logger.info(
                            f"check_for_indexing cc_pair try_creating_indexing_task: "
                            f"tenant={tenant_id} "
                            f"cc_pair={cc_pair_id} "
                            f"ttl={ttl}"
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

                    if tenant_id in debug_tenants:
                        ttl = redis_client.ttl(OnyxRedisLocks.CHECK_INDEXING_BEAT_LOCK)
                        task_logger.info(
                            f"check_for_indexing cc_pair try_creating_indexing_task finished: "
                            f"tenant={tenant_id} "
                            f"cc_pair={cc_pair_id} "
                            f"ttl={ttl}"
                        )

        # debugging logic - remove after we're done
        if tenant_id in debug_tenants:
            ttl = redis_client.ttl(OnyxRedisLocks.CHECK_INDEXING_BEAT_LOCK)
            task_logger.info(
                f"check_for_indexing unfenced lock: "
                f"tenant={tenant_id} "
                f"ttl={ttl}"
            )

        lock_beat.reacquire()

        # Fail any index attempts in the DB that don't have fences
        # This shouldn't ever happen!
        with get_session_with_tenant(tenant_id) as db_session:
            unfenced_attempt_ids = get_unfenced_index_attempt_ids(
                db_session, redis_client
            )

            if tenant_id in debug_tenants:
                ttl = redis_client.ttl(OnyxRedisLocks.CHECK_INDEXING_BEAT_LOCK)
                task_logger.info(
                    f"check_for_indexing after get unfenced lock: "
                    f"tenant={tenant_id} "
                    f"ttl={ttl}"
                )

            for attempt_id in unfenced_attempt_ids:
                # debugging logic - remove after we're done
                if tenant_id in debug_tenants:
                    ttl = redis_client.ttl(OnyxRedisLocks.CHECK_INDEXING_BEAT_LOCK)
                    task_logger.info(
                        f"check_for_indexing unfenced attempt id lock: "
                        f"tenant={tenant_id} "
                        f"ttl={ttl}"
                    )

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

        # debugging logic - remove after we're done
        if tenant_id in debug_tenants:
            ttl = redis_client.ttl(OnyxRedisLocks.CHECK_INDEXING_BEAT_LOCK)
            task_logger.info(
                f"check_for_indexing validate fences lock: "
                f"tenant={tenant_id} "
                f"ttl={ttl}"
            )

        lock_beat.reacquire()
        # we want to run this less frequently than the overall task
        if not redis_client.exists(OnyxRedisSignals.VALIDATE_INDEXING_FENCES):
            # clear any indexing fences that don't have associated celery tasks in progress
            # tasks can be in the queue in redis, in reserved tasks (prefetched by the worker),
            # or be currently executing
            try:
                validate_indexing_fences(
                    tenant_id, self.app, redis_client, redis_client_celery, lock_beat
                )
            except Exception:
                task_logger.exception("Exception while validating indexing fences")

            redis_client.set(OnyxRedisSignals.VALIDATE_INDEXING_FENCES, 1, ex=60)
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
    task_logger.debug(f"check_for_indexing finished: elapsed={time_elapsed:.2f}")
    return tasks_created


def validate_indexing_fences(
    tenant_id: str | None,
    celery_app: Celery,
    r: Redis,
    r_celery: Redis,
    lock_beat: RedisLock,
) -> None:
    reserved_indexing_tasks = celery_get_unacked_task_ids(
        OnyxCeleryQueues.CONNECTOR_INDEXING, r_celery
    )

    # validate all existing indexing jobs
    for key_bytes in r.scan_iter(
        RedisConnectorIndex.FENCE_PREFIX + "*", count=SCAN_ITER_COUNT_DEFAULT
    ):
        lock_beat.reacquire()
        with get_session_with_tenant(tenant_id) as db_session:
            validate_indexing_fence(
                tenant_id,
                key_bytes,
                reserved_indexing_tasks,
                r_celery,
                db_session,
            )
    return


def validate_indexing_fence(
    tenant_id: str | None,
    key_bytes: bytes,
    reserved_tasks: set[str],
    r_celery: Redis,
    db_session: Session,
) -> None:
    """Checks for the error condition where an indexing fence is set but the associated celery tasks don't exist.
    This can happen if the indexing worker hard crashes or is terminated.
    Being in this bad state means the fence will never clear without help, so this function
    gives the help.

    How this works:
    1. This function renews the active signal with a 5 minute TTL under the following conditions
    1.2. When the task is seen in the redis queue
    1.3. When the task is seen in the reserved / prefetched list

    2. Externally, the active signal is renewed when:
    2.1. The fence is created
    2.2. The indexing watchdog checks the spawned task.

    3. The TTL allows us to get through the transitions on fence startup
    and when the task starts executing.

    More TTL clarification: it is seemingly impossible to exactly query Celery for
    whether a task is in the queue or currently executing.
    1. An unknown task id is always returned as state PENDING.
    2. Redis can be inspected for the task id, but the task id is gone between the time a worker receives the task
    and the time it actually starts on the worker.
    """
    # if the fence doesn't exist, there's nothing to do
    fence_key = key_bytes.decode("utf-8")
    composite_id = RedisConnector.get_id_from_fence_key(fence_key)
    if composite_id is None:
        task_logger.warning(
            f"validate_indexing_fence - could not parse composite_id from {fence_key}"
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

    # check to see if the fence/payload exists
    if not redis_connector_index.fenced:
        return

    payload = redis_connector_index.payload
    if not payload:
        return

    # OK, there's actually something for us to validate

    if payload.celery_task_id is None:
        # the fence is just barely set up.
        if redis_connector_index.active():
            return

        # it would be odd to get here as there isn't that much that can go wrong during
        # initial fence setup, but it's still worth making sure we can recover
        logger.info(
            f"validate_indexing_fence - Resetting fence in basic state without any activity: fence={fence_key}"
        )
        redis_connector_index.reset()
        return

    found = celery_find_task(
        payload.celery_task_id, OnyxCeleryQueues.CONNECTOR_INDEXING, r_celery
    )
    if found:
        # the celery task exists in the redis queue
        redis_connector_index.set_active()
        return

    if payload.celery_task_id in reserved_tasks:
        # the celery task was prefetched and is reserved within the indexing worker
        redis_connector_index.set_active()
        return

    # we may want to enable this check if using the active task list somehow isn't good enough
    # if redis_connector_index.generator_locked():
    #     logger.info(f"{payload.celery_task_id} is currently executing.")

    # if we get here, we didn't find any direct indication that the associated celery tasks exist,
    # but they still might be there due to gaps in our ability to check states during transitions
    # Checking the active signal safeguards us against these transition periods
    # (which has a duration that allows us to bridge those gaps)
    if redis_connector_index.active():
        return

    # celery tasks don't exist and the active signal has expired, possibly due to a crash. Clean it up.
    logger.warning(
        f"validate_indexing_fence - Resetting fence because no associated celery tasks were found: "
        f"index_attempt={payload.index_attempt_id} "
        f"cc_pair={cc_pair_id} "
        f"search_settings={search_settings_id} "
        f"fence={fence_key}"
    )
    if payload.index_attempt_id:
        try:
            mark_attempt_failed(
                payload.index_attempt_id,
                db_session,
                "validate_indexing_fence - Canceling index attempt due to missing celery tasks",
            )
        except Exception:
            logger.exception(
                "validate_indexing_fence - Exception while marking index attempt as failed."
            )

    redis_connector_index.reset()
    return


def _should_index(
    cc_pair: ConnectorCredentialPair,
    last_index: IndexAttempt | None,
    search_settings_instance: SearchSettings,
    search_settings_primary: bool,
    secondary_index_building: bool,
    db_session: Session,
) -> bool:
    """Checks various global settings and past indexing attempts to determine if
    we should try to start indexing the cc pair / search setting combination.

    Note that tactical checks such as preventing overlap with a currently running task
    are not handled here.

    Return True if we should try to index, False if not.
    """
    connector = cc_pair.connector

    # uncomment for debugging
    # task_logger.info(f"_should_index: "
    #                  f"cc_pair={cc_pair.id} "
    #                  f"connector={cc_pair.connector_id} "
    #                  f"refresh_freq={connector.refresh_freq}")

    # don't kick off indexing for `NOT_APPLICABLE` sources
    if connector.source == DocumentSource.NOT_APPLICABLE:
        return False

    # User can still manually create single indexing attempts via the UI for the
    # currently in use index
    if DISABLE_INDEX_UPDATE_ON_SWAP:
        if (
            search_settings_instance.status == IndexModelStatus.PRESENT
            and secondary_index_building
        ):
            return False

    # When switching over models, always index at least once
    if search_settings_instance.status == IndexModelStatus.FUTURE:
        if last_index:
            # No new index if the last index attempt succeeded
            # Once is enough. The model will never be able to swap otherwise.
            if last_index.status == IndexingStatus.SUCCESS:
                return False

            # No new index if the last index attempt is waiting to start
            if last_index.status == IndexingStatus.NOT_STARTED:
                return False

            # No new index if the last index attempt is running
            if last_index.status == IndexingStatus.IN_PROGRESS:
                return False
        else:
            if (
                connector.id == 0 or connector.source == DocumentSource.INGESTION_API
            ):  # Ingestion API
                return False
        return True

    # If the connector is paused or is the ingestion API, don't index
    # NOTE: during an embedding model switch over, the following logic
    # is bypassed by the above check for a future model
    if (
        not cc_pair.status.is_active()
        or connector.id == 0
        or connector.source == DocumentSource.INGESTION_API
    ):
        return False

    if search_settings_primary:
        if cc_pair.indexing_trigger is not None:
            # if a manual indexing trigger is on the cc pair, honor it for primary search settings
            return True

    # if no attempt has ever occurred, we should index regardless of refresh_freq
    if not last_index:
        return True

    if connector.refresh_freq is None:
        return False

    current_db_time = get_db_current_time(db_session)
    time_since_index = current_db_time - last_index.time_updated
    if time_since_index.total_seconds() < connector.refresh_freq:
        return False

    return True


def try_creating_indexing_task(
    celery_app: Celery,
    cc_pair: ConnectorCredentialPair,
    search_settings: SearchSettings,
    reindex: bool,
    db_session: Session,
    r: Redis,
    tenant_id: str | None,
) -> int | None:
    """Checks for any conditions that should block the indexing task from being
    created, then creates the task.

    Does not check for scheduling related conditions as this function
    is used to trigger indexing immediately.
    """

    LOCK_TIMEOUT = 30
    index_attempt_id: int | None = None

    # we need to serialize any attempt to trigger indexing since it can be triggered
    # either via celery beat or manually (API call)
    lock: RedisLock = r.lock(
        DANSWER_REDIS_FUNCTION_LOCK_PREFIX + "try_creating_indexing_task",
        timeout=LOCK_TIMEOUT,
    )

    acquired = lock.acquire(blocking_timeout=LOCK_TIMEOUT / 2)
    if not acquired:
        return None

    try:
        redis_connector = RedisConnector(tenant_id, cc_pair.id)
        redis_connector_index = redis_connector.new_index(search_settings.id)

        # skip if already indexing
        if redis_connector_index.fenced:
            return None

        # skip indexing if the cc_pair is deleting
        if redis_connector.delete.fenced:
            return None

        db_session.refresh(cc_pair)
        if cc_pair.status == ConnectorCredentialPairStatus.DELETING:
            return None

        # add a long running generator task to the queue
        redis_connector_index.generator_clear()

        # set a basic fence to start
        payload = RedisConnectorIndexPayload(
            index_attempt_id=None,
            started=None,
            submitted=datetime.now(timezone.utc),
            celery_task_id=None,
        )

        redis_connector_index.set_active()
        redis_connector_index.set_fence(payload)

        # create the index attempt for tracking purposes
        # code elsewhere checks for index attempts without an associated redis key
        # and cleans them up
        # therefore we must create the attempt and the task after the fence goes up
        index_attempt_id = create_index_attempt(
            cc_pair.id,
            search_settings.id,
            from_beginning=reindex,
            db_session=db_session,
        )

        custom_task_id = redis_connector_index.generate_generator_task_id()

        # when the task is sent, we have yet to finish setting up the fence
        # therefore, the task must contain code that blocks until the fence is ready
        result = celery_app.send_task(
            OnyxCeleryTask.CONNECTOR_INDEXING_PROXY_TASK,
            kwargs=dict(
                index_attempt_id=index_attempt_id,
                cc_pair_id=cc_pair.id,
                search_settings_id=search_settings.id,
                tenant_id=tenant_id,
            ),
            queue=OnyxCeleryQueues.CONNECTOR_INDEXING,
            task_id=custom_task_id,
            priority=OnyxCeleryPriority.MEDIUM,
        )
        if not result:
            raise RuntimeError("send_task for connector_indexing_proxy_task failed.")

        # now fill out the fence with the rest of the data
        redis_connector_index.set_active()

        payload.index_attempt_id = index_attempt_id
        payload.celery_task_id = result.id
        redis_connector_index.set_fence(payload)
    except Exception:
        task_logger.exception(
            f"try_creating_indexing_task - Unexpected exception: "
            f"cc_pair={cc_pair.id} "
            f"search_settings={search_settings.id}"
        )

        if index_attempt_id is not None:
            delete_index_attempt(db_session, index_attempt_id)
        redis_connector_index.set_fence(None)
        return None
    finally:
        if lock.owned():
            lock.release()

    return index_attempt_id


@shared_task(
    name=OnyxCeleryTask.CONNECTOR_INDEXING_PROXY_TASK,
    bind=True,
    acks_late=False,
    track_started=True,
)
def connector_indexing_proxy_task(
    self: Task,
    index_attempt_id: int,
    cc_pair_id: int,
    search_settings_id: int,
    tenant_id: str | None,
) -> None:
    """celery tasks are forked, but forking is unstable.
    This is a thread that proxies work to a spawned task."""

    task_logger.info(
        f"Indexing watchdog - starting: attempt={index_attempt_id} "
        f"cc_pair={cc_pair_id} "
        f"search_settings={search_settings_id} "
        f"mp_start_method={multiprocessing.get_start_method()}"
    )

    if not self.request.id:
        task_logger.error("self.request.id is None!")

    client = SimpleJobClient()

    job = client.submit(
        connector_indexing_task_wrapper,
        index_attempt_id,
        cc_pair_id,
        search_settings_id,
        tenant_id,
        global_version.is_ee_version(),
        pure=False,
    )

    if not job:
        task_logger.info(
            f"Indexing watchdog - spawn failed: attempt={index_attempt_id} "
            f"cc_pair={cc_pair_id} "
            f"search_settings={search_settings_id}"
        )
        return

    task_logger.info(
        f"Indexing watchdog - spawn succeeded: attempt={index_attempt_id} "
        f"cc_pair={cc_pair_id} "
        f"search_settings={search_settings_id}"
    )

    redis_connector = RedisConnector(tenant_id, cc_pair_id)
    redis_connector_index = redis_connector.new_index(search_settings_id)

    while True:
        sleep(5)

        # renew active signal
        redis_connector_index.set_active()

        # if the job is done, clean up and break
        if job.done():
            try:
                if job.status == "error":
                    ignore_exitcode = False

                    exit_code: int | None = None
                    if job.process:
                        exit_code = job.process.exitcode

                    # seeing odd behavior where spawned tasks usually return exit code 1 in the cloud,
                    # even though logging clearly indicates successful completion
                    # to work around this, we ignore the job error state if the completion signal is OK
                    status_int = redis_connector_index.get_completion()
                    if status_int:
                        status_enum = HTTPStatus(status_int)
                        if status_enum == HTTPStatus.OK:
                            ignore_exitcode = True

                    if not ignore_exitcode:
                        raise RuntimeError("Spawned task exceptioned.")

                    task_logger.warning(
                        "Indexing watchdog - spawned task has non-zero exit code "
                        "but completion signal is OK. Continuing...: "
                        f"attempt={index_attempt_id} "
                        f"tenant={tenant_id} "
                        f"cc_pair={cc_pair_id} "
                        f"search_settings={search_settings_id} "
                        f"exit_code={exit_code}"
                    )
            except Exception:
                task_logger.error(
                    "Indexing watchdog - spawned task exceptioned: "
                    f"attempt={index_attempt_id} "
                    f"tenant={tenant_id} "
                    f"cc_pair={cc_pair_id} "
                    f"search_settings={search_settings_id} "
                    f"exit_code={exit_code} "
                    f"error={job.exception()}"
                )

                raise
            finally:
                job.release()

            break

        # if a termination signal is detected, clean up and break
        if self.request.id and redis_connector_index.terminating(self.request.id):
            task_logger.warning(
                "Indexing watchdog - termination signal detected: "
                f"attempt={index_attempt_id} "
                f"cc_pair={cc_pair_id} "
                f"search_settings={search_settings_id}"
            )

            try:
                with get_session_with_tenant(tenant_id) as db_session:
                    mark_attempt_canceled(
                        index_attempt_id,
                        db_session,
                        "Connector termination signal detected",
                    )
            except Exception:
                # if the DB exceptions, we'll just get an unfriendly failure message
                # in the UI instead of the cancellation message
                logger.exception(
                    "Indexing watchdog - transient exception marking index attempt as canceled: "
                    f"attempt={index_attempt_id} "
                    f"tenant={tenant_id} "
                    f"cc_pair={cc_pair_id} "
                    f"search_settings={search_settings_id}"
                )

            job.cancel()
            break

        # if the spawned task is still running, restart the check once again
        # if the index attempt is not in a finished status
        try:
            with get_session_with_tenant(tenant_id) as db_session:
                index_attempt = get_index_attempt(
                    db_session=db_session, index_attempt_id=index_attempt_id
                )

                if not index_attempt:
                    continue

                if not index_attempt.is_finished():
                    continue
        except Exception:
            # if the DB exceptioned, just restart the check.
            # polling the index attempt status doesn't need to be strongly consistent
            logger.exception(
                "Indexing watchdog - transient exception looking up index attempt: "
                f"attempt={index_attempt_id} "
                f"tenant={tenant_id} "
                f"cc_pair={cc_pair_id} "
                f"search_settings={search_settings_id}"
            )
            continue

    task_logger.info(
        f"Indexing watchdog - finished: attempt={index_attempt_id} "
        f"cc_pair={cc_pair_id} "
        f"search_settings={search_settings_id}"
    )
    return


def connector_indexing_task_wrapper(
    index_attempt_id: int,
    cc_pair_id: int,
    search_settings_id: int,
    tenant_id: str | None,
    is_ee: bool,
) -> int | None:
    """Just wraps connector_indexing_task so we can log any exceptions before
    re-raising it."""
    result: int | None = None

    try:
        result = connector_indexing_task(
            index_attempt_id,
            cc_pair_id,
            search_settings_id,
            tenant_id,
            is_ee,
        )
    except Exception:
        logger.exception(
            f"connector_indexing_task exceptioned: "
            f"tenant={tenant_id} "
            f"index_attempt={index_attempt_id} "
            f"cc_pair={cc_pair_id} "
            f"search_settings={search_settings_id}"
        )

        # There is a cloud related bug outside of our code
        # where spawned tasks return with an exit code of 1.
        # Unfortunately, exceptions also return with an exit code of 1,
        # so just raising an exception isn't informative
        # Exiting with 255 makes it possible to distinguish between normal exits
        # and exceptions.
        sys.exit(255)

    return result


def connector_indexing_task(
    index_attempt_id: int,
    cc_pair_id: int,
    search_settings_id: int,
    tenant_id: str | None,
    is_ee: bool,
) -> int | None:
    """Indexing task. For a cc pair, this task pulls all document IDs from the source
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

    attempt_found = False
    n_final_progress: int | None = None

    redis_connector = RedisConnector(tenant_id, cc_pair_id)
    redis_connector_index = redis_connector.new_index(search_settings_id)

    r = get_redis_client(tenant_id=tenant_id)

    if redis_connector.delete.fenced:
        raise RuntimeError(
            f"Indexing will not start because connector deletion is in progress: "
            f"attempt={index_attempt_id} "
            f"cc_pair={cc_pair_id} "
            f"fence={redis_connector.delete.fence_key}"
        )

    if redis_connector.stop.fenced:
        raise RuntimeError(
            f"Indexing will not start because a connector stop signal was detected: "
            f"attempt={index_attempt_id} "
            f"cc_pair={cc_pair_id} "
            f"fence={redis_connector.stop.fence_key}"
        )

    # this wait is needed to avoid a race condition where
    # the primary worker sends the task and it is immediately executed
    # before the primary worker can finalize the fence
    start = time.monotonic()
    while True:
        if time.monotonic() - start > CELERY_TASK_WAIT_FOR_FENCE_TIMEOUT:
            raise ValueError(
                f"connector_indexing_task - timed out waiting for fence to be ready: "
                f"fence={redis_connector.permissions.fence_key}"
            )

        if not redis_connector_index.fenced:  # The fence must exist
            raise ValueError(
                f"connector_indexing_task - fence not found: fence={redis_connector_index.fence_key}"
            )

        payload = redis_connector_index.payload  # The payload must exist
        if not payload:
            raise ValueError("connector_indexing_task: payload invalid or not found")

        if payload.index_attempt_id is None or payload.celery_task_id is None:
            logger.info(
                f"connector_indexing_task - Waiting for fence: fence={redis_connector_index.fence_key}"
            )
            sleep(1)
            continue

        if payload.index_attempt_id != index_attempt_id:
            raise ValueError(
                f"connector_indexing_task - id mismatch. Task may be left over from previous run.: "
                f"task_index_attempt={index_attempt_id} "
                f"payload_index_attempt={payload.index_attempt_id}"
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
        return None

    payload.started = datetime.now(timezone.utc)
    redis_connector_index.set_fence(payload)

    try:
        with get_session_with_tenant(tenant_id) as db_session:
            attempt = get_index_attempt(db_session, index_attempt_id)
            if not attempt:
                raise ValueError(
                    f"Index attempt not found: index_attempt={index_attempt_id}"
                )
            attempt_found = True

            cc_pair = get_connector_credential_pair_from_id(
                db_session=db_session,
                cc_pair_id=cc_pair_id,
            )

            if not cc_pair:
                raise ValueError(f"cc_pair not found: cc_pair={cc_pair_id}")

            if not cc_pair.connector:
                raise ValueError(
                    f"Connector not found: cc_pair={cc_pair_id} connector={cc_pair.connector_id}"
                )

            if not cc_pair.credential:
                raise ValueError(
                    f"Credential not found: cc_pair={cc_pair_id} credential={cc_pair.credential_id}"
                )

        # define a callback class
        callback = IndexingCallback(
            os.getppid(),
            redis_connector.stop.fence_key,
            redis_connector_index.generator_progress_key,
            lock,
            r,
        )

        logger.info(
            f"Indexing spawned task running entrypoint: attempt={index_attempt_id} "
            f"tenant={tenant_id} "
            f"cc_pair={cc_pair_id} "
            f"search_settings={search_settings_id}"
        )

        # This is where the heavy/real work happens
        run_indexing_entrypoint(
            index_attempt_id,
            tenant_id,
            cc_pair_id,
            is_ee,
            callback=callback,
        )

        # get back the total number of indexed docs and return it
        n_final_progress = redis_connector_index.get_progress()
        redis_connector_index.set_generator_complete(HTTPStatus.OK.value)
    except Exception as e:
        logger.exception(
            f"Indexing spawned task failed: attempt={index_attempt_id} "
            f"tenant={tenant_id} "
            f"cc_pair={cc_pair_id} "
            f"search_settings={search_settings_id}"
        )
        if attempt_found:
            try:
                with get_session_with_tenant(tenant_id) as db_session:
                    mark_attempt_failed(
                        index_attempt_id, db_session, failure_reason=str(e)
                    )
            except Exception:
                logger.exception(
                    "Indexing watchdog - transient exception looking up index attempt: "
                    f"attempt={index_attempt_id} "
                    f"tenant={tenant_id} "
                    f"cc_pair={cc_pair_id} "
                    f"search_settings={search_settings_id}"
                )

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
