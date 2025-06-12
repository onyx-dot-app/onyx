import time

from celery import shared_task
from celery import Task
from celery.exceptions import SoftTimeLimitExceeded
from redis.lock import Lock as RedisLock

from onyx.background.celery.apps.app_base import task_logger
from onyx.background.celery.tasks.kg_processing.utils import (
    block_kg_processing_current_tenant,
)
from onyx.background.celery.tasks.kg_processing.utils import (
    check_kg_processing_requirements,
)
from onyx.background.celery.tasks.kg_processing.utils import (
    check_kg_unclustered_extraction_requirements,
)
from onyx.background.celery.tasks.kg_processing.utils import (
    unblock_kg_processing_current_tenant,
)
from onyx.configs.constants import CELERY_GENERIC_BEAT_LOCK_TIMEOUT
from onyx.configs.constants import OnyxCeleryPriority
from onyx.configs.constants import OnyxCeleryQueues
from onyx.configs.constants import OnyxCeleryTask
from onyx.configs.constants import OnyxRedisLocks
from onyx.db.engine import get_session_with_current_tenant
from onyx.db.search_settings import get_current_search_settings
from onyx.kg.clustering.clustering import kg_clustering
from onyx.kg.extractions.extraction_processing import kg_extraction
from onyx.kg.resets.reset_source import reset_source_kg_index
from onyx.redis.redis_pool import get_redis_client
from onyx.redis.redis_pool import get_redis_replica_client
from onyx.redis.redis_pool import redis_lock_dump
from onyx.utils.logger import setup_logger

logger = setup_logger()


@shared_task(
    name=OnyxCeleryTask.CHECK_KG_PROCESSING,
    soft_time_limit=300,
    bind=True,
)
def check_for_kg_processing(self: Task, *, tenant_id: str) -> int | None:
    """a lightweight task used to kick off kg processing tasks."""

    time_start = time.monotonic()
    task_logger.warning("check_for_kg_processing - Starting")

    tasks_created = 0
    locked = False
    redis_client = get_redis_client()
    get_redis_replica_client()

    lock_beat: RedisLock = redis_client.lock(
        OnyxRedisLocks.KG_PROCESSING_LOCK,
        timeout=CELERY_GENERIC_BEAT_LOCK_TIMEOUT,
    )

    # these tasks should never overlap
    if not lock_beat.acquire(blocking=False):
        return None

    try:
        locked = True

        kg_processing_requirements_met = check_kg_processing_requirements(tenant_id)

        if not kg_processing_requirements_met:
            return None

        task_logger.info(
            f"Found documents needing KG processing for tenant {tenant_id}"
        )

        self.app.send_task(
            OnyxCeleryTask.KG_PROCESSING,
            kwargs={
                "tenant_id": tenant_id,
            },
            queue=OnyxCeleryQueues.KG_PROCESSING,
            priority=OnyxCeleryPriority.MEDIUM,
        )

    except SoftTimeLimitExceeded:
        task_logger.info(
            "Soft time limit exceeded, task is being terminated gracefully."
        )
    except Exception:
        task_logger.exception("Unexpected exception during kg processing check")
    finally:
        if locked:
            if lock_beat.owned():
                lock_beat.release()
            else:
                task_logger.error(
                    "check_for_kg_processing - Lock not owned on completion: "
                    f"tenant={tenant_id}"
                )
                redis_lock_dump(lock_beat, redis_client)

    time_elapsed = time.monotonic() - time_start
    task_logger.info(f"check_for_kg_processing finished: elapsed={time_elapsed:.2f}")
    return tasks_created


