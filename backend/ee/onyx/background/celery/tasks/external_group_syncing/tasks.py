import time
import traceback
from datetime import datetime, timedelta, timezone
from functools import partial
from uuid import uuid4

from celery import Celery, Task, shared_task
from celery.exceptions import SoftTimeLimitExceeded
from redis.lock import Lock as RedisLock
from sqlalchemy.exc import NoResultFound

from ee.onyx.background.celery.tasks.external_group_syncing.group_sync_utils import (
    mark_all_relevant_cc_pairs_as_external_group_synced,
)
from ee.onyx.db.connector_credential_pair import get_all_auto_sync_cc_pairs
from ee.onyx.db.external_perm import (
    ExternalUserGroup,
    mark_old_external_groups_as_stale,
    remove_stale_external_groups,
    upsert_external_groups,
)
from ee.onyx.external_permissions.sync_params import (
    get_all_cc_pair_agnostic_group_sync_sources,
    get_source_perm_sync_config,
)
from onyx.background.celery.apps.app_base import task_logger
from onyx.background.celery.celery_redis import (
    celery_get_broker_client,
    celery_get_queued_task_ids,
    celery_get_unacked_task_ids,
)
from onyx.background.celery.tasks.shared.lease_heartbeat import LeaseHeartbeat
from onyx.background.error_logging import emit_background_error
from onyx.configs.app_configs import JOB_TIMEOUT, PERMISSION_SYNC_TIMEOUT
from onyx.configs.constants import (
    CELERY_GENERIC_BEAT_LOCK_TIMEOUT,
    PERMISSION_SYNC_HEARTBEAT_INTERVAL,
    PERMISSION_SYNC_LEASE_OVERRUN,
    PERMISSION_SYNC_LEASE_SELF_EXPIRY,
    PERMISSION_SYNC_LEASE_TIMEOUT,
    PERMISSION_SYNC_LOST_TASK_GRACE,
    PERMISSION_SYNC_TASK_EXPIRES,
    DocumentSource,
    OnyxCeleryPriority,
    OnyxCeleryQueues,
    OnyxCeleryTask,
    OnyxRedisLocks,
)
from onyx.db.connector_credential_pair import get_connector_credential_pair_from_id
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import ConnectorCredentialPair
from onyx.db.permission_sync_attempt import (
    ExternalGroupSyncProgress,
    complete_external_group_sync_attempt,
    fail_expired_external_group_sync_attempts,
    fail_not_started_external_group_sync_attempts,
    get_cc_pair_ids_with_open_external_group_sync_attempt,
    get_external_group_sync_retry_after,
    get_not_started_external_group_sync_attempts_older_than,
    mark_external_group_sync_attempt_failed,
    mark_external_group_sync_attempt_in_progress,
    renew_external_group_sync_attempt_lease,
    try_create_external_group_sync_attempt,
)
from onyx.redis.redis_pool import get_redis_client
from onyx.redis.redis_tenant_work_gating import maybe_mark_tenant_active
from onyx.server.metrics.perm_sync_metrics import (
    inc_group_sync_errors,
    inc_group_sync_groups_processed,
    inc_group_sync_users_processed,
    observe_group_sync_duration,
    observe_group_sync_upsert_duration,
)
from onyx.utils.logger import format_error_for_logging, setup_logger

logger = setup_logger()


_EXTERNAL_GROUP_BATCH_SIZE = 100

EXTERNAL_GROUP_SYNC_TASK_ID_PREFIX = "externalgroupsync"


def _fail_external_group_sync_attempt(
    attempt_id: int, error_msg: str, full_exception_trace: str | None = None
) -> None:
    """Helper to mark an external group sync attempt as failed with an error message."""
    with get_session_with_current_tenant() as db_session:
        mark_external_group_sync_attempt_failed(
            attempt_id,
            db_session,
            error_message=error_msg,
            full_exception_trace=full_exception_trace,
        )


