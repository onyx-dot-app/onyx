from datetime import datetime
from datetime import timedelta
from datetime import timezone
from uuid import uuid4

from celery import Celery
from celery import shared_task
from celery import Task
from celery.exceptions import SoftTimeLimitExceeded
from redis import Redis
from redis.lock import Lock as RedisLock
from sqlalchemy.orm import Session

from onyx.background.celery.apps.app_base import task_logger
from onyx.background.celery.celery_utils import extract_ids_from_runnable_connector
from onyx.background.celery.tasks.indexing.tasks import IndexingCallback
from onyx.configs.app_configs import ALLOW_SIMULTANEOUS_PRUNING
from onyx.configs.app_configs import JOB_TIMEOUT
from onyx.configs.constants import CELERY_PRUNING_LOCK_TIMEOUT
from onyx.configs.constants import CELERY_VESPA_SYNC_BEAT_LOCK_TIMEOUT
from onyx.configs.constants import DANSWER_REDIS_FUNCTION_LOCK_PREFIX
from onyx.configs.constants import OnyxCeleryPriority
from onyx.configs.constants import OnyxCeleryQueues
from onyx.configs.constants import OnyxCeleryTask
from onyx.configs.constants import OnyxRedisLocks
from onyx.connectors.factory import instantiate_connector
from onyx.connectors.models import InputType
from onyx.db.connector_credential_pair import get_connector_credential_pair
from onyx.db.connector_credential_pair import get_connector_credential_pair_from_id
from onyx.db.connector_credential_pair import get_connector_credential_pairs
from onyx.db.document import get_documents_for_connector_credential_pair
from onyx.db.engine import get_session_with_tenant
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.models import ConnectorCredentialPair
from onyx.redis.redis_connector import RedisConnector
from onyx.redis.redis_pool import get_redis_client
from onyx.utils.logger import pruning_ctx
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _is_pruning_due(cc_pair: ConnectorCredentialPair) -> bool:
    """Returns boolean indicating if pruning is due.

    Next pruning time is calculated as a delta from the last successful prune, or the
    last successful indexing if pruning has never succeeded.

    TODO(rkuo): consider whether we should allow pruning to be immediately rescheduled
    if pruning fails (which is what it does now). A backoff could be reasonable.
    """

    # skip pruning if no prune frequency is set
    # pruning can still be forced via the API which will run a pruning task directly
    if not cc_pair.connector.prune_freq:
        return False

    # skip pruning if not active
    if cc_pair.status != ConnectorCredentialPairStatus.ACTIVE:
        return False

    # skip pruning if the next scheduled prune time hasn't been reached yet
    last_pruned = cc_pair.last_pruned
    if not last_pruned:
        if not cc_pair.last_successful_index_time:
            # if we've never indexed, we can't prune
            return False

        # if never pruned, use the last time the connector indexed successfully
        last_pruned = cc_pair.last_successful_index_time

    next_prune = last_pruned + timedelta(seconds=cc_pair.connector.prune_freq)
    if datetime.now(timezone.utc) < next_prune:
        return False

    return True


@shared_task(
    name=OnyxCeleryTask.CHECK_FOR_PRUNING,
    soft_time_limit=JOB_TIMEOUT,
    bind=True,
)
def check_for_pruning(self: Task, *, tenant_id: str | None) -> bool | None:
    r = get_redis_client(tenant_id=tenant_id)

    lock_beat: RedisLock = r.lock(
        OnyxRedisLocks.CHECK_PRUNE_BEAT_LOCK,
        timeout=CELERY_VESPA_SYNC_BEAT_LOCK_TIMEOUT,
    )

    # these tasks should never overlap
    if not lock_beat.acquire(blocking=False):
        return None

    try:
        cc_pair_ids: list[int] = []
        with get_session_with_tenant(tenant_id) as db_session:
            cc_pairs = get_connector_credential_pairs(db_session)
            for cc_pair_entry in cc_pairs:
                cc_pair_ids.append(cc_pair_entry.id)

        for cc_pair_id in cc_pair_ids:
            lock_beat.reacquire()
            with get_session_with_tenant(tenant_id) as db_session:
                cc_pair = get_connector_credential_pair_from_id(
                    db_session=db_session,
                    cc_pair_id=cc_pair_id,
                )
                if not cc_pair:
                    continue

                if not _is_pruning_due(cc_pair):
                    continue

                tasks_created = try_creating_prune_generator_task(
                    self.app, cc_pair, db_session, r, tenant_id
                )
                if not tasks_created:
                    continue

                task_logger.info(f"Pruning queued: cc_pair={cc_pair.id}")
    except SoftTimeLimitExceeded:
        task_logger.info(
            "Soft time limit exceeded, task is being terminated gracefully."
        )
    except Exception:
        task_logger.exception("Unexpected exception during pruning check")
    finally:
        if lock_beat.owned():
            lock_beat.release()

    return True


