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

    def __init__(self, tenant_id: str | None, id: int, redis: redis.Redis) -> None:
        self.tenant_id: str | None = tenant_id
        self.id = id
        self.redis = redis

        self.fence_key: str = f"{self.FENCE_PREFIX}_{id}"
        self.taskset_key = f"{self.TASKSET_PREFIX}_{id}"

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
            self.redis.delete(self.fence_key)
            return

        self.redis.set(self.fence_key, payload.model_dump_json())

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

            # Priority on sync's triggered by new indexing should be medium
            result = celery_app.send_task(
                OnyxCeleryTask.DOCUMENT_BY_CC_PAIR_CLEANUP_TASK,
                kwargs=dict(
                    document_id=doc.id,
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
        self.redis.delete(self.taskset_key)
        self.redis.delete(self.fence_key)

    @staticmethod
    def remove_from_taskset(id: int, task_id: str, r: redis.Redis) -> None:
        taskset_key = f"{RedisConnectorDelete.TASKSET_PREFIX}_{id}"
        r.srem(taskset_key, task_id)
        return

    @staticmethod
    def reset_all(r: redis.Redis) -> None:
        """Deletes all redis values for all connectors"""
        for key in r.scan_iter(RedisConnectorDelete.TASKSET_PREFIX + "*"):
            r.delete(key)

        for key in r.scan_iter(RedisConnectorDelete.FENCE_PREFIX + "*"):
            r.delete(key)