def _renew_external_group_sync_lease(
    attempt_id: int, progress: ExternalGroupSyncProgress
) -> bool:
    with get_session_with_current_tenant() as db_session:
        return renew_external_group_sync_attempt_lease(attempt_id, db_session, progress)


def fail_expired_external_group_sync_attempts_for_tenant() -> None:
    lease_timeout = timedelta(seconds=PERMISSION_SYNC_LEASE_TIMEOUT)
    with get_session_with_current_tenant() as db_session:
        failed_ids = fail_expired_external_group_sync_attempts(
            db_session,
            lease_timeout=lease_timeout,
            # Celery has dropped the task by then, so it can never start
            not_started_timeout=timedelta(seconds=PERMISSION_SYNC_TASK_EXPIRES)
            + lease_timeout,
        )
    if failed_ids:
        task_logger.warning(
            f"Failed external group sync attempts with expired leases: {failed_ids}"
        )


def fail_lost_queued_external_group_sync_attempts(app: Celery) -> None:
    """Fails NOT_STARTED attempts whose task is no longer in the broker, so a
    lost task (e.g. a Redis restart without persistence) does not hold the
    pair's lock until the task would have expired. A task that a worker has
    already taken also looks lost here; its claim then fails and the beat
    dispatches the pair again, so the check errs only toward a redispatch."""
    with get_session_with_current_tenant() as db_session:
        candidates = get_not_started_external_group_sync_attempts_older_than(
            db_session, timedelta(seconds=PERMISSION_SYNC_LOST_TASK_GRACE)
        )
    if not candidates:
        return

    queue = OnyxCeleryQueues.CONNECTOR_EXTERNAL_GROUP_SYNC
    r_celery = celery_get_broker_client(app)
    live_task_ids = celery_get_queued_task_ids(
        queue, r_celery
    ) | celery_get_unacked_task_ids(queue, r_celery)
    lost_ids = [
        attempt_id
        for attempt_id, celery_task_id in candidates.items()
        if celery_task_id not in live_task_ids
    ]
    if not lost_ids:
        return

    with get_session_with_current_tenant() as db_session:
        failed_ids = fail_not_started_external_group_sync_attempts(
            db_session,
            lost_ids,
            reason="The queued group sync task was lost before a worker started it",
        )
    if failed_ids:
        task_logger.warning(
            f"Failed external group sync attempts whose queued task was lost: {failed_ids}"
        )


def is_external_group_sync_due(cc_pair: ConnectorCredentialPair) -> bool:
    """Returns boolean indicating if external group sync is due."""

    if not cc_pair.access_type.is_perm_synced():
        task_logger.error(
            f"Received non-sync CC Pair {cc_pair.id} for external group sync. Actual access type: {cc_pair.access_type}"
        )
        return False

    # A paused, invalid or deleting pair does not sync until it is active again.
    if not cc_pair.status.is_active():
        task_logger.debug(
            f"Skipping group sync for CC Pair {cc_pair.id} - status is {cc_pair.status}"
        )
        return False

    sync_config = get_source_perm_sync_config(cc_pair.connector.source)
    if sync_config is None:
        task_logger.debug(
            f"Skipping group sync for CC Pair {cc_pair.id} - no sync config found for {cc_pair.connector.source}"
        )
        return False

    # If there is not group sync function for the connector, we don't run the sync
    # This is fine because all sources dont necessarily have a concept of groups
    if sync_config.group_sync_config is None:
        task_logger.debug(
            f"Skipping group sync for CC Pair {cc_pair.id} - no group sync config found for {cc_pair.connector.source}"
        )
        return False

    # If the last sync is None, it has never been run so we run the sync
    last_ext_group_sync = cc_pair.last_time_external_group_sync
    if last_ext_group_sync is None:
        return True

    # A sync that completed before the pair began to wait for its first
    # permission sync does not count, so the pair is not hidden for a period.
    # This value is the completion time: a sync that started before the wait
    # and completed after it counts. That narrow race is accepted.
    pending_since = cc_pair.perm_sync_pending_since
    if pending_since is not None and last_ext_group_sync < pending_since:
        return True

    source_sync_period = sync_config.group_sync_config.group_sync_frequency

    # If the last sync is greater than the full fetch period, we run the sync
    next_sync = last_ext_group_sync + timedelta(seconds=source_sync_period)
    if datetime.now(timezone.utc) >= next_sync:
        return True

    return False


