import time
from datetime import datetime
from datetime import timezone

from redis import Redis
from redis.exceptions import LockError
from redis.lock import Lock as RedisLock
from sqlalchemy.orm import Session

from onyx.configs.app_configs import DISABLE_INDEX_UPDATE_ON_SWAP
from onyx.configs.constants import CELERY_GENERIC_BEAT_LOCK_TIMEOUT
from onyx.configs.constants import DocumentSource
from onyx.db.engine.time_utils import get_db_current_time
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.enums import IndexingStatus
from onyx.db.enums import IndexModelStatus
from onyx.db.index_attempt import get_last_attempt_for_cc_pair
from onyx.db.index_attempt import get_recent_attempts_for_cc_pair
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
    cc_pair: ConnectorCredentialPair, search_settings_id: int, db_session: Session
) -> bool:
    """Checks if the cc pair / search setting combination is in a repeated error state."""
    # if the connector doesn't have a refresh_freq, a single failed attempt is enough
    number_of_failed_attempts_in_a_row_needed = (
        NUM_REPEAT_ERRORS_BEFORE_REPEATED_ERROR_STATE
        if cc_pair.connector.refresh_freq is not None
        else 1
    )

    most_recent_index_attempts = get_recent_attempts_for_cc_pair(
        cc_pair_id=cc_pair.id,
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
        cc_pair=cc_pair,
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
