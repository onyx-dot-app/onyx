import time
from typing import cast
from uuid import uuid4

import redis
from celery import Celery
from redis import Redis
from redis.lock import Lock as RedisLock
from sqlalchemy.orm import Session

from danswer.configs.constants import CELERY_VESPA_SYNC_BEAT_LOCK_TIMEOUT
from danswer.configs.constants import DanswerCeleryPriority
from danswer.configs.constants import DanswerCeleryQueues
from danswer.redis.redis_object_helper import RedisObjectHelper
from danswer.utils.variable_functionality import fetch_versioned_implementation
from danswer.utils.variable_functionality import global_version


class RedisUserGroup(RedisObjectHelper):
    PREFIX = "usergroup"
    FENCE_PREFIX = PREFIX + "_fence"
    TASKSET_PREFIX = PREFIX + "_taskset"

    def __init__(self, tenant_id: str | None, id: int) -> None:
        super().__init__(tenant_id, str(id))

    @property
    def fenced(self) -> bool:
        if self.redis.exists(self.fence_key):
            return True

        return False

    def set_fence(self, payload: int | None) -> None:
        if payload is None:
            self.redis.delete(self.fence_key)
            return

        self.redis.set(self.fence_key, payload)

    @property
    def payload(self) -> int | None:
        bytes = self.redis.get(self.fence_key)
        if bytes is None:
            return None

        progress = int(cast(int, bytes))
        return progress

    def generate_tasks(
        self,
        celery_app: Celery,
        db_session: Session,
        redis_client: Redis,
        lock: RedisLock,
        tenant_id: str | None,
    ) -> tuple[int, int] | None:
        last_lock_time = time.monotonic()

        async_results = []

        if not global_version.is_ee_version():
            return 0, 0

        try:
            construct_document_select_by_usergroup = fetch_versioned_implementation(
                "danswer.db.user_group",
                "construct_document_select_by_usergroup",
            )
        except ModuleNotFoundError:
            return 0, 0

        stmt = construct_document_select_by_usergroup(int(self._id))
        for doc in db_session.scalars(stmt).yield_per(1):
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

            result = celery_app.send_task(
                "vespa_metadata_sync_task",
                kwargs=dict(document_id=doc.id, tenant_id=tenant_id),
                queue=DanswerCeleryQueues.VESPA_METADATA_SYNC,
                task_id=custom_task_id,
                priority=DanswerCeleryPriority.LOW,
            )

            async_results.append(result)

        return len(async_results), len(async_results)

    def reset(self) -> None:
        self.redis.delete(self.taskset_key)
        self.redis.delete(self.fence_key)

    @staticmethod
    def reset_all(r: redis.Redis) -> None:
        for key in r.scan_iter(RedisUserGroup.TASKSET_PREFIX + "*"):
            r.delete(key)

        for key in r.scan_iter(RedisUserGroup.FENCE_PREFIX + "*"):
            r.delete(key)
