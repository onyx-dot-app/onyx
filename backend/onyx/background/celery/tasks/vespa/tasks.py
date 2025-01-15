import random
import time
import traceback
from collections.abc import Callable
from datetime import datetime
from datetime import timezone
from http import HTTPStatus
from typing import Any
from typing import cast

import httpx
from celery import Celery
from celery import shared_task
from celery import Task
from celery.exceptions import SoftTimeLimitExceeded
from celery.result import AsyncResult
from celery.states import READY_STATES
from redis import Redis
from redis.lock import Lock as RedisLock
from sqlalchemy.orm import Session
from tenacity import RetryError

from onyx.access.access import get_access_for_document
from onyx.background.celery.apps.app_base import task_logger
from onyx.background.celery.celery_redis import celery_get_queue_length
from onyx.background.celery.celery_redis import celery_get_unacked_task_ids
from onyx.background.celery.tasks.shared.RetryDocumentIndex import RetryDocumentIndex
from onyx.background.celery.tasks.shared.tasks import LIGHT_SOFT_TIME_LIMIT
from onyx.background.celery.tasks.shared.tasks import LIGHT_TIME_LIMIT
from onyx.configs.app_configs import JOB_TIMEOUT
from onyx.configs.app_configs import VESPA_SYNC_MAX_TASKS
from onyx.configs.constants import CELERY_VESPA_SYNC_BEAT_LOCK_TIMEOUT
from onyx.configs.constants import OnyxCeleryQueues
from onyx.configs.constants import OnyxCeleryTask
from onyx.configs.constants import OnyxRedisLocks
from onyx.db.connector import fetch_connector_by_id
from onyx.db.connector import mark_cc_pair_as_permissions_synced
from onyx.db.connector import mark_ccpair_as_pruned
from onyx.db.connector_credential_pair import add_deletion_failure_message
from onyx.db.connector_credential_pair import (
    delete_connector_credential_pair__no_commit,
)
from onyx.db.connector_credential_pair import get_connector_credential_pair_from_id
from onyx.db.connector_credential_pair import get_connector_credential_pairs
from onyx.db.document import count_documents_by_needs_sync
from onyx.db.document import get_document
from onyx.db.document import get_document_ids_for_connector_credential_pair
from onyx.db.document import mark_document_as_synced
from onyx.db.document_set import delete_document_set
from onyx.db.document_set import delete_document_set_cc_pair_relationship__no_commit
from onyx.db.document_set import fetch_document_sets
from onyx.db.document_set import fetch_document_sets_for_document
from onyx.db.document_set import get_document_set_by_id
from onyx.db.document_set import mark_document_set_as_synced
from onyx.db.engine import get_session_with_tenant
from onyx.db.enums import IndexingStatus
from onyx.db.enums import SyncStatus
from onyx.db.enums import SyncType
from onyx.db.index_attempt import delete_index_attempts
from onyx.db.index_attempt import get_index_attempt
from onyx.db.index_attempt import mark_attempt_failed
from onyx.db.models import DocumentSet
from onyx.db.models import UserGroup
from onyx.db.sync_record import cleanup_sync_records
from onyx.db.sync_record import insert_sync_record
from onyx.db.sync_record import update_sync_record_status
from onyx.document_index.document_index_utils import get_both_index_names
from onyx.document_index.factory import get_default_document_index
from onyx.document_index.interfaces import VespaDocumentFields
from onyx.redis.redis_connector import RedisConnector
from onyx.redis.redis_connector_credential_pair import RedisConnectorCredentialPair
from onyx.redis.redis_connector_delete import RedisConnectorDelete
from onyx.redis.redis_connector_doc_perm_sync import RedisConnectorPermissionSync
from onyx.redis.redis_connector_doc_perm_sync import (
    RedisConnectorPermissionSyncPayload,
)
from onyx.redis.redis_connector_index import RedisConnectorIndex
from onyx.redis.redis_connector_prune import RedisConnectorPrune
from onyx.redis.redis_document_set import RedisDocumentSet
from onyx.redis.redis_pool import get_redis_client
from onyx.redis.redis_pool import redis_lock_dump
from onyx.redis.redis_pool import SCAN_ITER_COUNT_DEFAULT
from onyx.redis.redis_usergroup import RedisUserGroup
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import fetch_versioned_implementation
from onyx.utils.variable_functionality import (
    fetch_versioned_implementation_with_fallback,
)
from onyx.utils.variable_functionality import global_version
from onyx.utils.variable_functionality import noop_fallback
from shared_configs.configs import MULTI_TENANT

