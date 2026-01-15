from uuid import uuid4

from celery import Celery
from redis import Redis
from redis.lock import Lock as RedisLock
from sqlalchemy.orm import Session

from onyx.background.celery.apps.app_base import task_logger
from onyx.configs.constants import DANSWER_REDIS_FUNCTION_LOCK_PREFIX
from onyx.configs.constants import OnyxCeleryPriority
from onyx.configs.constants import OnyxCeleryQueues
from onyx.configs.constants import OnyxCeleryTask
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.index_attempt import mark_attempt_failed
from onyx.db.indexing_coordination import IndexingCoordination
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import SearchSettings


def try_creating_docfetching_task(
    celery_app: Celery,
    cc_pair: ConnectorCredentialPair,
    search_settings: SearchSettings,
    reindex: bool,
    db_session: Session,
    r: Redis,
    tenant_id: str,
) -> int | None:
    """Checks for any conditions that should block the indexing task from being
    created, then creates the task.

    Does not check for scheduling related conditions as this function
    is used to trigger indexing immediately.

    Now uses database-based coordination instead of Redis fencing.
    """

    LOCK_TIMEOUT = 30

    # we need to serialize any attempt to trigger indexing since it can be triggered
    # either via celery beat or manually (API call)
    lock: RedisLock = r.lock(
        DANSWER_REDIS_FUNCTION_LOCK_PREFIX + "try_creating_indexing_task",
        timeout=LOCK_TIMEOUT,
    )

    acquired = lock.acquire(blocking_timeout=LOCK_TIMEOUT / 2)
    if not acquired:
        return None

    index_attempt_id = None
    try:
        # Basic status checks
        db_session.refresh(cc_pair)
        if cc_pair.status == ConnectorCredentialPairStatus.DELETING:
            return None

        # Generate custom task ID for tracking
        custom_task_id = f"docfetching_{cc_pair.id}_{search_settings.id}_{uuid4()}"

        # Try to create a new index attempt using database coordination
        # This replaces the Redis fencing mechanism
        index_attempt_id = IndexingCoordination.try_create_index_attempt(
            db_session=db_session,
            cc_pair_id=cc_pair.id,
            search_settings_id=search_settings.id,
            celery_task_id=custom_task_id,
            from_beginning=reindex,
        )

        if index_attempt_id is None:
            # Another indexing attempt is already running
            return None

        # Use higher priority for first-time indexing to ensure new connectors
        # get processed before re-indexing of existing connectors
        has_successful_attempt = cc_pair.last_successful_index_time is not None
        priority = (
            OnyxCeleryPriority.MEDIUM
            if has_successful_attempt
            else OnyxCeleryPriority.HIGH
        )

        # Send the task to Celery
        result = celery_app.send_task(
            OnyxCeleryTask.CONNECTOR_DOC_FETCHING_TASK,
            kwargs=dict(
                index_attempt_id=index_attempt_id,
                cc_pair_id=cc_pair.id,
                search_settings_id=search_settings.id,
                tenant_id=tenant_id,
            ),
            queue=OnyxCeleryQueues.CONNECTOR_DOC_FETCHING,
            task_id=custom_task_id,
            priority=priority,
        )
        if not result:
            raise RuntimeError("send_task for connector_doc_fetching_task failed.")

        task_logger.info(
            f"Created docfetching task: "
            f"cc_pair={cc_pair.id} "
            f"search_settings={search_settings.id} "
            f"attempt_id={index_attempt_id} "
            f"celery_task_id={custom_task_id}"
        )

        return index_attempt_id

    except Exception:
        task_logger.exception(
            f"try_creating_indexing_task - Unexpected exception: "
            f"cc_pair={cc_pair.id} "
            f"search_settings={search_settings.id}"
        )

        # Clean up on failure
        if index_attempt_id is not None:
            mark_attempt_failed(index_attempt_id, db_session)

        return None
    finally:
        if lock.owned():
            lock.release()

    return index_attempt_id