@shared_task(
    name=OnyxCeleryTask.CHECK_KG_PROCESSING_CLUSTERING_ONLY,
    soft_time_limit=300,
    bind=True,
)
def check_for_kg_processing_clustering_only(
    self: Task, *, tenant_id: str
) -> int | None:
    """a lightweight task used to kick off kg clustering tasks."""

    time_start = time.monotonic()
    task_logger.warning("check_for_kg_processing_clustering_only - Starting")

    tasks_created = 0
    locked = False
    redis_client = get_redis_client()
    get_redis_replica_client()

    lock_beat: RedisLock = redis_client.lock(
        OnyxRedisLocks.KG_PROCESSING_LOCK,
        timeout=CELERY_GENERIC_BEAT_LOCK_TIMEOUT,
    )

    # these tasks should never overlap
    if not lock_beat.acquire(blocking=False):
        return None

    try:
        locked = True

        kg_processing_requirements_met = check_kg_unclustered_extraction_requirements(
            tenant_id
        )

        if not kg_processing_requirements_met:

            task_logger.info(
                f"Found documents needing KG processing for tenant {tenant_id}"
            )
            return None

        self.app.send_task(
            OnyxCeleryTask.KG_CLUSTERING_ONLY,
            kwargs={
                "tenant_id": tenant_id,
            },
            queue=OnyxCeleryQueues.KG_PROCESSING,
            priority=OnyxCeleryPriority.MEDIUM,
        )

    except SoftTimeLimitExceeded:
        task_logger.info(
            "Soft time limit exceeded, task is being terminated gracefully."
        )
    except Exception:
        task_logger.exception("Unexpected exception during kg clustering-only check")
    finally:
        if locked:
            if lock_beat.owned():
                lock_beat.release()
            else:
                task_logger.error(
                    "check_for_kg_processing - Lock not owned on completion: "
                    f"tenant={tenant_id}"
                )
                redis_lock_dump(lock_beat, redis_client)

    time_elapsed = time.monotonic() - time_start
    task_logger.info(
        f"check_for_kg_processing_clustering_only finished: elapsed={time_elapsed:.2f}"
    )
    return tasks_created


@shared_task(
    name=OnyxCeleryTask.KG_PROCESSING,
    soft_time_limit=1000,
    bind=True,
)
def kg_processing(self: Task, *, tenant_id: str) -> int | None:
    """a task for doing kg extraction and clustering."""

    time.monotonic()
    task_logger.warning(f"kg_processing - Starting for tenant {tenant_id}")

    task_logger.debug("Starting kg processing task!")

    with get_session_with_current_tenant() as db_session:
        search_settings = get_current_search_settings(db_session)
        index_str = search_settings.index_name

        # prevent other tasks from running
        block_kg_processing_current_tenant(db_session)

        db_session.commit()
        task_logger.info(f"KG processing set to in progress for tenant {tenant_id}")

    try:
        kg_extraction(
            tenant_id=tenant_id, index_name=index_str, processing_chunk_batch_size=8
        )

        kg_clustering(
            tenant_id=tenant_id, index_name=index_str, processing_chunk_batch_size=8
        )
    except Exception:
        task_logger.exception("Error during kg processing")

    finally:
        with get_session_with_current_tenant() as db_session:
            unblock_kg_processing_current_tenant(db_session)
            db_session.commit()

    task_logger.debug("Completed kg processing task!")

    return None


@shared_task(
    name=OnyxCeleryTask.KG_CLUSTERING_ONLY,
    soft_time_limit=1000,
    bind=True,
)
def kg_clustering_only(self: Task, *, tenant_id: str) -> int | None:
    """a task for doing kg clustering only."""

    with get_session_with_current_tenant() as db_session:
        search_settings = get_current_search_settings(db_session)
        index_str = search_settings.index_name

        block_kg_processing_current_tenant(db_session)

        db_session.commit()

    task_logger.debug("Starting kg clustering-only task!")

    try:
        kg_clustering(
            tenant_id=tenant_id, index_name=index_str, processing_chunk_batch_size=8
        )
    except Exception as e:
        task_logger.exception(f"Error during kg clustering: {e}")
    finally:
        with get_session_with_current_tenant() as db_session:
            unblock_kg_processing_current_tenant(db_session)
            db_session.commit()

    task_logger.debug("Completed kg clustering task!")

    return None


@shared_task(
    name=OnyxCeleryTask.KG_RESET_SOURCE_INDEX,
    soft_time_limit=1000,
    bind=True,
)
def kg_reset_source_index(
    self: Task, *, tenant_id: str, source_name: str, index_name: str
) -> int | None:
    """a task for KG reset of a source."""

    with get_session_with_current_tenant() as db_session:
        block_kg_processing_current_tenant(db_session)
        db_session.commit()

    task_logger.debug("Starting source reset task!")

    try:
        reset_source_kg_index(
            source_name=source_name, tenant_id=tenant_id, index_name=index_name
        )

    except Exception as e:
        task_logger.exception(f"Error during kg reset: {e}")
    finally:
        with get_session_with_current_tenant() as db_session:
            unblock_kg_processing_current_tenant(db_session)
            db_session.commit()

        task_logger.debug("Completed kg reset task!")

    return None
