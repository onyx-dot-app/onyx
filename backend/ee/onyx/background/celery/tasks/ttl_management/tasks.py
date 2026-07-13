from uuid import UUID

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
from onyx.configs.constants import CHAT_TTL_DELETE_MAX_QUEUE_DEPTH
from onyx.configs.constants import OnyxCeleryPriority
from onyx.configs.constants import OnyxCeleryQueues
from onyx.configs.constants import OnyxCeleryTask
from onyx.configs.constants import OnyxRedisLocks
from onyx.db.chat import delete_chat_session
from onyx.db.chat import get_chat_sessions_older_than
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.redis.redis_pool import get_redis_client
from onyx.redis.tenant_redis_client import TenantRedisClient
from onyx.server.settings.store import load_settings
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _chat_ttl_queued_key(session_id: str | UUID) -> str:
    return f"{OnyxRedisLocks.CHAT_TTL_QUEUED_PREFIX}:{session_id}"


@shared_task(
    name=OnyxCeleryTask.PERFORM_TTL_MANAGEMENT_TASK,
    ignore_result=True,
    soft_time_limit=JOB_TIMEOUT,
    trail=False,
)
def perform_ttl_management_task(
    session_batch: list[tuple[str | None, str]],
    *,
    tenant_id: str,
) -> None:
    """Hard-delete one bounded batch of expired chat sessions, then exit.

    Each batch is an independent, short-lived task so the light worker can
    interleave it with other light-queue work. Sessions are enqueued in batches
    by ``check_ttl_management_task`` rather than drained in a single long task.
    """
    redis_client = get_redis_client(tenant_id=tenant_id)

    for user_id_raw, session_id_raw in session_batch:
        session_id = UUID(session_id_raw)
        user_id = UUID(user_id_raw) if user_id_raw else None

        # Clear the queued guard up front so that if deletion fails and the
        # session remains eligible, the dispatcher can re-enqueue it next cycle.
        redis_client.delete(_chat_ttl_queued_key(session_id))
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


@shared_task(
    name=OnyxCeleryTask.CHECK_TTL_MANAGEMENT_TASK,
    ignore_result=True,
    soft_time_limit=JOB_TIMEOUT,
    bind=True,
    trail=False,
)
def check_ttl_management_task(self: Task, *, tenant_id: str) -> None:
    """Fan expired chat sessions out to the light queue in bounded batches.

    Runs periodically. Instead of deleting the whole backlog in one task, it
    enqueues ``CHAT_TTL_DELETE_BATCH_SIZE``-session batches so deletion
    interleaves with other light-queue work. A per-tenant beat lock prevents
    overlapping fan-out, queue-depth backpressure prevents unbounded growth, and
    a per-session guard prevents re-enqueuing sessions already in flight.
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
    # Only one fan-out per tenant should run at a time.
    if not lock.acquire(blocking=False):
        return

    enqueued = 0
    try:
        # Backpressure: don't pile more batches on top of an already-deep queue.
        # Must use the broker's Redis client — Celery queues live on a separate
        # Redis DB with CELERY_SEPARATOR keys.
        r_celery = celery_get_broker_client(self.app)
        queue_len = celery_get_queue_length(
            OnyxCeleryQueues.CHAT_TTL_DELETION, r_celery
        )
        if queue_len > CHAT_TTL_DELETE_MAX_QUEUE_DEPTH:
            return

        with get_session_with_current_tenant() as db_session:
            old_chat_sessions = get_chat_sessions_older_than(
                retention_limit_days,
                db_session,
                limit=CHAT_TTL_DELETE_MAX_QUEUE_DEPTH * CHAT_TTL_DELETE_BATCH_SIZE,
            )

        batch: list[tuple[str | None, str]] = []
        for user_id, session_id in old_chat_sessions:
            # Skip sessions already queued (guard set) but not yet processed.
            guard_set = redis_client.set(
                _chat_ttl_queued_key(session_id),
                1,
                ex=CELERY_CHAT_TTL_DELETE_TASK_EXPIRES,
                nx=True,
            )
            if not guard_set:
                continue

            batch.append((str(user_id) if user_id else None, str(session_id)))
            if len(batch) >= CHAT_TTL_DELETE_BATCH_SIZE:
                _enqueue_ttl_batch(self, redis_client, batch, tenant_id)
                enqueued += len(batch)
                batch = []

        if batch:
            _enqueue_ttl_batch(self, redis_client, batch, tenant_id)
            enqueued += len(batch)
    finally:
        if lock.owned():
            lock.release()

    if enqueued:
        logger.info("check_ttl_management_task enqueued %d session(s)", enqueued)


def _enqueue_ttl_batch(
    task: Task,
    redis_client: TenantRedisClient,
    batch: list[tuple[str | None, str]],
    tenant_id: str,
) -> None:
    try:
        task.app.send_task(
            OnyxCeleryTask.PERFORM_TTL_MANAGEMENT_TASK,
            kwargs={"session_batch": batch, "tenant_id": tenant_id},
            queue=OnyxCeleryQueues.CHAT_TTL_DELETION,
            priority=OnyxCeleryPriority.LOW,
            expires=CELERY_CHAT_TTL_DELETE_TASK_EXPIRES,
        )
    except Exception:
        # Roll back the guards so these sessions can be re-enqueued next cycle.
        for _, session_id in batch:
            redis_client.delete(_chat_ttl_queued_key(session_id))
        raise
