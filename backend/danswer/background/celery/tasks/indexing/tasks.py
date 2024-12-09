from datetime import datetime
from datetime import timezone
from http import HTTPStatus
from time import sleep

import sentry_sdk
from celery import Celery
from celery import shared_task
from celery import Task
from celery.exceptions import SoftTimeLimitExceeded
from redis import Redis
from redis.exceptions import LockError
from redis.lock import Lock as RedisLock
from sqlalchemy.orm import Session

from danswer.background.celery.apps.app_base import task_logger
from danswer.background.indexing.job_client import SimpleJobClient
from danswer.background.indexing.run_indexing import run_indexing_entrypoint
from danswer.configs.app_configs import DISABLE_INDEX_UPDATE_ON_SWAP
from danswer.configs.constants import CELERY_INDEXING_LOCK_TIMEOUT
from danswer.configs.constants import CELERY_VESPA_SYNC_BEAT_LOCK_TIMEOUT
from danswer.configs.constants import DANSWER_REDIS_FUNCTION_LOCK_PREFIX
from danswer.configs.constants import DanswerCeleryPriority
from danswer.configs.constants import DanswerCeleryQueues
from danswer.configs.constants import DanswerRedisLocks
from danswer.configs.constants import DocumentSource
from danswer.db.connector import mark_ccpair_with_indexing_trigger
from danswer.db.connector_credential_pair import fetch_connector_credential_pairs
from danswer.db.connector_credential_pair import get_connector_credential_pair_from_id
from danswer.db.engine import get_db_current_time
from danswer.db.engine import get_session_with_tenant
from danswer.db.enums import ConnectorCredentialPairStatus
from danswer.db.enums import IndexingMode
from danswer.db.enums import IndexingStatus
from danswer.db.enums import IndexModelStatus
from danswer.db.index_attempt import create_index_attempt
from danswer.db.index_attempt import delete_index_attempt
from danswer.db.index_attempt import get_all_index_attempts_by_status
from danswer.db.index_attempt import get_index_attempt
from danswer.db.index_attempt import get_last_attempt_for_cc_pair
from danswer.db.index_attempt import mark_attempt_failed
from danswer.db.models import ConnectorCredentialPair
from danswer.db.models import IndexAttempt
from danswer.db.models import SearchSettings
from danswer.db.search_settings import get_current_search_settings
from danswer.db.search_settings import get_secondary_search_settings
from danswer.db.swap_index import check_index_swap
from danswer.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from danswer.natural_language_processing.search_nlp_models import EmbeddingModel
from danswer.natural_language_processing.search_nlp_models import warm_up_bi_encoder
from danswer.redis.redis_connector import RedisConnector
from danswer.redis.redis_connector_index import RedisConnectorIndex
from danswer.redis.redis_connector_index import RedisConnectorIndexPayload
from danswer.redis.redis_pool import get_redis_client
from danswer.utils.logger import setup_logger
from danswer.utils.variable_functionality import global_version
from shared_configs.configs import INDEXING_MODEL_SERVER_HOST
from shared_configs.configs import INDEXING_MODEL_SERVER_PORT
from shared_configs.configs import MULTI_TENANT
from shared_configs.configs import SENTRY_DSN

logger = setup_logger()


class IndexingCallback(IndexingHeartbeatInterface):
    def __init__(
        self,
        stop_key: str,
        generator_progress_key: str,
        redis_lock: RedisLock,
        redis_client: Redis,
    ):
        super().__init__()
        self.redis_lock: RedisLock = redis_lock
        self.stop_key: str = stop_key
        self.generator_progress_key: str = generator_progress_key
        self.redis_client = redis_client
        self.started: datetime = datetime.now(timezone.utc)
        self.redis_lock.reacquire()

        self.last_tag: str = "IndexingCallback.__init__"
        self.last_lock_reacquire: datetime = datetime.now(timezone.utc)

    def should_stop(self) -> bool:
        if self.redis_client.exists(self.stop_key):
            return True
        return False

    def progress(self, tag: str, amount: int) -> None:
        try:
            self.redis_lock.reacquire()
            self.last_tag = tag
            self.last_lock_reacquire = datetime.now(timezone.utc)
        except LockError:
            logger.exception(
                f"IndexingCallback - lock.reacquire exceptioned. "
                f"lock_timeout={self.redis_lock.timeout} "
                f"start={self.started} "
                f"last_tag={self.last_tag} "
                f"last_reacquired={self.last_lock_reacquire} "
                f"now={datetime.now(timezone.utc)}"
            )
            raise

        self.redis_client.incrby(self.generator_progress_key, amount)


