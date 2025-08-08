from datetime import datetime
from typing import cast

import redis
from pydantic import BaseModel

from onyx.configs.constants import CELERY_INDEXING_WATCHDOG_CONNECTOR_TIMEOUT


class RedisConnectorIndexPayload(BaseModel):
    index_attempt_id: int | None
    started: datetime | None
    submitted: datetime
    celery_task_id: str | None


class RedisConnectorIndex:
    """Manages interactions with redis for indexing tasks. Should only be accessed
    through RedisConnector."""

    PREFIX = "connectorindexing"
    FENCE_PREFIX = f"{PREFIX}_fence"  # "connectorindexing_fence"
    GENERATOR_TASK_PREFIX = PREFIX + "+generator"  # "connectorindexing+generator_fence"
    GENERATOR_PROGRESS_PREFIX = (
        PREFIX + "_generator_progress"
    )  # connectorindexing_generator_progress
    GENERATOR_COMPLETE_PREFIX = (
        PREFIX + "_generator_complete"
    )  # connectorindexing_generator_complete

    GENERATOR_LOCK_PREFIX = "da_lock:indexing:docfetching"
    FILESTORE_LOCK_PREFIX = "da_lock:indexing:filestore"
    DB_LOCK_PREFIX = "da_lock:indexing:db"
    PER_WORKER_LOCK_PREFIX = "da_lock:indexing:per_worker"

    TERMINATE_PREFIX = PREFIX + "_terminate"  # connectorindexing_terminate
    TERMINATE_TTL = 600

    # used to signal the overall workflow is still active
    # it's impossible to get the exact state of the system at a single point in time
    # so we need a signal with a TTL to bridge gaps in our checks
    ACTIVE_PREFIX = PREFIX + "_active"
    ACTIVE_TTL = 3600

    # used to signal that the watchdog is running
    WATCHDOG_PREFIX = PREFIX + "_watchdog"
    WATCHDOG_TTL = 300

    # used to signal that the connector itself is still running
    CONNECTOR_ACTIVE_PREFIX = PREFIX + "_connector_active"
    CONNECTOR_ACTIVE_TTL = CELERY_INDEXING_WATCHDOG_CONNECTOR_TIMEOUT

    def __init__(
        self,
        tenant_id: str,
        cc_pair_id: int,
        search_settings_id: int,
        redis: redis.Redis,
    ) -> None:
        self.tenant_id: str = tenant_id
        self.cc_pair_id = cc_pair_id
        self.search_settings_id = search_settings_id
        self.redis = redis

        self.generator_complete_key = (
            f"{self.GENERATOR_COMPLETE_PREFIX}_{cc_pair_id}/{search_settings_id}"
        )
        self.filestore_lock_key = (
            f"{self.FILESTORE_LOCK_PREFIX}_{cc_pair_id}/{search_settings_id}"
        )
        self.generator_lock_key = (
            f"{self.GENERATOR_LOCK_PREFIX}_{cc_pair_id}/{search_settings_id}"
        )
        self.per_worker_lock_key = (
            f"{self.PER_WORKER_LOCK_PREFIX}_{cc_pair_id}/{search_settings_id}"
        )
        self.db_lock_key = f"{self.DB_LOCK_PREFIX}_{cc_pair_id}/{search_settings_id}"
        self.terminate_key = (
            f"{self.TERMINATE_PREFIX}_{cc_pair_id}/{search_settings_id}"
        )

    def set_generator_complete(self, payload: int | None) -> None:
        if not payload:
            self.redis.delete(self.generator_complete_key)
            return

        self.redis.set(self.generator_complete_key, payload)

    def generator_clear(self) -> None:
        self.redis.delete(self.generator_complete_key)

    def get_completion(self) -> int | None:
        bytes = self.redis.get(self.generator_complete_key)
        if bytes is None:
            return None

        status = int(cast(int, bytes))
        return status

    def reset(self) -> None:
        self.redis.delete(self.filestore_lock_key)
        self.redis.delete(self.db_lock_key)
        self.redis.delete(self.generator_lock_key)
        self.redis.delete(self.generator_complete_key)

    @staticmethod
    def reset_all(r: redis.Redis) -> None:
        """Deletes all redis values for all connectors"""
        # leaving these temporarily for backwards compat, TODO: remove
        for key in r.scan_iter(RedisConnectorIndex.CONNECTOR_ACTIVE_PREFIX + "*"):
            r.delete(key)

        for key in r.scan_iter(RedisConnectorIndex.ACTIVE_PREFIX + "*"):
            r.delete(key)

        for key in r.scan_iter(RedisConnectorIndex.FILESTORE_LOCK_PREFIX + "*"):
            r.delete(key)

        for key in r.scan_iter(RedisConnectorIndex.GENERATOR_COMPLETE_PREFIX + "*"):
            r.delete(key)

        for key in r.scan_iter(RedisConnectorIndex.GENERATOR_PROGRESS_PREFIX + "*"):
            r.delete(key)

        for key in r.scan_iter(RedisConnectorIndex.FENCE_PREFIX + "*"):
            r.delete(key)
