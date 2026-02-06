"""Celery tasks for sandbox operations (cleanup, file sync, etc.)."""

from uuid import UUID

from celery import shared_task
from celery import Task
from redis.lock import Lock as RedisLock

from onyx.background.celery.apps.app_base import task_logger
from onyx.configs.constants import OnyxCeleryTask
from onyx.configs.constants import OnyxRedisLocks
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import SandboxStatus
from onyx.redis.redis_pool import get_redis_client
from onyx.server.features.build.configs import SANDBOX_BACKEND
from onyx.server.features.build.configs import SANDBOX_IDLE_TIMEOUT_SECONDS
from onyx.server.features.build.configs import SandboxBackend
from onyx.server.features.build.db.build_session import clear_nextjs_ports_for_user
from onyx.server.features.build.db.sandbox import get_sandbox_by_user_id
from onyx.server.features.build.sandbox.base import get_sandbox_manager
from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
    KubernetesSandboxManager,
)


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

    NOTE: This task is a no-op for local backend - sandboxes persist until
    manually terminated or server restart.

    Args:
        tenant_id: The tenant ID for multi-tenant isolation
    """
    # Skip cleanup for local backend - sandboxes persist until manual termination
    if SANDBOX_BACKEND == SandboxBackend.LOCAL:
        task_logger.debug(
            "cleanup_idle_sandboxes_task skipped (local backend - cleanup disabled)"
        )
        return

    task_logger.info(f"cleanup_idle_sandboxes_task starting for tenant {tenant_id}")

    redis_client = get_redis_client(tenant_id=tenant_id)
    lock: RedisLock = redis_client.lock(
        OnyxRedisLocks.CLEANUP_IDLE_SANDBOXES_BEAT_LOCK,
        timeout=TIMEOUT_SECONDS,
    )

    # Prevent overlapping runs of this task
    if not lock.acquire(blocking=False):
        task_logger.debug("cleanup_idle_sandboxes_task - lock not acquired, skipping")
        return

    try:
        # Import here to avoid circular imports
        from onyx.db.enums import SandboxStatus
        from onyx.server.features.build.db.sandbox import create_snapshot
        from onyx.server.features.build.db.sandbox import get_idle_sandboxes
        from onyx.server.features.build.db.sandbox import (
            update_sandbox_status__no_commit,
        )
        from onyx.server.features.build.sandbox import get_sandbox_manager

        sandbox_manager = get_sandbox_manager()

        # Type guard for kubernetes-specific methods
        if not isinstance(sandbox_manager, KubernetesSandboxManager):
            task_logger.debug(
                "cleanup_idle_sandboxes_task skipped (not kubernetes backend)"
            )
            return

        with get_session_with_current_tenant() as db_session:
            idle_sandboxes = get_idle_sandboxes(
                db_session, SANDBOX_IDLE_TIMEOUT_SECONDS
            )

            if not idle_sandboxes:
                task_logger.debug("No idle sandboxes found")
                return

            task_logger.info(
                f"Found {len(idle_sandboxes)} idle sandboxes to put to sleep"
            )

            for sandbox in idle_sandboxes:
                sandbox_id = sandbox.id
                sandbox_id_str = str(sandbox_id)
                task_logger.info(f"Putting sandbox {sandbox_id_str} to sleep")

                try:
                    # List session directories in the pod
                    session_ids = _list_session_directories(sandbox_manager, sandbox_id)
                    task_logger.info(
                        f"Found {len(session_ids)} sessions in sandbox {sandbox_id_str}"
                    )

                    # Snapshot each session
                    for session_id_str in session_ids:
                        try:
                            session_id = UUID(session_id_str)
                            task_logger.debug(
                                f"Creating snapshot for session {session_id_str}"
                            )
                            snapshot_result = sandbox_manager.create_snapshot(
                                sandbox_id, session_id, tenant_id
                            )
                            if snapshot_result:
                                # Create DB record for the snapshot
                                create_snapshot(
                                    db_session,
                                    session_id,
                                    snapshot_result.storage_path,
                                    snapshot_result.size_bytes,
                                )
                                task_logger.debug(
                                    f"Snapshot created for session {session_id_str}"
                                )
                        except Exception as e:
                            task_logger.warning(
                                f"Failed to create snapshot for session "
                                f"{session_id_str}: {e}"
                            )
                            # Continue with other sessions even if one fails

                    # Terminate the pod (but keep sandbox record)
                    sandbox_manager.terminate(sandbox_id)

                    # Zero out nextjs ports for all sessions (ports are no longer in use)
                    cleared = clear_nextjs_ports_for_user(db_session, sandbox.user_id)
                    task_logger.debug(
                        f"Cleared {cleared} nextjs_port allocations for user "
                        f"{sandbox.user_id}"
                    )

                    # Mark sandbox as SLEEPING (not TERMINATED)
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


def _list_session_directories(
    sandbox_manager: KubernetesSandboxManager,
    sandbox_id: UUID,
) -> list[str]:
    """List session directory names in the pod's /workspace/sessions/.

    Args:
        sandbox_manager: The kubernetes sandbox manager
        sandbox_id: The sandbox ID

    Returns:
        List of session ID strings (directory names)
    """
    from kubernetes.client.rest import ApiException  # type: ignore
    from kubernetes.stream import stream as k8s_stream  # type: ignore

    pod_name = sandbox_manager._get_pod_name(str(sandbox_id))

    # List directories in /workspace/sessions/
    exec_command = [
        "/bin/sh",
        "-c",
        'ls -1 /workspace/sessions/ 2>/dev/null || echo ""',
    ]

    try:
        resp = k8s_stream(
            sandbox_manager._core_api.connect_get_namespaced_pod_exec,
            name=pod_name,
            namespace=sandbox_manager._namespace,
            container="sandbox",
            command=exec_command,
            stderr=True,
            stdin=False,
            stdout=True,
            tty=False,
        )

        # Parse output - one directory name per line
        session_ids = []
        for line in resp.strip().split("\n"):
            line = line.strip()
            if line:
                # Validate it looks like a UUID
                try:
                    UUID(line)
                    session_ids.append(line)
                except ValueError:
                    # Not a valid UUID, skip
                    pass

        return session_ids

    except ApiException as e:
        task_logger.warning(f"Failed to list session directories: {e}")
        return []


@shared_task(
    name=OnyxCeleryTask.SANDBOX_FILE_SYNC,
    soft_time_limit=TIMEOUT_SECONDS,
    bind=True,
    ignore_result=True,
)
def sync_sandbox_files(
    self: Task, *, user_id: str, tenant_id: str  # noqa: ARG001
) -> bool:
    """Sync files from S3 to a user's running sandbox.

    This task is triggered after documents are written to S3 during indexing.
    It executes `s5cmd sync` in the file-sync sidecar container to download
    any new or changed files.

    This is safe to call multiple times - s5cmd sync is idempotent.

    Args:
        user_id: The user ID whose sandbox should be synced
        tenant_id: The tenant ID for S3 path construction

    Returns:
        True if sync was successful, False if skipped or failed
    """
    task_logger.info(
        f"sync_sandbox_files starting for user {user_id} in tenant {tenant_id}"
    )

    with get_session_with_current_tenant() as db_session:
        sandbox = get_sandbox_by_user_id(db_session, UUID(user_id))

        if sandbox is None:
            task_logger.debug(f"No sandbox found for user {user_id}, skipping sync")
            return False

        if sandbox.status not in [SandboxStatus.RUNNING, SandboxStatus.IDLE]:
            task_logger.debug(
                f"Sandbox {sandbox.id} not running (status={sandbox.status}), "
                f"skipping sync"
            )
            return False

        sandbox_manager = get_sandbox_manager()
        result = sandbox_manager.sync_files(
            sandbox_id=sandbox.id,
            user_id=UUID(user_id),
            tenant_id=tenant_id,
        )

        if result:
            task_logger.info(f"File sync completed for user {user_id}")
        else:
            task_logger.warning(f"File sync failed for user {user_id}")

        return result


# NOTE: in the future, may need to add this. For now, will do manual cleanup.
# @shared_task(
#     name=OnyxCeleryTask.CLEANUP_OLD_SNAPSHOTS,
#     soft_time_limit=300,
#     bind=True,
#     ignore_result=True,
# )
# def cleanup_old_snapshots_task(self: Task, *, tenant_id: str) -> None:
#     """Delete snapshots older than the retention period.