@shared_task(  # ty: ignore[invalid-argument-type]
    name=OnyxCeleryTask.CHECK_FOR_EXTERNAL_GROUP_SYNC,
    ignore_result=True,
    soft_time_limit=JOB_TIMEOUT,
    bind=True,
)
def check_for_external_group_sync(self: Task, *, tenant_id: str) -> bool | None:
    r = get_redis_client()

    lock_beat: RedisLock = r.lock(
        OnyxRedisLocks.CHECK_CONNECTOR_EXTERNAL_GROUP_SYNC_BEAT_LOCK,
        timeout=CELERY_GENERIC_BEAT_LOCK_TIMEOUT,
    )

    # these tasks should never overlap
    if not lock_beat.acquire(blocking=False):
        task_logger.warning(
            f"Failed to acquire beat lock for external group sync: {tenant_id}"
        )
        return None

    try:
        # Fail abandoned attempts first, so their cc_pairs can be dispatched again
        fail_expired_external_group_sync_attempts_for_tenant()
        fail_lost_queued_external_group_sync_attempts(self.app)

        cc_pair_ids_to_sync: list[int] = []
        with get_session_with_current_tenant() as db_session:
            cc_pairs = sorted(
                (
                    cc_pair
                    for cc_pair in get_all_auto_sync_cc_pairs(db_session)
                    if cc_pair.status.is_active()
                ),
                key=lambda cc_pair: cc_pair.id,
            )
            running_cc_pair_ids = get_cc_pair_ids_with_open_external_group_sync_attempt(
                db_session
            )

            # For some sources, the active cc_pair with the lowest id syncs
            # the groups for all cc_pairs of that source
            agnostic_sources = set(get_all_cc_pair_agnostic_group_sync_sources())
            seen_agnostic_sources: set[DocumentSource] = set()
            now = datetime.now(timezone.utc)
            for cc_pair in cc_pairs:
                source = cc_pair.connector.source
                if source in agnostic_sources:
                    if source in seen_agnostic_sources:
                        continue
                    seen_agnostic_sources.add(source)

                if cc_pair.id in running_cc_pair_ids:
                    continue

                if not is_external_group_sync_due(cc_pair):
                    continue

                retry_after = get_external_group_sync_retry_after(
                    cc_pair_id=cc_pair.id, db_session=db_session
                )
                if retry_after is not None and now < retry_after:
                    task_logger.debug(
                        f"Skipping group sync for CC Pair {cc_pair.id} - "
                        f"backing off after failures until {retry_after}"
                    )
                    continue

                cc_pair_ids_to_sync.append(cc_pair.id)

        # Tenant-work-gating hook: refresh this tenant's active-set membership
        # whenever external-group sync has any due cc_pairs to dispatch.
        if cc_pair_ids_to_sync:
            maybe_mark_tenant_active(tenant_id, caller="external_group_sync")

        lock_beat.reacquire()
        for cc_pair_id in cc_pair_ids_to_sync:
            attempt_id = try_creating_external_group_sync_task(
                self.app, cc_pair_id, tenant_id
            )
            if attempt_id is None:
                continue

            task_logger.info(
                f"External group sync queued: cc_pair={cc_pair_id} attempt={attempt_id}"
            )
    except SoftTimeLimitExceeded:
        task_logger.info(
            "Soft time limit exceeded, task is being terminated gracefully."
        )
    except Exception as e:
        error_msg = format_error_for_logging(e)
        task_logger.warning(
            f"Unexpected check_for_external_group_sync exception: tenant={tenant_id} {error_msg}"
        )
        task_logger.exception(f"Unexpected exception: tenant={tenant_id}")
    finally:
        if lock_beat.owned():
            lock_beat.release()

    task_logger.info(f"check_for_external_group_sync finished: tenant={tenant_id}")
    return True


