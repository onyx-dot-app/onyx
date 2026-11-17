import time
from datetime import datetime, timezone

from redis.exceptions import LockError
from redis.lock import Lock as RedisLock

from onyx.configs.constants import CELERY_GENERIC_BEAT_LOCK_TIMEOUT
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.redis.redis_connector import RedisConnector
from onyx.redis.redis_pool import redis_lock_dump
from onyx.redis.tenant_redis_client import TenantRedisClient
from onyx.utils.logger import setup_logger

logger = setup_logger()


class IndexingCallbackBase(IndexingHeartbeatInterface):
    PARENT_CHECK_INTERVAL = 60

    def __init__(
        self,
        parent_pid: int,
        redis_connector: RedisConnector,
        redis_lock: RedisLock,
        redis_client: TenantRedisClient,
        timeout_seconds: int | None = None,
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
        self.start_monotonic = time.monotonic()
        self.timeout_seconds = timeout_seconds

    def should_stop(self) -> bool:
        # Check if the associated indexing attempt has been cancelled
        # TODO: Pass index_attempt_id to the callback and check cancellation using the db
        if bool(self.redis_connector.stop.fenced):
            return True

        # Check if the task has exceeded its timeout
        # NOTE: Celery's soft_time_limit does not work with thread pools,
        # so we must enforce timeouts internally.
        if self.timeout_seconds is not None:
            elapsed = time.monotonic() - self.start_monotonic
            if elapsed > self.timeout_seconds:
                logger.warning(
                    "IndexingCallback Docprocessing - task timeout exceeded: elapsed=%ss timeout=%ss cc_pair=%s",
                    format(elapsed, ".0f"),
                    self.timeout_seconds,
                    self.redis_connector.cc_pair_id,
                )
                return True

        return False

    def progress(self, tag: str, amount: int) -> None:  # noqa: ARG002
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
                "%s - lock.reacquire exceptioned: lock_timeout=%s start=%s last_tag=%s last_reacquired=%s now=%s",
                self.__class__.__name__,
                self.redis_lock.timeout,
                self.started,
                self.last_tag,
                self.last_lock_reacquire,
                datetime.now(timezone.utc),
            )

            redis_lock_dump(self.redis_lock, self.redis_client)
            raise
