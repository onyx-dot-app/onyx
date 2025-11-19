import traceback
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import cast

from celery import Celery
from celery import shared_task
from celery import Task
from celery.exceptions import SoftTimeLimitExceeded
from pydantic import ValidationError
from redis import Redis
from redis.lock import Lock as RedisLock
from sqlalchemy.orm import Session

from onyx.background.celery.apps.app_base import task_logger
from onyx.background.celery.celery_redis import celery_get_queue_length
from onyx.background.celery.celery_redis import celery_get_queued_task_ids
from onyx.configs.app_configs import JOB_TIMEOUT
from onyx.configs.constants import CELERY_GENERIC_BEAT_LOCK_TIMEOUT
from onyx.configs.constants import OnyxCeleryQueues
from onyx.configs.constants import OnyxCeleryTask
from onyx.configs.constants import OnyxRedisConstants
from onyx.configs.constants import OnyxRedisLocks
from onyx.configs.constants import OnyxRedisSignals
from onyx.db.connector import fetch_connector_by_id
from onyx.db.connector_credential_pair import add_deletion_failure_message
from onyx.db.connector_credential_pair import (
    delete_connector_credential_pair__no_commit,
)
from onyx.db.connector_credential_pair import get_connector_credential_pair_from_id
from onyx.db.connector_credential_pair import get_connector_credential_pairs
from onyx.db.document import (
    delete_all_documents_by_connector_credential_pair__no_commit,
)
from onyx.db.document import get_document_ids_for_connector_credential_pair
from onyx.db.document_set import delete_document_set_cc_pair_relationship__no_commit
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.enums import IndexingStatus
from onyx.db.enums import SyncStatus
from onyx.db.enums import SyncType
from onyx.db.index_attempt import delete_index_attempts
from onyx.db.index_attempt import get_recent_attempts_for_cc_pair
from onyx.db.permission_sync_attempt import (
    delete_doc_permission_sync_attempts__no_commit,
)
from onyx.db.permission_sync_attempt import (
    delete_external_group_permission_sync_attempts__no_commit,
)
from onyx.db.search_settings import get_all_search_settings
from onyx.db.sync_record import cleanup_sync_records
from onyx.db.sync_record import insert_sync_record
from onyx.db.sync_record import update_sync_record_status
from onyx.db.tag import delete_orphan_tags__no_commit
from onyx.redis.redis_connector import RedisConnector
from onyx.redis.redis_connector_delete import RedisConnectorDelete
from onyx.redis.redis_connector_delete import RedisConnectorDeletePayload
from onyx.redis.redis_pool import get_redis_client
from onyx.redis.redis_pool import get_redis_replica_client
from onyx.utils.variable_functionality import (
    fetch_versioned_implementation_with_fallback,
)
from onyx.utils.variable_functionality import noop_fallback


class TaskDependencyError(RuntimeError):
    """Raised to the caller to indicate dependent tasks are running that would interfere
    with connector deletion."""


def revoke_tasks_blocking_deletion(
    redis_connector: RedisConnector, db_session: Session, app: Celery
) -> None:
    search_settings_list = get_all_search_settings(db_session)
    for search_settings in search_settings_list:
        try:
            recent_index_attempts = get_recent_attempts_for_cc_pair(
                cc_pair_id=redis_connector.cc_pair_id,
                search_settings_id=search_settings.id,
                limit=1,
                db_session=db_session,
            )
            if (
                recent_index_attempts
                and recent_index_attempts[0].status == IndexingStatus.IN_PROGRESS
                and recent_index_attempts[0].celery_task_id
            ):
                app.control.revoke(recent_index_attempts[0].celery_task_id)
                task_logger.info(
                    f"Revoked indexing task {recent_index_attempts[0].celery_task_id}."
                )
        except Exception:
            task_logger.exception("Exception while revoking indexing task")

    try:
        permissions_sync_payload = redis_connector.permissions.payload
        if permissions_sync_payload and permissions_sync_payload.celery_task_id:
            app.control.revoke(permissions_sync_payload.celery_task_id)
            task_logger.info(
                f"Revoked permissions sync task {permissions_sync_payload.celery_task_id}."
            )
    except Exception:
        task_logger.exception("Exception while revoking pruning task")

    try:
        prune_payload = redis_connector.prune.payload
        if prune_payload and prune_payload.celery_task_id:
            app.control.revoke(prune_payload.celery_task_id)
            task_logger.info(f"Revoked pruning task {prune_payload.celery_task_id}.")
    except Exception:
        task_logger.exception("Exception while revoking permissions sync task")

    try:
        external_group_sync_payload = redis_connector.external_group_sync.payload
        if external_group_sync_payload and external_group_sync_payload.celery_task_id:
            app.control.revoke(external_group_sync_payload.celery_task_id)
            task_logger.info(
                f"Revoked external group sync task {external_group_sync_payload.celery_task_id}."
            )
    except Exception:
        task_logger.exception("Exception while revoking external group sync task")