logger = setup_logger()


# celery auto associates tasks created inside another task,
# which bloats the result metadata considerably. trail=False prevents this.
@shared_task(
    name=OnyxCeleryTask.CHECK_FOR_VESPA_SYNC_TASK,
    soft_time_limit=JOB_TIMEOUT,
    trail=False,
    bind=True,
)
def check_for_vespa_sync_task(self: Task, *, tenant_id: str | None) -> bool | None:
    """Runs periodically to check if any document needs syncing.
    Generates sets of tasks for Celery if syncing is needed."""
    time_start = time.monotonic()

    r = get_redis_client(tenant_id=tenant_id)

    lock_beat: RedisLock = r.lock(
        OnyxRedisLocks.CHECK_VESPA_SYNC_BEAT_LOCK,
        timeout=CELERY_VESPA_SYNC_BEAT_LOCK_TIMEOUT,
    )

    # these tasks should never overlap
    if not lock_beat.acquire(blocking=False):
        return None

    try:
        with get_session_with_tenant(tenant_id) as db_session:
            try_generate_stale_document_sync_tasks(
                self.app, VESPA_SYNC_MAX_TASKS, db_session, r, lock_beat, tenant_id
            )

        # region document set scan
        lock_beat.reacquire()
        document_set_ids: list[int] = []
        with get_session_with_tenant(tenant_id) as db_session:
            # check if any document sets are not synced
            document_set_info = fetch_document_sets(
                user_id=None, db_session=db_session, include_outdated=True
            )

            for document_set, _ in document_set_info:
                document_set_ids.append(document_set.id)

        for document_set_id in document_set_ids:
            lock_beat.reacquire()
            with get_session_with_tenant(tenant_id) as db_session:
                try_generate_document_set_sync_tasks(
                    self.app, document_set_id, db_session, r, lock_beat, tenant_id
                )
        # endregion

        # check if any user groups are not synced
        if global_version.is_ee_version():
            lock_beat.reacquire()

            try:
                fetch_user_groups = fetch_versioned_implementation(
                    "onyx.db.user_group", "fetch_user_groups"
                )
            except ModuleNotFoundError:
                # Always exceptions on the MIT version, which is expected
                # We shouldn't actually get here if the ee version check works
                pass
            else:
                usergroup_ids: list[int] = []
                with get_session_with_tenant(tenant_id) as db_session:
                    user_groups = fetch_user_groups(
                        db_session=db_session, only_up_to_date=False
                    )

                    for usergroup in user_groups:
                        usergroup_ids.append(usergroup.id)

                for usergroup_id in usergroup_ids:
                    lock_beat.reacquire()
                    with get_session_with_tenant(tenant_id) as db_session:
                        try_generate_user_group_sync_tasks(
                            self.app, usergroup_id, db_session, r, lock_beat, tenant_id
                        )

    except SoftTimeLimitExceeded:
        task_logger.info(
            "Soft time limit exceeded, task is being terminated gracefully."
        )
    except Exception:
        task_logger.exception("Unexpected exception during vespa metadata sync")
    finally:
        if lock_beat.owned():
            lock_beat.release()
        else:
            task_logger.error(
                "check_for_vespa_sync_task - Lock not owned on completion: "
                f"tenant={tenant_id}"
            )
            redis_lock_dump(lock_beat, r)

    time_elapsed = time.monotonic() - time_start
    task_logger.debug(f"check_for_vespa_sync_task finished: elapsed={time_elapsed:.2f}")
    return True


