from uuid import UUID

from celery import shared_task
from celery import Task
from redis.lock import Lock as RedisLock

from ee.onyx.background.celery_utils import should_perform_chat_ttl_check
from onyx.configs.app_configs import JOB_TIMEOUT
from onyx.configs.constants import CELERY_GENERIC_BEAT_LOCK_TIMEOUT
from onyx.configs.constants import OnyxCeleryQueues
from onyx.configs.constants import OnyxCeleryTask
from onyx.configs.constants import OnyxRedisLocks
from onyx.db.chat import delete_chat_session
from onyx.db.chat import get_chat_sessions_older_than
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.redis.redis_pool import get_redis_client
from onyx.server.settings.store import load_settings
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Chat sessions are hard-deleted one at a time, each in its own transaction. We
# fetch and delete in bounded batches so a large backlog never loads every
# matching row into memory at once and never occupies a worker thread for hours.
_TTL_DELETE_BATCH_SIZE = 100


@shared_task(
    name=OnyxCeleryTask.PERFORM_TTL_MANAGEMENT_TASK,
    ignore_result=True,
    soft_time_limit=JOB_TIMEOUT,
    bind=True,
    trail=False,
)
def perform_ttl_management_task(
    self: Task,
    retention_limit_days: int,
    *,
    tenant_id: str,  # noqa: ARG001
) -> None:
    task_id = self.request.id
    if not task_id:
        raise RuntimeError("No task id defined for this task; cannot identify it")

    # Only one cleanup run should drain the backlog at a time; without this the
    # hourly check would stack a new full run on top of any still-draining one,
    # compounding queue congestion on large backlogs. get_redis_client()
    # tenant-prefixes the lock key, so this is per-tenant despite the constant
    # name (same pattern as the other beat locks).
    r = get_redis_client()
    lock: RedisLock = r.lock(
        OnyxRedisLocks.CHAT_TTL_MANAGEMENT_LOCK,
        timeout=CELERY_GENERIC_BEAT_LOCK_TIMEOUT,
    )
    if not lock.acquire(blocking=False):
        logger.info("Chat TTL cleanup already in progress; skipping this run.")
        return

    # Sessions that failed to delete are excluded from subsequent batches so a
    # few undeletable rows can't block the rest of the (oldest-first) backlog.
    # Every fetched session is either deleted or added here, so the eligible set
    # shrinks each iteration and the loop always terminates.
    failed_session_ids: set[UUID] = set()
    user_id: UUID | None = None
    session_id: UUID | None = None
    try:
        while True:
            lock.reacquire()
            with get_session_with_current_tenant() as db_session:
                old_chat_sessions = get_chat_sessions_older_than(
                    retention_limit_days,
                    db_session,
                    limit=_TTL_DELETE_BATCH_SIZE,
                    exclude_session_ids=failed_session_ids,
                )

            if not old_chat_sessions:
                break

            for user_id, session_id in old_chat_sessions:
                lock.reacquire()
                try:
                    with get_session_with_current_tenant() as db_session:
                        delete_chat_session(
                            user_id,
                            session_id,
                            db_session,
                            include_deleted=True,
                            hard_delete=True,
                        )
                except Exception:
                    logger.exception(
                        "Failed to delete chat session user_id=%s session_id=%s, continuing with remaining sessions",
                        user_id,
                        session_id,
                    )
                    failed_session_ids.add(session_id)

        if failed_session_ids:
            logger.error(
                "Chat TTL cleanup finished but %d session(s) could not be deleted; "
                "they will be retried on the next scheduled run.",
                len(failed_session_ids),
            )

    except Exception:
        logger.exception(
            "delete_chat_session exceptioned. user_id=%s session_id=%s",
            user_id,
            session_id,
        )
        raise
    finally:
        if lock.owned():
            lock.release()


@shared_task(
    name=OnyxCeleryTask.CHECK_TTL_MANAGEMENT_TASK,
    ignore_result=True,
    soft_time_limit=JOB_TIMEOUT,
)
def check_ttl_management_task(*, tenant_id: str) -> None:
    """Runs periodically to check if any ttl tasks should be run and adds them
    to the queue"""

    settings = load_settings()
    retention_limit_days = settings.maximum_chat_retention_days
    with get_session_with_current_tenant() as db_session:
        if should_perform_chat_ttl_check(retention_limit_days, db_session):
            perform_ttl_management_task.apply_async(
                kwargs=dict(
                    retention_limit_days=retention_limit_days, tenant_id=tenant_id
                ),
                queue=OnyxCeleryQueues.CHAT_TTL_DELETION,
                expires=JOB_TIMEOUT,
            )
