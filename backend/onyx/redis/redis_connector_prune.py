import time
from typing import cast
from uuid import uuid4

import redis
from celery import Celery
from redis.lock import Lock as RedisLock
from sqlalchemy.orm import Session

from onyx.configs.constants import CELERY_VESPA_SYNC_BEAT_LOCK_TIMEOUT
from onyx.configs.constants import OnyxCeleryPriority
from onyx.configs.constants import OnyxCeleryQueues
from onyx.configs.constants import OnyxCeleryTask
from onyx.db.connector_credential_pair import get_connector_credential_pair_from_id
from onyx.redis.redis_pool import SCAN_ITER_COUNT_DEFAULT


class RedisConnectorPrune:
    """Manages interactions with redis for pruning tasks. Should only be accessed
    through RedisConnector."""

    PREFIX = "connectorpruning"

    FENCE_PREFIX = f"{PREFIX}_fence"

    # phase 1 - geneartor task and progress signals
    GENERATORTASK_PREFIX = f"{PREFIX}+generator"  # connectorpruning+generator
    GENERATOR_PROGRESS_PREFIX = (
        PREFIX + "_generator_progress"
    )  # connectorpruning_generator_progress
    GENERATOR_COMPLETE_PREFIX = (
        PREFIX + "_generator_complete"
    )  # connectorpruning_generator_complete

    TASKSET_PREFIX = f"{PREFIX}_taskset"  # connectorpruning_taskset
    SUBTASK_PREFIX = f"{PREFIX}+sub"  # connectorpruning+sub

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
        """Count of active pruning tasks"""
        count = 0
        for key in self.redis.scan_iter(
            RedisConnectorPrune.FENCE_PREFIX + "*", count=SCAN_ITER_COUNT_DEFAULT
        ):
            count += 1
        return count

    @property
    def fenced(self) -> bool:
        if self.redis.exists(self.fence_key):
            return True

        return False

    def set_fence(self, value: bool) -> None:
        if not value:
            self.redis.delete(self.fence_key)
            return

        self.redis.set(self.fence_key, 0)

    @property
    def generator_complete(self) -> int | None:
        """the fence payload is an int representing the starting number of
        pruning tasks to be processed ... just after the generator completes."""
        fence_bytes = self.redis.get(self.generator_complete_key)
        if fence_bytes is None:
            return None

        fence_int = cast(int, fence_bytes)
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
        documents_to_prune: set[str],
        celery_app: Celery,
        db_session: Session,
        lock: RedisLock | None,
    ) -> int | None:
        last_lock_time = time.monotonic()

        async_results = []
        cc_pair = get_connector_credential_pair_from_id(
            db_session=db_session,
            cc_pair_id=int(self.id),
        )
        if not cc_pair:
            return None

        for doc_id in documents_to_prune:
            current_time = time.monotonic()
            if lock and current_time - last_lock_time >= (
                CELERY_VESPA_SYNC_BEAT_LOCK_TIMEOUT / 4
            ):
                lock.reacquire()
                last_lock_time = current_time

            # celery's default task id format is "dd32ded3-00aa-4884-8b21-42f8332e7fac"
            # the actual redis key is "celery-task-meta-dd32ded3-00aa-4884-8b21-42f8332e7fac"
            # we prefix the task id so it's easier to keep track of who created the task
            # aka "documentset_1_6dd32ded3-00aa-4884-8b21-42f8332e7fac"
            custom_task_id = f"{self.subtask_prefix}_{uuid4()}"

            # add to the tracking taskset in redis BEFORE creating the celery task.
            self.redis.sadd(self.taskset_key, custom_task_id)

            # Priority on sync's triggered by new indexing should be medium
            result = celery_app.send_task(
                OnyxCeleryTask.DOCUMENT_BY_CC_PAIR_CLEANUP_TASK,
                kwargs=dict(
                    document_id=doc_id,
                    connector_id=cc_pair.connector_id,
                    credential_id=cc_pair.credential_id,
                    tenant_id=self.tenant_id,
                ),
                queue=OnyxCeleryQueues.CONNECTOR_DELETION,
                task_id=custom_task_id,
                priority=OnyxCeleryPriority.MEDIUM,
            )

            async_results.append(result)

        return len(async_results)

    def reset(self) -> None:
        self.redis.delete(self.generator_progress_key)
        self.redis.delete(self.generator_complete_key)
        self.redis.delete(self.taskset_key)
        self.redis.delete(self.fence_key)

    @staticmethod
    def remove_from_taskset(id: int, task_id: str, r: redis.Redis) -> None:
        taskset_key = f"{RedisConnectorPrune.TASKSET_PREFIX}_{id}"
        r.srem(taskset_key, task_id)
        return

    @staticmethod
    def reset_all(r: redis.Redis) -> None:
        """Deletes all redis values for all connectors"""
        for key in r.scan_iter(RedisConnectorPrune.TASKSET_PREFIX + "*"):
            r.delete(key)

        for key in r.scan_iter(RedisConnectorPrune.GENERATOR_COMPLETE_PREFIX + "*"):
            r.delete(key)

        for key in r.scan_iter(RedisConnectorPrune.GENERATOR_PROGRESS_PREFIX + "*"):
            r.delete(key)

        for key in r.scan_iter(RedisConnectorPrune.FENCE_PREFIX + "*"):
            r.delete(key)