@shared_task(
    name=OnyxCeleryTask.CHECK_FOR_CONNECTOR_DELETION,
    ignore_result=True,
    soft_time_limit=JOB_TIMEOUT,
    trail=False,
    bind=True,
)
def check_for_connector_deletion_task(self: Task, *, tenant_id: str) -> bool | None:
    r = get_redis_client()
    r_replica = get_redis_replica_client()
    r_celery: Redis = self.app.broker_connection().channel().client  # type: ignore

    lock_beat: RedisLock = r.lock(
        OnyxRedisLocks.CHECK_CONNECTOR_DELETION_BEAT_LOCK,
        timeout=CELERY_GENERIC_BEAT_LOCK_TIMEOUT,
    )

    # Prevent this task from overlapping with itself
    if not lock_beat.acquire(blocking=False):
        return None

    try:
        # we want to run this less frequently than the overall task
        lock_beat.reacquire()
        if not r.exists(OnyxRedisSignals.BLOCK_VALIDATE_CONNECTOR_DELETION_FENCES):
            # clear fences that don't have associated celery tasks in progress
            try:
                validate_connector_deletion_fences(
                    tenant_id, r, r_replica, r_celery, lock_beat
                )
            except Exception:
                task_logger.exception(
                    "Exception while validating connector deletion fences"
                )

            r.set(OnyxRedisSignals.BLOCK_VALIDATE_CONNECTOR_DELETION_FENCES, 1, ex=300)

        # collect cc_pair_ids
        cc_pair_ids: list[int] = []
        with get_session_with_current_tenant() as db_session:
            cc_pairs = get_connector_credential_pairs(db_session)
            for cc_pair in cc_pairs:
                cc_pair_ids.append(cc_pair.id)

        # try running cleanup on the cc_pair_ids
        for cc_pair_id in cc_pair_ids:
            with get_session_with_current_tenant() as db_session:
                redis_connector = RedisConnector(tenant_id, cc_pair_id)
                try:
                    try_generate_document_cc_pair_cleanup_tasks(
                        self.app, cc_pair_id, db_session, lock_beat, tenant_id
                    )
                except TaskDependencyError as e:
                    # this means we wanted to start deleting but dependent tasks were running
                    # on the first error, we set a stop signal and revoke the dependent tasks
                    # on subsequent errors, we hard reset blocking fences after our specified timeout
                    # is exceeded
                    task_logger.info(str(e))

                    if not redis_connector.stop.fenced:
                        # one time revoke of celery tasks
                        task_logger.info("Revoking any tasks blocking deletion.")
                        revoke_tasks_blocking_deletion(
                            redis_connector, db_session, self.app
                        )
                        redis_connector.stop.set_fence(True)
                        redis_connector.stop.set_timeout()
                    else:
                        # stop signal already set
                        if redis_connector.stop.timed_out:
                            # waiting too long, just reset blocking fences
                            task_logger.info(
                                "Timed out waiting for tasks blocking deletion. Resetting blocking fences."
                            )

                            redis_connector.prune.reset()
                            redis_connector.permissions.reset()
                            redis_connector.external_group_sync.reset()
                        else:
                            # just wait
                            pass
                else:
                    # clear the stop signal if it exists ... no longer needed
                    redis_connector.stop.set_fence(False)

        lock_beat.reacquire()
        keys = cast(set[Any], r_replica.smembers(OnyxRedisConstants.ACTIVE_FENCES))
        for key in keys:
            key_bytes = cast(bytes, key)

            if not r.exists(key_bytes):
                r.srem(OnyxRedisConstants.ACTIVE_FENCES, key_bytes)
                continue

            key_str = key_bytes.decode("utf-8")
            if key_str.startswith(RedisConnectorDelete.FENCE_PREFIX):
                monitor_connector_deletion_taskset(tenant_id, key_bytes, r)
    except SoftTimeLimitExceeded:
        task_logger.info(
            "Soft time limit exceeded, task is being terminated gracefully."
        )
    except Exception:
        task_logger.exception("Unexpected exception during connector deletion check")
    finally:
        if lock_beat.owned():
            lock_beat.release()

    return True


