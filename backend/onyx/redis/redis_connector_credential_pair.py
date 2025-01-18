import time
from typing import cast
from uuid import uuid4

from celery import Celery
from redis import Redis
from redis.lock import Lock as RedisLock
from sqlalchemy.orm import Session

from onyx.configs.app_configs import DB_YIELD_PER_DEFAULT
from onyx.configs.constants import CELERY_VESPA_SYNC_BEAT_LOCK_TIMEOUT
from onyx.configs.constants import OnyxCeleryPriority
from onyx.configs.constants import OnyxCeleryQueues
from onyx.configs.constants import OnyxCeleryTask
from onyx.db.connector_credential_pair import get_connector_credential_pair_from_id
from onyx.db.document import (
    construct_document_select_for_connector_credential_pair_by_needs_sync,
)
from onyx.db.models import Document
from onyx.redis.redis_object_helper import RedisObjectHelper


class RedisConnectorCredentialPair(RedisObjectHelper):
    """This class is used to scan documents by cc_pair in the db and collect them into
    a unified set for syncing.

    It differs from the other redis helpers in that the taskset used spans
    all connectors and is not per connector."""

    PREFIX = "connectorsync"
    FENCE_PREFIX = PREFIX + "_fence"
    TASKSET_PREFIX = PREFIX + "_taskset"

    SYNCING_PREFIX = PREFIX + ":vespa_syncing"

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

    @staticmethod
    def make_redis_syncing_key(doc_id: str) -> str:
        """used to create a key in redis to block a doc from syncing"""
        return f"{RedisConnectorCredentialPair.SYNCING_PREFIX}:{doc_id}"

    def generate_tasks(
        self,
        max_tasks: int,
        celery_app: Celery,
        db_session: Session,
        redis_client: Redis,
        lock: RedisLock,
        tenant_id: str | None,
    ) -> tuple[int, int] | None:
        """We can limit the number of tasks generated here, which is useful to prevent
        one tenant from overwhelming the sync queue.

        This works because the dirty state of a document is in the DB, so more docs
        get picked up after the limited set of tasks is complete.
        """

        last_lock_time = time.monotonic()

        async_results = []
        cc_pair = get_connector_credential_pair_from_id(
            db_session=db_session,
            cc_pair_id=int(self._id),
        )
        if not cc_pair:
            return None

        stmt = construct_document_select_for_connector_credential_pair_by_needs_sync(
            cc_pair.connector_id, cc_pair.credential_id
        )

        num_docs = 0

        for doc in db_session.scalars(stmt).yield_per(DB_YIELD_PER_DEFAULT):
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

            # an arbitrary number in seconds to prevent the same doc from syncing repeatedly
            # SYNC_EXPIRATION = 24 * 60 * 60

            # a quick hack that can be uncommented to prevent a doc from resyncing over and over
            # redis_syncing_key = self.make_redis_syncing_key(doc.id)
            # if redis_client.exists(redis_syncing_key):
            #     continue
            # redis_client.set(redis_syncing_key, custom_task_id, ex=SYNC_EXPIRATION)

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
                OnyxCeleryTask.VESPA_METADATA_SYNC_TASK,
                kwargs=dict(document_id=doc.id, tenant_id=tenant_id),
                queue=OnyxCeleryQueues.VESPA_METADATA_SYNC,
                task_id=custom_task_id,
                priority=OnyxCeleryPriority.MEDIUM,
            )

            async_results.append(result)
            self.skip_docs.add(doc.id)

            if len(async_results) >= max_tasks:
                break

        return len(async_results), num_docs