def try_generate_stale_document_sync_tasks(
    celery_app: Celery,
    max_tasks: int,
    db_session: Session,
    r: Redis,
    lock_beat: RedisLock,
    tenant_id: str | None,
) -> int | None:
    # the fence is up, do nothing
    if r.exists(RedisConnectorCredentialPair.get_fence_key()):
        return None

    r.delete(RedisConnectorCredentialPair.get_taskset_key())  # delete the taskset

    # add tasks to celery and build up the task set to monitor in redis
    stale_doc_count = count_documents_by_needs_sync(db_session)
    if stale_doc_count == 0:
        return None

    task_logger.info(
        f"Stale documents found (at least {stale_doc_count}). Generating sync tasks by cc pair."
    )

    task_logger.info(
        "RedisConnector.generate_tasks starting by cc_pair. "
        "Documents spanning multiple cc_pairs will only be synced once."
    )

    docs_to_skip: set[str] = set()

    # rkuo: we could technically sync all stale docs in one big pass.
    # but I feel it's more understandable to group the docs by cc_pair
    total_tasks_generated = 0
    tasks_remaining = max_tasks
    cc_pairs = get_connector_credential_pairs(db_session)
    for cc_pair in cc_pairs:
        lock_beat.reacquire()

        rc = RedisConnectorCredentialPair(tenant_id, cc_pair.id)
        rc.set_skip_docs(docs_to_skip)
        result = rc.generate_tasks(
            tasks_remaining, celery_app, db_session, r, lock_beat, tenant_id
        )

        if result is None:
            continue

        if result[1] == 0:
            continue

        task_logger.info(
            f"RedisConnector.generate_tasks finished for single cc_pair. "
            f"cc_pair={cc_pair.id} tasks_generated={result[0]} tasks_possible={result[1]}"
        )

        total_tasks_generated += result[0]
        tasks_remaining -= result[0]
        if tasks_remaining <= 0:
            break

    if tasks_remaining <= 0:
        task_logger.info(
            f"RedisConnector.generate_tasks reached the task generation limit: "
            f"total_tasks_generated={total_tasks_generated} max_tasks={max_tasks}"
        )
    else:
        task_logger.info(
            f"RedisConnector.generate_tasks finished for all cc_pairs. total_tasks_generated={total_tasks_generated}"
        )

    r.set(RedisConnectorCredentialPair.get_fence_key(), total_tasks_generated)
    return total_tasks_generated


def try_generate_document_set_sync_tasks(
    celery_app: Celery,
    document_set_id: int,
    db_session: Session,
    r: Redis,
    lock_beat: RedisLock,
    tenant_id: str | None,
) -> int | None:
    lock_beat.reacquire()

    rds = RedisDocumentSet(tenant_id, document_set_id)

    # don't generate document set sync tasks if tasks are still pending
    if rds.fenced:
        return None

    # don't generate sync tasks if we're up to date
    # race condition with the monitor/cleanup function if we use a cached result!
    document_set = get_document_set_by_id(
        db_session=db_session,
        document_set_id=document_set_id,
    )
    if not document_set:
        return None

    if document_set.is_up_to_date:
        # there should be no in-progress sync records if this is up to date
        # clean it up just in case things got into a bad state
        cleanup_sync_records(
            db_session=db_session,
            entity_id=document_set_id,
            sync_type=SyncType.DOCUMENT_SET,
        )
        return None

    # add tasks to celery and build up the task set to monitor in redis
    r.delete(rds.taskset_key)

    task_logger.info(
        f"RedisDocumentSet.generate_tasks starting. document_set_id={document_set.id}"
    )

    # Add all documents that need to be updated into the queue
    result = rds.generate_tasks(
        VESPA_SYNC_MAX_TASKS, celery_app, db_session, r, lock_beat, tenant_id
    )
    if result is None:
        return None

    tasks_generated = result[0]
    # Currently we are allowing the sync to proceed with 0 tasks.
    # It's possible for sets/groups to be generated initially with no entries
    # and they still need to be marked as up to date.
    # if tasks_generated == 0:
    #     return 0

    task_logger.info(
        f"RedisDocumentSet.generate_tasks finished. "
        f"document_set={document_set.id} tasks_generated={tasks_generated}"
    )

    # create before setting fence to avoid race condition where the monitoring
    # task updates the sync record before it is created
    insert_sync_record(
        db_session=db_session,
        entity_id=document_set_id,
        sync_type=SyncType.DOCUMENT_SET,
    )
    # set this only after all tasks have been added
    rds.set_fence(tasks_generated)
    return tasks_generated


