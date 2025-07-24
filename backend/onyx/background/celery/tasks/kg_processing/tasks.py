import time

from celery import shared_task
from celery import Task
from celery.exceptions import SoftTimeLimitExceeded
from redis.lock import Lock as RedisLock

from onyx.background.celery.apps.app_base import task_logger
from onyx.background.celery.tasks.kg_processing.utils import (
    is_kg_clustering_only_requirements_met,
)
from onyx.background.celery.tasks.kg_processing.utils import (
    is_kg_processing_requirements_met,
)
from onyx.configs.constants import CELERY_GENERIC_BEAT_LOCK_TIMEOUT
from onyx.configs.constants import OnyxCeleryPriority
from onyx.configs.constants import OnyxCeleryQueues
from onyx.configs.constants import OnyxCeleryTask
from onyx.configs.constants import OnyxRedisLocks
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.search_settings import get_current_search_settings
from onyx.kg.clustering.clustering import kg_clustering
from onyx.kg.extractions.extraction_processing import kg_extraction
from onyx.kg.resets.reset_source import reset_source_kg_index
from onyx.redis.redis_pool import get_redis_client
from onyx.redis.redis_pool import redis_lock_dump
from onyx.utils.logger import setup_logger

logger = setup_logger()


@shared_task(
    name=OnyxCeleryTask.CHECK_KG_PROCESSING,
    soft_time_limit=300,
    bind=True,
)
def check_for_kg_processing(self: Task, *, tenant_id: str) -> None:
    """a lightweight task used to kick off kg processing tasks."""

    time_start = time.monotonic()
    task_logger.warning("check_for_kg_processing - Starting")
    try:
        if not is_kg_processing_requirements_met():
            return

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

    time_elapsed = time.monotonic() - time_start
    task_logger.info(f"check_for_kg_processing finished: elapsed={time_elapsed:.2f}")


@shared_task(
    name=OnyxCeleryTask.CHECK_KG_PROCESSING_CLUSTERING_ONLY,
    soft_time_limit=300,
    bind=True,
)
def check_for_kg_processing_clustering_only(self: Task, *, tenant_id: str) -> None:
    """a lightweight task used to kick off kg clustering tasks."""

    time_start = time.monotonic()
    task_logger.warning("check_for_kg_processing_clustering_only - Starting")

    try:
        if not is_kg_clustering_only_requirements_met():
            return

        task_logger.info(
            f"Found documents needing KG clustering for tenant {tenant_id}"
        )

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

    time_elapsed = time.monotonic() - time_start
    task_logger.info(
        f"check_for_kg_processing_clustering_only finished: elapsed={time_elapsed:.2f}"
    )


@shared_task(
    name=OnyxCeleryTask.KG_PROCESSING,
    bind=True,
)
def kg_processing(self: Task, *, tenant_id: str) -> None:
    """a task for doing kg extraction and clustering."""

    task_logger.warning(f"kg_processing - Starting for tenant {tenant_id}")

    redis_client = get_redis_client()
    lock_beat: RedisLock = redis_client.lock(
        OnyxRedisLocks.KG_PROCESSING_LOCK,
        timeout=CELERY_GENERIC_BEAT_LOCK_TIMEOUT,
    )

    # these tasks should never overlap
    if not lock_beat.acquire(blocking=False):
        return

    try:
        with get_session_with_current_tenant() as db_session:
            search_settings = get_current_search_settings(db_session)
            index_str = search_settings.index_name

        task_logger.info(f"KG processing set to in progress for tenant {tenant_id}")

        kg_extraction(
            tenant_id=tenant_id,
            index_name=index_str,
            lock=lock_beat,
            processing_chunk_batch_size=8,
        )

        kg_clustering(
            tenant_id=tenant_id,
            index_name=index_str,
            lock=lock_beat,
            processing_chunk_batch_size=8,
        )
    except Exception:
        task_logger.exception("Error during kg processing")
    finally:
        if lock_beat.owned():
            lock_beat.release()
        else:
            task_logger.error(
                "kg_processing - Lock not owned on completion: " f"tenant={tenant_id}"
            )
            redis_lock_dump(lock_beat, redis_client)

    task_logger.debug("Completed kg processing task!")


@shared_task(
    name=OnyxCeleryTask.KG_CLUSTERING_ONLY,
    bind=True,
)
def kg_clustering_only(self: Task, *, tenant_id: str) -> None:
    """a task for doing kg clustering only."""

    task_logger.warning(f"kg_clustering_only - Starting for tenant {tenant_id}")

    redis_client = get_redis_client()
    lock_beat: RedisLock = redis_client.lock(
        OnyxRedisLocks.KG_PROCESSING_LOCK,
        timeout=CELERY_GENERIC_BEAT_LOCK_TIMEOUT,
    )

    # these tasks should never overlap
    if not lock_beat.acquire(blocking=False):
        return

    try:
        with get_session_with_current_tenant() as db_session:
            search_settings = get_current_search_settings(db_session)
            index_str = search_settings.index_name

        task_logger.info(
            f"KG clustering-only set to in progress for tenant {tenant_id}"
        )

        kg_clustering(
            tenant_id=tenant_id,
            index_name=index_str,
            lock=lock_beat,
            processing_chunk_batch_size=8,
        )
    except Exception:
        task_logger.exception("Error during kg clustering-only")
    finally:
        if lock_beat.owned():
            lock_beat.release()
        else:
            task_logger.error(
                "kg_clustering_only - Lock not owned on completion: "
                f"tenant={tenant_id}"
            )
            redis_lock_dump(lock_beat, redis_client)

    task_logger.debug("Completed kg clustering-only task!")


@shared_task(
    name=OnyxCeleryTask.KG_RESET_SOURCE_INDEX,
    bind=True,
)
def kg_reset_source_index(
    self: Task, *, tenant_id: str, source_name: str, index_name: str
) -> None:
    """a task for KG reset of a source."""

    task_logger.warning(f"kg_reset_source_index - Starting for tenant {tenant_id}")

    redis_client = get_redis_client()
    lock_beat: RedisLock = redis_client.lock(
        OnyxRedisLocks.KG_PROCESSING_LOCK,
        timeout=CELERY_GENERIC_BEAT_LOCK_TIMEOUT,
    )

    # these tasks should never overlap
    if not lock_beat.acquire(blocking=False):
        return

    try:
        reset_source_kg_index(
            source_name=source_name,
            tenant_id=tenant_id,
            index_name=index_name,
            lock=lock_beat,
        )
    except Exception:
        task_logger.exception("Error during kg reset")
    finally:
        if lock_beat.owned():
            lock_beat.release()
        else:
            task_logger.error(
                "kg_reset_source_index - Lock not owned on completion: "
                f"tenant={tenant_id}"
            )
            redis_lock_dump(lock_beat, redis_client)

    task_logger.debug("Completed kg reset task!")