#     This task cleans up old snapshots to manage storage usage.
#     Snapshots older than SNAPSHOT_RETENTION_DAYS are deleted.

#     NOTE: This task is a no-op for local backend since snapshots are disabled.

#     Args:
#         tenant_id: The tenant ID for multi-tenant isolation
#     """
#     # Skip for local backend - no snapshots to clean up
#     if SANDBOX_BACKEND == SandboxBackend.LOCAL:
#         task_logger.debug(
#             "cleanup_old_snapshots_task skipped (local backend - snapshots disabled)"
#         )
#         return

#     task_logger.info(f"cleanup_old_snapshots_task starting for tenant {tenant_id}")

#     redis_client = get_redis_client(tenant_id=tenant_id)
#     lock: RedisLock = redis_client.lock(
#         OnyxRedisLocks.CLEANUP_OLD_SNAPSHOTS_BEAT_LOCK,
#         timeout=CELERY_GENERIC_BEAT_LOCK_TIMEOUT,
#     )

#     # Prevent overlapping runs of this task
#     if not lock.acquire(blocking=False):
#         task_logger.debug("cleanup_old_snapshots_task - lock not acquired, skipping")
#         return

#     try:
#         from onyx.server.features.build.db.sandbox import delete_old_snapshots

#         with get_session_with_current_tenant() as db_session:
#             deleted_count = delete_old_snapshots(
#                 db_session, tenant_id, SNAPSHOT_RETENTION_DAYS
#             )

#             if deleted_count > 0:
#                 task_logger.info(
#                     f"Deleted {deleted_count} old snapshots for tenant {tenant_id}"
#                 )
#             else:
#                 task_logger.debug("No old snapshots to delete")

#     except Exception:
#         task_logger.exception("Error in cleanup_old_snapshots_task")
#         raise

#     finally:
#         if lock.owned():
#             lock.release()

#     task_logger.info("cleanup_old_snapshots_task completed")