def try_generate_document_cc_pair_cleanup_tasks(
    app: Celery,
    cc_pair_id: int,
    db_session: Session,
    lock_beat: RedisLock,
    tenant_id: str,
) -> int | None:
    """Returns an int if syncing is needed. The int represents the number of sync tasks generated.
    Note that syncing can still be required even if the number of sync tasks generated is zero.
    Returns None if no syncing is required.

    Will raise TaskDependencyError if dependent tasks such as indexing and pruning are
    still running. In our case, the caller reacts by setting a stop signal in Redis to
    exit those tasks as quickly as possible.
    """

    lock_beat.reacquire()

    redis_connector = RedisConnector(tenant_id, cc_pair_id)

    # don't generate sync tasks if tasks are still pending
    if redis_connector.delete.fenced:
        return None

    # we need to load the state of the object inside the fence
    # to avoid a race condition with db.commit/fence deletion
    # at the end of this taskset
    cc_pair = get_connector_credential_pair_from_id(
        db_session=db_session,
        cc_pair_id=cc_pair_id,
    )
    if not cc_pair:
        return None

    if cc_pair.status != ConnectorCredentialPairStatus.DELETING:
        # there should be no in-progress sync records if this is up to date
        # clean it up just in case things got into a bad state
        cleanup_sync_records(
            db_session=db_session,
            entity_id=cc_pair_id,
            sync_type=SyncType.CONNECTOR_DELETION,
        )
        return None

    # set a basic fence to start
    redis_connector.delete.set_active()
    fence_payload = RedisConnectorDeletePayload(
        num_tasks=None,
        submitted=datetime.now(timezone.utc),
    )

    redis_connector.delete.set_fence(fence_payload)

    try:
        # do not proceed if connector indexing or connector pruning are running
        search_settings_list = get_all_search_settings(db_session)
        for search_settings in search_settings_list:
            recent_index_attempts = get_recent_attempts_for_cc_pair(
                cc_pair_id=cc_pair_id,
                search_settings_id=search_settings.id,
                limit=1,
                db_session=db_session,
            )
            if (
                recent_index_attempts
                and recent_index_attempts[0].status == IndexingStatus.IN_PROGRESS
            ):
                raise TaskDependencyError(
                    "Connector deletion - Delayed (indexing in progress): "
                    f"cc_pair={cc_pair_id} "
                    f"search_settings={search_settings.id}"
                )

        if redis_connector.prune.fenced:
            raise TaskDependencyError(
                "Connector deletion - Delayed (pruning in progress): "
                f"cc_pair={cc_pair_id}"
            )

        if redis_connector.permissions.fenced:
            raise TaskDependencyError(
                f"Connector deletion - Delayed (permissions in progress): "
                f"cc_pair={cc_pair_id}"
            )

        # add tasks to celery and build up the task set to monitor in redis
        redis_connector.delete.taskset_clear()

        # Add all documents that need to be updated into the queue
        task_logger.info(
            f"RedisConnectorDeletion.generate_tasks starting. cc_pair={cc_pair_id}"
        )
        tasks_generated = redis_connector.delete.generate_tasks(
            app, db_session, lock_beat
        )
        if tasks_generated is None:
            raise ValueError("RedisConnectorDeletion.generate_tasks returned None")

        try:
            insert_sync_record(
                db_session=db_session,
                entity_id=cc_pair_id,
                sync_type=SyncType.CONNECTOR_DELETION,
            )
        except Exception:
            task_logger.exception("insert_sync_record exceptioned.")

    except TaskDependencyError:
        redis_connector.delete.set_fence(None)
        raise
    except Exception:
        task_logger.exception("Unexpected exception")
        redis_connector.delete.set_fence(None)
        return None
    else:
        # Currently we are allowing the sync to proceed with 0 tasks.
        # It's possible for sets/groups to be generated initially with no entries
        # and they still need to be marked as up to date.
        # if tasks_generated == 0:
        #     return 0

        task_logger.info(
            "RedisConnectorDeletion.generate_tasks finished. "
            f"cc_pair={cc_pair_id} tasks_generated={tasks_generated}"
        )

        # set this only after all tasks have been added
        fence_payload.num_tasks = tasks_generated
        redis_connector.delete.set_fence(fence_payload)

    return tasks_generated


