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

from ee.onyx.db.connector_credential_pair import get_all_auto_sync_cc_pairs
from ee.onyx.db.connector_credential_pair import get_cc_pairs_by_source
from ee.onyx.db.external_perm import ExternalUserGroup
from ee.onyx.db.external_perm import replace_user__ext_group_for_cc_pair
from ee.onyx.external_permissions.sync_params import EXTERNAL_GROUP_SYNC_PERIODS
from ee.onyx.external_permissions.sync_params import GROUP_PERMISSIONS_FUNC_MAP
from ee.onyx.external_permissions.sync_params import (
    GROUP_PERMISSIONS_IS_CC_PAIR_AGNOSTIC,
)
from onyx.background.celery.apps.app_base import task_logger
from onyx.configs.app_configs import JOB_TIMEOUT
from onyx.configs.constants import CELERY_EXTERNAL_GROUP_SYNC_LOCK_TIMEOUT
from onyx.configs.constants import CELERY_VESPA_SYNC_BEAT_LOCK_TIMEOUT
from onyx.configs.constants import DANSWER_REDIS_FUNCTION_LOCK_PREFIX
from onyx.configs.constants import OnyxCeleryPriority
from onyx.configs.constants import OnyxCeleryQueues
from onyx.configs.constants import OnyxCeleryTask
from onyx.configs.constants import OnyxRedisLocks
from onyx.db.connector import mark_cc_pair_as_external_group_synced
from onyx.db.connector_credential_pair import get_connector_credential_pair_from_id
from onyx.db.engine import get_session_with_tenant
from onyx.db.enums import AccessType
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.models import ConnectorCredentialPair
from onyx.redis.redis_connector import RedisConnector
from onyx.redis.redis_connector_ext_group_sync import (
    RedisConnectorExternalGroupSyncPayload,
)
from onyx.redis.redis_pool import get_redis_client
from onyx.utils.logger import setup_logger

logger = setup_logger()


EXTERNAL_GROUPS_UPDATE_MAX_RETRIES = 3


# 5 seconds more than RetryDocumentIndex STOP_AFTER+MAX_WAIT
LIGHT_SOFT_TIME_LIMIT = 105
LIGHT_TIME_LIMIT = LIGHT_SOFT_TIME_LIMIT + 15


def _is_external_group_sync_due(cc_pair: ConnectorCredentialPair) -> bool:
    """Returns boolean indicating if external group sync is due."""

    if cc_pair.access_type != AccessType.SYNC:
        return False

    # skip external group sync if not active
    if cc_pair.status != ConnectorCredentialPairStatus.ACTIVE:
        return False

    if cc_pair.status == ConnectorCredentialPairStatus.DELETING:
        return False

    # If there is not group sync function for the connector, we don't run the sync
    # This is fine because all sources dont necessarily have a concept of groups
    if not GROUP_PERMISSIONS_FUNC_MAP.get(cc_pair.connector.source):
        return False

    # If the last sync is None, it has never been run so we run the sync
    last_ext_group_sync = cc_pair.last_time_external_group_sync
    if last_ext_group_sync is None:
        return True

    source_sync_period = EXTERNAL_GROUP_SYNC_PERIODS.get(cc_pair.connector.source)

    # If EXTERNAL_GROUP_SYNC_PERIODS is None, we always run the sync.
    if not source_sync_period:
        return True

    # If the last sync is greater than the full fetch period, we run the sync
    next_sync = last_ext_group_sync + timedelta(seconds=source_sync_period)
    if datetime.now(timezone.utc) >= next_sync:
        return True

    return False


@shared_task(
    name=OnyxCeleryTask.CHECK_FOR_EXTERNAL_GROUP_SYNC,
    soft_time_limit=JOB_TIMEOUT,
    bind=True,
)
def check_for_external_group_sync(self: Task, *, tenant_id: str | None) -> bool | None:
    r = get_redis_client(tenant_id=tenant_id)

    lock_beat: RedisLock = r.lock(
        OnyxRedisLocks.CHECK_CONNECTOR_EXTERNAL_GROUP_SYNC_BEAT_LOCK,
        timeout=CELERY_VESPA_SYNC_BEAT_LOCK_TIMEOUT,
    )

    # these tasks should never overlap
    if not lock_beat.acquire(blocking=False):
        return None

    try:
        cc_pair_ids_to_sync: list[int] = []
        with get_session_with_tenant(tenant_id) as db_session:
            cc_pairs = get_all_auto_sync_cc_pairs(db_session)

            # We only want to sync one cc_pair per source type in
            # GROUP_PERMISSIONS_IS_CC_PAIR_AGNOSTIC
            for source in GROUP_PERMISSIONS_IS_CC_PAIR_AGNOSTIC:
                # These are ordered by cc_pair id so the first one is the one we want
                cc_pairs_to_dedupe = get_cc_pairs_by_source(
                    db_session, source, only_sync=True
                )
                # We only want to sync one cc_pair per source type
                # in GROUP_PERMISSIONS_IS_CC_PAIR_AGNOSTIC so we dedupe here
                for cc_pair_to_remove in cc_pairs_to_dedupe[1:]:
                    cc_pairs = [
                        cc_pair
                        for cc_pair in cc_pairs
                        if cc_pair.id != cc_pair_to_remove.id
                    ]

            for cc_pair in cc_pairs:
                if _is_external_group_sync_due(cc_pair):
                    cc_pair_ids_to_sync.append(cc_pair.id)

        for cc_pair_id in cc_pair_ids_to_sync:
            tasks_created = try_creating_external_group_sync_task(
                self.app, cc_pair_id, r, tenant_id
            )
            if not tasks_created:
                continue

            task_logger.info(f"External group sync queued: cc_pair={cc_pair_id}")
    except SoftTimeLimitExceeded:
        task_logger.info(
            "Soft time limit exceeded, task is being terminated gracefully."
        )
    except Exception:
        task_logger.exception(f"Unexpected exception: tenant={tenant_id}")
    finally:
        if lock_beat.owned():
            lock_beat.release()

    return True


