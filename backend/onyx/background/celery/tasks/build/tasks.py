"""Celery tasks for sandbox operations (cleanup, etc.)."""

import datetime
import time

from celery import Task, shared_task
from redis.lock import Lock as RedisLock

from onyx.background.celery.apps.app_base import task_logger
from onyx.configs.constants import OnyxCeleryTask, OnyxRedisLocks
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import Sandbox
from onyx.redis.redis_pool import get_redis_client
from onyx.redis.redis_tenant_work_gating import maybe_mark_tenant_active
from onyx.server.features.build.configs import SANDBOX_IDLE_TIMEOUT_SECONDS
from onyx.server.features.build.db.sandbox import (
    get_latest_snapshot_for_session,
    get_running_sandboxes,
    user_has_stale_active_session,
)
from onyx.server.features.build.sandbox.factory import get_sandbox_manager
from onyx.server.features.build.session.sandbox_lifecycle import (
    create_session_snapshot_keep_latest,
    is_sandbox_idle,
    sleep_sandbox,
)

# 100 minutes - snapshotting can take time
TIMEOUT_SECONDS = 6000

# Background snapshots ride the idle timeout: a session is re-snapshotted when
# its latest snapshot is older than idle_timeout/4 (15 min at the default 1h),
# so the data-loss bound scales with the pace of sandboxes going to sleep.
SNAPSHOT_INTERVAL_DIVISOR = 4


@shared_task(
    name=OnyxCeleryTask.CLEANUP_IDLE_SANDBOXES,
    soft_time_limit=TIMEOUT_SECONDS,
    bind=True,
    ignore_result=True,
)
def cleanup_idle_sandboxes_task(self: Task, *, tenant_id: str) -> None:  # noqa: ARG001
    """Sweep RUNNING sandboxes: background-snapshot sessions, sleep idle ones.

    Background snapshots bound data loss from ungraceful pod death (kubelet
    eviction, node loss, spot reclaim) to ~idle_timeout/SNAPSHOT_INTERVAL_DIVISOR:
    sessions whose latest snapshot is fresher than that interval are skipped
    without touching the pod (except at reap — the pod is about to die, so
    always snapshot).
    The reap itself is ``sleep_sandbox`` (sandbox lifecycle), which stays
    fail-closed: snapshot failure on a reachable pod keeps the sandbox
    RUNNING for retry next sweep.
    """
    task_logger.info(f"cleanup_idle_sandboxes_task starting for tenant {tenant_id}")

    redis_client = get_redis_client(tenant_id=tenant_id)
    lock: RedisLock = redis_client.lock(
        OnyxRedisLocks.CLEANUP_IDLE_SANDBOXES_BEAT_LOCK,
        timeout=TIMEOUT_SECONDS,
    )

    # Prevent overlapping runs of this task
    if not lock.acquire(blocking=False):
        task_logger.info("cleanup_idle_sandboxes_task - lock not acquired, skipping")
        return

    try:
        sandbox_manager = get_sandbox_manager()

        with get_session_with_current_tenant() as db_session:
            running_sandboxes = get_running_sandboxes(db_session)
            if not running_sandboxes:
                task_logger.debug("No running sandboxes found")
                return

            # Tenant-work-gating hook: refresh this tenant's active-set
            # membership whenever the sweep has work to do.
            maybe_mark_tenant_active(tenant_id, caller="sandbox_cleanup")

            now = datetime.datetime.now(datetime.timezone.utc)
            snapshot_cutoff = now - datetime.timedelta(
                seconds=SANDBOX_IDLE_TIMEOUT_SECONDS // SNAPSHOT_INTERVAL_DIVISOR
            )

            # Partition so idle sandboxes are reaped first (reclaiming pods
            # is time-sensitive) before the rest are background-snapshotted.
            idle_sandboxes: list[Sandbox] = []
            non_idle_sandboxes: list[Sandbox] = []
            for sandbox in running_sandboxes:
                (
                    idle_sandboxes
                    if is_sandbox_idle(sandbox, now)
                    else non_idle_sandboxes
                ).append(sandbox)

            for sandbox in idle_sandboxes:
                try:
                    sleep_sandbox(
                        db_session=db_session,
                        sandbox_manager=sandbox_manager,
                        sandbox=sandbox,
                        tenant_id=tenant_id,
                    )
                except Exception as e:
                    task_logger.error(
                        f"Failed to sweep sandbox {sandbox.id}: {e}",
                        exc_info=True,
                    )
                    db_session.rollback()

            for sandbox in non_idle_sandboxes:
                sandbox_id = sandbox.id

                try:
                    # DB-only prefilter: listing workspaces is a pod exec, so
                    # skip it when every ACTIVE session already has a fresh
                    # snapshot.
                    if not user_has_stale_active_session(
                        db_session, sandbox.user_id, snapshot_cutoff
                    ):
                        continue

                    # List session directories in the sandbox via the
                    # backend-agnostic manager API. K8s lists pod paths via
                    # exec; Docker lists container paths via exec; Local
                    # walks the on-disk sessions/ directory.
                    session_ids = sandbox_manager.list_session_workspaces(sandbox_id)

                    # Background snapshot failures are log-only (unlike the
                    # reap path, nothing is about to be terminated).
                    snapshots_created = 0
                    for session_id in session_ids:
                        try:
                            latest = get_latest_snapshot_for_session(
                                db_session, session_id
                            )
                            if latest and latest.created_at > snapshot_cutoff:
                                continue

                            snapshot_start = time.monotonic()
                            snapshot_result = create_session_snapshot_keep_latest(
                                sandbox_manager=sandbox_manager,
                                db_session=db_session,
                                sandbox_id=sandbox_id,
                                session_id=session_id,
                                tenant_id=tenant_id,
                            )
                            snapshot_elapsed = time.monotonic() - snapshot_start
                            if snapshot_result:
                                snapshots_created += 1
                                task_logger.info(
                                    f"Snapshot created for session {session_id}: "
                                    f"{snapshot_result.size_bytes / 1_048_576:.1f} MiB "
                                    f"in {snapshot_elapsed:.1f}s"
                                )
                        except Exception as e:
                            task_logger.warning(
                                f"Failed to create snapshot for session {session_id}: {e}"
                            )
                            db_session.rollback()

                    # Chat history lives outside session workspaces;
                    # keep it equally fresh.
                    if (
                        snapshots_created
                        and sandbox_manager.supports_opencode_history_persistence
                    ):
                        try:
                            sandbox_manager.create_opencode_history_snapshot(
                                sandbox_id, tenant_id
                            )
                        except Exception as e:
                            task_logger.warning(
                                f"Background opencode history snapshot failed "
                                f"for sandbox {sandbox_id}: {e}"
                            )

                except Exception as e:
                    task_logger.error(
                        f"Failed to sweep sandbox {sandbox_id}: {e}",
                        exc_info=True,
                    )
                    db_session.rollback()

    except Exception:
        task_logger.exception("Error in cleanup_idle_sandboxes_task")
        raise

    finally:
        if lock.owned():
            lock.release()

    task_logger.info("cleanup_idle_sandboxes_task completed")
