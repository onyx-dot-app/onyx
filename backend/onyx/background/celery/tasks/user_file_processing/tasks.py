import datetime
import time
from typing import Any
from uuid import UUID

import httpx
import sqlalchemy as sa
from celery import shared_task
from celery import Task
from redis.lock import Lock as RedisLock
from sqlalchemy import select

from onyx.background.celery.apps.app_base import task_logger
from onyx.background.celery.celery_utils import httpx_init_vespa_pool
from onyx.background.celery.tasks.shared.RetryDocumentIndex import RetryDocumentIndex
from onyx.background.celery.tasks.shared.tasks import LIGHT_SOFT_TIME_LIMIT
from onyx.background.celery.tasks.shared.tasks import LIGHT_TIME_LIMIT
from onyx.configs.app_configs import MANAGED_VESPA
from onyx.configs.app_configs import VESPA_CLOUD_CERT_PATH
from onyx.configs.app_configs import VESPA_CLOUD_KEY_PATH
from onyx.configs.constants import CELERY_GENERIC_BEAT_LOCK_TIMEOUT
from onyx.configs.constants import DocumentSource
from onyx.configs.constants import OnyxCeleryPriority
from onyx.configs.constants import OnyxCeleryQueues
from onyx.configs.constants import OnyxCeleryTask
from onyx.configs.constants import OnyxRedisLocks
from onyx.connectors.file.connector import LocalFileConnector
from onyx.connectors.models import Document
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import UserFileStatus
from onyx.db.models import UserFile
from onyx.db.search_settings import get_active_search_settings
from onyx.db.search_settings import get_active_search_settings_list
from onyx.document_index.factory import get_default_document_index
from onyx.document_index.interfaces import VespaDocumentUserFields
from onyx.document_index.vespa.shared_utils.utils import get_vespa_http_client
from onyx.document_index.vespa.shared_utils.utils import (
    replace_invalid_doc_id_characters,
)
from onyx.document_index.vespa_constants import DOCUMENT_ID_ENDPOINT
from onyx.document_index.vespa_constants import USER_PROJECT
from onyx.httpx.httpx_pool import HttpxPool
from onyx.indexing.adapters.user_file_indexing_adapter import UserFileIndexingAdapter
from onyx.indexing.embedder import DefaultIndexingEmbedder
from onyx.indexing.indexing_pipeline import run_indexing_pipeline
from onyx.natural_language_processing.search_nlp_models import (
    InformationContentClassificationModel,
)
from onyx.redis.redis_pool import get_redis_client


def _as_uuid(value: str | UUID) -> UUID:
    """Return a UUID, accepting either a UUID or a string-like value."""
    return value if isinstance(value, UUID) else UUID(str(value))


def _user_file_lock_key(user_file_id: int) -> str:
    return f"{OnyxRedisLocks.USER_FILE_PROCESSING_LOCK_PREFIX}:{user_file_id}"


def _user_file_project_sync_lock_key(user_file_id: int) -> str:
    return f"{OnyxRedisLocks.USER_FILE_PROJECT_SYNC_LOCK_PREFIX}:{user_file_id}"


@shared_task(
    name=OnyxCeleryTask.CHECK_FOR_USER_FILE_PROCESSING,
    soft_time_limit=300,
    bind=True,
    ignore_result=True,
)
def check_user_file_processing(self: Task, *, tenant_id: str) -> None:
    """Scan for user files with PROCESSING status and enqueue per-file tasks.

    Uses direct Redis locks to avoid overlapping runs.
    """
    task_logger.info("check_user_file_processing - Starting")

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
def process_single_user_file(self: Task, *, user_file_id: str, tenant_id: str) -> None:
    task_logger.info(f"process_single_user_file - Starting id={user_file_id}")
    start = time.monotonic()

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
            uf = db_session.get(UserFile, _as_uuid(user_file_id))
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
                (
                    search_settings_instance
                    for search_settings_instance in search_settings_list
                    if search_settings_instance.status.is_current()
                ),
                None,
            )

            if current_search_settings is None:
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

                # update the doument id to userfile id in the documents
                for document in documents:
                    document.id = str(user_file_id)
                    document.source = DocumentSource.USER_FILE

                # real work happens here!
                index_pipeline_result = run_indexing_pipeline(
                    embedder=embedding_model,
                    information_content_classification_model=information_content_classification_model,
                    document_index=document_index,
                    ignore_time_skip=True,
                    db_session=db_session,
                    tenant_id=tenant_id,
                    document_batch=documents,
                    request_id=None,
                    adapter=adapter,
                )

                task_logger.info(
                    f"process_single_user_file - Indexing pipeline completed ={index_pipeline_result}"
                )

                if index_pipeline_result.failures:
                    task_logger.error(
                        f"process_single_user_file - Indexing pipeline failed id={user_file_id}"
                    )
                    uf.status = UserFileStatus.FAILED
                    db_session.add(uf)
                    db_session.commit()
                    return None

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
            uf = db_session.get(UserFile, _as_uuid(user_file_id))
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