def get_unfenced_index_attempt_ids(db_session: Session, r: Redis) -> list[int]:
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
    name="check_for_indexing",
    soft_time_limit=300,
    bind=True,
)
def check_for_indexing(self: Task, *, tenant_id: str | None) -> int | None:
    tasks_created = 0
    locked = False
    r = get_redis_client(tenant_id=tenant_id)

    lock_beat: RedisLock = r.lock(
        DanswerRedisLocks.CHECK_INDEXING_BEAT_LOCK,
        timeout=CELERY_VESPA_SYNC_BEAT_LOCK_TIMEOUT,
    )

    try:
        # these tasks should never overlap
        if not lock_beat.acquire(blocking=False):
            return None

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
        cc_pair_ids: list[int] = []
        with get_session_with_tenant(tenant_id) as db_session:
            lock_beat.reacquire()
            cc_pairs = fetch_connector_credential_pairs(db_session)
            for cc_pair_entry in cc_pairs:
                cc_pair_ids.append(cc_pair_entry.id)

        # kick off index attempts
        for cc_pair_id in cc_pair_ids:
            lock_beat.reacquire()

            redis_connector = RedisConnector(tenant_id, cc_pair_id)
            with get_session_with_tenant(tenant_id) as db_session:
                # Get the primary search settings
                primary_search_settings = get_current_search_settings(db_session)
                search_settings = [primary_search_settings]

                # Check for secondary search settings
                secondary_search_settings = get_secondary_search_settings(db_session)
                if secondary_search_settings is not None:
                    # If secondary settings exist, add them to the list
                    search_settings.append(secondary_search_settings)

                for search_settings_instance in search_settings:
                    redis_connector_index = redis_connector.new_index(
                        search_settings_instance.id
                    )
                    if redis_connector_index.fenced:
                        continue

                    cc_pair = get_connector_credential_pair_from_id(
                        cc_pair_id, db_session
                    )
                    if not cc_pair:
                        continue

                    last_attempt = get_last_attempt_for_cc_pair(
                        cc_pair.id, search_settings_instance.id, db_session
                    )

                    search_settings_primary = False
                    if search_settings_instance.id == primary_search_settings.id:
                        search_settings_primary = True

                    if not _should_index(
                        cc_pair=cc_pair,
                        last_index=last_attempt,
                        search_settings_instance=search_settings_instance,
                        search_settings_primary=search_settings_primary,
                        secondary_index_building=len(search_settings) > 1,
                        db_session=db_session,
                    ):
                        continue

                    reindex = False
                    if search_settings_instance.id == primary_search_settings.id:
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

                    # using a task queue and only allowing one task per cc_pair/search_setting
                    # prevents us from starving out certain attempts
                    attempt_id = try_creating_indexing_task(
                        self.app,
                        cc_pair,
                        search_settings_instance,
                        reindex,
                        db_session,
                        r,
                        tenant_id,
                    )
                    if attempt_id:
                        task_logger.info(
                            f"Connector indexing queued: "
                            f"index_attempt={attempt_id} "
                            f"cc_pair={cc_pair.id} "
                            f"search_settings={search_settings_instance.id} "
                        )
                        tasks_created += 1

        # Fail any index attempts in the DB that don't have fences
        # This shouldn't ever happen!
        with get_session_with_tenant(tenant_id) as db_session:
            unfenced_attempt_ids = get_unfenced_index_attempt_ids(db_session, r)
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
    except SoftTimeLimitExceeded:
        task_logger.info(
            "Soft time limit exceeded, task is being terminated gracefully."
        )
    except Exception:
        task_logger.exception(f"Unexpected exception: tenant={tenant_id}")
    finally:
        if locked:
            if lock_beat.owned():
                lock_beat.release()
            else:
                task_logger.error(
                    "check_for_indexing - Lock not owned on completion: "
                    f"tenant={tenant_id}"
                )

    return tasks_created


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
            "connector_indexing_proxy_task",
            kwargs=dict(
                index_attempt_id=index_attempt_id,
                cc_pair_id=cc_pair.id,
                search_settings_id=search_settings.id,
                tenant_id=tenant_id,
            ),
            queue=DanswerCeleryQueues.CONNECTOR_INDEXING,
            task_id=custom_task_id,
            priority=DanswerCeleryPriority.MEDIUM,
        )
        if not result:
            raise RuntimeError("send_task for connector_indexing_proxy_task failed.")

        # now fill out the fence with the rest of the data
        payload.index_attempt_id = index_attempt_id
        payload.celery_task_id = result.id
        redis_connector_index.set_fence(payload)
    except Exception:
        task_logger.exception(
            f"try_creating_indexing_task - Unexpected exception: "
            f"tenant={tenant_id} "
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


@shared_task(name="connector_indexing_proxy_task", acks_late=False, track_started=True)
def connector_indexing_proxy_task(
    index_attempt_id: int,
    cc_pair_id: int,
    search_settings_id: int,
    tenant_id: str | None,
) -> None:
    """celery tasks are forked, but forking is unstable.  This proxies work to a spawned task."""
    task_logger.info(
        f"Indexing watchdog - starting: attempt={index_attempt_id} "
        f"tenant={tenant_id} "
        f"cc_pair={cc_pair_id} "
        f"search_settings={search_settings_id}"
    )
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
            f"tenant={tenant_id} "
            f"cc_pair={cc_pair_id} "
            f"search_settings={search_settings_id}"
        )
        return

    task_logger.info(
        f"Indexing watchdog - spawn succeeded: attempt={index_attempt_id} "
        f"tenant={tenant_id} "
        f"cc_pair={cc_pair_id} "
        f"search_settings={search_settings_id}"
    )

    while True:
        sleep(10)

        # do nothing for ongoing jobs that haven't been stopped
        if not job.done():
            with get_session_with_tenant(tenant_id) as db_session:
                index_attempt = get_index_attempt(
                    db_session=db_session, index_attempt_id=index_attempt_id
                )

                if not index_attempt:
                    continue

                if not index_attempt.is_finished():
                    continue

        if job.status == "error":
            task_logger.error(
                f"Indexing watchdog - spawned task exceptioned: "
                f"attempt={index_attempt_id} "
                f"tenant={tenant_id} "
                f"cc_pair={cc_pair_id} "
                f"search_settings={search_settings_id} "
                f"error={job.exception()}"
            )

        job.release()
        break

    task_logger.info(
        f"Indexing watchdog - finished: attempt={index_attempt_id} "
        f"tenant={tenant_id} "
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
    except:
        logger.exception(
            f"connector_indexing_task exceptioned: "
            f"tenant={tenant_id} "
            f"index_attempt={index_attempt_id} "
            f"cc_pair={cc_pair_id} "
            f"search_settings={search_settings_id}"
        )
        raise

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

    while True:
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

    lock: RedisLock = r.lock(
        redis_connector_index.generator_lock_key,
        timeout=CELERY_INDEXING_LOCK_TIMEOUT,
    )

    acquired = lock.acquire(blocking=False)
    if not acquired:
        logger.warning(
            f"Indexing task already running, exiting...: "
            f"index_attempt={index_attempt_id} cc_pair={cc_pair_id} search_settings={search_settings_id}"
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
                cc_pair_id=cc_pair_id,
                db_session=db_session,
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
            with get_session_with_tenant(tenant_id) as db_session:
                mark_attempt_failed(index_attempt_id, db_session, failure_reason=str(e))

        raise e
    finally:
        if lock.owned():
            lock.release()

    logger.info(
        f"Indexing spawned task finished: attempt={index_attempt_id} "
        f"tenant={tenant_id} "
        f"cc_pair={cc_pair_id} "
        f"search_settings={search_settings_id}"
    )
    return n_final_progress
