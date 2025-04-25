import time
from typing import cast
from uuid import uuid4

import redis
from celery import Celery
from redis import Redis
from redis.lock import Lock as RedisLock
from sqlalchemy.orm import Session

from onyx.configs.app_configs import DB_YIELD_PER_DEFAULT
from onyx.configs.constants import CELERY_VESPA_SYNC_BEAT_LOCK_TIMEOUT
from onyx.configs.constants import OnyxCeleryPriority
from onyx.configs.constants import OnyxCeleryQueues
from onyx.configs.constants import OnyxCeleryTask
from onyx.configs.constants import OnyxRedisConstants
from onyx.redis.redis_object_helper import RedisObjectHelper
from onyx.utils.variable_functionality import fetch_versioned_implementation
from onyx.utils.variable_functionality import global_version


class RedisUserGroup(RedisObjectHelper):
    PREFIX = "usergroup"
    FENCE_PREFIX = PREFIX + "_fence"
    TASKSET_PREFIX = PREFIX + "_taskset"

    def __init__(self, tenant_id: str, id: int) -> None:
        super().__init__(tenant_id, str(id))

    @property
    def fenced(self) -> bool:
        if self.redis.exists(self.fence_key):
            return True

        return False

    def set_fence(self, payload: int | None) -> None:
        if payload is None:
            self.redis.srem(OnyxRedisConstants.ACTIVE_FENCES, self.fence_key)
            self.redis.delete(self.fence_key)
            return

        self.redis.set(self.fence_key, payload)
        self.redis.sadd(OnyxRedisConstants.ACTIVE_FENCES, self.fence_key)

    @property
    def payload(self) -> int | None:
        bytes = self.redis.get(self.fence_key)
        if bytes is None:
            return None

        progress = int(cast(int, bytes))
        return progress

    def generate_tasks(
        self,
        max_tasks: int,
        celery_app: Celery,
        db_session: Session,
        redis_client: Redis,
        lock: RedisLock,
        tenant_id: str,
    ) -> tuple[int, int] | None:
        """Max tasks is ignored for now until we can build the logic to mark the
        user group up to date over multiple batches.
        """
        last_lock_time = time.monotonic()
        num_tasks_sent = 0

        if not global_version.is_ee_version():
            return 0, 0

        try:
            construct_document_id_select_by_usergroup = fetch_versioned_implementation(
                "onyx.db.user_group",
                "construct_document_id_select_by_usergroup",
            )
        except ModuleNotFoundError:
            return 0, 0

        stmt = construct_document_id_select_by_usergroup(int(self._id))
        for doc_id in db_session.scalars(stmt).yield_per(DB_YIELD_PER_DEFAULT):
            doc_id = cast(str, doc_id)
            current_time = time.monotonic()
            if current_time - last_lock_time >= (
                CELERY_VESPA_SYNC_BEAT_LOCK_TIMEOUT / 4
            ):
                lock.reacquire()
                last_lock_time = current_time

            # celery's default task id format is "dd32ded3-00aa-4884-8b21-42f8332e7fac"
            # the key for the result is "celery-task-meta-dd32ded3-00aa-4884-8b21-42f8332e7fac"
            # we prefix the task id so it's easier to keep track of who created the task
            # aka "documentset_1_6dd32ded3-00aa-4884-8b21-42f8332e7fac"
            custom_task_id = f"{self.task_id_prefix}_{uuid4()}"

            # add to the set BEFORE creating the task.
            redis_client.sadd(self.taskset_key, custom_task_id)

            celery_app.send_task(
                OnyxCeleryTask.VESPA_METADATA_SYNC_TASK,
                kwargs=dict(document_id=doc_id, tenant_id=tenant_id),
                queue=OnyxCeleryQueues.VESPA_METADATA_SYNC,
                task_id=custom_task_id,
                priority=OnyxCeleryPriority.MEDIUM,
            )

            num_tasks_sent += 1

        return num_tasks_sent, num_tasks_sent

    def reset(self) -> None:
        self.redis.srem(OnyxRedisConstants.ACTIVE_FENCES, self.fence_key)
        self.redis.delete(self.taskset_key)
        self.redis.delete(self.fence_key)

    @staticmethod
    def reset_all(r: redis.Redis) -> None:
        for key in r.scan_iter(RedisUserGroup.TASKSET_PREFIX + "*"):
            r.delete(key)

        for key in r.scan_iter(RedisUserGroup.FENCE_PREFIX + "*"):
            r.delete(key)