def try_creating_prune_generator_task(
    celery_app: Celery,
    cc_pair: ConnectorCredentialPair,
    db_session: Session,
    r: Redis,
    tenant_id: str | None,
) -> int | None:
    """Checks for any conditions that should block the pruning generator task from being
    created, then creates the task.

    Does not check for scheduling related conditions as this function
    is used to trigger prunes immediately, e.g. via the web ui.
    """

    redis_connector = RedisConnector(tenant_id, cc_pair.id)

    if not ALLOW_SIMULTANEOUS_PRUNING:
        count = redis_connector.prune.get_active_task_count()
        if count > 0:
            return None

    LOCK_TIMEOUT = 30

    # we need to serialize starting pruning since it can be triggered either via
    # celery beat or manually (API call)
    lock = r.lock(
        DANSWER_REDIS_FUNCTION_LOCK_PREFIX + "try_creating_prune_generator_task",
        timeout=LOCK_TIMEOUT,
    )

    acquired = lock.acquire(blocking_timeout=LOCK_TIMEOUT / 2)
    if not acquired:
        return None

    try:
        # skip pruning if already pruning
        if redis_connector.prune.fenced:
            return None

        # skip pruning if the cc_pair is deleting
        if redis_connector.delete.fenced:
            return None

        # skip pruning if doc permissions sync is running
        if redis_connector.permissions.fenced:
            return None

        db_session.refresh(cc_pair)
        if cc_pair.status == ConnectorCredentialPairStatus.DELETING:
            return None

        # add a long running generator task to the queue
        redis_connector.prune.generator_clear()
        redis_connector.prune.taskset_clear()

        custom_task_id = f"{redis_connector.prune.generator_task_key}_{uuid4()}"

        celery_app.send_task(
            OnyxCeleryTask.CONNECTOR_PRUNING_GENERATOR_TASK,
            kwargs=dict(
                cc_pair_id=cc_pair.id,
                connector_id=cc_pair.connector_id,
                credential_id=cc_pair.credential_id,
                tenant_id=tenant_id,
            ),
            queue=OnyxCeleryQueues.CONNECTOR_PRUNING,
            task_id=custom_task_id,
            priority=OnyxCeleryPriority.LOW,
        )

        # set this only after all tasks have been added
        redis_connector.prune.set_fence(True)
    except Exception:
        task_logger.exception(f"Unexpected exception: cc_pair={cc_pair.id}")
        return None
    finally:
        if lock.owned():
            lock.release()

    return 1


@shared_task(
    name=OnyxCeleryTask.CONNECTOR_PRUNING_GENERATOR_TASK,
    acks_late=False,
    soft_time_limit=JOB_TIMEOUT,
    track_started=True,
    trail=False,
    bind=True,
)
def connector_pruning_generator_task(
    self: Task,
    cc_pair_id: int,
    connector_id: int,
    credential_id: int,
    tenant_id: str | None,
) -> None:
    """connector pruning task. For a cc pair, this task pulls all document IDs from the source
    and compares those IDs to locally stored documents and deletes all locally stored IDs missing
    from the most recently pulled document ID list"""

    pruning_ctx_dict = pruning_ctx.get()
    pruning_ctx_dict["cc_pair_id"] = cc_pair_id
    pruning_ctx_dict["request_id"] = self.request.id
    pruning_ctx.set(pruning_ctx_dict)

    task_logger.info(f"Pruning generator starting: cc_pair={cc_pair_id}")

    redis_connector = RedisConnector(tenant_id, cc_pair_id)

    r = get_redis_client(tenant_id=tenant_id)

    # set thread_local=False since we don't control what thread the indexing/pruning
    # might run our callback with
    lock: RedisLock = r.lock(
        OnyxRedisLocks.PRUNING_LOCK_PREFIX + f"_{redis_connector.id}",
        timeout=CELERY_PRUNING_LOCK_TIMEOUT,
        thread_local=False,
    )

    acquired = lock.acquire(blocking=False)
    if not acquired:
        task_logger.warning(
            f"Pruning task already running, exiting...: cc_pair={cc_pair_id}"
        )
        return None

    try:
        with get_session_with_tenant(tenant_id) as db_session:
            cc_pair = get_connector_credential_pair(
                db_session=db_session,
                connector_id=connector_id,
                credential_id=credential_id,
            )

            if not cc_pair:
                task_logger.warning(
                    f"cc_pair not found for {connector_id} {credential_id}"
                )
                return

            task_logger.info(
                f"Pruning generator running connector: "
                f"cc_pair={cc_pair_id} "
                f"connector_source={cc_pair.connector.source}"
            )
            runnable_connector = instantiate_connector(
                db_session,
                cc_pair.connector.source,
                InputType.SLIM_RETRIEVAL,
                cc_pair.connector.connector_specific_config,
                cc_pair.credential,
            )

            callback = IndexingCallback(
                0,
                redis_connector.stop.fence_key,
                redis_connector.prune.generator_progress_key,
                lock,
                r,
            )

            # a list of docs in the source
            all_connector_doc_ids: set[str] = extract_ids_from_runnable_connector(
                runnable_connector, callback
            )

            # a list of docs in our local index
            all_indexed_document_ids = {
                doc.id
                for doc in get_documents_for_connector_credential_pair(
                    db_session=db_session,
                    connector_id=connector_id,
                    credential_id=credential_id,
                )
            }

            # generate list of docs to remove (no longer in the source)
            doc_ids_to_remove = list(all_indexed_document_ids - all_connector_doc_ids)

            task_logger.info(
                "Pruning set collected: "
                f"cc_pair={cc_pair_id} "
                f"connector_source={cc_pair.connector.source} "
                f"docs_to_remove={len(doc_ids_to_remove)}"
            )

            task_logger.info(
                f"RedisConnector.prune.generate_tasks starting. cc_pair={cc_pair_id}"
            )
            tasks_generated = redis_connector.prune.generate_tasks(
                set(doc_ids_to_remove), self.app, db_session, None
            )
            if tasks_generated is None:
                return None

            task_logger.info(
                "RedisConnector.prune.generate_tasks finished. "
                f"cc_pair={cc_pair_id} tasks_generated={tasks_generated}"
            )

            redis_connector.prune.generator_complete = tasks_generated
    except Exception as e:
        task_logger.exception(
            f"Failed to run pruning: cc_pair={cc_pair_id} connector={connector_id}"
        )

        redis_connector.prune.reset()
        raise e
    finally:
        if lock.owned():
            lock.release()

        task_logger.info(f"Pruning generator finished: cc_pair={cc_pair_id}")
