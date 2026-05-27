"""Celery tasks for sandbox operations (cleanup, etc.)."""

from celery import shared_task
from celery import Task
from redis.lock import Lock as RedisLock

from onyx.background.celery.apps.app_base import task_logger
from onyx.configs.constants import OnyxCeleryTask
from onyx.configs.constants import OnyxRedisLocks
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.redis.redis_pool import get_redis_client
from onyx.redis.redis_tenant_work_gating import maybe_mark_tenant_active
from onyx.server.features.build.configs import SANDBOX_IDLE_TIMEOUT_SECONDS
from onyx.server.features.build.db.build_session import clear_nextjs_ports_for_user
from onyx.server.features.build.db.build_session import (
    mark_user_sessions_idle__no_commit,
)
from onyx.server.features.build.sandbox.base import get_sandbox_manager

# Snapshot retention period in days
SNAPSHOT_RETENTION_DAYS = 30

# 100 minutes - snapshotting can take time
TIMEOUT_SECONDS = 6000


@shared_task(
    name=OnyxCeleryTask.CLEANUP_IDLE_SANDBOXES,
    soft_time_limit=TIMEOUT_SECONDS,
    bind=True,
    ignore_result=True,
)
def cleanup_idle_sandboxes_task(self: Task, *, tenant_id: str) -> None:  # noqa: ARG001
    """Put idle sandboxes to sleep after snapshotting all sessions.

    This task:
    1. Finds sandboxes that have been idle longer than SANDBOX_IDLE_TIMEOUT_SECONDS
    2. Lists all session directories in the pod's /workspace/sessions/
    3. Creates a snapshot of each session's outputs to S3
    4. Terminates the pod (but keeps the sandbox record)
    5. Marks the sandbox as SLEEPING (can be restored later)

    Args:
        tenant_id: The tenant ID for multi-tenant isolation
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
        # Import here to avoid circular imports
        from onyx.db.enums import SandboxStatus
        from onyx.server.features.build.db.sandbox import create_snapshot__no_commit
        from onyx.server.features.build.db.sandbox import get_idle_sandboxes
        from onyx.server.features.build.db.sandbox import (
            update_sandbox_status__no_commit,
        )

        sandbox_manager = get_sandbox_manager()

        with get_session_with_current_tenant() as db_session:
            idle_sandboxes = get_idle_sandboxes(
                db_session, SANDBOX_IDLE_TIMEOUT_SECONDS
            )

            if not idle_sandboxes:
                task_logger.debug("No idle sandboxes found")
                return

            # Tenant-work-gating hook: refresh this tenant's active-set
            # membership whenever sandbox cleanup has work to do.
            maybe_mark_tenant_active(tenant_id, caller="sandbox_cleanup")

            task_logger.info(
                f"Found {len(idle_sandboxes)} idle sandboxes to put to sleep"
            )

            for sandbox in idle_sandboxes:
                sandbox_id = sandbox.id
                sandbox_id_str = str(sandbox_id)
                task_logger.info(f"Putting sandbox {sandbox_id_str} to sleep")

                try:
                    # List session directories in the sandbox via the
                    # backend-agnostic manager API. K8s lists pod paths via
                    # exec; Docker lists container paths via exec; Local
                    # walks the on-disk sessions/ directory.
                    session_ids = sandbox_manager.list_session_workspaces(sandbox_id)
                    task_logger.info(
                        f"Found {len(session_ids)} sessions in sandbox {sandbox_id_str}"
                    )

                    # Snapshot each session
                    for session_id in session_ids:
                        try:
                            task_logger.debug(
                                f"Creating snapshot for session {session_id}"
                            )
                            snapshot_result = sandbox_manager.create_snapshot(
                                sandbox_id, session_id, tenant_id
                            )
                            if snapshot_result:
                                # Create DB record for the snapshot
                                create_snapshot__no_commit(
                                    db_session,
                                    session_id,
                                    snapshot_result.storage_path,
                                    snapshot_result.size_bytes,
                                )
                                task_logger.debug(
                                    f"Snapshot created for session {session_id}"
                                )
                        except Exception as e:
                            task_logger.warning(
                                f"Failed to create snapshot for session {session_id}: {e}"
                            )
                            # Continue with other sessions even if one fails

                    # Terminate the pod (but keep sandbox record)
                    sandbox_manager.terminate(sandbox_id)

                    # Zero out nextjs ports for all sessions (ports are no longer in use)
                    cleared = clear_nextjs_ports_for_user(db_session, sandbox.user_id)
                    task_logger.debug(
                        f"Cleared {cleared} nextjs_port allocations for user {sandbox.user_id}"
                    )

                    # Mark all active sessions as IDLE
                    idled = mark_user_sessions_idle__no_commit(
                        db_session, sandbox.user_id
                    )
                    task_logger.debug(
                        f"Marked {idled} sessions as IDLE for user {sandbox.user_id}"
                    )

                    update_sandbox_status__no_commit(
                        db_session, sandbox_id, SandboxStatus.SLEEPING
                    )
                    db_session.commit()
                    task_logger.info(f"Sandbox {sandbox_id_str} is now sleeping")

                except Exception as e:
                    task_logger.error(
                        f"Failed to put sandbox {sandbox_id_str} to sleep: {e}",
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
