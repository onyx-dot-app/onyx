import time
from datetime import datetime
from typing import Any
from typing import cast
from uuid import uuid4

import redis
from celery import Celery
from pydantic import BaseModel
from redis.lock import Lock as RedisLock

from onyx.access.models import DocExternalAccess
from onyx.configs.constants import CELERY_GENERIC_BEAT_LOCK_TIMEOUT
from onyx.configs.constants import CELERY_PERMISSIONS_SYNC_LOCK_TIMEOUT
from onyx.configs.constants import OnyxCeleryPriority
from onyx.configs.constants import OnyxCeleryQueues
from onyx.configs.constants import OnyxCeleryTask
from onyx.configs.constants import OnyxRedisConstants
from onyx.redis.redis_pool import SCAN_ITER_COUNT_DEFAULT


class RedisConnectorPermissionSyncPayload(BaseModel):
    id: str
    submitted: datetime
    started: datetime | None
    celery_task_id: str | None


class RedisConnectorPermissionSync:
    """Manages interactions with redis for doc permission sync tasks. Should only be accessed
    through RedisConnector."""

    PREFIX = "connectordocpermissionsync"

    FENCE_PREFIX = f"{PREFIX}_fence"

    # phase 1 - geneartor task and progress signals
    GENERATORTASK_PREFIX = f"{PREFIX}+generator"  # connectorpermissions+generator
    GENERATOR_PROGRESS_PREFIX = (
        PREFIX + "_generator_progress"
    )  # connectorpermissions_generator_progress
    GENERATOR_COMPLETE_PREFIX = (
        PREFIX + "_generator_complete"
    )  # connectorpermissions_generator_complete

    TASKSET_PREFIX = f"{PREFIX}_taskset"  # connectorpermissions_taskset
    SUBTASK_PREFIX = f"{PREFIX}+sub"  # connectorpermissions+sub

    # used to signal the overall workflow is still active
    # it's impossible to get the exact state of the system at a single point in time
    # so we need a signal with a TTL to bridge gaps in our checks
    ACTIVE_PREFIX = PREFIX + "_active"
    ACTIVE_TTL = CELERY_PERMISSIONS_SYNC_LOCK_TIMEOUT * 2

    SUBTASK_CREATION_TIMES_PREFIX = f"{PREFIX}_subtask_creation_times"
    SUBTASK_HEARTBEAT_PREFIX = f"{PREFIX}_subtask_heartbeat"

    def __init__(self, tenant_id: str | None, id: int, redis: redis.Redis) -> None:
        self.tenant_id: str | None = tenant_id
        self.id = id
        self.redis = redis

        self.fence_key: str = f"{self.FENCE_PREFIX}_{id}"
        self.generator_task_key = f"{self.GENERATORTASK_PREFIX}_{id}"
        self.generator_progress_key = f"{self.GENERATOR_PROGRESS_PREFIX}_{id}"
        self.generator_complete_key = f"{self.GENERATOR_COMPLETE_PREFIX}_{id}"

        self.taskset_key = f"{self.TASKSET_PREFIX}_{id}"

        self.subtask_prefix: str = f"{self.SUBTASK_PREFIX}_{id}"
        self.active_key = f"{self.ACTIVE_PREFIX}_{id}"

        self.subtask_creation_times_key = f"{self.SUBTASK_CREATION_TIMES_PREFIX}_{id}"
        self.subtask_heartbeat_prefix = f"{self.SUBTASK_HEARTBEAT_PREFIX}_{id}"

    def taskset_clear(self) -> None:
        self.redis.delete(self.taskset_key)

    def generator_clear(self) -> None:
        self.redis.delete(self.generator_progress_key)
        self.redis.delete(self.generator_complete_key)

    def get_remaining(self) -> int:
        remaining = cast(int, self.redis.scard(self.taskset_key))
        return remaining

    def get_active_task_count(self) -> int:
        """Count of active permission sync tasks"""
        count = 0
        for _ in self.redis.sscan_iter(
            OnyxRedisConstants.ACTIVE_FENCES,
            RedisConnectorPermissionSync.FENCE_PREFIX + "*",
            count=SCAN_ITER_COUNT_DEFAULT,
        ):
            count += 1
        return count

    @property
    def fenced(self) -> bool:
        if self.redis.exists(self.fence_key):
            return True

        return False

    @property
    def payload(self) -> RedisConnectorPermissionSyncPayload | None:
        # read related data and evaluate/print task progress
        fence_bytes = cast(Any, self.redis.get(self.fence_key))
        if fence_bytes is None:
            return None

        fence_str = fence_bytes.decode("utf-8")
        payload = RedisConnectorPermissionSyncPayload.model_validate_json(
            cast(str, fence_str)
        )

        return payload

    def set_fence(
        self,
        payload: RedisConnectorPermissionSyncPayload | None,
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
        if self.redis.exists(self.active_key):
            return True

        return False

    @property
    def generator_complete(self) -> int | None:
        """the fence payload is an int representing the starting number of
        permission sync tasks to be processed ... just after the generator completes."""
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
        lock: RedisLock,
        new_permissions: list[DocExternalAccess],
        source_string: str,
        connector_id: int,
        credential_id: int,
    ) -> int | None:
        last_lock_time = time.monotonic()

        async_results = []
        for doc_external_access in new_permissions:
            current_time = time.monotonic()
            if current_time - last_lock_time >= (CELERY_GENERIC_BEAT_LOCK_TIMEOUT / 4):
                lock.reacquire()
                last_lock_time = current_time

            custom_task_id = f"{self.subtask_prefix}_{uuid4()}"

            # Add to the tracking taskset in redis
            self.redis.sadd(self.taskset_key, custom_task_id)

            # Record creation time as a string
            self.redis.hset(
                self.subtask_creation_times_key, custom_task_id, str(time.time())
            )

            result = celery_app.send_task(
                OnyxCeleryTask.UPDATE_EXTERNAL_DOCUMENT_PERMISSIONS_TASK,
                kwargs=dict(
                    tenant_id=self.tenant_id,
                    serialized_doc_external_access=doc_external_access.to_dict(),
                    source_string=source_string,
                    connector_id=connector_id,
                    credential_id=credential_id,
                ),
                queue=OnyxCeleryQueues.DOC_PERMISSIONS_UPSERT,
                task_id=custom_task_id,
                priority=OnyxCeleryPriority.MEDIUM,
            )

            async_results.append(result)

        return len(async_results)

    def reset(self) -> None:
        self.redis.srem(OnyxRedisConstants.ACTIVE_FENCES, self.fence_key)
        self.redis.delete(self.active_key)
        self.redis.delete(self.generator_progress_key)
        self.redis.delete(self.generator_complete_key)
        self.redis.delete(self.taskset_key)
        self.redis.delete(self.fence_key)

    @staticmethod
    def remove_from_taskset(id: int, task_id: str, r: redis.Redis) -> None:
        taskset_key = f"{RedisConnectorPermissionSync.TASKSET_PREFIX}_{id}"
        creation_times_key = (
            f"{RedisConnectorPermissionSync.SUBTASK_CREATION_TIMES_PREFIX}_{id}"
        )
        r.srem(taskset_key, task_id)
        r.hdel(creation_times_key, task_id)
        return

    @staticmethod
    def update_subtask_heartbeat(id: int, subtask_id: str, r: redis.Redis) -> None:
        heartbeat_key = (
            f"{RedisConnectorPermissionSync.SUBTASK_HEARTBEAT_PREFIX}_{id}:{subtask_id}"
        )
        r.set(heartbeat_key, str(time.time()), ex=300)  # TTL set to 5 minutes

    @staticmethod
    def _parse_float(val: bytes | str) -> float:
        if isinstance(val, bytes):
            val_str = val.decode("utf-8")
        else:
            val_str = str(val)

        return float(val_str)

    @staticmethod
    def detect_stuck_subtasks(
        id: int,
        r: redis.Redis,
        threshold_s: float = 600,
    ) -> None:
        """
        Removes stale or never-started subtasks from the permission sync taskset
        if their heartbeat or creation time exceeds threshold_s seconds.
        """
        taskset_key = f"{RedisConnectorPermissionSync.TASKSET_PREFIX}_{id}"
        creation_times_key = (
            f"{RedisConnectorPermissionSync.SUBTASK_CREATION_TIMES_PREFIX}_{id}"
        )
        heartbeat_prefix = (
            f"{RedisConnectorPermissionSync.SUBTASK_HEARTBEAT_PREFIX}_{id}"
        )

        now = time.time()

        for subtask_id_bytes in r.sscan_iter(taskset_key):
            subtask_id = subtask_id_bytes.decode("utf-8")
            hb_key = f"{heartbeat_prefix}:{subtask_id}"
            last_beat_raw = cast(bytes, r.get(hb_key))

            if last_beat_raw is not None:
                try:
                    last_beat_val = RedisConnectorPermissionSync._parse_float(
                        last_beat_raw
                    )
                except ValueError:
                    raise ValueError(
                        f"Failed to parse heartbeat value for subtask {subtask_id}"
                    )

                if now - last_beat_val > threshold_s:
                    r.srem(taskset_key, subtask_id)
                    r.hdel(creation_times_key, subtask_id)
            else:
                creation_time_raw = cast(bytes, r.hget(creation_times_key, subtask_id))
                if creation_time_raw is not None:
                    try:
                        creation_time_val = RedisConnectorPermissionSync._parse_float(
                            creation_time_raw
                        )
                    except ValueError:
                        raise ValueError(
                            f"Failed to parse creation time value for subtask {subtask_id}"
                        )

                    if now - creation_time_val > threshold_s:
                        r.srem(taskset_key, subtask_id)
                        r.hdel(creation_times_key, subtask_id)

    @staticmethod
    def reset_all(r: redis.Redis) -> None:
        """Deletes all redis values for all connectors"""
        for key in r.scan_iter(RedisConnectorPermissionSync.ACTIVE_PREFIX + "*"):
            r.delete(key)

        for key in r.scan_iter(RedisConnectorPermissionSync.TASKSET_PREFIX + "*"):
            r.delete(key)

        for key in r.scan_iter(
            RedisConnectorPermissionSync.GENERATOR_COMPLETE_PREFIX + "*"
        ):
            r.delete(key)

        for key in r.scan_iter(
            RedisConnectorPermissionSync.GENERATOR_PROGRESS_PREFIX + "*"
        ):
            r.delete(key)

        for key in r.scan_iter(RedisConnectorPermissionSync.FENCE_PREFIX + "*"):
            r.delete(key)
