from datetime import datetime
from typing import Any
from typing import cast
from uuid import uuid4

import redis
from pydantic import BaseModel

from onyx.configs.constants import OnyxRedisConstants


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

    GENERATOR_LOCK_PREFIX = "da_lock:indexing"

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

    def __init__(
        self,
        tenant_id: str | None,
        id: int,
        search_settings_id: int,
        redis: redis.Redis,
    ) -> None:
        self.tenant_id: str | None = tenant_id
        self.id = id
        self.search_settings_id = search_settings_id
        self.redis = redis

        self.fence_key: str = f"{self.FENCE_PREFIX}_{id}/{search_settings_id}"
        self.generator_progress_key = (
            f"{self.GENERATOR_PROGRESS_PREFIX}_{id}/{search_settings_id}"
        )
        self.generator_complete_key = (
            f"{self.GENERATOR_COMPLETE_PREFIX}_{id}/{search_settings_id}"
        )
        self.generator_lock_key = (
            f"{self.GENERATOR_LOCK_PREFIX}_{id}/{search_settings_id}"
        )
        self.terminate_key = f"{self.TERMINATE_PREFIX}_{id}/{search_settings_id}"
        self.active_key = f"{self.ACTIVE_PREFIX}_{id}/{search_settings_id}"
        self.watchdog_key = f"{self.WATCHDOG_PREFIX}_{id}/{search_settings_id}"

    @classmethod
    def fence_key_with_ids(cls, cc_pair_id: int, search_settings_id: int) -> str:
        return f"{cls.FENCE_PREFIX}_{cc_pair_id}/{search_settings_id}"

    def generate_generator_task_id(self) -> str:
        # celery's default task id format is "dd32ded3-00aa-4884-8b21-42f8332e7fac"
        # we prefix the task id so it's easier to keep track of who created the task
        # aka "connectorindexing+generator_1_6dd32ded3-00aa-4884-8b21-42f8332e7fac"

        return f"{self.GENERATOR_TASK_PREFIX}_{self.id}/{self.search_settings_id}_{uuid4()}"

    @property
    def fenced(self) -> bool:
        if self.redis.exists(self.fence_key):
            return True

        return False

    @property
    def payload(self) -> RedisConnectorIndexPayload | None:
        # read related data and evaluate/print task progress
        fence_bytes = cast(Any, self.redis.get(self.fence_key))
        if fence_bytes is None:
            return None

        fence_str = fence_bytes.decode("utf-8")
        payload = RedisConnectorIndexPayload.model_validate_json(cast(str, fence_str))

        return payload

    def set_fence(
        self,
        payload: RedisConnectorIndexPayload | None,
    ) -> None:
        if not payload:
            self.redis.srem(OnyxRedisConstants.ACTIVE_FENCES, self.fence_key)
            self.redis.delete(self.fence_key)
            return

        self.redis.set(self.fence_key, payload.model_dump_json())
        self.redis.sadd(OnyxRedisConstants.ACTIVE_FENCES, self.fence_key)

    def terminating(self, celery_task_id: str) -> bool:
        if self.redis.exists(f"{self.terminate_key}_{celery_task_id}"):
            return True

        return False

    def set_terminate(self, celery_task_id: str) -> None:
        """This sets a signal. It does not block!"""
        # We shouldn't need very long to terminate the spawned task.
        # 10 minute TTL is good.
        self.redis.set(
            f"{self.terminate_key}_{celery_task_id}", 0, ex=self.TERMINATE_TTL
        )

    def set_watchdog(self, value: bool) -> None:
        """Signal the state of the watchdog."""
        if not value:
            self.redis.delete(self.watchdog_key)
            return

        self.redis.set(self.watchdog_key, 0, ex=self.WATCHDOG_TTL)

    def watchdog_signaled(self) -> bool:
        """Check the state of the watchdog."""
        if self.redis.exists(self.watchdog_key):
            return True

        return False

    def set_active(self) -> None:
        """This sets a signal to keep the indexing flow from getting cleaned up within
        the expiration time.

        The slack in timing is needed to avoid race conditions where simply checking
        the celery queue and task status could result in race conditions."""
        self.redis.set(self.active_key, 0, ex=self.ACTIVE_TTL)

    def active(self) -> bool:
        if self.redis.exists(self.active_key):
            return True

        return False

    def generator_locked(self) -> bool:
        if self.redis.exists(self.generator_lock_key):
            return True

        return False

    def set_generator_complete(self, payload: int | None) -> None:
        if not payload:
            self.redis.delete(self.generator_complete_key)
            return

        self.redis.set(self.generator_complete_key, payload)

    def generator_clear(self) -> None:
        self.redis.delete(self.generator_progress_key)
        self.redis.delete(self.generator_complete_key)

    def get_progress(self) -> int | None:
        """Returns None if the key doesn't exist. The"""
        # TODO: move into fence?
        bytes = self.redis.get(self.generator_progress_key)
        if bytes is None:
            return None

        progress = int(cast(int, bytes))
        return progress

    def get_completion(self) -> int | None:
        # TODO: move into fence?
        bytes = self.redis.get(self.generator_complete_key)
        if bytes is None:
            return None

        status = int(cast(int, bytes))
        return status

    def reset(self) -> None:
        self.redis.srem(OnyxRedisConstants.ACTIVE_FENCES, self.fence_key)
        self.redis.delete(self.active_key)
        self.redis.delete(self.generator_lock_key)
        self.redis.delete(self.generator_progress_key)
        self.redis.delete(self.generator_complete_key)
        self.redis.delete(self.fence_key)

    @staticmethod
    def reset_all(r: redis.Redis) -> None:
        """Deletes all redis values for all connectors"""
        for key in r.scan_iter(RedisConnectorIndex.ACTIVE_PREFIX + "*"):
            r.delete(key)

        for key in r.scan_iter(RedisConnectorIndex.GENERATOR_LOCK_PREFIX + "*"):
            r.delete(key)

        for key in r.scan_iter(RedisConnectorIndex.GENERATOR_COMPLETE_PREFIX + "*"):
            r.delete(key)

        for key in r.scan_iter(RedisConnectorIndex.GENERATOR_PROGRESS_PREFIX + "*"):
            r.delete(key)

        for key in r.scan_iter(RedisConnectorIndex.FENCE_PREFIX + "*"):
            r.delete(key)
