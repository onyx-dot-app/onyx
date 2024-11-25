from datetime import datetime
from datetime import timedelta
from datetime import timezone
from uuid import uuid4

from celery import Celery
from celery import shared_task
from celery import Task
from celery.exceptions import SoftTimeLimitExceeded
from redis import Redis
from sqlalchemy.orm import Session

from danswer.background.celery.apps.app_base import task_logger
from danswer.background.celery.celery_utils import extract_ids_from_runnable_connector
from danswer.background.celery.tasks.indexing.tasks import RunIndexingCallback
from danswer.configs.app_configs import ALLOW_SIMULTANEOUS_PRUNING
from danswer.configs.app_configs import JOB_TIMEOUT
from danswer.configs.constants import CELERY_PRUNING_LOCK_TIMEOUT
from danswer.configs.constants import CELERY_VESPA_SYNC_BEAT_LOCK_TIMEOUT
from danswer.configs.constants import DANSWER_REDIS_FUNCTION_LOCK_PREFIX
from danswer.configs.constants import DanswerCeleryPriority
from danswer.configs.constants import DanswerCeleryQueues
from danswer.configs.constants import DanswerRedisLocks
from danswer.connectors.factory import instantiate_connector
from danswer.connectors.models import InputType
from danswer.db.connector_credential_pair import get_connector_credential_pair
from danswer.db.connector_credential_pair import get_connector_credential_pair_from_id
from danswer.db.connector_credential_pair import get_connector_credential_pairs
from danswer.db.document import get_documents_for_connector_credential_pair
from danswer.db.engine import get_session_with_tenant
from danswer.db.enums import ConnectorCredentialPairStatus
from danswer.db.models import ConnectorCredentialPair
from danswer.redis.redis_connector import RedisConnector
from danswer.redis.redis_pool import get_redis_client
from danswer.utils.logger import pruning_ctx
from danswer.utils.logger import setup_logger

logger = setup_logger()


@shared_task(
    name="check_for_pruning",
    soft_time_limit=JOB_TIMEOUT,
    bind=True,
)
def check_for_pruning(self: Task, *, tenant_id: str | None) -> None:
    r = get_redis_client(tenant_id=tenant_id)

    lock_beat = r.lock(
        DanswerRedisLocks.CHECK_PRUNE_BEAT_LOCK,
        timeout=CELERY_VESPA_SYNC_BEAT_LOCK_TIMEOUT,
    )

    try:
        # these tasks should never overlap
        if not lock_beat.acquire(blocking=False):
            return

        cc_pair_ids: list[int] = []
        with get_session_with_tenant(tenant_id) as db_session:
            cc_pairs = get_connector_credential_pairs(db_session)
            for cc_pair_entry in cc_pairs:
                cc_pair_ids.append(cc_pair_entry.id)

        for cc_pair_id in cc_pair_ids:
            lock_beat.reacquire()
            with get_session_with_tenant(tenant_id) as db_session:
                cc_pair = get_connector_credential_pair_from_id(cc_pair_id, db_session)
                if not cc_pair:
                    continue

                if not is_pruning_due(cc_pair, db_session, r):
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
        task_logger.exception(f"Unexpected exception: tenant={tenant_id}")
    finally:
        if lock_beat.owned():
            lock_beat.release()


def is_pruning_due(
    cc_pair: ConnectorCredentialPair,
    db_session: Session,
    r: Redis,
) -> bool:
    """Returns an int if pruning is triggered.
    The int represents the number of prune tasks generated (in this case, only one
    because the task is a long running generator task.)
    Returns None if no pruning is triggered (due to not being needed or
    other reasons such as simultaneous pruning restrictions.

    Checks for scheduling related conditions, then delegates the rest of the checks to
    try_creating_prune_generator_task.
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
        if redis_connector.prune.fenced:  # skip pruning if already pruning
            return None

        if redis_connector.delete.fenced:  # skip pruning if the cc_pair is deleting
            return None

        db_session.refresh(cc_pair)
        if cc_pair.status == ConnectorCredentialPairStatus.DELETING:
            return None

        # add a long running generator task to the queue
        redis_connector.prune.generator_clear()
        redis_connector.prune.taskset_clear()

        custom_task_id = f"{redis_connector.prune.generator_task_key}_{uuid4()}"

        celery_app.send_task(
            "connector_pruning_generator_task",
            kwargs=dict(
                cc_pair_id=cc_pair.id,
                connector_id=cc_pair.connector_id,
                credential_id=cc_pair.credential_id,
                tenant_id=tenant_id,
            ),
            queue=DanswerCeleryQueues.CONNECTOR_PRUNING,
            task_id=custom_task_id,
            priority=DanswerCeleryPriority.LOW,
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
    name="connector_pruning_generator_task",
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

    redis_connector = RedisConnector(tenant_id, cc_pair_id)

    r = get_redis_client(tenant_id=tenant_id)

    lock = r.lock(
        DanswerRedisLocks.PRUNING_LOCK_PREFIX + f"_{redis_connector.id}",
        timeout=CELERY_PRUNING_LOCK_TIMEOUT,
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

            runnable_connector = instantiate_connector(
                db_session,
                cc_pair.connector.source,
                InputType.SLIM_RETRIEVAL,
                cc_pair.connector.connector_specific_config,
                cc_pair.credential,
            )

            callback = RunIndexingCallback(
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
                f"Pruning set collected: "
                f"cc_pair={cc_pair_id} "
                f"docs_to_remove={len(doc_ids_to_remove)} "
                f"doc_source={cc_pair.connector.source}"
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
                f"RedisConnector.prune.generate_tasks finished. "
                f"cc_pair={cc_pair_id} tasks_generated={tasks_generated}"
            )

            redis_connector.prune.generator_complete = tasks_generated
    except Exception as e:
        task_logger.exception(
            f"Failed to run pruning: cc_pair={cc_pair_id} connector={connector_id}"
        )

        redis_connector.prune.generator_clear()
        redis_connector.prune.taskset_clear()
        redis_connector.prune.set_fence(False)
        raise e
    finally:
        if lock.owned():
            lock.release()
