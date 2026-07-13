import uuid

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
from onyx.redis.tenant_redis_client import TenantRedisClient
from onyx.server.settings.store import load_settings
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Extend the chain lease only if we still own it (marker value == our token).
# Returns 1 when owned+extended, 0 otherwise. Prevents a task whose lease lapsed
# (and whose chain a later beat has replaced) from extending someone else's lease.
_REFRESH_IF_OWNED = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('expire', KEYS[1], ARGV[2])
else
    return 0
end
"""

# Release the chain marker only if we still own it.
_RELEASE_IF_OWNED = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
"""


def _release_chain_if_owned(redis_client: TenantRedisClient, chain_token: str) -> None:
    """Delete the chain marker only if ``chain_token`` still owns it."""
    redis_client.eval(
        _RELEASE_IF_OWNED,
        [OnyxRedisLocks.CHAT_TTL_CHAIN_ACTIVE],
        [chain_token],
    )


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
    # Defaulted for rollout compatibility: a message enqueued by the pre-upgrade
    # code carries no chain_token. An empty token never matches the marker, so
    # such a message harmlessly no-ops below and the beat starts a fresh chain.
    chain_token: str = "",
    *,
    tenant_id: str,
) -> None:
    """Delete the oldest batch of expired chat sessions, then chain the next task.

    Each run hard-deletes at most ``CHAT_TTL_DELETE_BATCH_SIZE`` of the *oldest*
    expired sessions and exits, so it occupies a single light-worker thread for
    only one short batch and interleaves with the other light-queue work. If a
    full batch is deleted (more sessions likely remain) it enqueues the next task
    with the same ``chain_token``; otherwise the chain is done and it releases the
    in-flight marker so ``check_ttl_management_task`` can start a fresh chain.

    ``chain_token`` fences the chain: each run extends the lease only if it still
    owns the marker, and stops if it doesn't. So if a slow batch outlives the
    lease and the beat starts a replacement chain, the superseded task can neither
    extend nor delete the new chain's marker — it just exits. Only one chain runs
    per tenant at a time, so at most one light-worker thread does TTL work.

    NOTE: every run re-selects the oldest sessions, so a session that repeatedly
    fails to delete is retried on every run. If the oldest ``CHAT_TTL_DELETE_BATCH_SIZE``
    sessions can never be deleted, the chain loops on them indefinitely (across
    tasks) and never reaches newer sessions. This is an accepted trade-off for
    keeping the task simple; each failure is logged.
    """
    redis_client = get_redis_client(tenant_id=tenant_id)
    # Extend our lease only if we still own the chain; if a replacement chain has
    # taken over, stop — we're a superseded task and must not touch its marker.
    owns_chain = redis_client.eval(
        _REFRESH_IF_OWNED,
        [OnyxRedisLocks.CHAT_TTL_CHAIN_ACTIVE],
        [chain_token, str(CELERY_CHAT_TTL_DELETE_TASK_EXPIRES)],
    )
    if not owns_chain:
        return

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
    # chain. Otherwise the backlog is drained — release the marker (if we own it).
    if len(old_chat_sessions) == CHAT_TTL_DELETE_BATCH_SIZE:
        try:
            self.app.send_task(
                OnyxCeleryTask.PERFORM_TTL_MANAGEMENT_TASK,
                kwargs={
                    "retention_limit_days": retention_limit_days,
                    "chain_token": chain_token,
                    "tenant_id": tenant_id,
                },
                queue=OnyxCeleryQueues.CHAT_TTL_DELETION,
                priority=OnyxCeleryPriority.LOW,
                expires=CELERY_CHAT_TTL_DELETE_TASK_EXPIRES,
            )
        except Exception:
            _release_chain_if_owned(redis_client, chain_token)
            raise
    else:
        _release_chain_if_owned(redis_client, chain_token)


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
    batch-by-batch and holds a token-fenced in-flight marker for the whole chain.
    This dispatcher claims that marker with a fresh token (``SET NX``); if it's
    already held a chain is active, so we skip and don't stack a second one.
    """
    settings = load_settings()
    retention_limit_days = settings.maximum_chat_retention_days
    with get_session_with_current_tenant() as db_session:
        if not should_perform_chat_ttl_check(retention_limit_days, db_session):
            return
    if retention_limit_days is None:
        return

    redis_client = get_redis_client(tenant_id=tenant_id)
    chain_token = uuid.uuid4().hex
    # Claim the chain. If the marker is already set, a chain is in flight (its
    # active task may not be sitting in the queue), so don't start another.
    if not redis_client.set(
        OnyxRedisLocks.CHAT_TTL_CHAIN_ACTIVE,
        chain_token,
        nx=True,
        ex=CELERY_CHAT_TTL_DELETE_TASK_EXPIRES,
    ):
        return

    try:
        self.app.send_task(
            OnyxCeleryTask.PERFORM_TTL_MANAGEMENT_TASK,
            kwargs={
                "retention_limit_days": retention_limit_days,
                "chain_token": chain_token,
                "tenant_id": tenant_id,
            },
            queue=OnyxCeleryQueues.CHAT_TTL_DELETION,
            priority=OnyxCeleryPriority.LOW,
            expires=CELERY_CHAT_TTL_DELETE_TASK_EXPIRES,
        )
    except Exception:
        # Roll back the claim so the next beat can start the chain.
        _release_chain_if_owned(redis_client, chain_token)
        raise
