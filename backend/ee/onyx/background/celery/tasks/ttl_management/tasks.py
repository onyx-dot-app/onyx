from celery import shared_task
from celery import Task

from ee.onyx.background.celery_utils import should_perform_chat_ttl_check
from onyx.configs.app_configs import JOB_TIMEOUT
from onyx.configs.constants import CELERY_CHAT_TTL_DELETE_TASK_EXPIRES
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
    tenant_id: str,
) -> None:
    """Delete the oldest batch of expired chat sessions, then chain the next task.

    Each run hard-deletes at most ``CHAT_TTL_DELETE_BATCH_SIZE`` of the *oldest*
    expired sessions and exits, so it occupies a single light-worker thread for
    only one short batch and interleaves with the other light-queue work. If a
    full batch is deleted (more sessions likely remain) it enqueues the next task
    to continue the chain; otherwise the chain is done and it releases the
    in-flight marker so ``check_ttl_management_task`` can start a fresh chain.
    Only one chain runs per tenant at a time (guarded by the marker), so at most
    one light-worker thread does TTL work at a time.

    NOTE: every run re-selects the oldest sessions, so a session that repeatedly
    fails to delete is retried on every run. If the oldest ``CHAT_TTL_DELETE_BATCH_SIZE``
    sessions can never be deleted, the chain loops on them indefinitely (across
    tasks) and never reaches newer sessions. This is an accepted trade-off for
    keeping the task simple; each failure is logged.
    """
    redis_client = get_redis_client(tenant_id=tenant_id)
    # Refresh the in-flight marker. The active batch isn't in the queue, so queue
    # length can't be the guard; the marker spans the whole chain and keeps the
    # beat from starting a second one.
    redis_client.set(
        OnyxRedisLocks.CHAT_TTL_CHAIN_ACTIVE,
        1,
        ex=CELERY_CHAT_TTL_DELETE_TASK_EXPIRES,
    )

    with get_session_with_current_tenant() as db_session:
        old_chat_sessions = get_chat_sessions_older_than(
            retention_limit_days, db_session, limit=CHAT_TTL_DELETE_BATCH_SIZE
        )

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

    # A full batch means more expired sessions probably remain; continue the
    # chain. Otherwise the backlog is drained — release the marker.
    if len(old_chat_sessions) == CHAT_TTL_DELETE_BATCH_SIZE:
        try:
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
        except Exception:
            # Chain broke; release the marker so the beat can restart it.
            redis_client.delete(OnyxRedisLocks.CHAT_TTL_CHAIN_ACTIVE)
            raise
    else:
        redis_client.delete(OnyxRedisLocks.CHAT_TTL_CHAIN_ACTIVE)


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
    batch-by-batch and holds an in-flight marker for the whole chain. This
    dispatcher claims that marker (``SET NX``); if it's already held a chain is
    active, so we skip and don't stack a second one.
    """
    settings = load_settings()
    retention_limit_days = settings.maximum_chat_retention_days
    with get_session_with_current_tenant() as db_session:
        if not should_perform_chat_ttl_check(retention_limit_days, db_session):
            return
    if retention_limit_days is None:
        return

    redis_client = get_redis_client(tenant_id=tenant_id)
    # Claim the chain. If the marker is already set, a chain is in flight (its
    # active task may not be sitting in the queue), so don't start another.
    if not redis_client.set(
        OnyxRedisLocks.CHAT_TTL_CHAIN_ACTIVE,
        1,
        ex=CELERY_CHAT_TTL_DELETE_TASK_EXPIRES,
        nx=True,
    ):
        return

    try:
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
    except Exception:
        # Roll back the claim so the next beat can start the chain.
        redis_client.delete(OnyxRedisLocks.CHAT_TTL_CHAIN_ACTIVE)
        raise
