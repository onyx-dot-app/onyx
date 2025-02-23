import time
from datetime import datetime
from typing import cast
from uuid import uuid4

import redis
from celery import Celery
from pydantic import BaseModel
from redis.lock import Lock as RedisLock
from sqlalchemy.orm import Session

from onyx.configs.app_configs import DB_YIELD_PER_DEFAULT
from onyx.configs.constants import CELERY_VESPA_SYNC_BEAT_LOCK_TIMEOUT
from onyx.configs.constants import OnyxCeleryPriority
from onyx.configs.constants import OnyxCeleryQueues
from onyx.configs.constants import OnyxCeleryTask
from onyx.configs.constants import OnyxRedisConstants
from onyx.db.connector_credential_pair import get_connector_credential_pair_from_id
from onyx.db.document import construct_document_select_for_connector_credential_pair
from onyx.db.models import Document as DbDocument


class RedisConnectorDeletePayload(BaseModel):
    num_tasks: int | None
    submitted: datetime


class RedisConnectorDelete:
    """Manages interactions with redis for deletion tasks. Should only be accessed
    through RedisConnector."""

    PREFIX = "connectordeletion"
    FENCE_PREFIX = f"{PREFIX}_fence"  # "connectordeletion_fence"
    TASKSET_PREFIX = f"{PREFIX}_taskset"  # "connectordeletion_taskset"
    SUBTASK_CREATION_TIMES_PREFIX = f"{PREFIX}_subtask_creation_times"
    SUBTASK_HEARTBEAT_PREFIX = f"{PREFIX}_subtask_heartbeat"

    def __init__(self, tenant_id: str | None, id: int, redis: redis.Redis) -> None:
        self.tenant_id: str | None = tenant_id
        self.id = id
        self.redis = redis

        self.fence_key: str = f"{self.FENCE_PREFIX}_{id}"
        self.taskset_key = f"{self.TASKSET_PREFIX}_{id}"

        self.subtask_creation_times_key = f"{self.SUBTASK_CREATION_TIMES_PREFIX}_{id}"
        self.subtask_heartbeat_prefix = f"{self.SUBTASK_HEARTBEAT_PREFIX}_{id}"

    def taskset_clear(self) -> None:
        self.redis.delete(self.taskset_key)

    def get_remaining(self) -> int:
        # todo: move into fence
        remaining = cast(int, self.redis.scard(self.taskset_key))
        return remaining

    @property
    def fenced(self) -> bool:
        if self.redis.exists(self.fence_key):
            return True

        return False

    @property
    def payload(self) -> RedisConnectorDeletePayload | None:
        # read related data and evaluate/print task progress
        fence_bytes = cast(bytes, self.redis.get(self.fence_key))
        if fence_bytes is None:
            return None

        fence_str = fence_bytes.decode("utf-8")
        payload = RedisConnectorDeletePayload.model_validate_json(cast(str, fence_str))

        return payload

    def set_fence(self, payload: RedisConnectorDeletePayload | None) -> None:
        if not payload:
            self.redis.srem(OnyxRedisConstants.ACTIVE_FENCES, self.fence_key)
            self.redis.delete(self.fence_key)
            return

        self.redis.set(self.fence_key, payload.model_dump_json())
        self.redis.sadd(OnyxRedisConstants.ACTIVE_FENCES, self.fence_key)

    def _generate_task_id(self) -> str:
        # celery's default task id format is "dd32ded3-00aa-4884-8b21-42f8332e7fac"
        # we prefix the task id so it's easier to keep track of who created the task
        # aka "connectordeletion_1_6dd32ded3-00aa-4884-8b21-42f8332e7fac"

        return f"{self.PREFIX}_{self.id}_{uuid4()}"

    def generate_tasks(
        self,
        celery_app: Celery,
        db_session: Session,
        lock: RedisLock,
    ) -> int | None:
        """Returns None if the cc_pair doesn't exist.
        Otherwise, returns an int with the number of generated tasks."""
        last_lock_time = time.monotonic()

        async_results = []
        cc_pair = get_connector_credential_pair_from_id(
            db_session=db_session,
            cc_pair_id=int(self.id),
        )
        if not cc_pair:
            return None

        stmt = construct_document_select_for_connector_credential_pair(
            cc_pair.connector_id, cc_pair.credential_id
        )
        for doc_temp in db_session.scalars(stmt).yield_per(DB_YIELD_PER_DEFAULT):
            doc: DbDocument = doc_temp
            current_time = time.monotonic()
            if current_time - last_lock_time >= (
                CELERY_VESPA_SYNC_BEAT_LOCK_TIMEOUT / 4
            ):
                lock.reacquire()
                last_lock_time = current_time

            custom_task_id = self._generate_task_id()

            # add to the tracking taskset in redis BEFORE creating the celery task.
            # note that for the moment we are using a single taskset key, not differentiated by cc_pair id
            self.redis.sadd(self.taskset_key, custom_task_id)

            # Record creation time in a dedicated hash
            self.redis.hset(
                self.subtask_creation_times_key, custom_task_id, str(time.time())
            )

            # Priority on sync's triggered by new indexing should be medium
            result = celery_app.send_task(
                OnyxCeleryTask.DOCUMENT_BY_CC_PAIR_CLEANUP_TASK,
                kwargs=dict(
                    document_id=doc.id,
                    connector_id=cc_pair.connector_id,
                    credential_id=cc_pair.credential_id,
                    flow_type="delete",
                    tenant_id=self.tenant_id,
                ),
                queue=OnyxCeleryQueues.CONNECTOR_DELETION,
                task_id=custom_task_id,
                priority=OnyxCeleryPriority.MEDIUM,
                ignore_result=True,
            )

            async_results.append(result)

        return len(async_results)

    def reset(self) -> None:
        self.redis.srem(OnyxRedisConstants.ACTIVE_FENCES, self.fence_key)
        self.redis.delete(self.taskset_key)
        self.redis.delete(self.fence_key)

    @staticmethod
    def remove_from_taskset(id: int, task_id: str, r: redis.Redis) -> None:
        taskset_key = f"{RedisConnectorDelete.TASKSET_PREFIX}_{id}"
        creation_times_key = (
            f"{RedisConnectorDelete.SUBTASK_CREATION_TIMES_PREFIX}_{id}"
        )

        r.srem(taskset_key, task_id)
        r.hdel(creation_times_key, task_id)

    @staticmethod
    def update_subtask_heartbeat(id: int, task_id: str, r: redis.Redis) -> None:
        """
        Subtask calls this to mark 'I am alive'.
        """
        heartbeat_key = (
            f"{RedisConnectorDelete.SUBTASK_HEARTBEAT_PREFIX}_{id}:{task_id}"
        )
        r.set(heartbeat_key, time.time(), ex=300)  # e.g. 5-min TTL

    @staticmethod
    def _parse_float(val: bytes | str) -> float:
        """
        Safely parse the raw Redis value (bytes/str) into a float or raise ValueError.
        """
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
        Removes stale or never-started subtasks from the deletion taskset
        if their heartbeat or creation time exceeds threshold_s seconds.
        """
        taskset_key = f"{RedisConnectorDelete.TASKSET_PREFIX}_{id}"
        creation_times_key = (
            f"{RedisConnectorDelete.SUBTASK_CREATION_TIMES_PREFIX}_{id}"
        )
        heartbeat_prefix = f"{RedisConnectorDelete.SUBTASK_HEARTBEAT_PREFIX}_{id}"

        now = time.time()

        for subtask_id_bytes in r.sscan_iter(taskset_key):
            subtask_id = subtask_id_bytes.decode("utf-8")
            hb_key = f"{heartbeat_prefix}:{subtask_id}"
            last_beat_raw = cast(bytes, r.get(hb_key))

            if last_beat_raw is not None:
                # Subtask heartbeated; check if stale
                try:
                    last_beat_val = RedisConnectorDelete._parse_float(last_beat_raw)
                except ValueError:
                    raise ValueError(
                        f"Failed to parse heartbeat value for subtask {subtask_id}"
                    )

                if now - last_beat_val > threshold_s:
                    r.srem(taskset_key, subtask_id)
                    r.hdel(creation_times_key, subtask_id)
            else:
                # No heartbeat; check creation time
                creation_time_raw = cast(bytes, r.hget(creation_times_key, subtask_id))
                if creation_time_raw is not None:
                    try:
                        creation_time_val = RedisConnectorDelete._parse_float(
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
        for key in r.scan_iter(RedisConnectorDelete.TASKSET_PREFIX + "*"):
            r.delete(key)

        for key in r.scan_iter(RedisConnectorDelete.FENCE_PREFIX + "*"):
            r.delete(key)
