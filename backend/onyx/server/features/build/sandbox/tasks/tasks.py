# """Celery tasks for sandbox cleanup operations."""

# from celery import shared_task
# from celery import Task
# from redis.lock import Lock as RedisLock

# from onyx.background.celery.apps.app_base import task_logger
# from onyx.configs.constants import CELERY_GENERIC_BEAT_LOCK_TIMEOUT
# from onyx.configs.constants import OnyxCeleryTask
# from onyx.configs.constants import OnyxRedisLocks
# from onyx.db.engine.sql_engine import get_session_with_current_tenant
# from onyx.redis.redis_pool import get_redis_client
# from onyx.server.features.build.configs import SANDBOX_BACKEND
# from onyx.server.features.build.configs import SANDBOX_IDLE_TIMEOUT_SECONDS
# from onyx.server.features.build.configs import SandboxBackend


# # Snapshot retention period in days
# SNAPSHOT_RETENTION_DAYS = 30


# @shared_task(
#     name=OnyxCeleryTask.CLEANUP_IDLE_SANDBOXES,
#     soft_time_limit=300,
#     bind=True,
#     ignore_result=True,
# )
# def cleanup_idle_sandboxes_task(self: Task, *, tenant_id: str) -> None:
#     """Clean up sandboxes that have been idle for longer than the timeout.

#     This task:
#     1. Finds sandboxes that have been idle longer than SANDBOX_IDLE_TIMEOUT_SECONDS
#     2. Creates a snapshot of each idle sandbox (to preserve work) - kubernetes only
#     3. Terminates the sandbox and cleans up resources

#     NOTE: This task is a no-op for local backend - sandboxes persist until
#     manually terminated or server restart.

#     Args:
#         tenant_id: The tenant ID for multi-tenant isolation
#     """
#     # Skip cleanup for local backend - sandboxes persist until manual termination
#     if SANDBOX_BACKEND == SandboxBackend.LOCAL:
#         task_logger.debug(
#             "cleanup_idle_sandboxes_task skipped (local backend - cleanup disabled)"
#         )
#         return

#     task_logger.info(f"cleanup_idle_sandboxes_task starting for tenant {tenant_id}")

#     redis_client = get_redis_client(tenant_id=tenant_id)
#     lock: RedisLock = redis_client.lock(
#         OnyxRedisLocks.CLEANUP_IDLE_SANDBOXES_BEAT_LOCK,
#         timeout=CELERY_GENERIC_BEAT_LOCK_TIMEOUT,
#     )

#     # Prevent overlapping runs of this task
#     if not lock.acquire(blocking=False):
#         task_logger.debug("cleanup_idle_sandboxes_task - lock not acquired, skipping")
#         return

#     try:
#         # Import here to avoid circular imports
#         from onyx.db.enums import SandboxStatus
#         from onyx.server.features.build.db.sandbox import create_snapshot
#         from onyx.server.features.build.db.sandbox import get_idle_sandboxes
#         from onyx.server.features.build.db.sandbox import (
#             update_sandbox_status__no_commit,
#         )
#         from onyx.server.features.build.sandbox import get_sandbox_manager

#         sandbox_manager = get_sandbox_manager()

#         with get_session_with_current_tenant() as db_session:
#             idle_sandboxes = get_idle_sandboxes(
#                 db_session, SANDBOX_IDLE_TIMEOUT_SECONDS
#             )

#             if not idle_sandboxes:
#                 task_logger.debug("No idle sandboxes found")
#                 return

#             task_logger.info(f"Found {len(idle_sandboxes)} idle sandboxes to clean up")

#             for sandbox in idle_sandboxes:
#                 sandbox_id = sandbox.id
#                 sandbox_id_str = str(sandbox_id)
#                 task_logger.info(f"Cleaning up idle sandbox {sandbox_id_str}")

#                 try:
#                     # Create snapshot before terminating to preserve work
#                     task_logger.debug(f"Creating snapshot for sandbox {sandbox_id_str}")
#                     snapshot_result = sandbox_manager.create_snapshot(
#                         sandbox_id, tenant_id
#                     )
#                     if snapshot_result:
#                         # Create DB record for the snapshot
#                         create_snapshot(
#                             db_session,
#                             sandbox_id,
#                             snapshot_result.storage_path,
#                             snapshot_result.size_bytes,
#                         )
#                         task_logger.debug(
#                             f"Snapshot created for sandbox {sandbox_id_str}"
#                         )
#                 except Exception as e:
#                     task_logger.warning(
#                         f"Failed to create snapshot for sandbox {sandbox_id_str}: {e}"
#                     )
#                     # Continue with termination even if snapshot fails

#                 try:
#                     sandbox_manager.terminate(sandbox_id)
#                     # Update sandbox status after termination
#                     update_sandbox_status__no_commit(
#                         db_session, sandbox_id, SandboxStatus.TERMINATED
#                     )
#                     db_session.commit()
#                     task_logger.info(f"Terminated idle sandbox {sandbox_id_str}")
#                 except Exception as e:
#                     task_logger.error(
#                         f"Failed to terminate sandbox {sandbox_id}: {e}",
#                         exc_info=True,
#                     )

#     except Exception:
#         task_logger.exception("Error in cleanup_idle_sandboxes_task")
#         raise

#     finally:
#         if lock.owned():
#             lock.release()

#     task_logger.info("cleanup_idle_sandboxes_task completed")


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
