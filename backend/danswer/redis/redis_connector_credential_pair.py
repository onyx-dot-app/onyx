import time
from typing import cast
from uuid import uuid4

from celery import Celery
from redis import Redis
from redis.lock import Lock as RedisLock
from sqlalchemy.orm import Session

from danswer.configs.constants import CELERY_VESPA_SYNC_BEAT_LOCK_TIMEOUT
from danswer.configs.constants import DanswerCeleryPriority
from danswer.configs.constants import DanswerCeleryQueues
from danswer.db.connector_credential_pair import get_connector_credential_pair_from_id
from danswer.db.document import (
    construct_document_select_for_connector_credential_pair_by_needs_sync,
)
from danswer.db.models import Document
from danswer.redis.redis_object_helper import RedisObjectHelper


class RedisConnectorCredentialPair(RedisObjectHelper):
    """This class is used to scan documents by cc_pair in the db and collect them into
    a unified set for syncing.

    It differs from the other redis helpers in that the taskset used spans
    all connectors and is not per connector."""

    PREFIX = "connectorsync"
    FENCE_PREFIX = PREFIX + "_fence"
    TASKSET_PREFIX = PREFIX + "_taskset"

    def __init__(self, tenant_id: str | None, id: int) -> None:
        super().__init__(tenant_id, str(id))

        # documents that should be skipped
        self.skip_docs: set[str] = set()

    @classmethod
    def get_fence_key(cls) -> str:
        return RedisConnectorCredentialPair.FENCE_PREFIX

    @classmethod
    def get_taskset_key(cls) -> str:
        return RedisConnectorCredentialPair.TASKSET_PREFIX

    @property
    def taskset_key(self) -> str:
        """Notice that this is intentionally reusing the same taskset for all
        connector syncs"""
        # example: connector_taskset
        return f"{self.TASKSET_PREFIX}"

    def set_skip_docs(self, skip_docs: set[str]) -> None:
        # documents that should be skipped. Note that this classes updates
        # the list on the fly
        self.skip_docs = skip_docs

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
        cc_pair = get_connector_credential_pair_from_id(int(self._id), db_session)
        if not cc_pair:
            return None

        stmt = construct_document_select_for_connector_credential_pair_by_needs_sync(
            cc_pair.connector_id, cc_pair.credential_id
        )

        num_docs = 0
        for doc in db_session.scalars(stmt).yield_per(1):
            doc = cast(Document, doc)
            current_time = time.monotonic()
            if current_time - last_lock_time >= (
                CELERY_VESPA_SYNC_BEAT_LOCK_TIMEOUT / 4
            ):
                lock.reacquire()
                last_lock_time = current_time

            num_docs += 1

            # check if we should skip the document (typically because it's already syncing)
            if doc.id in self.skip_docs:
                continue

            # celery's default task id format is "dd32ded3-00aa-4884-8b21-42f8332e7fac"
            # the key for the result is "celery-task-meta-dd32ded3-00aa-4884-8b21-42f8332e7fac"
            # we prefix the task id so it's easier to keep track of who created the task
            # aka "documentset_1_6dd32ded3-00aa-4884-8b21-42f8332e7fac"
            custom_task_id = f"{self.task_id_prefix}_{uuid4()}"

            # add to the tracking taskset in redis BEFORE creating the celery task.
            # note that for the moment we are using a single taskset key, not differentiated by cc_pair id
            redis_client.sadd(
                RedisConnectorCredentialPair.get_taskset_key(), custom_task_id
            )

            # Priority on sync's triggered by new indexing should be medium
            result = celery_app.send_task(
                "vespa_metadata_sync_task",
                kwargs=dict(document_id=doc.id, tenant_id=tenant_id),
                queue=DanswerCeleryQueues.VESPA_METADATA_SYNC,
                task_id=custom_task_id,
                priority=DanswerCeleryPriority.MEDIUM,
            )

            async_results.append(result)
            self.skip_docs.add(doc.id)

        return len(async_results), num_docs