def try_generate_user_group_sync_tasks(
    celery_app: Celery,
    usergroup_id: int,
    db_session: Session,
    r: Redis,
    lock_beat: RedisLock,
    tenant_id: str | None,
) -> int | None:
    lock_beat.reacquire()

    rug = RedisUserGroup(tenant_id, usergroup_id)
    if rug.fenced:
        # don't generate sync tasks if tasks are still pending
        return None

    # race condition with the monitor/cleanup function if we use a cached result!
    fetch_user_group = cast(
        Callable[[Session, int], UserGroup | None],
        fetch_versioned_implementation("onyx.db.user_group", "fetch_user_group"),
    )

    usergroup = fetch_user_group(db_session, usergroup_id)
    if not usergroup:
        return None

    if usergroup.is_up_to_date:
        # there should be no in-progress sync records if this is up to date
        # clean it up just in case things got into a bad state
        cleanup_sync_records(
            db_session=db_session,
            entity_id=usergroup_id,
            sync_type=SyncType.USER_GROUP,
        )
        return None

    # add tasks to celery and build up the task set to monitor in redis
    r.delete(rug.taskset_key)

    # Add all documents that need to be updated into the queue
    task_logger.info(
        f"RedisUserGroup.generate_tasks starting. usergroup_id={usergroup.id}"
    )
    result = rug.generate_tasks(
        VESPA_SYNC_MAX_TASKS, celery_app, db_session, r, lock_beat, tenant_id
    )
    if result is None:
        return None

    tasks_generated = result[0]
    # Currently we are allowing the sync to proceed with 0 tasks.
    # It's possible for sets/groups to be generated initially with no entries
    # and they still need to be marked as up to date.
    # if tasks_generated == 0:
    #     return 0

    task_logger.info(
        f"RedisUserGroup.generate_tasks finished. "
        f"usergroup={usergroup.id} tasks_generated={tasks_generated}"
    )

    # create before setting fence to avoid race condition where the monitoring
    # task updates the sync record before it is created
    insert_sync_record(
        db_session=db_session,
        entity_id=usergroup_id,
        sync_type=SyncType.USER_GROUP,
    )
    # set this only after all tasks have been added
    rug.set_fence(tasks_generated)

    return tasks_generated


def monitor_connector_taskset(r: Redis) -> None:
    fence_value = r.get(RedisConnectorCredentialPair.get_fence_key())
    if fence_value is None:
        return

    try:
        initial_count = int(cast(int, fence_value))
    except ValueError:
        task_logger.error("The value is not an integer.")
        return

    count = r.scard(RedisConnectorCredentialPair.get_taskset_key())
    task_logger.info(
        f"Stale document sync progress: remaining={count} initial={initial_count}"
    )
    if count == 0:
        r.delete(RedisConnectorCredentialPair.get_taskset_key())
        r.delete(RedisConnectorCredentialPair.get_fence_key())
        task_logger.info(f"Successfully synced stale documents. count={initial_count}")


def monitor_document_set_taskset(
    tenant_id: str | None, key_bytes: bytes, r: Redis, db_session: Session
) -> None:
    fence_key = key_bytes.decode("utf-8")
    document_set_id_str = RedisDocumentSet.get_id_from_fence_key(fence_key)
    if document_set_id_str is None:
        task_logger.warning(f"could not parse document set id from {fence_key}")
        return

    document_set_id = int(document_set_id_str)

    rds = RedisDocumentSet(tenant_id, document_set_id)
    if not rds.fenced:
        return

    initial_count = rds.payload
    if initial_count is None:
        return

    count = cast(int, r.scard(rds.taskset_key))
    task_logger.info(
        f"Document set sync progress: document_set={document_set_id} "
        f"remaining={count} initial={initial_count}"
    )
    if count > 0:
        update_sync_record_status(
            db_session=db_session,
            entity_id=document_set_id,
            sync_type=SyncType.DOCUMENT_SET,
            sync_status=SyncStatus.IN_PROGRESS,
            num_docs_synced=count,
        )
        return

    document_set = cast(
        DocumentSet,
        get_document_set_by_id(db_session=db_session, document_set_id=document_set_id),
    )  # casting since we "know" a document set with this ID exists
    if document_set:
        if not document_set.connector_credential_pairs:
            # if there are no connectors, then delete the document set.
            delete_document_set(document_set_row=document_set, db_session=db_session)
            task_logger.info(
                f"Successfully deleted document set: document_set={document_set_id}"
            )
        else:
            mark_document_set_as_synced(document_set_id, db_session)
            task_logger.info(
                f"Successfully synced document set: document_set={document_set_id}"
            )
        update_sync_record_status(
            db_session=db_session,
            entity_id=document_set_id,
            sync_type=SyncType.DOCUMENT_SET,
            sync_status=SyncStatus.SUCCESS,
            num_docs_synced=initial_count,
        )

    rds.reset()


