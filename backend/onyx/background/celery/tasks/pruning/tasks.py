import time
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any
from typing import cast
from uuid import uuid4

from celery import Celery
from celery import shared_task
from celery import Task
from celery.exceptions import SoftTimeLimitExceeded
from pydantic import ValidationError
from redis import Redis
from redis.lock import Lock as RedisLock
from sqlalchemy.orm import Session

from onyx.background.celery.apps.app_base import task_logger
from onyx.background.celery.celery_redis import celery_find_task
from onyx.background.celery.celery_redis import celery_get_queue_length
from onyx.background.celery.celery_redis import celery_get_queued_task_ids
from onyx.background.celery.celery_redis import celery_get_unacked_task_ids
from onyx.background.celery.celery_utils import extract_ids_from_runnable_connector
from onyx.background.celery.tasks.beat_schedule import CLOUD_BEAT_MULTIPLIER_DEFAULT
from onyx.background.celery.tasks.docprocessing.utils import IndexingCallbackBase
from onyx.configs.app_configs import ALLOW_SIMULTANEOUS_PRUNING
from onyx.configs.app_configs import JOB_TIMEOUT
from onyx.configs.constants import CELERY_GENERIC_BEAT_LOCK_TIMEOUT
from onyx.configs.constants import CELERY_PRUNING_LOCK_TIMEOUT
from onyx.configs.constants import CELERY_TASK_WAIT_FOR_FENCE_TIMEOUT
from onyx.configs.constants import DANSWER_REDIS_FUNCTION_LOCK_PREFIX
from onyx.configs.constants import OnyxCeleryPriority
from onyx.configs.constants import OnyxCeleryQueues
from onyx.configs.constants import OnyxCeleryTask
from onyx.configs.constants import OnyxRedisConstants
from onyx.configs.constants import OnyxRedisLocks
from onyx.configs.constants import OnyxRedisSignals
from onyx.connectors.factory import instantiate_connector
from onyx.connectors.models import InputType
from onyx.db.connector import mark_ccpair_as_pruned
from onyx.db.connector_credential_pair import get_connector_credential_pair
from onyx.db.connector_credential_pair import get_connector_credential_pair_from_id
from onyx.db.connector_credential_pair import get_connector_credential_pairs
from onyx.db.document import get_documents_for_connector_credential_pair
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.enums import SyncStatus
from onyx.db.enums import SyncType
from onyx.db.models import ConnectorCredentialPair
from onyx.db.sync_record import insert_sync_record
from onyx.db.sync_record import update_sync_record_status
from onyx.db.tag import delete_orphan_tags__no_commit
from onyx.redis.redis_connector import RedisConnector
from onyx.redis.redis_connector_prune import RedisConnectorPrune
from onyx.redis.redis_connector_prune import RedisConnectorPrunePayload
from onyx.redis.redis_pool import get_redis_client
from onyx.redis.redis_pool import get_redis_replica_client
from onyx.server.runtime.onyx_runtime import OnyxRuntime
from onyx.server.utils import make_short_id
from onyx.utils.logger import format_error_for_logging
from onyx.utils.logger import LoggerContextVars
from onyx.utils.logger import pruning_ctx
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT

logger = setup_logger()


def _get_pruning_block_expiration() -> int:
    """
    Compute the expiration time for the pruning block signal.
    Base expiration is 60 seconds (1 minute), multiplied by the beat multiplier only in MULTI_TENANT mode.
    """
    base_expiration = 60  # seconds

    if not MULTI_TENANT:
        return base_expiration

    try:
        beat_multiplier = OnyxRuntime.get_beat_multiplier()
    except Exception:
        beat_multiplier = CLOUD_BEAT_MULTIPLIER_DEFAULT

    return int(base_expiration * beat_multiplier)


