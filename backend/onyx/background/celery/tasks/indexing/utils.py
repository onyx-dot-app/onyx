import time
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import cast

import redis
from celery import Celery
from redis import Redis
from redis.exceptions import LockError
from redis.lock import Lock as RedisLock
from sqlalchemy.orm import Session

from onyx.background.celery.apps.app_base import task_logger
from onyx.background.celery.celery_redis import celery_find_task
from onyx.background.celery.celery_redis import celery_get_unacked_task_ids
from onyx.configs.app_configs import DISABLE_INDEX_UPDATE_ON_SWAP
from onyx.configs.constants import CELERY_GENERIC_BEAT_LOCK_TIMEOUT
from onyx.configs.constants import DANSWER_REDIS_FUNCTION_LOCK_PREFIX
from onyx.configs.constants import DocumentSource
from onyx.configs.constants import OnyxCeleryPriority
from onyx.configs.constants import OnyxCeleryQueues
from onyx.configs.constants import OnyxCeleryTask
from onyx.configs.constants import OnyxRedisConstants
from onyx.db.engine import get_db_current_time
from onyx.db.engine import get_session_with_current_tenant
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.enums import IndexingStatus
from onyx.db.enums import IndexModelStatus
from onyx.db.index_attempt import create_index_attempt
from onyx.db.index_attempt import delete_index_attempt
from onyx.db.index_attempt import get_all_index_attempts_by_status
from onyx.db.index_attempt import get_index_attempt
from onyx.db.index_attempt import mark_attempt_failed
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import IndexAttempt
from onyx.db.models import SearchSettings
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.redis.redis_connector import RedisConnector
from onyx.redis.redis_connector_index import RedisConnectorIndex
from onyx.redis.redis_connector_index import RedisConnectorIndexPayload
from onyx.redis.redis_pool import redis_lock_dump
from onyx.utils.logger import setup_logger

logger = setup_logger()


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


class IndexingCallbackBase(IndexingHeartbeatInterface):
    PARENT_CHECK_INTERVAL = 60

    def __init__(
        self,
        parent_pid: int,
        redis_connector: RedisConnector,
        redis_lock: RedisLock,
        redis_client: Redis,
    ):
        super().__init__()
        self.parent_pid = parent_pid
        self.redis_connector: RedisConnector = redis_connector
        self.redis_lock: RedisLock = redis_lock
        self.redis_client = redis_client
        self.started: datetime = datetime.now(timezone.utc)
        self.redis_lock.reacquire()

        self.last_tag: str = f"{self.__class__.__name__}.__init__"
        self.last_lock_reacquire: datetime = datetime.now(timezone.utc)
        self.last_lock_monotonic = time.monotonic()

        self.last_parent_check = time.monotonic()

    def should_stop(self) -> bool:
        if self.redis_connector.stop.fenced:
            return True

        return False

    def progress(self, tag: str, amount: int) -> None:
        # rkuo: this shouldn't be necessary yet because we spawn the process this runs inside
        # with daemon=True. It seems likely some indexing tasks will need to spawn other processes
        # eventually, which daemon=True prevents, so leave this code in until we're ready to test it.

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
                CELERY_GENERIC_BEAT_LOCK_TIMEOUT / 4
            ):
                self.redis_lock.reacquire()
                self.last_lock_reacquire = datetime.now(timezone.utc)
                self.last_lock_monotonic = time.monotonic()

            self.last_tag = tag
        except LockError:
            logger.exception(
                f"{self.__class__.__name__} - lock.reacquire exceptioned: "
                f"lock_timeout={self.redis_lock.timeout} "
                f"start={self.started} "
                f"last_tag={self.last_tag} "
                f"last_reacquired={self.last_lock_reacquire} "
                f"now={datetime.now(timezone.utc)}"
            )

            redis_lock_dump(self.redis_lock, self.redis_client)
            raise


class IndexingCallback(IndexingCallbackBase):
    def __init__(
        self,
        parent_pid: int,
        redis_connector: RedisConnector,
        redis_lock: RedisLock,
        redis_client: Redis,
        redis_connector_index: RedisConnectorIndex,
    ):
        super().__init__(parent_pid, redis_connector, redis_lock, redis_client)

        self.redis_connector_index: RedisConnectorIndex = redis_connector_index

    def progress(self, tag: str, amount: int) -> None:
        self.redis_connector_index.set_active()
        self.redis_connector_index.set_connector_active()
        super().progress(tag, amount)
        self.redis_client.incrby(
            self.redis_connector_index.generator_progress_key, amount
        )


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
            f"validate_indexing_fence - "
            f"Resetting fence in basic state without any activity: fence={fence_key}"
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
                "validate_indexing_fence - Canceling index attempt due to missing celery tasks: "
                f"index_attempt={payload.index_attempt_id}",
            )
        except Exception:
            logger.exception(
                "validate_indexing_fence - Exception while marking index attempt as failed: "
                f"index_attempt={payload.index_attempt_id}",
            )

    redis_connector_index.reset()
    return


def validate_indexing_fences(
    tenant_id: str | None,
    r_replica: Redis,
    r_celery: Redis,
    lock_beat: RedisLock,
) -> None:
    """Validates all indexing fences for this tenant ... aka makes sure
    indexing tasks sent to celery are still in flight.
    """
    reserved_indexing_tasks = celery_get_unacked_task_ids(
        OnyxCeleryQueues.CONNECTOR_INDEXING, r_celery
    )

    # Use replica for this because the worst thing that happens
    # is that we don't run the validation on this pass
    keys = cast(set[Any], r_replica.smembers(OnyxRedisConstants.ACTIVE_FENCES))
    for key in keys:
        key_bytes = cast(bytes, key)
        key_str = key_bytes.decode("utf-8")
        if not key_str.startswith(RedisConnectorIndex.FENCE_PREFIX):
            continue

        with get_session_with_current_tenant() as db_session:
            validate_indexing_fence(
                tenant_id,
                key_bytes,
                reserved_indexing_tasks,
                r_celery,
                db_session,
            )

        lock_beat.reacquire()

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

    redis_connector_index: RedisConnectorIndex
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
