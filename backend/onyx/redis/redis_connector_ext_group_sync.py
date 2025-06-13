from datetime import datetime
from typing import cast

import redis
from celery import Celery
from pydantic import BaseModel
from redis.lock import Lock as RedisLock
from sqlalchemy.orm import Session

from onyx.configs.constants import OnyxRedisConstants
from onyx.redis.redis_pool import SCAN_ITER_COUNT_DEFAULT


class RedisConnectorExternalGroupSyncPayload(BaseModel):
    id: str
    submitted: datetime
    started: datetime | None
    celery_task_id: str | None


class RedisConnectorExternalGroupSync:
    """Manages interactions with redis for external group syncing tasks. Should only be accessed
    through RedisConnector."""

    PREFIX = "connectorexternalgroupsync"

    FENCE_PREFIX = f"{PREFIX}_fence"

    # phase 1 - geneartor task and progress signals
    GENERATORTASK_PREFIX = f"{PREFIX}+generator"  # connectorexternalgroupsync+generator
    GENERATOR_PROGRESS_PREFIX = (
        PREFIX + "_generator_progress"
    )  # connectorexternalgroupsync_generator_progress
    GENERATOR_COMPLETE_PREFIX = (
        PREFIX + "_generator_complete"
    )  # connectorexternalgroupsync_generator_complete

    TASKSET_PREFIX = f"{PREFIX}_taskset"  # connectorexternalgroupsync_taskset
    SUBTASK_PREFIX = f"{PREFIX}+sub"  # connectorexternalgroupsync+sub

    # used to signal the overall workflow is still active
    # it's impossible to get the exact state of the system at a single point in time
    # so we need a signal with a TTL to bridge gaps in our checks
    ACTIVE_PREFIX = PREFIX + "_active"
    ACTIVE_TTL = 3600

    def __init__(self, tenant_id: str, id: int, redis: redis.Redis) -> None:
        self.tenant_id: str = tenant_id
        self.id = id
        self.redis = redis

        self.fence_key: str = f"{self.FENCE_PREFIX}_{id}"
        self.generator_task_key = f"{self.GENERATORTASK_PREFIX}_{id}"
        self.generator_progress_key = f"{self.GENERATOR_PROGRESS_PREFIX}_{id}"
        self.generator_complete_key = f"{self.GENERATOR_COMPLETE_PREFIX}_{id}"

        self.taskset_key = f"{self.TASKSET_PREFIX}_{id}"

        self.subtask_prefix: str = f"{self.SUBTASK_PREFIX}_{id}"
        self.active_key = f"{self.ACTIVE_PREFIX}_{id}"

    def taskset_clear(self) -> None:
        self.redis.delete(self.taskset_key)

    def generator_clear(self) -> None:
        self.redis.delete(self.generator_progress_key)
        self.redis.delete(self.generator_complete_key)

    def get_remaining(self) -> int:
        # todo: move into fence
        remaining = cast(int, self.redis.scard(self.taskset_key))
        return remaining

    def get_active_task_count(self) -> int:
        """Count of active external group syncing tasks"""
        count = 0
        for _ in self.redis.sscan_iter(
            OnyxRedisConstants.ACTIVE_FENCES,
            RedisConnectorExternalGroupSync.FENCE_PREFIX + "*",
            count=SCAN_ITER_COUNT_DEFAULT,
        ):
            count += 1
        return count

    @property
    def fenced(self) -> bool:
        return bool(self.redis.exists(self.fence_key))

    @property
    def payload(self) -> RedisConnectorExternalGroupSyncPayload | None:
        # read related data and evaluate/print task progress
        fence_raw = self.redis.get(self.fence_key)
        if fence_raw is None:
            return None

        fence_bytes = cast(bytes, fence_raw)
        fence_str = fence_bytes.decode("utf-8")
        payload = RedisConnectorExternalGroupSyncPayload.model_validate_json(
            cast(str, fence_str)
        )

        return payload

    def set_fence(
        self,
        payload: RedisConnectorExternalGroupSyncPayload | None,
    ) -> None:
        if not payload:
            self.redis.srem(OnyxRedisConstants.ACTIVE_FENCES, self.fence_key)
            self.redis.delete(self.fence_key)
            return

        self.redis.set(self.fence_key, payload.model_dump_json())
        self.redis.sadd(OnyxRedisConstants.ACTIVE_FENCES, self.fence_key)

    def set_active(self) -> None:
        """This sets a signal to keep the permissioning flow from getting cleaned up within
        the expiration time.

        The slack in timing is needed to avoid race conditions where simply checking
        the celery queue and task status could result in race conditions."""
        self.redis.set(self.active_key, 0, ex=self.ACTIVE_TTL)

    def active(self) -> bool:
        return bool(self.redis.exists(self.active_key))

    @property
    def generator_complete(self) -> int | None:
        """the fence payload is an int representing the starting number of
        external group syncing tasks to be processed ... just after the generator completes.
        """
        fence_bytes = self.redis.get(self.generator_complete_key)
        if fence_bytes is None:
            return None

        if fence_bytes == b"None":
            return None

        fence_int = int(cast(bytes, fence_bytes).decode())
        return fence_int

    @generator_complete.setter
    def generator_complete(self, payload: int | None) -> None:
        """Set the payload to an int to set the fence, otherwise if None it will
        be deleted"""
        if payload is None:
            self.redis.delete(self.generator_complete_key)
            return

        self.redis.set(self.generator_complete_key, payload)

    def generate_tasks(
        self,
        celery_app: Celery,
        db_session: Session,
        lock: RedisLock | None,
    ) -> int | None:
        pass

    def reset(self) -> None:
        self.redis.srem(OnyxRedisConstants.ACTIVE_FENCES, self.fence_key)
        self.redis.delete(self.active_key)
        self.redis.delete(self.generator_progress_key)
        self.redis.delete(self.generator_complete_key)
        self.redis.delete(self.taskset_key)
        self.redis.delete(self.fence_key)

    @staticmethod
    def remove_from_taskset(id: int, task_id: str, r: redis.Redis) -> None:
        taskset_key = f"{RedisConnectorExternalGroupSync.TASKSET_PREFIX}_{id}"
        r.srem(taskset_key, task_id)
        return

    @staticmethod
    def reset_all(r: redis.Redis) -> None:
        """Deletes all redis values for all connectors"""
        for key in r.scan_iter(RedisConnectorExternalGroupSync.ACTIVE_PREFIX + "*"):
            r.delete(key)

        for key in r.scan_iter(RedisConnectorExternalGroupSync.TASKSET_PREFIX + "*"):
            r.delete(key)

        for key in r.scan_iter(
            RedisConnectorExternalGroupSync.GENERATOR_COMPLETE_PREFIX + "*"
        ):
            r.delete(key)

        for key in r.scan_iter(
            RedisConnectorExternalGroupSync.GENERATOR_PROGRESS_PREFIX + "*"
        ):
            r.delete(key)

        for key in r.scan_iter(RedisConnectorExternalGroupSync.FENCE_PREFIX + "*"):
            r.delete(key)