@shared_task(
    name=OnyxCeleryTask.CHECK_FOR_USER_FILE_PROJECT_SYNC,
    soft_time_limit=300,
    bind=True,
    ignore_result=True,
)
def check_for_user_file_project_sync(self: Task, *, tenant_id: str) -> None:
    """Scan for user files with PROJECT_SYNC status and enqueue per-file tasks."""
    task_logger.info("check_for_user_file_project_sync - Starting")

    redis_client = get_redis_client(tenant_id=tenant_id)
    lock: RedisLock = redis_client.lock(
        OnyxRedisLocks.USER_FILE_PROJECT_SYNC_BEAT_LOCK,
        timeout=CELERY_GENERIC_BEAT_LOCK_TIMEOUT,
    )

    if not lock.acquire(blocking=False):
        return None

    enqueued = 0
    try:
        with get_session_with_current_tenant() as db_session:
            user_file_ids = (
                db_session.execute(
                    select(UserFile.id).where(
                        UserFile.needs_project_sync.is_(True)
                        and UserFile.status == UserFileStatus.COMPLETED
                    )
                )
                .scalars()
                .all()
            )

            for user_file_id in user_file_ids:
                self.app.send_task(
                    OnyxCeleryTask.PROCESS_SINGLE_USER_FILE_PROJECT_SYNC,
                    kwargs={"user_file_id": user_file_id, "tenant_id": tenant_id},
                    queue=OnyxCeleryQueues.USER_FILE_PROJECT_SYNC,
                    priority=OnyxCeleryPriority.HIGH,
                )
                enqueued += 1
    finally:
        if lock.owned():
            lock.release()

    task_logger.info(
        f"check_for_user_file_project_sync - Enqueued {enqueued} tasks for tenant={tenant_id}"
    )
    return None


@shared_task(
    name=OnyxCeleryTask.PROCESS_SINGLE_USER_FILE_PROJECT_SYNC,
    bind=True,
    ignore_result=True,
)
def process_single_user_file_project_sync(
    self: Task, *, user_file_id: str, tenant_id: str
) -> None:
    """Process a single user file project sync."""
    task_logger.info(
        f"process_single_user_file_project_sync - Starting id={user_file_id}"
    )

    redis_client = get_redis_client(tenant_id=tenant_id)
    file_lock: RedisLock = redis_client.lock(
        _user_file_project_sync_lock_key(user_file_id),
        timeout=CELERY_GENERIC_BEAT_LOCK_TIMEOUT,
    )

    if not file_lock.acquire(blocking=False):
        task_logger.info(
            f"process_single_user_file_project_sync - Lock held, skipping user_file_id={user_file_id}"
        )
        return None

    try:
        with get_session_with_current_tenant() as db_session:
            active_search_settings = get_active_search_settings(db_session)
            doc_index = get_default_document_index(
                search_settings=active_search_settings.primary,
                secondary_search_settings=active_search_settings.secondary,
                httpx_client=HttpxPool.get("vespa"),
            )
            retry_index = RetryDocumentIndex(doc_index)

            user_file = db_session.get(UserFile, _as_uuid(user_file_id))
            if not user_file:
                task_logger.info(
                    f"process_single_user_file_project_sync - User file not found id={user_file_id}"
                )
                return None

            project_ids = [project.id for project in user_file.projects]
            chunks_affected = retry_index.update_single(
                doc_id=str(user_file.id),
                tenant_id=tenant_id,
                chunk_count=user_file.chunk_count,
                fields=None,
                user_fields=VespaDocumentUserFields(user_projects=project_ids),
            )

            task_logger.info(
                f"process_single_user_file_project_sync - Chunks affected id={user_file_id} chunks={chunks_affected}"
            )

            user_file.needs_project_sync = False
            user_file.last_project_sync_at = datetime.datetime.now(
                datetime.timezone.utc
            )
            db_session.add(user_file)
            db_session.commit()

    except Exception as e:
        task_logger.exception(
            f"process_single_user_file_project_sync - Error id={user_file_id}: {e}"
        )
        return None
    finally:
        if file_lock.owned():
            file_lock.release()

    return None


def _normalize_legacy_user_file_doc_id(old_id: str) -> str:
    # Convert USER_FILE_CONNECTOR__<uuid> -> FILE_CONNECTOR__<uuid> for legacy values
    user_prefix = "USER_FILE_CONNECTOR__"
    file_prefix = "FILE_CONNECTOR__"
    if old_id.startswith(user_prefix):
        remainder = old_id[len(user_prefix) :]
        return file_prefix + remainder
    return old_id


