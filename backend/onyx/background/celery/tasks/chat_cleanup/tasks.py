"""Garbage collection for "failed" chat sessions (husks).

The web client creates a chat session lazily at first send, and the send flow
writes an empty SYSTEM root message before committing the user message. A send
that never lands or fails during setup therefore leaves a session that has
never contained a non-SYSTEM message — no user-visible content. These husks
used to be hidden at read time by get_chat_sessions_by_user; now they are
returned as-is and reclaimed here in the background instead.

The sweep walks chat_session in primary-key order, one bounded batch per task,
chaining batches on the light queue with the same token-fenced Redis marker
the chat-TTL cleanup uses, so at most one sweep runs per tenant at a time.
"""

import uuid
from datetime import datetime, timedelta, timezone
from uuid import UUID

from celery import Task, shared_task

from onyx.configs.app_configs import JOB_TIMEOUT
from onyx.configs.chat_configs import FAILED_CHAT_CLEANUP_AFTER_DAYS
from onyx.configs.constants import (
    CELERY_FAILED_CHAT_CLEANUP_TASK_EXPIRES,
    FAILED_CHAT_CLEANUP_BATCH_SIZE,
    OnyxCeleryPriority,
    OnyxCeleryQueues,
    OnyxCeleryTask,
    OnyxRedisLocks,
)
from onyx.db.chat import delete_chat_session, get_failed_chat_session_batch
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.redis.chain_fence import (
    claim_chain,
    refresh_chain_if_owned,
    release_chain_if_owned,
)
from onyx.redis.redis_pool import get_redis_client
from onyx.utils.logger import setup_logger

logger = setup_logger()


@shared_task(
    name=OnyxCeleryTask.PERFORM_FAILED_CHAT_CLEANUP_TASK,
    ignore_result=True,
    soft_time_limit=JOB_TIMEOUT,
    bind=True,
    trail=False,
)
def perform_failed_chat_cleanup_task(
    self: Task,
    cleanup_after_days: float,
    chain_token: str,
    after_id: str | None,
    deleted_so_far: int,
    *,
    tenant_id: str,
) -> None:
    """Delete one batch of failed chat sessions, then chain the next batch.

    Each run scans at most ``FAILED_CHAT_CLEANUP_BATCH_SIZE`` GC-candidate
    sessions starting after the ``after_id`` keyset cursor, hard-deletes the
    husks among them, and exits, so it occupies a single light-worker thread
    for only one short batch. While the scan returns full batches the sweep
    continues by enqueuing the next task with the advanced cursor; once the
    table is exhausted it logs the sweep total and releases the in-flight
    marker so ``check_failed_chat_cleanup_task`` can start a fresh sweep.

    ``chain_token`` fences the chain exactly like the chat-TTL cleanup: a run
    that no longer owns the marker exits without touching anything.
    """
    redis_client = get_redis_client(tenant_id=tenant_id)
    if not refresh_chain_if_owned(
        redis_client,
        OnyxRedisLocks.FAILED_CHAT_CLEANUP_CHAIN_ACTIVE,
        chain_token,
        CELERY_FAILED_CHAT_CLEANUP_TASK_EXPIRES,
    ):
        return

    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=cleanup_after_days)
    with get_session_with_current_tenant() as db_session:
        failed_sessions, next_after_id = get_failed_chat_session_batch(
            db_session=db_session,
            cutoff=cutoff,
            after_id=UUID(after_id) if after_id else None,
            batch_size=FAILED_CHAT_CLEANUP_BATCH_SIZE,
        )

    num_deleted = 0
    for user_id, session_id in failed_sessions:
        try:
            with get_session_with_current_tenant() as db_session:
                delete_chat_session(
                    user_id,
                    session_id,
                    db_session,
                    include_deleted=True,
                    hard_delete=True,
                )
            num_deleted += 1
        except Exception:
            logger.exception(
                "Failed to delete failed chat session user_id=%s session_id=%s, "
                "continuing with remaining sessions",
                user_id,
                session_id,
            )

    total_deleted = deleted_so_far + num_deleted
    if next_after_id is not None:
        try:
            self.app.send_task(
                OnyxCeleryTask.PERFORM_FAILED_CHAT_CLEANUP_TASK,
                kwargs={
                    "cleanup_after_days": cleanup_after_days,
                    "chain_token": chain_token,
                    "after_id": str(next_after_id),
                    "deleted_so_far": total_deleted,
                    "tenant_id": tenant_id,
                },
                queue=OnyxCeleryQueues.CHAT_TTL_DELETION,
                priority=OnyxCeleryPriority.LOW,
                expires=CELERY_FAILED_CHAT_CLEANUP_TASK_EXPIRES,
            )
        except Exception:
            release_chain_if_owned(
                redis_client,
                OnyxRedisLocks.FAILED_CHAT_CLEANUP_CHAIN_ACTIVE,
                chain_token,
            )
            raise
    else:
        logger.info(
            "Failed-chat cleanup sweep complete: deleted %d session(s) with no "
            "user-visible content older than %s day(s)",
            total_deleted,
            cleanup_after_days,
        )
        release_chain_if_owned(
            redis_client,
            OnyxRedisLocks.FAILED_CHAT_CLEANUP_CHAIN_ACTIVE,
            chain_token,
        )


@shared_task(
    name=OnyxCeleryTask.CHECK_FAILED_CHAT_CLEANUP_TASK,
    ignore_result=True,
    soft_time_limit=JOB_TIMEOUT,
    bind=True,
    trail=False,
)
def check_failed_chat_cleanup_task(self: Task, *, tenant_id: str) -> None:
    """Start a failed-chat cleanup sweep if one isn't already running.

    Deletion happens in ``perform_failed_chat_cleanup_task``, which chains
    itself batch-by-batch and holds a token-fenced in-flight marker for the
    whole sweep. This dispatcher claims that marker with a fresh token; if
    it's already held a sweep is active, so we skip and don't stack a second
    one.
    """
    if FAILED_CHAT_CLEANUP_AFTER_DAYS <= 0:
        return

    redis_client = get_redis_client(tenant_id=tenant_id)
    chain_token = uuid.uuid4().hex
    if not claim_chain(
        redis_client,
        OnyxRedisLocks.FAILED_CHAT_CLEANUP_CHAIN_ACTIVE,
        chain_token,
        CELERY_FAILED_CHAT_CLEANUP_TASK_EXPIRES,
    ):
        return

    try:
        self.app.send_task(
            OnyxCeleryTask.PERFORM_FAILED_CHAT_CLEANUP_TASK,
            kwargs={
                "cleanup_after_days": FAILED_CHAT_CLEANUP_AFTER_DAYS,
                "chain_token": chain_token,
                "after_id": None,
                "deleted_so_far": 0,
                "tenant_id": tenant_id,
            },
            queue=OnyxCeleryQueues.CHAT_TTL_DELETION,
            priority=OnyxCeleryPriority.LOW,
            expires=CELERY_FAILED_CHAT_CLEANUP_TASK_EXPIRES,
        )
    except Exception:
        # Roll back the claim so the next beat can start the sweep.
        release_chain_if_owned(
            redis_client,
            OnyxRedisLocks.FAILED_CHAT_CLEANUP_CHAIN_ACTIVE,
            chain_token,
        )
        raise