def monitor_connector_deletion_taskset(
    tenant_id: str, key_bytes: bytes, r: Redis
) -> None:
    fence_key = key_bytes.decode("utf-8")
    cc_pair_id_str = RedisConnector.get_id_from_fence_key(fence_key)
    if cc_pair_id_str is None:
        task_logger.warning(f"could not parse cc_pair_id from {fence_key}")
        return

    cc_pair_id = int(cc_pair_id_str)

    redis_connector = RedisConnector(tenant_id, cc_pair_id)

    fence_data = redis_connector.delete.payload
    if not fence_data:
        task_logger.warning(
            f"Connector deletion - fence payload invalid: cc_pair={cc_pair_id}"
        )
        return

    if fence_data.num_tasks is None:
        # the fence is setting up but isn't ready yet
        return

    remaining = redis_connector.delete.get_remaining()
    task_logger.info(
        f"Connector deletion progress: cc_pair={cc_pair_id} remaining={remaining} initial={fence_data.num_tasks}"
    )
    if remaining > 0:
        with get_session_with_current_tenant() as db_session:
            update_sync_record_status(
                db_session=db_session,
                entity_id=cc_pair_id,
                sync_type=SyncType.CONNECTOR_DELETION,
                sync_status=SyncStatus.IN_PROGRESS,
                num_docs_synced=remaining,
            )
        return

    with get_session_with_current_tenant() as db_session:
        cc_pair = get_connector_credential_pair_from_id(
            db_session=db_session,
            cc_pair_id=cc_pair_id,
        )
        credential_id_to_delete: int | None = None
        connector_id_to_delete: int | None = None
        if not cc_pair:
            task_logger.warning(
                f"Connector deletion - cc_pair not found: cc_pair={cc_pair_id}"
            )
            return

        try:
            doc_ids = get_document_ids_for_connector_credential_pair(
                db_session, cc_pair.connector_id, cc_pair.credential_id
            )
            if len(doc_ids) > 0:
                # NOTE(rkuo): if this happens, documents somehow got added while
                # deletion was in progress. Likely a bug gating off pruning and indexing
                # work before deletion starts.
                task_logger.warning(
                    "Connector deletion - documents still found after taskset completion. "
                    "Clearing the current deletion attempt and allowing deletion to restart: "
                    f"cc_pair={cc_pair_id} "
                    f"docs_deleted={fence_data.num_tasks} "
                    f"docs_remaining={len(doc_ids)}"
                )

                # We don't want to waive off why we get into this state, but resetting
                # our attempt and letting the deletion restart is a good way to recover
                redis_connector.delete.reset()
                raise RuntimeError(
                    "Connector deletion - documents still found after taskset completion"
                )

            # clean up the rest of the related Postgres entities
            # index attempts
            delete_index_attempts(
                db_session=db_session,
                cc_pair_id=cc_pair_id,
            )

            # permission sync attempts
            delete_doc_permission_sync_attempts__no_commit(
                db_session=db_session,
                cc_pair_id=cc_pair_id,
            )
            delete_external_group_permission_sync_attempts__no_commit(
                db_session=db_session,
                cc_pair_id=cc_pair_id,
            )

            # document sets
            delete_document_set_cc_pair_relationship__no_commit(
                db_session=db_session,
                connector_id=cc_pair.connector_id,
                credential_id=cc_pair.credential_id,
            )

            # user groups
            cleanup_user_groups = fetch_versioned_implementation_with_fallback(
                "onyx.db.user_group",
                "delete_user_group_cc_pair_relationship__no_commit",
                noop_fallback,
            )
            cleanup_user_groups(
                cc_pair_id=cc_pair_id,
                db_session=db_session,
            )

            # delete orphan tags
            delete_orphan_tags__no_commit(db_session)

            # Store IDs before potentially expiring cc_pair
            connector_id_to_delete = cc_pair.connector_id
            credential_id_to_delete = cc_pair.credential_id

            # Explicitly delete document by connector credential pair records before deleting the connector
            # This is needed because connector_id is a primary key in that table and cascading deletes won't work
            delete_all_documents_by_connector_credential_pair__no_commit(
                db_session=db_session,
                connector_id=connector_id_to_delete,
                credential_id=credential_id_to_delete,
            )

            # Flush to ensure document deletion happens before connector deletion
            db_session.flush()

            # Expire the cc_pair to ensure SQLAlchemy doesn't try to manage its state
            # related to the deleted DocumentByConnectorCredentialPair during commit
            db_session.expire(cc_pair)

            # finally, delete the cc-pair
            delete_connector_credential_pair__no_commit(
                db_session=db_session,
                connector_id=connector_id_to_delete,
                credential_id=credential_id_to_delete,
            )
            # if there are no credentials left, delete the connector
            connector = fetch_connector_by_id(
                db_session=db_session,
                connector_id=connector_id_to_delete,
            )
            if not connector or not len(connector.credentials):
                task_logger.info(
                    "Connector deletion - Found no credentials left for connector, deleting connector"
                )
                db_session.delete(connector)
            db_session.commit()

            update_sync_record_status(
                db_session=db_session,
                entity_id=cc_pair_id,
                sync_type=SyncType.CONNECTOR_DELETION,
                sync_status=SyncStatus.SUCCESS,
                num_docs_synced=fence_data.num_tasks,
            )

        except Exception as e:
            db_session.rollback()
            stack_trace = traceback.format_exc()
            error_message = f"Error: {str(e)}\n\nStack Trace:\n{stack_trace}"
            add_deletion_failure_message(db_session, cc_pair_id, error_message)

            update_sync_record_status(
                db_session=db_session,
                entity_id=cc_pair_id,
                sync_type=SyncType.CONNECTOR_DELETION,
                sync_status=SyncStatus.FAILED,
                num_docs_synced=fence_data.num_tasks,
            )

            task_logger.exception(
                f"Connector deletion exceptioned: "
                f"cc_pair={cc_pair_id} connector={connector_id_to_delete} credential={credential_id_to_delete}"
            )
            raise e

    task_logger.info(
        f"Connector deletion succeeded: "
        f"cc_pair={cc_pair_id} "
        f"connector={connector_id_to_delete} "
        f"credential={credential_id_to_delete} "
        f"docs_deleted={fence_data.num_tasks}"
    )

    redis_connector.delete.reset()