def try_creating_external_group_sync_task(
    app: Celery,
    cc_pair_id: int,
    tenant_id: str,
) -> int | None:
    """Creates a NOT_STARTED attempt and dispatches the task that runs it.
    Returns the attempt ID, or None when nothing was dispatched because the
    cc_pair already has an open attempt."""
    celery_task_id = f"{EXTERNAL_GROUP_SYNC_TASK_ID_PREFIX}_{cc_pair_id}_{uuid4()}"
    with get_session_with_current_tenant() as db_session:
        attempt_id = try_create_external_group_sync_attempt(
            cc_pair_id, celery_task_id, db_session
        )
    if attempt_id is None:
        return None

    try:
        app.send_task(
            OnyxCeleryTask.CONNECTOR_EXTERNAL_GROUP_SYNC_GENERATOR_TASK,
            kwargs={
                "cc_pair_id": cc_pair_id,
                "tenant_id": tenant_id,
                "attempt_id": attempt_id,
            },
            queue=OnyxCeleryQueues.CONNECTOR_EXTERNAL_GROUP_SYNC,
            task_id=celery_task_id,
            priority=OnyxCeleryPriority.MEDIUM,
            expires=PERMISSION_SYNC_TASK_EXPIRES,
        )
    except Exception as e:
        task_logger.exception(
            f"Failed to dispatch external group sync: cc_pair={cc_pair_id} attempt={attempt_id}"
        )
        _fail_external_group_sync_attempt(
            attempt_id,
            f"Failed to dispatch the external group sync task: {format_error_for_logging(e)}",
            full_exception_trace=traceback.format_exc(),
        )
        return None

    return attempt_id


@shared_task(  # ty: ignore[invalid-argument-type]
    name=OnyxCeleryTask.CONNECTOR_EXTERNAL_GROUP_SYNC_GENERATOR_TASK,
    acks_late=False,
    soft_time_limit=JOB_TIMEOUT,
    track_started=True,
    trail=False,
    bind=True,
)
def connector_external_group_sync_generator_task(
    self: Task,  # noqa: ARG001
    cc_pair_id: int,
    tenant_id: str,
    attempt_id: int | None = None,
) -> None:
    """
    External group sync task for a given connector credential pair.
    The dispatcher created the NOT_STARTED attempt; this task owns it while its lease holds.
    """
    if attempt_id is None:
        # Dispatched by a release that kept the sync lock in Redis
        task_logger.warning(
            f"External group sync task has no attempt, skipping: cc_pair={cc_pair_id}"
        )
        return None

    with get_session_with_current_tenant() as db_session:
        try:
            mark_external_group_sync_attempt_in_progress(attempt_id, db_session)
        except (RuntimeError, NoResultFound):
            # The reaper or a cancel closed the attempt while the task was queued
            task_logger.warning(
                f"External group sync attempt is no longer runnable, skipping: "
                f"cc_pair={cc_pair_id} attempt={attempt_id}"
            )
            return None

    sync_start = time.monotonic()
    connector_type: str = "unknown"
    progress = ExternalGroupSyncProgress()
    heartbeat = LeaseHeartbeat(
        f"external_group_sync_attempt={attempt_id}",
        renew=partial(_renew_external_group_sync_lease, attempt_id, progress),
        interval=PERMISSION_SYNC_HEARTBEAT_INTERVAL,
        max_silence=PERMISSION_SYNC_LEASE_SELF_EXPIRY,
        max_duration=PERMISSION_SYNC_TIMEOUT + PERMISSION_SYNC_LEASE_OVERRUN,
    )
    heartbeat.start()
    try:
        connector_type = _timed_perform_external_group_sync(
            cc_pair_id=cc_pair_id,
            tenant_id=tenant_id,
            attempt_id=attempt_id,
            heartbeat=heartbeat,
            progress=progress,
        )
    except Exception as e:
        msg = f"External group sync exceptioned: cc_pair={cc_pair_id} attempt={attempt_id}"
        task_logger.exception(msg)
        emit_background_error(msg + f"\n\n{e}", cc_pair_id=cc_pair_id)
        # A no-op when the sync already recorded its own failure
        _fail_external_group_sync_attempt(
            attempt_id, str(e), full_exception_trace=traceback.format_exc()
        )
        raise e
    finally:
        heartbeat.stop()
        observe_group_sync_duration(time.monotonic() - sync_start, connector_type)

    task_logger.info(
        f"External group sync finished: cc_pair={cc_pair_id} attempt={attempt_id}"
    )


