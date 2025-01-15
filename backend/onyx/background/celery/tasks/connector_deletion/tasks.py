from datetime import datetime
from datetime import timezone

from celery import Celery
from celery import shared_task
from celery import Task
from celery.exceptions import SoftTimeLimitExceeded
from redis.lock import Lock as RedisLock
from sqlalchemy.orm import Session

from onyx.background.celery.apps.app_base import task_logger
from onyx.configs.app_configs import JOB_TIMEOUT
from onyx.configs.constants import CELERY_VESPA_SYNC_BEAT_LOCK_TIMEOUT
from onyx.configs.constants import OnyxCeleryTask
from onyx.configs.constants import OnyxRedisLocks
from onyx.db.connector_credential_pair import get_connector_credential_pair_from_id
from onyx.db.connector_credential_pair import get_connector_credential_pairs
from onyx.db.engine import get_session_with_tenant
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.enums import SyncType
from onyx.db.search_settings import get_all_search_settings
from onyx.db.sync_record import cleanup_sync_records
from onyx.db.sync_record import insert_sync_record
from onyx.redis.redis_connector import RedisConnector
from onyx.redis.redis_connector_delete import RedisConnectorDeletePayload
from onyx.redis.redis_pool import get_redis_client


class TaskDependencyError(RuntimeError):
    """Raised to the caller to indicate dependent tasks are running that would interfere
    with connector deletion."""


@shared_task(
    name=OnyxCeleryTask.CHECK_FOR_CONNECTOR_DELETION,
    soft_time_limit=JOB_TIMEOUT,
    trail=False,
    bind=True,
)
def check_for_connector_deletion_task(
    self: Task, *, tenant_id: str | None
) -> bool | None:
    r = get_redis_client(tenant_id=tenant_id)

    lock_beat: RedisLock = r.lock(
        OnyxRedisLocks.CHECK_CONNECTOR_DELETION_BEAT_LOCK,
        timeout=CELERY_VESPA_SYNC_BEAT_LOCK_TIMEOUT,
    )

    # these tasks should never overlap
    if not lock_beat.acquire(blocking=False):
        return None

    try:
        # collect cc_pair_ids
        cc_pair_ids: list[int] = []
        with get_session_with_tenant(tenant_id) as db_session:
            cc_pairs = get_connector_credential_pairs(db_session)
            for cc_pair in cc_pairs:
                cc_pair_ids.append(cc_pair.id)

        # try running cleanup on the cc_pair_ids
        for cc_pair_id in cc_pair_ids:
            with get_session_with_tenant(tenant_id) as db_session:
                redis_connector = RedisConnector(tenant_id, cc_pair_id)
                try:
                    try_generate_document_cc_pair_cleanup_tasks(
                        self.app, cc_pair_id, db_session, lock_beat, tenant_id
                    )
                except TaskDependencyError as e:
                    # this means we wanted to start deleting but dependent tasks were running
                    # Leave a stop signal to clear indexing and pruning tasks more quickly
                    task_logger.info(str(e))
                    redis_connector.stop.set_fence(True)
                else:
                    # clear the stop signal if it exists ... no longer needed
                    redis_connector.stop.set_fence(False)

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
    tenant_id: str | None,
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
    fence_payload = RedisConnectorDeletePayload(
        num_tasks=None,
        submitted=datetime.now(timezone.utc),
    )

    # create before setting fence to avoid race condition where the monitoring
    # task updates the sync record before it is created
    insert_sync_record(
        db_session=db_session,
        entity_id=cc_pair_id,
        sync_type=SyncType.CONNECTOR_DELETION,
    )
    redis_connector.delete.set_fence(fence_payload)

    try:
        # do not proceed if connector indexing or connector pruning are running
        search_settings_list = get_all_search_settings(db_session)
        for search_settings in search_settings_list:
            redis_connector_index = redis_connector.new_index(search_settings.id)
            if redis_connector_index.fenced:
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