def try_creating_external_group_sync_task(
    app: Celery,
    cc_pair_id: int,
    r: Redis,
    tenant_id: str | None,
) -> int | None:
    """Returns an int if syncing is needed. The int represents the number of sync tasks generated.
    Returns None if no syncing is required."""
    redis_connector = RedisConnector(tenant_id, cc_pair_id)

    LOCK_TIMEOUT = 30

    lock: RedisLock = r.lock(
        DANSWER_REDIS_FUNCTION_LOCK_PREFIX + "try_generate_external_group_sync_tasks",
        timeout=LOCK_TIMEOUT,
    )

    acquired = lock.acquire(blocking_timeout=LOCK_TIMEOUT / 2)
    if not acquired:
        return None

    try:
        # Dont kick off a new sync if the previous one is still running
        if redis_connector.external_group_sync.fenced:
            return None

        redis_connector.external_group_sync.generator_clear()
        redis_connector.external_group_sync.taskset_clear()

        custom_task_id = f"{redis_connector.external_group_sync.taskset_key}_{uuid4()}"

        result = app.send_task(
            OnyxCeleryTask.CONNECTOR_EXTERNAL_GROUP_SYNC_GENERATOR_TASK,
            kwargs=dict(
                cc_pair_id=cc_pair_id,
                tenant_id=tenant_id,
            ),
            queue=OnyxCeleryQueues.CONNECTOR_EXTERNAL_GROUP_SYNC,
            task_id=custom_task_id,
            priority=OnyxCeleryPriority.HIGH,
        )

        payload = RedisConnectorExternalGroupSyncPayload(
            started=datetime.now(timezone.utc),
            celery_task_id=result.id,
        )

        redis_connector.external_group_sync.set_fence(payload)

    except Exception:
        task_logger.exception(
            f"Unexpected exception while trying to create external group sync task: cc_pair={cc_pair_id}"
        )
        return None
    finally:
        if lock.owned():
            lock.release()

    return 1


@shared_task(
    name=OnyxCeleryTask.CONNECTOR_EXTERNAL_GROUP_SYNC_GENERATOR_TASK,
    acks_late=False,
    soft_time_limit=JOB_TIMEOUT,
    track_started=True,
    trail=False,
    bind=True,
)
def connector_external_group_sync_generator_task(
    self: Task,
    cc_pair_id: int,
    tenant_id: str | None,
) -> None:
    """
    Permission sync task that handles external group syncing for a given connector credential pair
    This task assumes that the task has already been properly fenced
    """

    redis_connector = RedisConnector(tenant_id, cc_pair_id)

    r = get_redis_client(tenant_id=tenant_id)

    lock: RedisLock = r.lock(
        OnyxRedisLocks.CONNECTOR_EXTERNAL_GROUP_SYNC_LOCK_PREFIX
        + f"_{redis_connector.id}",
        timeout=CELERY_EXTERNAL_GROUP_SYNC_LOCK_TIMEOUT,
    )

    try:
        acquired = lock.acquire(blocking=False)
        if not acquired:
            task_logger.warning(
                f"External group sync task already running, exiting...: cc_pair={cc_pair_id}"
            )
            return None

        with get_session_with_tenant(tenant_id) as db_session:
            cc_pair = get_connector_credential_pair_from_id(
                cc_pair_id=cc_pair_id,
                db_session=db_session,
            )
            if cc_pair is None:
                raise ValueError(
                    f"No connector credential pair found for id: {cc_pair_id}"
                )

            source_type = cc_pair.connector.source

            ext_group_sync_func = GROUP_PERMISSIONS_FUNC_MAP.get(source_type)
            if ext_group_sync_func is None:
                raise ValueError(
                    f"No external group sync func found for {source_type} for cc_pair: {cc_pair_id}"
                )

            logger.info(
                f"Syncing external groups for {source_type} for cc_pair: {cc_pair_id}"
            )

            external_user_groups: list[ExternalUserGroup] = ext_group_sync_func(cc_pair)

            logger.info(
                f"Syncing {len(external_user_groups)} external user groups for {source_type}"
            )

            replace_user__ext_group_for_cc_pair(
                db_session=db_session,
                cc_pair_id=cc_pair.id,
                group_defs=external_user_groups,
                source=cc_pair.connector.source,
            )
            logger.info(
                f"Synced {len(external_user_groups)} external user groups for {source_type}"
            )

            mark_cc_pair_as_external_group_synced(db_session, cc_pair.id)
    except Exception as e:
        task_logger.exception(
            f"Failed to run external group sync: cc_pair={cc_pair_id}"
        )

        redis_connector.external_group_sync.generator_clear()
        redis_connector.external_group_sync.taskset_clear()
        raise e
    finally:
        # we always want to clear the fence after the task is done or failed so it doesn't get stuck
        redis_connector.external_group_sync.set_fence(None)
        if lock.owned():
            lock.release()