def _visit_chunks(
    *,
    http_client: httpx.Client,
    index_name: str,
    selection: str,
    continuation: str | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    base_url = DOCUMENT_ID_ENDPOINT.format(index_name=index_name)
    params: dict[str, str] = {
        "selection": selection,
        "wantedDocumentCount": "1000",
    }
    if continuation:
        params["continuation"] = continuation
    resp = http_client.get(base_url, params=params, timeout=None)
    resp.raise_for_status()
    payload = resp.json()
    return payload.get("documents", []), payload.get("continuation")


def _update_document_id_in_vespa(
    *,
    index_name: str,
    old_doc_id: str,
    new_doc_id: str,
    user_project_ids: list[int] | None = None,
) -> None:
    clean_new_doc_id = replace_invalid_doc_id_characters(new_doc_id)
    normalized_old = _normalize_legacy_user_file_doc_id(old_doc_id)
    clean_old_doc_id = replace_invalid_doc_id_characters(normalized_old)

    selection = f"{index_name}.document_id=='{clean_old_doc_id}'"
    task_logger.debug(f"Vespa selection: {selection}")

    with get_vespa_http_client() as http_client:
        continuation: str | None = None
        while True:
            docs, continuation = _visit_chunks(
                http_client=http_client,
                index_name=index_name,
                selection=selection,
                continuation=continuation,
            )
            if not docs:
                break
            for doc in docs:
                vespa_full_id = doc.get("id")
                if not vespa_full_id:
                    continue
                vespa_doc_uuid = vespa_full_id.split("::")[-1]
                vespa_url = f"{DOCUMENT_ID_ENDPOINT.format(index_name=index_name)}/{vespa_doc_uuid}"
                update_request = {
                    "fields": {"document_id": {"assign": clean_new_doc_id}}
                }
                if user_project_ids is not None:
                    update_request["fields"][USER_PROJECT] = {
                        "assign": user_project_ids
                    }
                r = http_client.put(vespa_url, json=update_request)
                r.raise_for_status()
            if not continuation:
                break


@shared_task(
    name=OnyxCeleryTask.USER_FILE_DOCID_MIGRATION,
    ignore_result=True,
    soft_time_limit=LIGHT_SOFT_TIME_LIMIT,
    time_limit=LIGHT_TIME_LIMIT,
    bind=True,
)
def user_file_docid_migration_task(self: Task, *, tenant_id: str) -> bool:
    """Per-tenant job to update Vespa and search_doc document_id values for user files.

    - For each user_file with a legacy document_id, set Vespa `document_id` to the UUID `user_file.id`.
    - Update `search_doc.document_id` to the same UUID string.
    """

    try:
        with get_session_with_current_tenant() as db_session:
            active_settings = get_active_search_settings(db_session)
            document_index = get_default_document_index(
                active_settings.primary,
                active_settings.secondary,
            )
            if hasattr(document_index, "index_name"):
                index_name = document_index.index_name
            else:
                index_name = "danswer_index"

            # Fetch mappings of legacy -> new ids
            rows = db_session.execute(
                sa.text(
                    """
                    SELECT document_id, id
                    FROM user_file
                    WHERE document_id IS NOT NULL AND document_id_migrated IS NOT TRUE
                    """
                )
            ).fetchall()

            # dedupe by old document_id
            seen: set[str] = set()
            for row in rows:
                old_doc_id = str(row.document_id)
                new_uuid = str(row.id)
                if not old_doc_id or not new_uuid or old_doc_id in seen:
                    continue
                seen.add(old_doc_id)
                # collect user project ids for a combined Vespa update
                user_project_ids: list[int] | None = None
                try:
                    uf = db_session.get(UserFile, UUID(new_uuid))
                    if uf is not None:
                        user_project_ids = [project.id for project in uf.projects]
                except Exception as e:
                    task_logger.warning(
                        f"Tenant={tenant_id} failed fetching projects for doc_id={new_uuid}: {e}"
                    )
                try:
                    _update_document_id_in_vespa(
                        index_name=index_name,
                        old_doc_id=old_doc_id,
                        new_doc_id=new_uuid,
                        user_project_ids=user_project_ids,
                    )
                except Exception as e:
                    task_logger.warning(
                        f"Tenant={tenant_id} failed Vespa update for {old_doc_id} -> {new_uuid}: {e}"
                    )

            # Update search_doc records to refer to the UUID string
            db_session.execute(
                sa.text(
                    """
                    UPDATE search_doc sd
                    SET document_id = uf.id::text
                    FROM user_file uf
                    WHERE uf.document_id IS NOT NULL AND uf.document_id_migrated IS NOT TRUE
                      AND sd.document_id = uf.document_id
                    """
                )
            )
            # Mark all processed user_files as migrated
            db_session.execute(
                sa.text(
                    """
                    UPDATE user_file
                    SET document_id_migrated = TRUE
                    WHERE document_id IS NOT NULL AND document_id_migrated IS NOT TRUE
                    """
                )
            )
            db_session.commit()

        task_logger.info(
            f"user_file_docid_migration_task completed for tenant={tenant_id} (rows={len(rows)})"
        )
        return True
    except Exception:
        task_logger.exception(
            f"user_file_docid_migration_task encountered an error for tenant={tenant_id}"
        )
        return False
