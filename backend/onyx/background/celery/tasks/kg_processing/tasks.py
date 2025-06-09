import time

from celery import shared_task
from celery import Task
from celery.exceptions import SoftTimeLimitExceeded
from redis.lock import Lock as RedisLock

from onyx.background.celery.apps.app_base import task_logger
from onyx.configs.constants import CELERY_GENERIC_BEAT_LOCK_TIMEOUT
from onyx.configs.constants import OnyxCeleryPriority
from onyx.configs.constants import OnyxCeleryQueues
from onyx.configs.constants import OnyxCeleryTask
from onyx.configs.constants import OnyxRedisLocks
from onyx.db.document import check_for_documents_needing_kg_clustering
from onyx.db.document import check_for_documents_needing_kg_processing
from onyx.db.engine import get_session_with_current_tenant
from onyx.db.kg_config import get_kg_config_settings
from onyx.db.kg_config import get_kg_processing_in_progress_status
from onyx.db.kg_config import KGProcessingType
from onyx.db.kg_config import set_kg_processing_in_progress_status
from onyx.db.search_settings import get_current_search_settings
from onyx.kg.clustering.clustering import kg_clustering
from onyx.kg.extractions.extraction_processing import kg_extraction
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

        with get_session_with_current_tenant() as db_session:

            kg_config = get_kg_config_settings(db_session)

            if not kg_config.KG_ENABLED:

                return None

            kg_coverage_start = kg_config.KG_COVERAGE_START
            kg_max_coverage_days = kg_config.KG_MAX_COVERAGE_DAYS

            kg_extraction_in_progress = kg_config.KG_EXTRACTION_IN_PROGRESS
            kg_clustering_in_progress = kg_config.KG_CLUSTERING_IN_PROGRESS

        if kg_extraction_in_progress or kg_clustering_in_progress:
            task_logger.info(
                f"KG processing already in progress for tenant {tenant_id}, skipping"
            )
            return None

        with get_session_with_current_tenant() as db_session:
            documents_needing_kg_processing = check_for_documents_needing_kg_processing(
                db_session, kg_coverage_start, kg_max_coverage_days
            )

        if not documents_needing_kg_processing:
            task_logger.info(
                f"No documents needing KG processing for tenant {tenant_id}, skipping"
            )
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

        with get_session_with_current_tenant() as db_session:
            kg_clustering_in_progress = get_kg_processing_in_progress_status(
                db_session, processing_type=KGProcessingType.CLUSTERING
            )
            documents_needing_kg_clustering = check_for_documents_needing_kg_clustering(
                db_session
            )

        if kg_clustering_in_progress:
            task_logger.info(
                f"KG clustering already in progress for tenant {tenant_id}, skipping"
            )
            return None
        elif not documents_needing_kg_clustering:
            task_logger.info(
                f"No documents needing KG clustering for tenant {tenant_id}, skipping"
            )
            return None

        task_logger.info(
            f"Found documents needing KG processing for tenant {tenant_id}"
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

        set_kg_processing_in_progress_status(
            db_session, processing_type=KGProcessingType.EXTRACTION, in_progress=True
        )
        set_kg_processing_in_progress_status(
            db_session, processing_type=KGProcessingType.CLUSTERING, in_progress=True
        )

        db_session.commit()
        task_logger.info(f"KG processing set to in progress for tenant {tenant_id}")

    try:
        kg_extraction(
            tenant_id=tenant_id, index_name=index_str, processing_chunk_batch_size=8
        )
    except Exception as e:
        task_logger.exception(f"Error during kg extraction: {e}")
    finally:
        with get_session_with_current_tenant() as db_session:
            set_kg_processing_in_progress_status(
                db_session,
                processing_type=KGProcessingType.EXTRACTION,
                in_progress=False,
            )
            db_session.commit()

        task_logger.debug("Completed kg extraction task. Moving to clustering")

    try:
        kg_clustering(
            tenant_id=tenant_id, index_name=index_str, processing_chunk_batch_size=8
        )
    except Exception as e:
        task_logger.exception(f"Error during kg clustering: {e}")
    finally:
        with get_session_with_current_tenant() as db_session:
            set_kg_processing_in_progress_status(
                db_session,
                processing_type=KGProcessingType.CLUSTERING,
                in_progress=False,
            )
            db_session.commit()

        task_logger.debug("Completed kg clustering task!")

    task_logger.debug("Completed kg clustering task!")

    return None


@shared_task(
    name=OnyxCeleryTask.KG_CLUSTERING_ONLY,
    soft_time_limit=1000,
    bind=True,
)
def kg_clustering_only(self: Task, *, tenant_id: str) -> int | None:
    """a task for doing kg clustering only."""

    time.monotonic()
    with get_session_with_current_tenant() as db_session:
        search_settings = get_current_search_settings(db_session)
        index_str = search_settings.index_name

        set_kg_processing_in_progress_status(
            db_session, processing_type=KGProcessingType.CLUSTERING, in_progress=True
        )

        db_session.commit()
        task_logger.info(f"KG processing set to in progress for tenant {tenant_id}")

    task_logger.debug("Starting kg clustering-only task!")

    try:
        kg_clustering(
            tenant_id=tenant_id, index_name=index_str, processing_chunk_batch_size=8
        )
    except Exception as e:
        task_logger.exception(f"Error during kg clustering: {e}")
    finally:
        with get_session_with_current_tenant() as db_session:
            set_kg_processing_in_progress_status(
                db_session,
                processing_type=KGProcessingType.CLUSTERING,
                in_progress=False,
            )
            db_session.commit()

        task_logger.debug("Completed kg clustering task!")

    task_logger.debug("Completed kg clustering task!")

    return None
