import time
from datetime import datetime
from datetime import timezone
from uuid import uuid4

from celery import Celery
from redis import Redis
from redis.exceptions import LockError
from redis.lock import Lock as RedisLock
from sqlalchemy.orm import Session

from onyx.background.celery.apps.app_base import task_logger
from onyx.configs.app_configs import DISABLE_INDEX_UPDATE_ON_SWAP
from onyx.configs.constants import CELERY_GENERIC_BEAT_LOCK_TIMEOUT
from onyx.configs.constants import DANSWER_REDIS_FUNCTION_LOCK_PREFIX
from onyx.configs.constants import DocumentSource
from onyx.configs.constants import OnyxCeleryPriority
from onyx.configs.constants import OnyxCeleryQueues
from onyx.configs.constants import OnyxCeleryTask
from onyx.db.connector_credential_pair import get_connector_credential_pair_from_id
from onyx.db.engine.time_utils import get_db_current_time
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.enums import IndexingStatus
from onyx.db.enums import IndexModelStatus
from onyx.db.index_attempt import get_last_attempt_for_cc_pair
from onyx.db.index_attempt import get_recent_attempts_for_cc_pair
from onyx.db.index_attempt import mark_attempt_failed
from onyx.db.indexing_coordination import IndexingCoordination
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import SearchSettings
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.redis.redis_connector import RedisConnector
from onyx.redis.redis_pool import redis_lock_dump
from onyx.utils.logger import setup_logger

logger = setup_logger()

NUM_REPEAT_ERRORS_BEFORE_REPEATED_ERROR_STATE = 5


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
        # Check if the associated indexing attempt has been cancelled
        # TODO: Pass index_attempt_id to the callback and check cancellation using the db
        return bool(self.redis_connector.stop.fenced)

    def progress(self, tag: str, amount: int) -> None:
        """Amount isn't used yet."""

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


# NOTE: we're in the process of removing all fences from indexing; this will
# eventually no longer be used. For now, it is used only for connector pausing.
class IndexingCallback(IndexingHeartbeatInterface):
    def __init__(
        self,
        redis_connector: RedisConnector,
    ):
        self.redis_connector = redis_connector

    def should_stop(self) -> bool:
        # Check if the associated indexing attempt has been cancelled
        # TODO: Pass index_attempt_id to the callback and check cancellation using the db
        return bool(self.redis_connector.stop.fenced)

    # included to satisfy old interface
    def progress(self, tag: str, amount: int) -> None:
        pass


# NOTE: The validate_indexing_fence and validate_indexing_fences functions have been removed
# as they are no longer needed with database-based coordination. The new validation is
# handled by validate_active_indexing_attempts in the main indexing tasks module.


def is_in_repeated_error_state(
    cc_pair_id: int, search_settings_id: int, db_session: Session
) -> bool:
    """Checks if the cc pair / search setting combination is in a repeated error state."""
    cc_pair = get_connector_credential_pair_from_id(
        db_session=db_session,
        cc_pair_id=cc_pair_id,
    )
    if not cc_pair:
        raise RuntimeError(
            f"is_in_repeated_error_state - could not find cc_pair with id={cc_pair_id}"
        )

    # if the connector doesn't have a refresh_freq, a single failed attempt is enough
    number_of_failed_attempts_in_a_row_needed = (
        NUM_REPEAT_ERRORS_BEFORE_REPEATED_ERROR_STATE
        if cc_pair.connector.refresh_freq is not None
        else 1
    )

    most_recent_index_attempts = get_recent_attempts_for_cc_pair(
        cc_pair_id=cc_pair_id,
        search_settings_id=search_settings_id,
        limit=number_of_failed_attempts_in_a_row_needed,
        db_session=db_session,
    )
    return len(
        most_recent_index_attempts
    ) >= number_of_failed_attempts_in_a_row_needed and all(
        attempt.status == IndexingStatus.FAILED
        for attempt in most_recent_index_attempts
    )


