import time

from celery import shared_task
from celery import Task
from redis.lock import Lock as RedisLock
from sqlalchemy import select

from onyx.background.celery.apps.app_base import task_logger
from onyx.background.celery.celery_utils import httpx_init_vespa_pool
from onyx.configs.app_configs import MANAGED_VESPA
from onyx.configs.app_configs import VESPA_CLOUD_CERT_PATH
from onyx.configs.app_configs import VESPA_CLOUD_KEY_PATH
from onyx.configs.constants import CELERY_GENERIC_BEAT_LOCK_TIMEOUT
from onyx.configs.constants import OnyxCeleryPriority
from onyx.configs.constants import OnyxCeleryQueues
from onyx.configs.constants import OnyxCeleryTask
from onyx.configs.constants import OnyxRedisLocks
from onyx.connectors.file.connector import LocalFileConnector
from onyx.connectors.models import Document
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import UserFileStatus
from onyx.db.models import UserFile
from onyx.db.search_settings import get_active_search_settings_list
from onyx.document_index.factory import get_default_document_index
from onyx.httpx.httpx_pool import HttpxPool
from onyx.indexing.adapters.user_file_indexing_adapter import UserFileIndexingAdapter
from onyx.indexing.embedder import DefaultIndexingEmbedder
from onyx.indexing.indexing_pipeline import run_indexing_pipeline
from onyx.natural_language_processing.search_nlp_models import (
    InformationContentClassificationModel,
)
from onyx.redis.redis_pool import get_redis_client
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR


def _user_file_lock_key(user_file_id: int) -> str:
    return f"{OnyxRedisLocks.USER_FILE_PROCESSING_LOCK_PREFIX}:{user_file_id}"


@shared_task(
    name=OnyxCeleryTask.CHECK_FOR_USER_FILE_PROCESSING,
    soft_time_limit=300,
    bind=True,
    ignore_result=True,
)
def check_user_file_processing(self: Task, *, tenant_id: str) -> None:
    """Scan for user files with PROCESSING status and enqueue per-file tasks.

    Uses direct Redis locks to avoid overlapping runs. No cc-pair usage.
    """
    task_logger.info("check_user_file_processing - Starting")
    CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)

    redis_client = get_redis_client(tenant_id=tenant_id)
    lock: RedisLock = redis_client.lock(
        OnyxRedisLocks.USER_FILE_PROCESSING_BEAT_LOCK,
        timeout=CELERY_GENERIC_BEAT_LOCK_TIMEOUT,
    )

    # Do not overlap generator runs
    if not lock.acquire(blocking=False):
        return None

    enqueued = 0
    try:
        with get_session_with_current_tenant() as db_session:
            user_file_ids = (
                db_session.execute(
                    select(UserFile.id).where(
                        UserFile.status == UserFileStatus.PROCESSING
                    )
                )
                .scalars()
                .all()
            )

            for user_file_id in user_file_ids:
                self.app.send_task(
                    OnyxCeleryTask.PROCESS_SINGLE_USER_FILE,
                    kwargs={"user_file_id": user_file_id, "tenant_id": tenant_id},
                    queue=OnyxCeleryQueues.USER_FILE_PROCESSING,
                    priority=OnyxCeleryPriority.HIGH,
                )
                enqueued += 1

    finally:
        if lock.owned():
            lock.release()

    task_logger.info(
        f"check_user_file_processing - Enqueued {enqueued} tasks for tenant={tenant_id}"
    )
    return None


@shared_task(
    name=OnyxCeleryTask.PROCESS_SINGLE_USER_FILE,
    bind=True,
    ignore_result=True,
)
def process_single_user_file(self: Task, *, user_file_id: int, tenant_id: str) -> None:
    """Process a single user file by invoking the LocalFileConnector.

    - Uses the file_id as the connector path
    - Collects documents returned by the connector
    - Updates the UserFile status to COMPLETED/FAILED
    - No cc-pair interactions; direct file processing only
    """
    start = time.monotonic()
    CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)

    redis_client = get_redis_client(tenant_id=tenant_id)
    file_lock: RedisLock = redis_client.lock(
        _user_file_lock_key(user_file_id), timeout=CELERY_GENERIC_BEAT_LOCK_TIMEOUT
    )

    if not file_lock.acquire(blocking=False):
        task_logger.info(
            f"process_single_user_file - Lock held, skipping user_file_id={user_file_id}"
        )
        return None

    documents: list[Document] = []
    try:
        with get_session_with_current_tenant() as db_session:
            uf = db_session.get(UserFile, user_file_id)
            if not uf:
                task_logger.warning(
                    f"process_single_user_file - UserFile not found id={user_file_id}"
                )
                return None

            if uf.status != UserFileStatus.PROCESSING:
                task_logger.info(
                    f"process_single_user_file - Skipping id={user_file_id} status={uf.status}"
                )
                return None

            connector = LocalFileConnector(
                file_locations=[uf.file_id],
                file_names=[uf.name] if uf.name else None,
                zip_metadata={},
            )
            connector.load_credentials({})

            # 20 is the documented default for httpx max_keepalive_connections
            if MANAGED_VESPA:
                httpx_init_vespa_pool(
                    20, ssl_cert=VESPA_CLOUD_CERT_PATH, ssl_key=VESPA_CLOUD_KEY_PATH
                )
            else:
                httpx_init_vespa_pool(20)

            search_settings_list = get_active_search_settings_list(db_session)

            current_search_settings = next(
                search_settings_instance
                for search_settings_instance in search_settings_list
                if search_settings_instance.status.is_current()
            )

            if not current_search_settings:
                raise RuntimeError(
                    f"process_single_user_file - No current search settings found for tenant={tenant_id}"
                )

            try:
                for batch in connector.load_from_state():
                    documents.extend(batch)

                adapter = UserFileIndexingAdapter(
                    tenant_id=tenant_id,
                    db_session=db_session,
                )

                # Set up indexing pipeline components
                embedding_model = DefaultIndexingEmbedder.from_db_search_settings(
                    search_settings=current_search_settings,
                )

                information_content_classification_model = (
                    InformationContentClassificationModel()
                )

                document_index = get_default_document_index(
                    current_search_settings,
                    None,
                    httpx_client=HttpxPool.get("vespa"),
                )
                # real work happens here!
                index_pipeline_result = run_indexing_pipeline(
                    embedder=embedding_model,
                    information_content_classification_model=information_content_classification_model,
                    document_index=document_index,
                    ignore_time_skip=True,  # Documents are already filtered during extraction
                    db_session=db_session,
                    tenant_id=tenant_id,
                    document_batch=documents,
                    request_id=None,
                    adapter=adapter,
                )

                task_logger.info(
                    f"process_single_user_file - Indexing pipeline completed ={index_pipeline_result}"
                )

            except Exception as e:
                task_logger.exception(
                    f"process_single_user_file - Error id={user_file_id}: {e}"
                )
                uf.status = UserFileStatus.FAILED
                db_session.add(uf)
                db_session.commit()
                return None

        elapsed = time.monotonic() - start
        task_logger.info(
            f"process_single_user_file - Finished id={user_file_id} docs={len(documents)} elapsed={elapsed:.2f}s"
        )
        return None
    except Exception as e:
        # Attempt to mark the file as failed
        with get_session_with_current_tenant() as db_session:
            uf = db_session.get(UserFile, user_file_id)
            if uf:
                uf.status = UserFileStatus.FAILED
                db_session.add(uf)
                db_session.commit()

        task_logger.exception(
            f"process_single_user_file - Error id={user_file_id}: {e}"
        )
        return None
    finally:
        if file_lock.owned():
            file_lock.release()
