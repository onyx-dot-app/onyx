from datetime import datetime
from datetime import timedelta
from datetime import timezone
from uuid import uuid4

import redis
from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from redis import Redis
from sqlalchemy.orm import Session

from danswer.background.celery.celery_app import celery_app
from danswer.background.celery.celery_app import task_logger
from danswer.background.celery.celery_redis import RedisConnectorPruning
from danswer.background.celery.celery_utils import extract_ids_from_runnable_connector
from danswer.configs.app_configs import ALLOW_SIMULTANEOUS_PRUNING
from danswer.configs.app_configs import JOB_TIMEOUT
from danswer.configs.constants import CELERY_VESPA_SYNC_BEAT_LOCK_TIMEOUT
from danswer.configs.constants import DanswerCeleryPriority
from danswer.configs.constants import DanswerCeleryQueues
from danswer.configs.constants import DanswerRedisLocks
from danswer.connectors.factory import instantiate_connector
from danswer.connectors.models import InputType
from danswer.db.connector_credential_pair import get_connector_credential_pair
from danswer.db.connector_credential_pair import get_connector_credential_pairs
from danswer.db.document import get_documents_for_connector_credential_pair
from danswer.db.engine import get_sqlalchemy_engine
from danswer.db.enums import ConnectorCredentialPairStatus
from danswer.db.models import ConnectorCredentialPair
from danswer.redis.redis_pool import get_redis_client


@shared_task(
    name="check_for_prune_task_2",
    soft_time_limit=JOB_TIMEOUT,
)
def check_for_prune_task_2() -> None:
    r = get_redis_client()

    lock_beat = r.lock(
        DanswerRedisLocks.CHECK_PRUNE_BEAT_LOCK,
        timeout=CELERY_VESPA_SYNC_BEAT_LOCK_TIMEOUT,
    )

    try:
        # these tasks should never overlap
        if not lock_beat.acquire(blocking=False):
            return

        with Session(get_sqlalchemy_engine()) as db_session:
            cc_pairs = get_connector_credential_pairs(db_session)
            for cc_pair in cc_pairs:
                tasks_created = ccpair_pruning_generator_task_creation_helper(
                    cc_pair, db_session, r, lock_beat
                )
                if not tasks_created:
                    continue

                task_logger.info(f"Pruning started: cc_pair_id={cc_pair.id}")
    except SoftTimeLimitExceeded:
        task_logger.info(
            "Soft time limit exceeded, task is being terminated gracefully."
        )
    except Exception:
        task_logger.exception("Unexpected exception")
    finally:
        if lock_beat.owned():
            lock_beat.release()


def ccpair_pruning_generator_task_creation_helper(
    cc_pair: ConnectorCredentialPair,
    db_session: Session,
    r: Redis,
    lock_beat: redis.lock.Lock,
) -> int | None:
    """Returns an int if pruning is triggered.
    The int represents the number of prune tasks generated (in this case, only one
    because the task is a long running generator task.)
    Returns None if no pruning is triggered (due to not being needed or
    other reasons such as simultaneous pruning restrictions.

    Checks for scheduling related conditions, then delegates the rest of the checks to
    try_creating_prune_generator_task.
    """

    lock_beat.reacquire()

    # skip pruning if no prune frequency is set
    # pruning can still be forced via the API which will run a pruning task directly
    if not cc_pair.connector.prune_freq:
        return None

    # skip pruning if the next scheduled prune time hasn't been reached yet
    last_pruned = cc_pair.last_pruned
    if not last_pruned:
        # if never pruned, use the connector time created as the last_pruned time
        last_pruned = cc_pair.connector.time_created

    next_prune = last_pruned + timedelta(seconds=cc_pair.connector.prune_freq)
    if datetime.now(timezone.utc) < next_prune:
        return None

    return try_creating_prune_generator_task(cc_pair, db_session, r)


def try_creating_prune_generator_task(
    cc_pair: ConnectorCredentialPair,
    db_session: Session,
    r: Redis,
) -> int | None:
    """Checks for any conditions that should block the pruning generator task from being
    created, then creates the task.

    Does not check for scheduling related conditions as this function
    is used to trigger prunes immediately.
    """

    if not ALLOW_SIMULTANEOUS_PRUNING:
        for key in r.scan_iter(RedisConnectorPruning.FENCE_PREFIX + "*"):
            return None

    rcp = RedisConnectorPruning(cc_pair.id)

    # skip pruning if already pruning
    if r.exists(rcp.fence_key):
        return None

    # skip pruning if the cc_pair is deleting
    db_session.refresh(cc_pair)
    if cc_pair.status == ConnectorCredentialPairStatus.DELETING:
        return None

    # add a long running generator task to the queue
    r.delete(rcp.generator_complete_key)
    r.delete(rcp.taskset_key)

    custom_task_id = f"{rcp.generator_task_id_prefix}_{uuid4()}"

    celery_app.send_task(
        "connector_pruning_generator_task",
        kwargs=dict(
            connector_id=cc_pair.connector_id, credential_id=cc_pair.credential_id
        ),
        queue=DanswerCeleryQueues.CONNECTOR_PRUNING,
        task_id=custom_task_id,
        priority=DanswerCeleryPriority.LOW,
    )

    # set this only after all tasks have been added
    r.set(rcp.fence_key, 1)
    return 1


@shared_task(name="connector_pruning_generator_task", soft_time_limit=JOB_TIMEOUT)
def connector_pruning_generator_task(connector_id: int, credential_id: int) -> None:
    """connector pruning task. For a cc pair, this task pulls all document IDs from the source
    and compares those IDs to locally stored documents and deletes all locally stored IDs missing
    from the most recently pulled document ID list"""

    r = get_redis_client()

    with Session(get_sqlalchemy_engine()) as db_session:
        try:
            cc_pair = get_connector_credential_pair(
                db_session=db_session,
                connector_id=connector_id,
                credential_id=credential_id,
            )

            if not cc_pair:
                task_logger.warning(
                    f"ccpair not found for {connector_id} {credential_id}"
                )
                return

            rcp = RedisConnectorPruning(cc_pair.id)

            # Define the callback function
            def redis_increment_callback(amount: int) -> None:
                r.incrby(rcp.generator_progress_key, amount)

            runnable_connector = instantiate_connector(
                db_session,
                cc_pair.connector.source,
                InputType.PRUNE,
                cc_pair.connector.connector_specific_config,
                cc_pair.credential,
            )

            # a list of docs in the source
            all_connector_doc_ids: set[str] = extract_ids_from_runnable_connector(
                runnable_connector, redis_increment_callback
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
                f"cc_pair_id={cc_pair.id} "
                f"docs_to_remove={len(doc_ids_to_remove)} "
                f"doc_source={cc_pair.connector.source}"
            )

            rcp.documents_to_prune = set(doc_ids_to_remove)

            task_logger.info(
                f"RedisConnectorPruning.generate_tasks starting. cc_pair_id={cc_pair.id}"
            )
            tasks_generated = rcp.generate_tasks(celery_app, db_session, r, None)
            if tasks_generated is None:
                return None

            task_logger.info(
                f"RedisConnectorPruning.generate_tasks finished. "
                f"cc_pair_id={cc_pair.id} tasks_generated={tasks_generated}"
            )

            r.set(rcp.generator_complete_key, tasks_generated)
        except Exception as e:
            task_logger.exception(
                f"Failed to run pruning for connector id {connector_id}."
            )

            r.delete(rcp.generator_progress_key)
            r.delete(rcp.taskset_key)
            r.delete(rcp.fence_key)
            raise e