def _get_fence_validation_block_expiration() -> int:
    """
    Compute the expiration time for the fence validation block signal.
    Base expiration is 300 seconds, multiplied by the beat multiplier only in MULTI_TENANT mode.
    """
    base_expiration = 300  # seconds

    if not MULTI_TENANT:
        return base_expiration

    try:
        beat_multiplier = OnyxRuntime.get_beat_multiplier()
    except Exception:
        beat_multiplier = CLOUD_BEAT_MULTIPLIER_DEFAULT

    return int(base_expiration * beat_multiplier)


class PruneCallback(IndexingCallbackBase):
    def progress(self, tag: str, amount: int) -> None:
        self.redis_connector.prune.set_active()
        super().progress(tag, amount)


"""Jobs / utils for kicking off pruning tasks."""


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

        # if never pruned, use the connector creation time. We could also
        # compute the completion time of the first successful index attempt, but
        # that is a reasonably heavy operation. This is a reasonable approximation —
        # in the worst case, we'll prune a little bit earlier than we should.
        last_pruned = cc_pair.connector.time_created

    next_prune = last_pruned + timedelta(seconds=cc_pair.connector.prune_freq)
    return datetime.now(timezone.utc) >= next_prune


@shared_task(
    name=OnyxCeleryTask.CHECK_FOR_PRUNING,
    ignore_result=True,
    soft_time_limit=JOB_TIMEOUT,
    bind=True,
)
def check_for_pruning(self: Task, *, tenant_id: str) -> bool | None:
    r = get_redis_client()
    r_replica = get_redis_replica_client()
    r_celery: Redis = self.app.broker_connection().channel().client  # type: ignore

    lock_beat: RedisLock = r.lock(
        OnyxRedisLocks.CHECK_PRUNE_BEAT_LOCK,
        timeout=CELERY_GENERIC_BEAT_LOCK_TIMEOUT,
    )

    # these tasks should never overlap
    if not lock_beat.acquire(blocking=False):
        return None

    try:
        # the entire task needs to run frequently in order to finalize pruning

        # but pruning only kicks off once per hour
        if not r.exists(OnyxRedisSignals.BLOCK_PRUNING):

            task_logger.info("Checking for pruning due")

            cc_pair_ids: list[int] = []
            with get_session_with_current_tenant() as db_session:
                cc_pairs = get_connector_credential_pairs(db_session)
                for cc_pair_entry in cc_pairs:
                    cc_pair_ids.append(cc_pair_entry.id)

            for cc_pair_id in cc_pair_ids:
                lock_beat.reacquire()
                with get_session_with_current_tenant() as db_session:
                    cc_pair = get_connector_credential_pair_from_id(
                        db_session=db_session,
                        cc_pair_id=cc_pair_id,
                    )
                    if not cc_pair:
                        logger.error(f"CC pair not found: {cc_pair_id}")
                        continue

                    if not _is_pruning_due(cc_pair):
                        logger.info(f"CC pair not due for pruning: {cc_pair_id}")
                        continue

                    payload_id = try_creating_prune_generator_task(
                        self.app, cc_pair, db_session, r, tenant_id
                    )
                    if not payload_id:
                        logger.info(f"Pruning not created: {cc_pair_id}")
                        continue

                    task_logger.info(
                        f"Pruning queued: cc_pair={cc_pair.id} id={payload_id}"
                    )
            r.set(OnyxRedisSignals.BLOCK_PRUNING, 1, ex=_get_pruning_block_expiration())

        # we want to run this less frequently than the overall task
        lock_beat.reacquire()
        if not r.exists(OnyxRedisSignals.BLOCK_VALIDATE_PRUNING_FENCES):
            # clear any permission fences that don't have associated celery tasks in progress
            # tasks can be in the queue in redis, in reserved tasks (prefetched by the worker),
            # or be currently executing
            try:
                validate_pruning_fences(tenant_id, r, r_replica, r_celery, lock_beat)
            except Exception:
                task_logger.exception("Exception while validating pruning fences")

            r.set(
                OnyxRedisSignals.BLOCK_VALIDATE_PRUNING_FENCES,
                1,
                ex=_get_fence_validation_block_expiration(),
            )

        # use a lookup table to find active fences. We still have to verify the fence
        # exists since it is an optimization and not the source of truth.
        lock_beat.reacquire()
        keys = cast(set[Any], r_replica.smembers(OnyxRedisConstants.ACTIVE_FENCES))
        for key in keys:
            key_bytes = cast(bytes, key)

            if not r.exists(key_bytes):
                r.srem(OnyxRedisConstants.ACTIVE_FENCES, key_bytes)
                continue

            key_str = key_bytes.decode("utf-8")
            if key_str.startswith(RedisConnectorPrune.FENCE_PREFIX):
                with get_session_with_current_tenant() as db_session:
                    monitor_ccpair_pruning_taskset(tenant_id, key_bytes, r, db_session)
    except SoftTimeLimitExceeded:
        task_logger.info(
            "Soft time limit exceeded, task is being terminated gracefully."
        )
    except Exception as e:
        error_msg = format_error_for_logging(e)
        task_logger.warning(f"Unexpected pruning check exception: {error_msg}")
        task_logger.exception("Unexpected exception during pruning check")
    finally:
        if lock_beat.owned():
            lock_beat.release()
    task_logger.info(f"check_for_pruning finished: tenant={tenant_id}")
    return True


