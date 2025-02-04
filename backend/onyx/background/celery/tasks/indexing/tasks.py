import multiprocessing
import os
import sys
import time
from datetime import datetime
from datetime import timezone
from http import HTTPStatus
from time import sleep

import sentry_sdk
from celery import shared_task
from celery import Task
from celery.exceptions import SoftTimeLimitExceeded
from redis import Redis
from redis.lock import Lock as RedisLock

from onyx.background.celery.apps.app_base import task_logger
from onyx.background.celery.tasks.beat_schedule import BEAT_EXPIRES_DEFAULT
from onyx.background.celery.tasks.indexing.utils import _should_index
from onyx.background.celery.tasks.indexing.utils import get_unfenced_index_attempt_ids
from onyx.background.celery.tasks.indexing.utils import IndexingCallback
from onyx.background.celery.tasks.indexing.utils import try_creating_indexing_task
from onyx.background.celery.tasks.indexing.utils import validate_indexing_fences
from onyx.background.indexing.job_client import SimpleJobClient
from onyx.background.indexing.run_indexing import run_indexing_entrypoint
from onyx.configs.constants import CELERY_GENERIC_BEAT_LOCK_TIMEOUT
from onyx.configs.constants import CELERY_INDEXING_LOCK_TIMEOUT
from onyx.configs.constants import CELERY_TASK_WAIT_FOR_FENCE_TIMEOUT
from onyx.configs.constants import ONYX_CLOUD_TENANT_ID
from onyx.configs.constants import OnyxCeleryPriority
from onyx.configs.constants import OnyxCeleryTask
from onyx.configs.constants import OnyxRedisLocks
from onyx.configs.constants import OnyxRedisSignals
from onyx.db.connector import mark_ccpair_with_indexing_trigger
from onyx.db.connector_credential_pair import fetch_connector_credential_pairs
from onyx.db.connector_credential_pair import get_connector_credential_pair_from_id
from onyx.db.engine import get_all_tenant_ids
from onyx.db.engine import get_session_with_tenant
from onyx.db.enums import IndexingMode
from onyx.db.index_attempt import get_index_attempt
from onyx.db.index_attempt import get_last_attempt_for_cc_pair
from onyx.db.index_attempt import mark_attempt_canceled
from onyx.db.index_attempt import mark_attempt_failed
from onyx.db.models import SearchSettings
from onyx.db.search_settings import get_active_search_settings
from onyx.db.search_settings import get_current_search_settings
from onyx.db.swap_index import check_index_swap
from onyx.natural_language_processing.search_nlp_models import EmbeddingModel
from onyx.natural_language_processing.search_nlp_models import warm_up_bi_encoder
from onyx.redis.redis_connector import RedisConnector
from onyx.redis.redis_pool import get_redis_client
from onyx.redis.redis_pool import redis_lock_dump
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import global_version
from shared_configs.configs import INDEXING_MODEL_SERVER_HOST
from shared_configs.configs import INDEXING_MODEL_SERVER_PORT
from shared_configs.configs import MULTI_TENANT
from shared_configs.configs import SENTRY_DSN

logger = setup_logger()


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
        timeout=CELERY_GENERIC_BEAT_LOCK_TIMEOUT,
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
    task_logger.info(f"check_for_indexing finished: elapsed={time_elapsed:.2f}")
    return tasks_created


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
    """celery tasks are forked, but forking is unstable.  This proxies work to a spawned task."""
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


@shared_task(
    name=OnyxCeleryTask.CLOUD_CHECK_FOR_INDEXING,
    trail=False,
    bind=True,
)
def cloud_check_for_indexing(self: Task) -> bool | None:
    """a lightweight task used to kick off individual check tasks for each tenant."""
    time_start = time.monotonic()

    redis_client = get_redis_client(tenant_id=ONYX_CLOUD_TENANT_ID)

    lock_beat: RedisLock = redis_client.lock(
        OnyxRedisLocks.CLOUD_CHECK_INDEXING_BEAT_LOCK,
        timeout=CELERY_GENERIC_BEAT_LOCK_TIMEOUT,
    )

    # these tasks should never overlap
    if not lock_beat.acquire(blocking=False):
        return None

    last_lock_time = time.monotonic()

    try:
        tenant_ids = get_all_tenant_ids()
        for tenant_id in tenant_ids:
            current_time = time.monotonic()
            if current_time - last_lock_time >= (CELERY_GENERIC_BEAT_LOCK_TIMEOUT / 4):
                lock_beat.reacquire()
                last_lock_time = current_time

            self.app.send_task(
                OnyxCeleryTask.CHECK_FOR_INDEXING,
                kwargs=dict(
                    tenant_id=tenant_id,
                ),
                priority=OnyxCeleryPriority.HIGH,
                expires=BEAT_EXPIRES_DEFAULT,
            )
    except SoftTimeLimitExceeded:
        task_logger.info(
            "Soft time limit exceeded, task is being terminated gracefully."
        )
    except Exception:
        task_logger.exception("Unexpected exception during cloud indexing check")
    finally:
        if lock_beat.owned():
            lock_beat.release()
        else:
            task_logger.error("cloud_check_for_indexing - Lock not owned on completion")
            redis_lock_dump(lock_beat, redis_client)

    time_elapsed = time.monotonic() - time_start
    task_logger.info(
        f"cloud_check_for_indexing finished: num_tenants={len(tenant_ids)} elapsed={time_elapsed:.2f}"
    )
    return True