def should_index(
    cc_pair: ConnectorCredentialPair,
    search_settings_instance: SearchSettings,
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
    last_index_attempt = get_last_attempt_for_cc_pair(
        cc_pair_id=cc_pair.id,
        search_settings_id=search_settings_instance.id,
        db_session=db_session,
    )
    all_recent_errored = is_in_repeated_error_state(
        cc_pair_id=cc_pair.id,
        search_settings_id=search_settings_instance.id,
        db_session=db_session,
    )

    # uncomment for debugging
    # task_logger.debug(
    #     f"_should_index: "
    #     f"cc_pair={cc_pair.id} "
    #     f"connector={cc_pair.connector_id} "
    #     f"refresh_freq={connector.refresh_freq}"
    # )

    # don't kick off indexing for `NOT_APPLICABLE` sources
    if connector.source == DocumentSource.NOT_APPLICABLE:
        # print(f"Not indexing cc_pair={cc_pair.id}: NOT_APPLICABLE source")
        return False

    # User can still manually create single indexing attempts via the UI for the
    # currently in use index
    if DISABLE_INDEX_UPDATE_ON_SWAP:
        if (
            search_settings_instance.status == IndexModelStatus.PRESENT
            and secondary_index_building
        ):
            # print(
            #     f"Not indexing cc_pair={cc_pair.id}: DISABLE_INDEX_UPDATE_ON_SWAP is True and secondary index building"
            # )
            return False

    # When switching over models, always index at least once
    if search_settings_instance.status == IndexModelStatus.FUTURE:
        if last_index_attempt:
            # No new index if the last index attempt succeeded
            # Once is enough. The model will never be able to swap otherwise.
            if last_index_attempt.status == IndexingStatus.SUCCESS:
                # print(
                #     f"Not indexing cc_pair={cc_pair.id}: FUTURE model with successful last index attempt={last_index.id}"
                # )
                return False

            # No new index if the last index attempt is waiting to start
            if last_index_attempt.status == IndexingStatus.NOT_STARTED:
                # print(
                #     f"Not indexing cc_pair={cc_pair.id}: FUTURE model with NOT_STARTED last index attempt={last_index.id}"
                # )
                return False

            # No new index if the last index attempt is running
            if last_index_attempt.status == IndexingStatus.IN_PROGRESS:
                # print(
                #     f"Not indexing cc_pair={cc_pair.id}: FUTURE model with IN_PROGRESS last index attempt={last_index.id}"
                # )
                return False
        else:
            if (
                connector.id == 0 or connector.source == DocumentSource.INGESTION_API
            ):  # Ingestion API
                # print(
                #     f"Not indexing cc_pair={cc_pair.id}: FUTURE model with Ingestion API source"
                # )
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
        # print(
        #     f"Not indexing cc_pair={cc_pair.id}: Connector is paused or is Ingestion API"
        # )
        return False

    if search_settings_instance.status.is_current():
        if cc_pair.indexing_trigger is not None:
            # if a manual indexing trigger is on the cc pair, honor it for live search settings
            return True

    # if no attempt has ever occurred, we should index regardless of refresh_freq
    if not last_index_attempt:
        return True

    if connector.refresh_freq is None:
        # print(f"Not indexing cc_pair={cc_pair.id}: refresh_freq is None")
        return False

    # if in the "initial" phase, we should always try and kick-off indexing
    # as soon as possible if there is no ongoing attempt. In other words,
    # no delay UNLESS we're repeatedly failing to index.
    if (
        cc_pair.status == ConnectorCredentialPairStatus.INITIAL_INDEXING
        and not all_recent_errored
    ):
        return True

    current_db_time = get_db_current_time(db_session)
    time_since_index = current_db_time - last_index_attempt.time_updated
    if time_since_index.total_seconds() < connector.refresh_freq:
        # print(
        #     f"Not indexing cc_pair={cc_pair.id}: Last index attempt={last_index_attempt.id} "
        #     f"too recent ({time_since_index.total_seconds()}s < {connector.refresh_freq}s)"
        # )
        return False

    return True


def try_creating_docfetching_task(
    celery_app: Celery,
    cc_pair: ConnectorCredentialPair,
    search_settings: SearchSettings,
    reindex: bool,
    db_session: Session,
    r: Redis,
    tenant_id: str,
) -> int | None:
    """Checks for any conditions that should block the indexing task from being
    created, then creates the task.

    Does not check for scheduling related conditions as this function
    is used to trigger indexing immediately.

    Now uses database-based coordination instead of Redis fencing.
    """

    LOCK_TIMEOUT = 30

    # we need to serialize any attempt to trigger indexing since it can be triggered
    # either via celery beat or manually (API call)
    lock: RedisLock = r.lock(
        DANSWER_REDIS_FUNCTION_LOCK_PREFIX + "try_creating_indexing_task",
        timeout=LOCK_TIMEOUT,
    )

    acquired = lock.acquire(blocking_timeout=LOCK_TIMEOUT / 2)
    if not acquired:
        return None

    index_attempt_id = None
    try:
        # Basic status checks
        db_session.refresh(cc_pair)
        if cc_pair.status == ConnectorCredentialPairStatus.DELETING:
            return None

        # Generate custom task ID for tracking
        custom_task_id = f"docfetching_{cc_pair.id}_{search_settings.id}_{uuid4()}"

        # Try to create a new index attempt using database coordination
        # This replaces the Redis fencing mechanism
        index_attempt_id = IndexingCoordination.try_create_index_attempt(
            db_session=db_session,
            cc_pair_id=cc_pair.id,
            search_settings_id=search_settings.id,
            celery_task_id=custom_task_id,
            from_beginning=reindex,
        )

        if index_attempt_id is None:
            # Another indexing attempt is already running
            return None

        # Determine which queue to use based on whether this is a user file
        # TODO: at the moment the indexing pipeline is
        # shared between user files and connectors
        queue = (
            OnyxCeleryQueues.USER_FILES_INDEXING
            if cc_pair.is_user_file
            else OnyxCeleryQueues.CONNECTOR_DOC_FETCHING
        )

        # Send the task to Celery
        result = celery_app.send_task(
            OnyxCeleryTask.CONNECTOR_DOC_FETCHING_TASK,
            kwargs=dict(
                index_attempt_id=index_attempt_id,
                cc_pair_id=cc_pair.id,
                search_settings_id=search_settings.id,
                tenant_id=tenant_id,
            ),
            queue=queue,
            task_id=custom_task_id,
            priority=OnyxCeleryPriority.MEDIUM,
        )
        if not result:
            raise RuntimeError("send_task for connector_doc_fetching_task failed.")

        task_logger.info(
            f"Created docfetching task: "
            f"cc_pair={cc_pair.id} "
            f"search_settings={search_settings.id} "
            f"attempt_id={index_attempt_id} "
            f"celery_task_id={custom_task_id}"
        )

        return index_attempt_id

    except Exception:
        task_logger.exception(
            f"try_creating_indexing_task - Unexpected exception: "
            f"cc_pair={cc_pair.id} "
            f"search_settings={search_settings.id}"
        )

        # Clean up on failure
        if index_attempt_id is not None:
            mark_attempt_failed(index_attempt_id, db_session)

        return None
    finally:
        if lock.owned():
            lock.release()

    return index_attempt_id