def try_creating_prune_generator_task(
    celery_app: Celery,
    cc_pair: ConnectorCredentialPair,
    db_session: Session,
    r: Redis,
    tenant_id: str,
) -> str | None:
    """Checks for any conditions that should block the pruning generator task from being
    created, then creates the task.

    Does not check for scheduling related conditions as this function
    is used to trigger prunes immediately, e.g. via the web ui.
    """

    logger.info(f"try_creating_prune_generator_task: cc_pair={cc_pair.id}")

    redis_connector = RedisConnector(tenant_id, cc_pair.id)

    if not ALLOW_SIMULTANEOUS_PRUNING:
        count = redis_connector.prune.get_active_task_count()
        if count > 0:
            logger.info(
                f"try_creating_prune_generator_task: cc_pair={cc_pair.id} no simultaneous pruning allowed"
            )
            return None

    LOCK_TIMEOUT = 30

    # we need to serialize starting pruning since it can be triggered either via
    # celery beat or manually (API call)
    lock: RedisLock = r.lock(
        DANSWER_REDIS_FUNCTION_LOCK_PREFIX + "try_creating_prune_generator_task",
        timeout=LOCK_TIMEOUT,
    )

    acquired = lock.acquire(blocking_timeout=LOCK_TIMEOUT / 2)
    if not acquired:
        logger.info(
            f"try_creating_prune_generator_task: cc_pair={cc_pair.id} lock not acquired"
        )
        return None

    try:
        # skip pruning if already pruning
        if redis_connector.prune.fenced:
            logger.info(
                f"try_creating_prune_generator_task: cc_pair={cc_pair.id} already pruning"
            )
            return None

        # skip pruning if the cc_pair is deleting
        if redis_connector.delete.fenced:
            logger.info(
                f"try_creating_prune_generator_task: cc_pair={cc_pair.id} deleting"
            )
            return None

        # skip pruning if doc permissions sync is running
        if redis_connector.permissions.fenced:
            logger.info(
                f"try_creating_prune_generator_task: cc_pair={cc_pair.id} permissions sync running"
            )
            return None

        db_session.refresh(cc_pair)
        if cc_pair.status == ConnectorCredentialPairStatus.DELETING:
            logger.info(
                f"try_creating_prune_generator_task: cc_pair={cc_pair.id} deleting"
            )
            return None

        # add a long running generator task to the queue
        redis_connector.prune.generator_clear()
        redis_connector.prune.taskset_clear()

        custom_task_id = f"{redis_connector.prune.generator_task_key}_{uuid4()}"

        # create before setting fence to avoid race condition where the monitoring
        # task updates the sync record before it is created
        try:
            insert_sync_record(
                db_session=db_session,
                entity_id=cc_pair.id,
                sync_type=SyncType.PRUNING,
            )
        except Exception:
            task_logger.exception("insert_sync_record exceptioned.")

        # signal active before the fence is set
        redis_connector.prune.set_active()

        # set a basic fence to start
        payload = RedisConnectorPrunePayload(
            id=make_short_id(),
            submitted=datetime.now(timezone.utc),
            started=None,
            celery_task_id=None,
        )
        redis_connector.prune.set_fence(payload)

        result = celery_app.send_task(
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

        # fill in the celery task id
        payload.celery_task_id = result.id
        redis_connector.prune.set_fence(payload)

        payload_id = payload.id
    except Exception as e:
        error_msg = format_error_for_logging(e)
        task_logger.warning(
            f"Unexpected try_creating_prune_generator_task exception: cc_pair={cc_pair.id} {error_msg}"
        )
        task_logger.exception(f"Unexpected exception: cc_pair={cc_pair.id}")
        return None
    finally:
        if lock.owned():
            lock.release()
    task_logger.info(
        f"try_creating_prune_generator_task finished: cc_pair={cc_pair.id} payload_id={payload_id}"
    )
    return payload_id


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
    tenant_id: str,
) -> None:
    """connector pruning task. For a cc pair, this task pulls all document IDs from the source
    and compares those IDs to locally stored documents and deletes all locally stored IDs missing
    from the most recently pulled document ID list"""

    payload_id: str | None = None

    LoggerContextVars.reset()

    pruning_ctx_dict = pruning_ctx.get()
    pruning_ctx_dict["cc_pair_id"] = cc_pair_id
    pruning_ctx_dict["request_id"] = self.request.id
    pruning_ctx.set(pruning_ctx_dict)

    task_logger.info(f"Pruning generator starting: cc_pair={cc_pair_id}")

    redis_connector = RedisConnector(tenant_id, cc_pair_id)

    r = get_redis_client()

    # this wait is needed to avoid a race condition where
    # the primary worker sends the task and it is immediately executed
    # before the primary worker can finalize the fence
    start = time.monotonic()
    while True:
        if time.monotonic() - start > CELERY_TASK_WAIT_FOR_FENCE_TIMEOUT:
            raise ValueError(
                f"connector_prune_generator_task - timed out waiting for fence to be ready: "
                f"fence={redis_connector.prune.fence_key}"
            )

        if not redis_connector.prune.fenced:  # The fence must exist
            raise ValueError(
                f"connector_prune_generator_task - fence not found: "
                f"fence={redis_connector.prune.fence_key}"
            )

        payload = redis_connector.prune.payload  # The payload must exist
        if not payload:
            raise ValueError(
                "connector_prune_generator_task: payload invalid or not found"
            )

        if payload.celery_task_id is None:
            logger.info(
                f"connector_prune_generator_task - Waiting for fence: "
                f"fence={redis_connector.prune.fence_key}"
            )
            time.sleep(1)
            continue

        payload_id = payload.id

        logger.info(
            f"connector_prune_generator_task - Fence found, continuing...: "
            f"fence={redis_connector.prune.fence_key} "
            f"payload_id={payload.id}"
        )
        break

    # set thread_local=False since we don't control what thread the indexing/pruning
    # might run our callback with
    lock: RedisLock = r.lock(
        OnyxRedisLocks.PRUNING_LOCK_PREFIX + f"_{redis_connector.cc_pair_id}",
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
        with get_session_with_current_tenant() as db_session:
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

            payload = redis_connector.prune.payload
            if not payload:
                raise ValueError(f"No fence payload found: cc_pair={cc_pair_id}")

            new_payload = RedisConnectorPrunePayload(
                id=payload.id,
                submitted=payload.submitted,
                started=datetime.now(timezone.utc),
                celery_task_id=payload.celery_task_id,
            )
            redis_connector.prune.set_fence(new_payload)

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

            callback = PruneCallback(
                0,
                redis_connector,
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
            f"Pruning exceptioned: cc_pair={cc_pair_id} "
            f"connector={connector_id} "
            f"payload_id={payload_id}"
        )

        redis_connector.prune.reset()
        raise e
    finally:
        if lock.owned():
            lock.release()

    task_logger.info(
        f"Pruning generator finished: cc_pair={cc_pair_id} payload_id={payload_id}"
    )


"""Monitoring pruning utils"""


def monitor_ccpair_pruning_taskset(
    tenant_id: str, key_bytes: bytes, r: Redis, db_session: Session
) -> None:
    fence_key = key_bytes.decode("utf-8")
    cc_pair_id_str = RedisConnector.get_id_from_fence_key(fence_key)
    if cc_pair_id_str is None:
        task_logger.warning(
            f"monitor_ccpair_pruning_taskset: could not parse cc_pair_id from {fence_key}"
        )
        return

    cc_pair_id = int(cc_pair_id_str)

    redis_connector = RedisConnector(tenant_id, cc_pair_id)
    if not redis_connector.prune.fenced:
        return

    initial = redis_connector.prune.generator_complete
    if initial is None:
        return

    remaining = redis_connector.prune.get_remaining()
    task_logger.info(
        f"Connector pruning progress: cc_pair={cc_pair_id} remaining={remaining} initial={initial}"
    )
    if remaining > 0:
        return

    mark_ccpair_as_pruned(int(cc_pair_id), db_session)
    task_logger.info(
        f"Connector pruning finished: cc_pair={cc_pair_id} num_pruned={initial}"
    )

    update_sync_record_status(
        db_session=db_session,
        entity_id=cc_pair_id,
        sync_type=SyncType.PRUNING,
        sync_status=SyncStatus.SUCCESS,
        num_docs_synced=initial,
    )

    delete_orphan_tags__no_commit(db_session)

    redis_connector.prune.taskset_clear()
    redis_connector.prune.generator_clear()
    redis_connector.prune.set_fence(None)


def validate_pruning_fences(
    tenant_id: str,
    r: Redis,
    r_replica: Redis,
    r_celery: Redis,
    lock_beat: RedisLock,
) -> None:
    # building lookup table can be expensive, so we won't bother
    # validating until the queue is small
    PERMISSION_SYNC_VALIDATION_MAX_QUEUE_LEN = 1024

    queue_len = celery_get_queue_length(OnyxCeleryQueues.CONNECTOR_DELETION, r_celery)
    if queue_len > PERMISSION_SYNC_VALIDATION_MAX_QUEUE_LEN:
        return

    # the queue for a single pruning generator task
    reserved_generator_tasks = celery_get_unacked_task_ids(
        OnyxCeleryQueues.CONNECTOR_PRUNING, r_celery
    )

    # the queue for a reasonably large set of lightweight deletion tasks
    queued_upsert_tasks = celery_get_queued_task_ids(
        OnyxCeleryQueues.CONNECTOR_DELETION, r_celery
    )

    # Use replica for this because the worst thing that happens
    # is that we don't run the validation on this pass
    keys = cast(set[Any], r_replica.smembers(OnyxRedisConstants.ACTIVE_FENCES))
    for key in keys:
        key_bytes = cast(bytes, key)
        key_str = key_bytes.decode("utf-8")
        if not key_str.startswith(RedisConnectorPrune.FENCE_PREFIX):
            continue

        validate_pruning_fence(
            tenant_id,
            key_bytes,
            reserved_generator_tasks,
            queued_upsert_tasks,
            r,
            r_celery,
        )

        lock_beat.reacquire()

    return


def validate_pruning_fence(
    tenant_id: str,
    key_bytes: bytes,
    reserved_tasks: set[str],
    queued_tasks: set[str],
    r: Redis,
    r_celery: Redis,
) -> None:
    """See validate_indexing_fence for an overall idea of validation flows.

    queued_tasks: the celery queue of lightweight permission sync tasks
    reserved_tasks: prefetched tasks for sync task generator
    """
    # if the fence doesn't exist, there's nothing to do
    fence_key = key_bytes.decode("utf-8")
    cc_pair_id_str = RedisConnector.get_id_from_fence_key(fence_key)
    if cc_pair_id_str is None:
        task_logger.warning(
            f"validate_pruning_fence - could not parse id from {fence_key}"
        )
        return

    cc_pair_id = int(cc_pair_id_str)
    # parse out metadata and initialize the helper class with it
    redis_connector = RedisConnector(tenant_id, int(cc_pair_id))

    # check to see if the fence/payload exists
    if not redis_connector.prune.fenced:
        return

    # in the cloud, the payload format may have changed ...
    # it's a little sloppy, but just reset the fence for now if that happens
    # TODO: add intentional cleanup/abort logic
    try:
        payload = redis_connector.prune.payload
    except ValidationError:
        task_logger.exception(
            "validate_pruning_fence - "
            "Resetting fence because fence schema is out of date: "
            f"cc_pair={cc_pair_id} "
            f"fence={fence_key}"
        )

        redis_connector.prune.reset()
        return

    if not payload:
        return

    if not payload.celery_task_id:
        return

    # OK, there's actually something for us to validate

    # either the generator task must be in flight or its subtasks must be
    found = celery_find_task(
        payload.celery_task_id,
        OnyxCeleryQueues.CONNECTOR_PRUNING,
        r_celery,
    )
    if found:
        # the celery task exists in the redis queue
        redis_connector.prune.set_active()
        return

    if payload.celery_task_id in reserved_tasks:
        # the celery task was prefetched and is reserved within a worker
        redis_connector.prune.set_active()
        return

    # look up every task in the current taskset in the celery queue
    # every entry in the taskset should have an associated entry in the celery task queue
    # because we get the celery tasks first, the entries in our own pruning taskset
    # should be roughly a subset of the tasks in celery

    # this check isn't very exact, but should be sufficient over a period of time
    # A single successful check over some number of attempts is sufficient.

    # TODO: if the number of tasks in celery is much lower than than the taskset length
    # we might be able to shortcut the lookup since by definition some of the tasks
    # must not exist in celery.

    tasks_scanned = 0
    tasks_not_in_celery = 0  # a non-zero number after completing our check is bad

    for member in r.sscan_iter(redis_connector.prune.taskset_key):
        tasks_scanned += 1

        member_bytes = cast(bytes, member)
        member_str = member_bytes.decode("utf-8")
        if member_str in queued_tasks:
            continue

        if member_str in reserved_tasks:
            continue

        tasks_not_in_celery += 1

    task_logger.info(
        "validate_pruning_fence task check: "
        f"tasks_scanned={tasks_scanned} tasks_not_in_celery={tasks_not_in_celery}"
    )

    # we're active if there are still tasks to run and those tasks all exist in celery
    if tasks_scanned > 0 and tasks_not_in_celery == 0:
        redis_connector.prune.set_active()
        return

    # we may want to enable this check if using the active task list somehow isn't good enough
    # if redis_connector_index.generator_locked():
    #     logger.info(f"{payload.celery_task_id} is currently executing.")

    # if we get here, we didn't find any direct indication that the associated celery tasks exist,
    # but they still might be there due to gaps in our ability to check states during transitions
    # Checking the active signal safeguards us against these transition periods
    # (which has a duration that allows us to bridge those gaps)
    if redis_connector.prune.active():
        return

    # celery tasks don't exist and the active signal has expired, possibly due to a crash. Clean it up.
    task_logger.warning(
        "validate_pruning_fence - "
        "Resetting fence because no associated celery tasks were found: "
        f"cc_pair={cc_pair_id} "
        f"fence={fence_key} "
        f"payload_id={payload.id}"
    )

    redis_connector.prune.reset()
    return