def validate_connector_deletion_fences(
    tenant_id: str,
    r: Redis,
    r_replica: Redis,
    r_celery: Redis,
    lock_beat: RedisLock,
) -> None:
    # building lookup table can be expensive, so we won't bother
    # validating until the queue is small
    CONNECTION_DELETION_VALIDATION_MAX_QUEUE_LEN = 1024

    queue_len = celery_get_queue_length(OnyxCeleryQueues.CONNECTOR_DELETION, r_celery)
    if queue_len > CONNECTION_DELETION_VALIDATION_MAX_QUEUE_LEN:
        return

    queued_upsert_tasks = celery_get_queued_task_ids(
        OnyxCeleryQueues.CONNECTOR_DELETION, r_celery
    )

    # validate all existing connector deletion jobs
    lock_beat.reacquire()
    keys = cast(set[Any], r_replica.smembers(OnyxRedisConstants.ACTIVE_FENCES))
    for key in keys:
        key_bytes = cast(bytes, key)
        key_str = key_bytes.decode("utf-8")
        if not key_str.startswith(RedisConnectorDelete.FENCE_PREFIX):
            continue

        validate_connector_deletion_fence(
            tenant_id,
            key_bytes,
            queued_upsert_tasks,
            r,
        )

        lock_beat.reacquire()

    return