def _timed_perform_external_group_sync(
    cc_pair_id: int,
    tenant_id: str,
    attempt_id: int,
    heartbeat: LeaseHeartbeat,
    progress: ExternalGroupSyncProgress,
    timeout_seconds: int = PERMISSION_SYNC_TIMEOUT,
) -> str:
    with get_session_with_current_tenant() as db_session:
        cc_pair = get_connector_credential_pair_from_id(
            db_session=db_session,
            cc_pair_id=cc_pair_id,
            eager_load_credential=True,
        )
        if cc_pair is None:
            raise ValueError(f"No connector credential pair found for id: {cc_pair_id}")

        if not cc_pair.access_type.is_perm_synced():
            msg = f"cc_pair={cc_pair_id} is not perm-synced: {cc_pair.access_type}"
            _fail_external_group_sync_attempt(attempt_id, msg)
            raise ValueError(msg)

        source_type = cc_pair.connector.source
        connector_type = source_type.value
        sync_config = get_source_perm_sync_config(source_type)
        if sync_config is None:
            msg = f"No sync config found for {source_type} for cc_pair: {cc_pair_id}"
            emit_background_error(msg, cc_pair_id=cc_pair_id)
            _fail_external_group_sync_attempt(attempt_id, msg)
            raise ValueError(msg)

        if sync_config.group_sync_config is None:
            msg = f"No group sync config found for {source_type} for cc_pair: {cc_pair_id}"
            emit_background_error(msg, cc_pair_id=cc_pair_id)
            _fail_external_group_sync_attempt(attempt_id, msg)
            raise ValueError(msg)

        ext_group_sync_func = sync_config.group_sync_config.group_sync_func

        # Clean up stale rows from previous cycle BEFORE marking new ones.
        # This ensures cleanup always runs regardless of whether the current
        # sync succeeds — previously, cleanup only ran at the END of the sync,
        # so if the sync failed (e.g. DB connection killed by
        # idle_in_transaction_session_timeout during long API calls), stale
        # rows would accumulate indefinitely.
        logger.info(
            "Removing stale external groups from prior cycle for %s for cc_pair: %s",
            source_type,
            cc_pair_id,
        )
        remove_stale_external_groups(
            db_session, cc_pair_id, owning_attempt_id=attempt_id
        )

        logger.info(
            "Marking old external groups as stale for %s for cc_pair: %s",
            source_type,
            cc_pair_id,
        )
        mark_old_external_groups_as_stale(db_session, cc_pair_id)

        logger.info(
            "Syncing external groups for %s for cc_pair: %s",
            source_type,
            cc_pair_id,
        )
        external_user_group_batch: list[ExternalUserGroup] = []
        seen_users: set[str] = set()  # Track unique users across all groups
        total_groups_processed = 0
        total_group_memberships_synced = 0
        cumulative_upsert_time = 0.0
        start_time = time.monotonic()
        try:
            external_user_group_generator = ext_group_sync_func(tenant_id, cc_pair)
            for external_user_group in external_user_group_generator:
                # Check if the task has exceeded its timeout
                # NOTE: Celery's soft_time_limit does not work with thread pools,
                # so we must enforce timeouts internally.
                elapsed = time.monotonic() - start_time
                if elapsed > timeout_seconds:
                    raise RuntimeError(
                        f"External group sync stopped: timed out after "
                        f"{elapsed:.0f}s "
                        f"(PERMISSION_SYNC_TIMEOUT_SECONDS={timeout_seconds}): "
                        f"cc_pair={cc_pair_id} "
                        f"groups_processed={total_groups_processed}"
                    )
                if heartbeat.is_lost():
                    raise RuntimeError(
                        f"External group sync stopped: attempt lost its lease "
                        f"(the reaper failed it): "
                        f"cc_pair={cc_pair_id} attempt={attempt_id}"
                    )

                external_user_group_batch.append(external_user_group)

                # Track progress
                total_groups_processed += 1
                total_group_memberships_synced += len(external_user_group.user_emails)
                seen_users.update(external_user_group.user_emails)
                progress.total_groups_processed = total_groups_processed
                progress.total_group_memberships_synced = total_group_memberships_synced
                progress.total_users_processed = len(seen_users)
                progress.last_progress_at = datetime.now(timezone.utc)

                if len(external_user_group_batch) >= _EXTERNAL_GROUP_BATCH_SIZE:
                    logger.debug(
                        "New external user groups: %s", external_user_group_batch
                    )
                    upsert_start = time.monotonic()
                    upsert_external_groups(
                        db_session=db_session,
                        cc_pair_id=cc_pair_id,
                        external_groups=external_user_group_batch,
                        source=cc_pair.connector.source,
                        owning_attempt_id=attempt_id,
                    )
                    cumulative_upsert_time += time.monotonic() - upsert_start
                    external_user_group_batch = []

            if external_user_group_batch:
                logger.debug("New external user groups: %s", external_user_group_batch)
                upsert_start = time.monotonic()
                upsert_external_groups(
                    db_session=db_session,
                    cc_pair_id=cc_pair_id,
                    external_groups=external_user_group_batch,
                    source=cc_pair.connector.source,
                    owning_attempt_id=attempt_id,
                )
                cumulative_upsert_time += time.monotonic() - upsert_start
        except Exception as e:
            format_error_for_logging(e)

            # Mark as failed (this also updates progress to show partial progress)
            mark_external_group_sync_attempt_failed(
                attempt_id,
                db_session,
                error_message=str(e),
                full_exception_trace=traceback.format_exc(),
            )

            # TODO: add some notification to the admins here
            inc_group_sync_errors(connector_type)
            logger.exception(
                "Error syncing external groups for %s for cc_pair: %s %s",
                source_type,
                cc_pair_id,
                e,
            )
            raise e

        observe_group_sync_upsert_duration(cumulative_upsert_time, connector_type)

        logger.info(
            "Removing stale external groups for %s for cc_pair: %s",
            source_type,
            cc_pair_id,
        )
        remove_stale_external_groups(
            db_session, cc_pair_id, owning_attempt_id=attempt_id
        )

        # Calculate total unique users processed
        total_users_processed = len(seen_users)

        # Complete the sync attempt with final progress
        complete_external_group_sync_attempt(
            db_session=db_session,
            attempt_id=attempt_id,
            total_users_processed=total_users_processed,
            total_groups_processed=total_groups_processed,
            total_group_memberships_synced=total_group_memberships_synced,
            errors_encountered=0,
        )
        logger.info(
            "Completed external group sync attempt %s: %s groups, %s users, %s memberships",
            attempt_id,
            total_groups_processed,
            total_users_processed,
            total_group_memberships_synced,
        )

        inc_group_sync_groups_processed(connector_type, total_groups_processed)
        inc_group_sync_users_processed(connector_type, total_users_processed)

        mark_all_relevant_cc_pairs_as_external_group_synced(db_session, cc_pair)

    return connector_type
