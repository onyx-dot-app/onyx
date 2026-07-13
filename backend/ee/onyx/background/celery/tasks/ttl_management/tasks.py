from celery import shared_task
from celery import Task
from redis.lock import Lock as RedisLock

from ee.onyx.background.celery_utils import should_perform_chat_ttl_check
from onyx.background.celery.celery_redis import celery_get_broker_client
from onyx.background.celery.celery_redis import celery_get_queue_length
from onyx.configs.app_configs import JOB_TIMEOUT
from onyx.configs.constants import CELERY_CHAT_TTL_DELETE_TASK_EXPIRES
from onyx.configs.constants import CELERY_GENERIC_BEAT_LOCK_TIMEOUT
from onyx.configs.constants import CHAT_TTL_DELETE_BATCH_SIZE
from onyx.configs.constants import OnyxCeleryPriority
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


@shared_task(
    name=OnyxCeleryTask.PERFORM_TTL_MANAGEMENT_TASK,
    ignore_result=True,
    soft_time_limit=JOB_TIMEOUT,
    bind=True,
    trail=False,
)
def perform_ttl_management_task(
    self: Task,
    retention_limit_days: float,
    *,
    tenant_id: str,  # noqa: ARG001
) -> None:
    """Delete the oldest batch of expired chat sessions, then chain the next task.

    Each run hard-deletes at most ``CHAT_TTL_DELETE_BATCH_SIZE`` of the *oldest*
    expired sessions and exits, so it occupies a single light-worker thread for
    only one short batch and interleaves with the other light-queue work. If a
    full batch is deleted (more sessions likely remain) it enqueues the next task
    to continue the chain. Only one task is ever in flight (``check_ttl_management_task``
    starts a chain only when the queue is empty), so at most one light-worker
    thread does TTL work at a time.

    NOTE: every run re-selects the oldest sessions, so a session that repeatedly
    fails to delete is retried on every run. If the oldest ``CHAT_TTL_DELETE_BATCH_SIZE``
    sessions can never be deleted, the chain loops on them indefinitely (across
    tasks) and never reaches newer sessions. This is an accepted trade-off for
    keeping the task simple; each failure is logged.
    """
    with get_session_with_current_tenant() as db_session:
        old_chat_sessions = get_chat_sessions_older_than(
            retention_limit_days, db_session, limit=CHAT_TTL_DELETE_BATCH_SIZE
        )

    if not old_chat_sessions:
        return

    for user_id, session_id in old_chat_sessions:
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

    # A full batch means more expired sessions probably remain; continue the chain.
    if len(old_chat_sessions) == CHAT_TTL_DELETE_BATCH_SIZE:
        self.app.send_task(
            OnyxCeleryTask.PERFORM_TTL_MANAGEMENT_TASK,
            kwargs={
                "retention_limit_days": retention_limit_days,
                "tenant_id": tenant_id,
            },
            queue=OnyxCeleryQueues.CHAT_TTL_DELETION,
            priority=OnyxCeleryPriority.LOW,
            expires=CELERY_CHAT_TTL_DELETE_TASK_EXPIRES,
        )


@shared_task(
    name=OnyxCeleryTask.CHECK_TTL_MANAGEMENT_TASK,
    ignore_result=True,
    soft_time_limit=JOB_TIMEOUT,
    bind=True,
    trail=False,
)
def check_ttl_management_task(self: Task, *, tenant_id: str) -> None:
    """Start a chat-retention cleanup chain if one isn't already running.

    Deletion happens in ``perform_ttl_management_task``, which chains itself
    batch-by-batch. This dispatcher only kicks off a new chain when the
    ``chat_ttl_deletion`` queue is empty, so chains don't stack.
    """
    settings = load_settings()
    retention_limit_days = settings.maximum_chat_retention_days
    with get_session_with_current_tenant() as db_session:
        if not should_perform_chat_ttl_check(retention_limit_days, db_session):
            return
    if retention_limit_days is None:
        return

    redis_client = get_redis_client(tenant_id=tenant_id)
    lock: RedisLock = redis_client.lock(
        OnyxRedisLocks.CHAT_TTL_MANAGEMENT_LOCK,
        timeout=CELERY_GENERIC_BEAT_LOCK_TIMEOUT,
    )
    if not lock.acquire(blocking=False):
        return

    try:
        # A non-empty queue means a chain is already draining; don't start another.
        r_celery = celery_get_broker_client(self.app)
        if celery_get_queue_length(OnyxCeleryQueues.CHAT_TTL_DELETION, r_celery) > 0:
            return

        self.app.send_task(
            OnyxCeleryTask.PERFORM_TTL_MANAGEMENT_TASK,
            kwargs={
                "retention_limit_days": retention_limit_days,
                "tenant_id": tenant_id,
            },
            queue=OnyxCeleryQueues.CHAT_TTL_DELETION,
            priority=OnyxCeleryPriority.LOW,
            expires=CELERY_CHAT_TTL_DELETE_TASK_EXPIRES,
        )
    finally:
        if lock.owned():
            lock.release()