def validate_connector_deletion_fence(
    tenant_id: str,
    key_bytes: bytes,
    queued_upsert_tasks: set[str],
    r: Redis,
) -> None:
    """Checks for the error condition where an indexing fence is set but the associated celery tasks don't exist.
    This can happen if the indexing worker hard crashes or is terminated.
    Being in this bad state means the fence will never clear without help, so this function
    gives the help.

    How this works:
    1. This function renews the active signal with a 5 minute TTL under the following conditions
    1.2. When the task is seen in the redis queue
    1.3. When the task is seen in the reserved / prefetched list

    2. Externally, the active signal is renewed when:
    2.1. The fence is created
    2.2. The indexing watchdog checks the spawned task.

    3. The TTL allows us to get through the transitions on fence startup
    and when the task starts executing.

    More TTL clarification: it is seemingly impossible to exactly query Celery for
    whether a task is in the queue or currently executing.
    1. An unknown task id is always returned as state PENDING.
    2. Redis can be inspected for the task id, but the task id is gone between the time a worker receives the task
    and the time it actually starts on the worker.

    queued_tasks: the celery queue of lightweight permission sync tasks
    reserved_tasks: prefetched tasks for sync task generator
    """
    # if the fence doesn't exist, there's nothing to do
    fence_key = key_bytes.decode("utf-8")
    cc_pair_id_str = RedisConnector.get_id_from_fence_key(fence_key)
    if cc_pair_id_str is None:
        task_logger.warning(
            f"validate_connector_deletion_fence - could not parse id from {fence_key}"
        )
        return

    cc_pair_id = int(cc_pair_id_str)
    # parse out metadata and initialize the helper class with it
    redis_connector = RedisConnector(tenant_id, int(cc_pair_id))

    # check to see if the fence/payload exists
    if not redis_connector.delete.fenced:
        return

    # in the cloud, the payload format may have changed ...
    # it's a little sloppy, but just reset the fence for now if that happens
    # TODO: add intentional cleanup/abort logic
    try:
        payload = redis_connector.delete.payload
    except ValidationError:
        task_logger.exception(
            "validate_connector_deletion_fence - "
            "Resetting fence because fence schema is out of date: "
            f"cc_pair={cc_pair_id} "
            f"fence={fence_key}"
        )

        redis_connector.delete.reset()
        return

    if not payload:
        return

    # OK, there's actually something for us to validate

    # look up every task in the current taskset in the celery queue
    # every entry in the taskset should have an associated entry in the celery task queue
    # because we get the celery tasks first, the entries in our own permissions taskset
    # should be roughly a subset of the tasks in celery

    # this check isn't very exact, but should be sufficient over a period of time
    # A single successful check over some number of attempts is sufficient.

    # TODO: if the number of tasks in celery is much lower than than the taskset length
    # we might be able to shortcut the lookup since by definition some of the tasks
    # must not exist in celery.

    tasks_scanned = 0
    tasks_not_in_celery = 0  # a non-zero number after completing our check is bad

    for member in r.sscan_iter(redis_connector.delete.taskset_key):
        tasks_scanned += 1

        member_bytes = cast(bytes, member)
        member_str = member_bytes.decode("utf-8")
        if member_str in queued_upsert_tasks:
            continue

        tasks_not_in_celery += 1

    task_logger.info(
        "validate_connector_deletion_fence task check: "
        f"tasks_scanned={tasks_scanned} tasks_not_in_celery={tasks_not_in_celery}"
    )

    # we're active if there are still tasks to run and those tasks all exist in celery
    if tasks_scanned > 0 and tasks_not_in_celery == 0:
        redis_connector.delete.set_active()
        return

    # we may want to enable this check if using the active task list somehow isn't good enough
    # if redis_connector_index.generator_locked():
    #     logger.info(f"{payload.celery_task_id} is currently executing.")

    # if we get here, we didn't find any direct indication that the associated celery tasks exist,
    # but they still might be there due to gaps in our ability to check states during transitions
    # Checking the active signal safeguards us against these transition periods
    # (which has a duration that allows us to bridge those gaps)
    if redis_connector.delete.active():
        return

    # celery tasks don't exist and the active signal has expired, possibly due to a crash. Clean it up.
    task_logger.warning(
        "validate_connector_deletion_fence - "
        "Resetting fence because no associated celery tasks were found: "
        f"cc_pair={cc_pair_id} "
        f"fence={fence_key}"
    )

    redis_connector.delete.reset()
    return
