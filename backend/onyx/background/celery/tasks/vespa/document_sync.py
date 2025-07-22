import time
from typing import cast
from uuid import uuid4

from celery import Celery
from redis import Redis
from redis.lock import Lock as RedisLock
from sqlalchemy.orm import Session

from onyx.configs.app_configs import DB_YIELD_PER_DEFAULT
from onyx.configs.constants import CELERY_VESPA_SYNC_BEAT_LOCK_TIMEOUT
from onyx.configs.constants import OnyxCeleryPriority
from onyx.configs.constants import OnyxCeleryQueues
from onyx.configs.constants import OnyxCeleryTask
from onyx.configs.constants import OnyxRedisConstants
from onyx.db.document import construct_document_id_select_by_needs_sync
from onyx.db.document import count_documents_by_needs_sync
from onyx.utils.logger import setup_logger

# Redis keys for document sync tracking
DOCUMENT_SYNC_PREFIX = "documentsync"
DOCUMENT_SYNC_FENCE_KEY = f"{DOCUMENT_SYNC_PREFIX}_fence"
DOCUMENT_SYNC_TASKSET_KEY = f"{DOCUMENT_SYNC_PREFIX}_taskset"

logger = setup_logger()


def is_document_sync_fenced(r: Redis) -> bool:
    """Check if document sync tasks are currently in progress."""
    return bool(r.exists(DOCUMENT_SYNC_FENCE_KEY))


def get_document_sync_payload(r: Redis) -> int | None:
    """Get the initial number of tasks that were created."""
    bytes_result = r.get(DOCUMENT_SYNC_FENCE_KEY)
    if bytes_result is None:
        return None
    return int(cast(int, bytes_result))


def get_document_sync_remaining(r: Redis) -> int:
    """Get the number of tasks still pending completion."""
    return cast(int, r.scard(DOCUMENT_SYNC_TASKSET_KEY))


def set_document_sync_fence(r: Redis, payload: int | None) -> None:
    """Set up the fence and register with active fences."""
    if payload is None:
        r.srem(OnyxRedisConstants.ACTIVE_FENCES, DOCUMENT_SYNC_FENCE_KEY)
        r.delete(DOCUMENT_SYNC_FENCE_KEY)
        return

    r.set(DOCUMENT_SYNC_FENCE_KEY, payload)
    r.sadd(OnyxRedisConstants.ACTIVE_FENCES, DOCUMENT_SYNC_FENCE_KEY)


def delete_document_sync_taskset(r: Redis) -> None:
    """Clear the document sync taskset."""
    r.delete(DOCUMENT_SYNC_TASKSET_KEY)


def reset_document_sync(r: Redis) -> None:
    """Reset all document sync tracking data."""
    r.srem(OnyxRedisConstants.ACTIVE_FENCES, DOCUMENT_SYNC_FENCE_KEY)
    r.delete(DOCUMENT_SYNC_TASKSET_KEY)
    r.delete(DOCUMENT_SYNC_FENCE_KEY)


def generate_document_sync_tasks(
    r: Redis,
    max_tasks: int,
    celery_app: Celery,
    db_session: Session,
    lock: RedisLock,
    tenant_id: str,
) -> tuple[int, int]:
    """Generate sync tasks for all documents that need syncing.

    Args:
        r: Redis client
        max_tasks: Maximum number of tasks to generate
        celery_app: Celery application instance
        db_session: Database session
        lock: Redis lock for coordination
        tenant_id: Tenant identifier

    Returns:
        tuple[int, int]: (tasks_generated, total_docs_found)
    """
    last_lock_time = time.monotonic()
    num_tasks_sent = 0
    num_docs = 0

    # Get all documents that need syncing
    stmt = construct_document_id_select_by_needs_sync()

    for doc_id in db_session.scalars(stmt).yield_per(DB_YIELD_PER_DEFAULT):
        doc_id = cast(str, doc_id)
        current_time = time.monotonic()

        # Reacquire lock periodically to prevent timeout
        if current_time - last_lock_time >= (CELERY_VESPA_SYNC_BEAT_LOCK_TIMEOUT / 4):
            lock.reacquire()
            last_lock_time = current_time

        num_docs += 1

        # Create a unique task ID
        custom_task_id = f"{DOCUMENT_SYNC_PREFIX}_{uuid4()}"

        # Add to the tracking taskset in Redis BEFORE creating the celery task
        r.sadd(DOCUMENT_SYNC_TASKSET_KEY, custom_task_id)

        # Create the Celery task
        celery_app.send_task(
            OnyxCeleryTask.VESPA_METADATA_SYNC_TASK,
            kwargs=dict(document_id=doc_id, tenant_id=tenant_id),
            queue=OnyxCeleryQueues.VESPA_METADATA_SYNC,
            task_id=custom_task_id,
            priority=OnyxCeleryPriority.MEDIUM,
            ignore_result=True,
        )

        num_tasks_sent += 1

        if num_tasks_sent >= max_tasks:
            break

    return num_tasks_sent, num_docs


def try_generate_stale_document_sync_tasks(
    celery_app: Celery,
    max_tasks: int,
    db_session: Session,
    r: Redis,
    lock_beat: RedisLock,
    tenant_id: str,
) -> int | None:
    # the fence is up, do nothing
    if is_document_sync_fenced(r):
        return None

    # add tasks to celery and build up the task set to monitor in redis
    stale_doc_count = count_documents_by_needs_sync(db_session)
    if stale_doc_count == 0:
        logger.info("No stale documents found. Skipping sync tasks generation.")
        return None

    logger.info(
        f"Stale documents found (at least {stale_doc_count}). Generating sync tasks in one batch."
    )

    logger.info("generate_document_sync_tasks starting for all documents.")

    # Generate all tasks in one pass
    result = generate_document_sync_tasks(
        r, max_tasks, celery_app, db_session, lock_beat, tenant_id
    )

    if result is None:
        return None

    tasks_generated, total_docs = result

    if tasks_generated >= max_tasks:
        logger.info(
            f"generate_document_sync_tasks reached the task generation limit: "
            f"tasks_generated={tasks_generated} max_tasks={max_tasks}"
        )
    else:
        logger.info(
            f"generate_document_sync_tasks finished for all documents. "
            f"tasks_generated={tasks_generated} total_docs_found={total_docs}"
        )

    set_document_sync_fence(r, tasks_generated)
    return tasks_generated