def monitor_connector_deletion_taskset(
    tenant_id: str | None, key_bytes: bytes, r: Redis
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
        with get_session_with_tenant(tenant_id) as db_session:
            update_sync_record_status(
                db_session=db_session,
                entity_id=cc_pair_id,
                sync_type=SyncType.CONNECTOR_DELETION,
                sync_status=SyncStatus.IN_PROGRESS,
                num_docs_synced=remaining,
            )
        return

    with get_session_with_tenant(tenant_id) as db_session:
        cc_pair = get_connector_credential_pair_from_id(
            db_session=db_session,
            cc_pair_id=cc_pair_id,
        )
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

            # finally, delete the cc-pair
            delete_connector_credential_pair__no_commit(
                db_session=db_session,
                connector_id=cc_pair.connector_id,
                credential_id=cc_pair.credential_id,
            )
            # if there are no credentials left, delete the connector
            connector = fetch_connector_by_id(
                db_session=db_session,
                connector_id=cc_pair.connector_id,
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
                f"cc_pair={cc_pair_id} connector={cc_pair.connector_id} credential={cc_pair.credential_id}"
            )
            raise e

    task_logger.info(
        f"Connector deletion succeeded: "
        f"cc_pair={cc_pair_id} "
        f"connector={cc_pair.connector_id} "
        f"credential={cc_pair.credential_id} "
        f"docs_deleted={fence_data.num_tasks}"
    )

    redis_connector.delete.reset()


def monitor_ccpair_pruning_taskset(
    tenant_id: str | None, key_bytes: bytes, r: Redis, db_session: Session
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
        f"Successfully pruned connector credential pair. cc_pair={cc_pair_id}"
    )

    redis_connector.prune.taskset_clear()
    redis_connector.prune.generator_clear()
    redis_connector.prune.set_fence(False)


def monitor_ccpair_permissions_taskset(
    tenant_id: str | None, key_bytes: bytes, r: Redis, db_session: Session
) -> None:
    fence_key = key_bytes.decode("utf-8")
    cc_pair_id_str = RedisConnector.get_id_from_fence_key(fence_key)
    if cc_pair_id_str is None:
        task_logger.warning(
            f"monitor_ccpair_permissions_taskset: could not parse cc_pair_id from {fence_key}"
        )
        return

    cc_pair_id = int(cc_pair_id_str)

    redis_connector = RedisConnector(tenant_id, cc_pair_id)
    if not redis_connector.permissions.fenced:
        return

    initial = redis_connector.permissions.generator_complete
    if initial is None:
        return

    remaining = redis_connector.permissions.get_remaining()
    task_logger.info(
        f"Permissions sync progress: cc_pair={cc_pair_id} remaining={remaining} initial={initial}"
    )
    if remaining > 0:
        return

    payload: RedisConnectorPermissionSyncPayload | None = (
        redis_connector.permissions.payload
    )
    start_time: datetime | None = payload.started if payload else None

    mark_cc_pair_as_permissions_synced(db_session, int(cc_pair_id), start_time)
    task_logger.info(f"Successfully synced permissions for cc_pair={cc_pair_id}")

    redis_connector.permissions.reset()


def monitor_ccpair_indexing_taskset(
    tenant_id: str | None, key_bytes: bytes, r: Redis, db_session: Session
) -> None:
    # if the fence doesn't exist, there's nothing to do
    fence_key = key_bytes.decode("utf-8")
    composite_id = RedisConnector.get_id_from_fence_key(fence_key)
    if composite_id is None:
        task_logger.warning(
            f"monitor_ccpair_indexing_taskset: could not parse composite_id from {fence_key}"
        )
        return

    # parse out metadata and initialize the helper class with it
    parts = composite_id.split("/")
    if len(parts) != 2:
        return

    cc_pair_id = int(parts[0])
    search_settings_id = int(parts[1])

    redis_connector = RedisConnector(tenant_id, cc_pair_id)
    redis_connector_index = redis_connector.new_index(search_settings_id)
    if not redis_connector_index.fenced:
        return

    payload = redis_connector_index.payload
    if not payload:
        return

    elapsed_started_str = None
    if payload.started:
        elapsed_started = datetime.now(timezone.utc) - payload.started
        elapsed_started_str = f"{elapsed_started.total_seconds():.2f}"

    elapsed_submitted = datetime.now(timezone.utc) - payload.submitted

    progress = redis_connector_index.get_progress()
    if progress is not None:
        task_logger.info(
            f"Connector indexing progress: "
            f"attempt={payload.index_attempt_id} "
            f"cc_pair={cc_pair_id} "
            f"search_settings={search_settings_id} "
            f"progress={progress} "
            f"elapsed_submitted={elapsed_submitted.total_seconds():.2f} "
            f"elapsed_started={elapsed_started_str}"
        )

    if payload.index_attempt_id is None or payload.celery_task_id is None:
        # the task is still setting up
        return

    # never use any blocking methods on the result from inside a task!
    result: AsyncResult = AsyncResult(payload.celery_task_id)

    # inner/outer/inner double check pattern to avoid race conditions when checking for
    # bad state

    # inner = get_completion / generator_complete not signaled
    # outer = result.state in READY state
    status_int = redis_connector_index.get_completion()
    if status_int is None:  # inner signal not set ... possible error
        task_state = result.state
        if (
            task_state in READY_STATES
        ):  # outer signal in terminal state ... possible error
            # Now double check!
            if redis_connector_index.get_completion() is None:
                # inner signal still not set (and cannot change when outer result_state is READY)
                # Task is finished but generator complete isn't set.
                # We have a problem! Worker may have crashed.
                task_result = str(result.result)
                task_traceback = str(result.traceback)

                msg = (
                    f"Connector indexing aborted or exceptioned: "
                    f"attempt={payload.index_attempt_id} "
                    f"celery_task={payload.celery_task_id} "
                    f"cc_pair={cc_pair_id} "
                    f"search_settings={search_settings_id} "
                    f"elapsed_submitted={elapsed_submitted.total_seconds():.2f} "
                    f"result.state={task_state} "
                    f"result.result={task_result} "
                    f"result.traceback={task_traceback}"
                )
                task_logger.warning(msg)

                try:
                    index_attempt = get_index_attempt(
                        db_session, payload.index_attempt_id
                    )
                    if index_attempt:
                        if (
                            index_attempt.status != IndexingStatus.CANCELED
                            and index_attempt.status != IndexingStatus.FAILED
                        ):
                            mark_attempt_failed(
                                index_attempt_id=payload.index_attempt_id,
                                db_session=db_session,
                                failure_reason=msg,
                            )
                except Exception:
                    task_logger.exception(
                        "monitor_ccpair_indexing_taskset - transient exception marking index attempt as failed: "
                        f"attempt={payload.index_attempt_id} "
                        f"tenant={tenant_id} "
                        f"cc_pair={cc_pair_id} "
                        f"search_settings={search_settings_id}"
                    )

                redis_connector_index.reset()
        return

    status_enum = HTTPStatus(status_int)

    task_logger.info(
        f"Connector indexing finished: "
        f"attempt={payload.index_attempt_id} "
        f"cc_pair={cc_pair_id} "
        f"search_settings={search_settings_id} "
        f"progress={progress} "
        f"status={status_enum.name} "
        f"elapsed_submitted={elapsed_submitted.total_seconds():.2f} "
        f"elapsed_started={elapsed_started_str}"
    )

    redis_connector_index.reset()


@shared_task(name=OnyxCeleryTask.MONITOR_VESPA_SYNC, soft_time_limit=300, bind=True)
def monitor_vespa_sync(self: Task, tenant_id: str | None) -> bool | None:
    """This is a celery beat task that monitors and finalizes metadata sync tasksets.
    It scans for fence values and then gets the counts of any associated tasksets.
    If the count is 0, that means all tasks finished and we should clean up.

    This task lock timeout is CELERY_METADATA_SYNC_BEAT_LOCK_TIMEOUT seconds, so don't
    do anything too expensive in this function!

    Returns True if the task actually did work, False if it exited early to prevent overlap
    """
    task_logger.info(f"monitor_vespa_sync starting: tenant={tenant_id}")

    time_start = time.monotonic()

    timings: dict[str, Any] = {}
    timings["start"] = time_start

    r = get_redis_client(tenant_id=tenant_id)

    lock_beat: RedisLock = r.lock(
        OnyxRedisLocks.MONITOR_VESPA_SYNC_BEAT_LOCK,
        timeout=CELERY_VESPA_SYNC_BEAT_LOCK_TIMEOUT,
    )

    # prevent overlapping tasks
    if not lock_beat.acquire(blocking=False):
        return None

    try:
        # print current queue lengths
        phase_start = time.monotonic()
        # we don't need every tenant polling redis for this info.
        if not MULTI_TENANT or random.randint(1, 10) == 10:
            r_celery = self.app.broker_connection().channel().client  # type: ignore
            n_celery = celery_get_queue_length("celery", r_celery)
            n_indexing = celery_get_queue_length(
                OnyxCeleryQueues.CONNECTOR_INDEXING, r_celery
            )
            n_sync = celery_get_queue_length(
                OnyxCeleryQueues.VESPA_METADATA_SYNC, r_celery
            )
            n_deletion = celery_get_queue_length(
                OnyxCeleryQueues.CONNECTOR_DELETION, r_celery
            )
            n_pruning = celery_get_queue_length(
                OnyxCeleryQueues.CONNECTOR_PRUNING, r_celery
            )
            n_permissions_sync = celery_get_queue_length(
                OnyxCeleryQueues.CONNECTOR_DOC_PERMISSIONS_SYNC, r_celery
            )
            n_external_group_sync = celery_get_queue_length(
                OnyxCeleryQueues.CONNECTOR_EXTERNAL_GROUP_SYNC, r_celery
            )
            n_permissions_upsert = celery_get_queue_length(
                OnyxCeleryQueues.DOC_PERMISSIONS_UPSERT, r_celery
            )

            prefetched = celery_get_unacked_task_ids(
                OnyxCeleryQueues.CONNECTOR_INDEXING, r_celery
            )

            task_logger.info(
                f"Queue lengths: celery={n_celery} "
                f"indexing={n_indexing} "
                f"indexing_prefetched={len(prefetched)} "
                f"sync={n_sync} "
                f"deletion={n_deletion} "
                f"pruning={n_pruning} "
                f"permissions_sync={n_permissions_sync} "
                f"external_group_sync={n_external_group_sync} "
                f"permissions_upsert={n_permissions_upsert} "
            )
        timings["queues"] = time.monotonic() - phase_start
        timings["queues_ttl"] = r.ttl(OnyxRedisLocks.MONITOR_VESPA_SYNC_BEAT_LOCK)

        # scan and monitor activity to completion
        phase_start = time.monotonic()
        lock_beat.reacquire()
        if r.exists(RedisConnectorCredentialPair.get_fence_key()):
            monitor_connector_taskset(r)
        timings["connector"] = time.monotonic() - phase_start
        timings["connector_ttl"] = r.ttl(OnyxRedisLocks.MONITOR_VESPA_SYNC_BEAT_LOCK)

        phase_start = time.monotonic()
        lock_beat.reacquire()
        for key_bytes in r.scan_iter(
            RedisConnectorDelete.FENCE_PREFIX + "*", count=SCAN_ITER_COUNT_DEFAULT
        ):
            monitor_connector_deletion_taskset(tenant_id, key_bytes, r)
            lock_beat.reacquire()

        timings["connector_deletion"] = time.monotonic() - phase_start
        timings["connector_deletion_ttl"] = r.ttl(
            OnyxRedisLocks.MONITOR_VESPA_SYNC_BEAT_LOCK
        )

        phase_start = time.monotonic()
        lock_beat.reacquire()
        for key_bytes in r.scan_iter(
            RedisDocumentSet.FENCE_PREFIX + "*", count=SCAN_ITER_COUNT_DEFAULT
        ):
            with get_session_with_tenant(tenant_id) as db_session:
                monitor_document_set_taskset(tenant_id, key_bytes, r, db_session)
            lock_beat.reacquire()
        timings["documentset"] = time.monotonic() - phase_start
        timings["documentset_ttl"] = r.ttl(OnyxRedisLocks.MONITOR_VESPA_SYNC_BEAT_LOCK)

        phase_start = time.monotonic()
        lock_beat.reacquire()
        for key_bytes in r.scan_iter(
            RedisUserGroup.FENCE_PREFIX + "*", count=SCAN_ITER_COUNT_DEFAULT
        ):
            monitor_usergroup_taskset = fetch_versioned_implementation_with_fallback(
                "onyx.background.celery.tasks.vespa.tasks",
                "monitor_usergroup_taskset",
                noop_fallback,
            )
            with get_session_with_tenant(tenant_id) as db_session:
                monitor_usergroup_taskset(tenant_id, key_bytes, r, db_session)
            lock_beat.reacquire()
        timings["usergroup"] = time.monotonic() - phase_start
        timings["usergroup_ttl"] = r.ttl(OnyxRedisLocks.MONITOR_VESPA_SYNC_BEAT_LOCK)

        phase_start = time.monotonic()
        lock_beat.reacquire()
        for key_bytes in r.scan_iter(
            RedisConnectorPrune.FENCE_PREFIX + "*", count=SCAN_ITER_COUNT_DEFAULT
        ):
            with get_session_with_tenant(tenant_id) as db_session:
                monitor_ccpair_pruning_taskset(tenant_id, key_bytes, r, db_session)
            lock_beat.reacquire()
        timings["pruning"] = time.monotonic() - phase_start
        timings["pruning_ttl"] = r.ttl(OnyxRedisLocks.MONITOR_VESPA_SYNC_BEAT_LOCK)

        phase_start = time.monotonic()
        lock_beat.reacquire()
        for key_bytes in r.scan_iter(
            RedisConnectorIndex.FENCE_PREFIX + "*", count=SCAN_ITER_COUNT_DEFAULT
        ):
            with get_session_with_tenant(tenant_id) as db_session:
                monitor_ccpair_indexing_taskset(tenant_id, key_bytes, r, db_session)
            lock_beat.reacquire()
        timings["indexing"] = time.monotonic() - phase_start
        timings["indexing_ttl"] = r.ttl(OnyxRedisLocks.MONITOR_VESPA_SYNC_BEAT_LOCK)

        phase_start = time.monotonic()
        lock_beat.reacquire()
        for key_bytes in r.scan_iter(
            RedisConnectorPermissionSync.FENCE_PREFIX + "*",
            count=SCAN_ITER_COUNT_DEFAULT,
        ):
            with get_session_with_tenant(tenant_id) as db_session:
                monitor_ccpair_permissions_taskset(tenant_id, key_bytes, r, db_session)
            lock_beat.reacquire()

        timings["permissions"] = time.monotonic() - phase_start
        timings["permissions_ttl"] = r.ttl(OnyxRedisLocks.MONITOR_VESPA_SYNC_BEAT_LOCK)

    except SoftTimeLimitExceeded:
        task_logger.info(
            "Soft time limit exceeded, task is being terminated gracefully."
        )
    finally:
        if lock_beat.owned():
            lock_beat.release()
        else:
            task_logger.error(
                "monitor_vespa_sync - Lock not owned on completion: "
                f"tenant={tenant_id} "
                f"timings={timings}"
            )
            redis_lock_dump(lock_beat, r)

    time_elapsed = time.monotonic() - time_start
    task_logger.info(f"monitor_vespa_sync finished: elapsed={time_elapsed:.2f}")
    return True


@shared_task(
    name=OnyxCeleryTask.VESPA_METADATA_SYNC_TASK,
    bind=True,
    soft_time_limit=LIGHT_SOFT_TIME_LIMIT,
    time_limit=LIGHT_TIME_LIMIT,
    max_retries=3,
)
def vespa_metadata_sync_task(
    self: Task, document_id: str, tenant_id: str | None
) -> bool:
    try:
        with get_session_with_tenant(tenant_id) as db_session:
            curr_ind_name, sec_ind_name = get_both_index_names(db_session)
            doc_index = get_default_document_index(
                primary_index_name=curr_ind_name, secondary_index_name=sec_ind_name
            )

            retry_index = RetryDocumentIndex(doc_index)

            doc = get_document(document_id, db_session)
            if not doc:
                return False

            # document set sync
            doc_sets = fetch_document_sets_for_document(document_id, db_session)
            update_doc_sets: set[str] = set(doc_sets)

            # User group sync
            doc_access = get_access_for_document(
                document_id=document_id, db_session=db_session
            )

            fields = VespaDocumentFields(
                document_sets=update_doc_sets,
                access=doc_access,
                boost=doc.boost,
                hidden=doc.hidden,
            )

            # update Vespa. OK if doc doesn't exist. Raises exception otherwise.
            chunks_affected = retry_index.update_single(
                document_id,
                tenant_id=tenant_id,
                chunk_count=doc.chunk_count,
                fields=fields,
            )

            # update db last. Worst case = we crash right before this and
            # the sync might repeat again later
            mark_document_as_synced(document_id, db_session)

            # this code checks for and removes a per document sync key that is
            # used to block out the same doc from continualy resyncing
            # a quick hack that is only needed for production issues
            # redis_syncing_key = RedisConnectorCredentialPair.make_redis_syncing_key(
            #     document_id
            # )
            # r = get_redis_client(tenant_id=tenant_id)
            # r.delete(redis_syncing_key)

            task_logger.info(f"doc={document_id} action=sync chunks={chunks_affected}")
    except SoftTimeLimitExceeded:
        task_logger.info(f"SoftTimeLimitExceeded exception. doc={document_id}")
    except Exception as ex:
        if isinstance(ex, RetryError):
            task_logger.warning(
                f"Tenacity retry failed: num_attempts={ex.last_attempt.attempt_number}"
            )

            # only set the inner exception if it is of type Exception
            e_temp = ex.last_attempt.exception()
            if isinstance(e_temp, Exception):
                e = e_temp
        else:
            e = ex

        if isinstance(e, httpx.HTTPStatusError):
            if e.response.status_code == HTTPStatus.BAD_REQUEST:
                task_logger.exception(
                    f"Non-retryable HTTPStatusError: "
                    f"doc={document_id} "
                    f"status={e.response.status_code}"
                )
            return False

        task_logger.exception(
            f"Unexpected exception during vespa metadata sync: doc={document_id}"
        )

        # Exponential backoff from 2^4 to 2^6 ... i.e. 16, 32, 64
        countdown = 2 ** (self.request.retries + 4)
        self.retry(exc=e, countdown=countdown)

    return True
