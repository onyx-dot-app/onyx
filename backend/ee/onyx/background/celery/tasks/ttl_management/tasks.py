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

    # A per-tenant lock ensures only one cleanup run drains the backlog at a
    # time. Without it the hourly check would stack a new full run on top of any
    # still-draining one, compounding queue congestion on large backlogs.
    r = get_redis_client()
    lock: RedisLock = r.lock(
        OnyxRedisLocks.CHAT_TTL_MANAGEMENT_LOCK,
        timeout=CELERY_GENERIC_BEAT_LOCK_TIMEOUT,
    )
    if not lock.acquire(blocking=False):
        logger.info("Chat TTL cleanup already in progress; skipping this run.")
        return

    user_id: UUID | None = None
    session_id: UUID | None = None
    try:
        while True:
            lock.reacquire()
            with get_session_with_current_tenant() as db_session:
                old_chat_sessions = get_chat_sessions_older_than(
                    retention_limit_days, db_session, limit=_TTL_DELETE_BATCH_SIZE
                )

            if not old_chat_sessions:
                break

            deleted_count = 0
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
                    deleted_count += 1
                except Exception:
                    logger.exception(
                        "Failed to delete chat session user_id=%s session_id=%s, continuing with remaining sessions",
                        user_id,
                        session_id,
                    )

            # If a full batch was fetched but nothing could be deleted, the same
            # rows would be re-fetched forever. Stop and let the next scheduled
            # check retry rather than spin.
            if deleted_count == 0:
                logger.error(
                    "Chat TTL cleanup made no progress on a full batch of %d sessions; stopping.",
                    len(old_chat_sessions),
                )
                break

            # A partial batch means we've reached the tail of the backlog.
            if len(old_chat_sessions) < _TTL_DELETE_BATCH_SIZE:
                break

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
