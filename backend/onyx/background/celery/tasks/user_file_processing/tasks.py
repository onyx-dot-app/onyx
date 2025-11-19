import datetime
import time
from collections.abc import Sequence
from typing import Any
from uuid import UUID

import httpx
import sqlalchemy as sa
from celery import shared_task
from celery import Task
from redis.lock import Lock as RedisLock
from retry import retry
from sqlalchemy import select

from onyx.background.celery.apps.app_base import task_logger
from onyx.background.celery.celery_utils import httpx_init_vespa_pool
from onyx.background.celery.tasks.shared.RetryDocumentIndex import RetryDocumentIndex
from onyx.configs.app_configs import MANAGED_VESPA
from onyx.configs.app_configs import VESPA_CLOUD_CERT_PATH
from onyx.configs.app_configs import VESPA_CLOUD_KEY_PATH
from onyx.configs.constants import CELERY_GENERIC_BEAT_LOCK_TIMEOUT
from onyx.configs.constants import CELERY_USER_FILE_DOCID_MIGRATION_LOCK_TIMEOUT
from onyx.configs.constants import CELERY_USER_FILE_PROCESSING_LOCK_TIMEOUT
from onyx.configs.constants import CELERY_USER_FILE_PROJECT_SYNC_LOCK_TIMEOUT
from onyx.configs.constants import DocumentSource
from onyx.configs.constants import FileOrigin
from onyx.configs.constants import OnyxCeleryPriority
from onyx.configs.constants import OnyxCeleryQueues
from onyx.configs.constants import OnyxCeleryTask
from onyx.configs.constants import OnyxRedisLocks
from onyx.connectors.file.connector import LocalFileConnector
from onyx.connectors.models import Document
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import UserFileStatus
from onyx.db.models import FileRecord
from onyx.db.models import SearchDoc
from onyx.db.models import UserFile
from onyx.db.search_settings import get_active_search_settings
from onyx.db.search_settings import get_active_search_settings_list
from onyx.document_index.factory import get_default_document_index
from onyx.document_index.interfaces import VespaDocumentFields
from onyx.document_index.interfaces import VespaDocumentUserFields
from onyx.document_index.vespa.shared_utils.utils import (
    replace_invalid_doc_id_characters,
)
from onyx.document_index.vespa_constants import DOCUMENT_ID_ENDPOINT
from onyx.file_store.file_store import get_default_file_store
from onyx.file_store.file_store import S3BackedFileStore
from onyx.file_store.utils import user_file_id_to_plaintext_file_name
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


def _user_file_lock_key(user_file_id: str | UUID) -> str:
    return f"{OnyxRedisLocks.USER_FILE_PROCESSING_LOCK_PREFIX}:{user_file_id}"


def _user_file_project_sync_lock_key(user_file_id: str | UUID) -> str:
    return f"{OnyxRedisLocks.USER_FILE_PROJECT_SYNC_LOCK_PREFIX}:{user_file_id}"


def _user_file_delete_lock_key(user_file_id: str | UUID) -> str:
    return f"{OnyxRedisLocks.USER_FILE_DELETE_LOCK_PREFIX}:{user_file_id}"


@retry(tries=3, delay=1, backoff=2, jitter=(0.0, 1.0))
def _visit_chunks(
    *,
    http_client: httpx.Client,
    index_name: str,
    selection: str,
    continuation: str | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    task_logger.info(
        f"Visiting chunks for index={index_name} with selection={selection}"
    )
    base_url = DOCUMENT_ID_ENDPOINT.format(index_name=index_name)
    params: dict[str, str] = {
        "selection": selection,
        "wantedDocumentCount": "100",  # Use smaller batch size to avoid timeouts
    }
    if continuation:
        params["continuation"] = continuation
    resp = http_client.get(base_url, params=params, timeout=None)
    resp.raise_for_status()
    payload = resp.json()
    return payload.get("documents", []), payload.get("continuation")


def _get_document_chunk_count(
    *,
    index_name: str,
    selection: str,
) -> int:
    chunk_count = 0
    continuation = None
    while True:
        docs, continuation = _visit_chunks(
            http_client=HttpxPool.get("vespa"),
            index_name=index_name,
            selection=selection,
            continuation=continuation,
        )
        if not docs:
            break
        chunk_count += len(docs)
        if not continuation:
            break
    return chunk_count


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
                    kwargs={"user_file_id": str(user_file_id), "tenant_id": tenant_id},
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
        _user_file_lock_key(user_file_id),
        timeout=CELERY_USER_FILE_PROCESSING_LOCK_TIMEOUT,
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

                if (
                    index_pipeline_result.failures
                    or index_pipeline_result.total_docs != len(documents)
                    or index_pipeline_result.total_chunks == 0
                ):
                    task_logger.error(
                        f"process_single_user_file - Indexing pipeline failed id={user_file_id}"
                    )
                    # don't update the status if the user file is being deleted
                    # Re-fetch to avoid mypy error
                    current_user_file = db_session.get(UserFile, _as_uuid(user_file_id))
                    if (
                        current_user_file
                        and current_user_file.status != UserFileStatus.DELETING
                    ):
                        uf.status = UserFileStatus.FAILED
                        db_session.add(uf)
                        db_session.commit()
                    return None

            except Exception as e:
                task_logger.exception(
                    f"process_single_user_file - Error processing file id={user_file_id} - {e.__class__.__name__}"
                )
                # don't update the status if the user file is being deleted
                current_user_file = db_session.get(UserFile, _as_uuid(user_file_id))
                if (
                    current_user_file
                    and current_user_file.status != UserFileStatus.DELETING
                ):
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
                # don't update the status if the user file is being deleted
                if uf.status != UserFileStatus.DELETING:
                    uf.status = UserFileStatus.FAILED
                db_session.add(uf)
                db_session.commit()

        task_logger.exception(
            f"process_single_user_file - Error processing file id={user_file_id} - {e.__class__.__name__}"
        )
        return None
    finally:
        if file_lock.owned():
            file_lock.release()


@shared_task(
    name=OnyxCeleryTask.CHECK_FOR_USER_FILE_DELETE,
    soft_time_limit=300,
    bind=True,
    ignore_result=True,
)
def check_for_user_file_delete(self: Task, *, tenant_id: str) -> None:
    """Scan for user files with DELETING status and enqueue per-file tasks."""
    task_logger.info("check_for_user_file_delete - Starting")
    redis_client = get_redis_client(tenant_id=tenant_id)
    lock: RedisLock = redis_client.lock(
        OnyxRedisLocks.USER_FILE_DELETE_BEAT_LOCK,
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
                        UserFile.status == UserFileStatus.DELETING
                    )
                )
                .scalars()
                .all()
            )
            for user_file_id in user_file_ids:
                self.app.send_task(
                    OnyxCeleryTask.DELETE_SINGLE_USER_FILE,
                    kwargs={"user_file_id": str(user_file_id), "tenant_id": tenant_id},
                    queue=OnyxCeleryQueues.USER_FILE_DELETE,
                    priority=OnyxCeleryPriority.HIGH,
                )
                enqueued += 1
    except Exception as e:
        task_logger.exception(
            f"check_for_user_file_delete - Error enqueuing deletes - {e.__class__.__name__}"
        )
        return None
    finally:
        if lock.owned():
            lock.release()
    task_logger.info(
        f"check_for_user_file_delete - Enqueued {enqueued} tasks for tenant={tenant_id}"
    )
    return None


@shared_task(
    name=OnyxCeleryTask.DELETE_SINGLE_USER_FILE,
    bind=True,
    ignore_result=True,
)
def process_single_user_file_delete(
    self: Task, *, user_file_id: str, tenant_id: str
) -> None:
    """Process a single user file delete."""
    task_logger.info(f"process_single_user_file_delete - Starting id={user_file_id}")
    redis_client = get_redis_client(tenant_id=tenant_id)
    file_lock: RedisLock = redis_client.lock(
        _user_file_delete_lock_key(user_file_id),
        timeout=CELERY_GENERIC_BEAT_LOCK_TIMEOUT,
    )
    if not file_lock.acquire(blocking=False):
        task_logger.info(
            f"process_single_user_file_delete - Lock held, skipping user_file_id={user_file_id}"
        )
        return None
    try:
        with get_session_with_current_tenant() as db_session:
            # 20 is the documented default for httpx max_keepalive_connections
            if MANAGED_VESPA:
                httpx_init_vespa_pool(
                    20, ssl_cert=VESPA_CLOUD_CERT_PATH, ssl_key=VESPA_CLOUD_KEY_PATH
                )
            else:
                httpx_init_vespa_pool(20)

            active_search_settings = get_active_search_settings(db_session)
            document_index = get_default_document_index(
                search_settings=active_search_settings.primary,
                secondary_search_settings=active_search_settings.secondary,
                httpx_client=HttpxPool.get("vespa"),
            )
            retry_index = RetryDocumentIndex(document_index)
            index_name = active_search_settings.primary.index_name
            selection = f"{index_name}.document_id=='{user_file_id}'"

            user_file = db_session.get(UserFile, _as_uuid(user_file_id))
            if not user_file:
                task_logger.info(
                    f"process_single_user_file_delete - User file not found id={user_file_id}"
                )
                return None

            # 1) Delete Vespa chunks for the document
            chunk_count = 0
            if user_file.chunk_count is None or user_file.chunk_count == 0:
                chunk_count = _get_document_chunk_count(
                    index_name=index_name,
                    selection=selection,
                )
            else:
                chunk_count = user_file.chunk_count

            retry_index.delete_single(
                doc_id=user_file_id,
                tenant_id=tenant_id,
                chunk_count=chunk_count,
            )

            # 2) Delete the user-uploaded file content from filestore (blob + metadata)
            file_store = get_default_file_store()
            try:
                file_store.delete_file(user_file.file_id)
                file_store.delete_file(
                    user_file_id_to_plaintext_file_name(user_file.id)
                )
            except Exception as e:
                # This block executed only if the file is not found in the filestore
                task_logger.exception(
                    f"process_single_user_file_delete - Error deleting file id={user_file.id} - {e.__class__.__name__}"
                )

            # 3) Finally, delete the UserFile row
            db_session.delete(user_file)
            db_session.commit()
            task_logger.info(
                f"process_single_user_file_delete - Completed id={user_file_id}"
            )
    except Exception as e:
        task_logger.exception(
            f"process_single_user_file_delete - Error processing file id={user_file_id} - {e.__class__.__name__}"
        )
        return None
    finally:
        if file_lock.owned():
            file_lock.release()
    return None


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
                        sa.and_(
                            UserFile.needs_project_sync.is_(True),
                            UserFile.status == UserFileStatus.COMPLETED,
                        )
                    )
                )
                .scalars()
                .all()
            )

            for user_file_id in user_file_ids:
                self.app.send_task(
                    OnyxCeleryTask.PROCESS_SINGLE_USER_FILE_PROJECT_SYNC,
                    kwargs={"user_file_id": str(user_file_id), "tenant_id": tenant_id},
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
        timeout=CELERY_USER_FILE_PROJECT_SYNC_LOCK_TIMEOUT,
    )

    if not file_lock.acquire(blocking=False):
        task_logger.info(
            f"process_single_user_file_project_sync - Lock held, skipping user_file_id={user_file_id}"
        )
        return None

    try:
        with get_session_with_current_tenant() as db_session:

            # 20 is the documented default for httpx max_keepalive_connections
            if MANAGED_VESPA:
                httpx_init_vespa_pool(
                    20, ssl_cert=VESPA_CLOUD_CERT_PATH, ssl_key=VESPA_CLOUD_KEY_PATH
                )
            else:
                httpx_init_vespa_pool(20)

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
            f"process_single_user_file_project_sync - Error syncing project for file id={user_file_id} - {e.__class__.__name__}"
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


def update_legacy_plaintext_file_records() -> None:
    """Migrate legacy plaintext cache objects from int-based keys to UUID-based
    keys. Copies each S3 object to its expected UUID key and updates DB.

    Examples:
    - Old key: bucket/schema/plaintext_<int>
    - New key: bucket/schema/plaintext_<uuid>
    """

    task_logger.info("update_legacy_plaintext_file_records - Starting")

    with get_session_with_current_tenant() as db_session:
        store = get_default_file_store()

        if not isinstance(store, S3BackedFileStore):
            task_logger.info(
                "update_legacy_plaintext_file_records - Skipping non-S3 store"
            )
            return

        s3_client = store._get_s3_client()
        bucket_name = store._get_bucket_name()

        # Select PLAINTEXT_CACHE records whose object_key ends with 'plaintext_' + non-hyphen chars
        # Example: 'some/path/plaintext_abc123' matches; '.../plaintext_foo-bar' does not
        plaintext_records: Sequence[FileRecord] = (
            db_session.execute(
                sa.select(FileRecord).where(
                    FileRecord.file_origin == FileOrigin.PLAINTEXT_CACHE,
                    FileRecord.object_key.op("~")(r"plaintext_[^-]+$"),
                )
            )
            .scalars()
            .all()
        )

        task_logger.info(
            f"update_legacy_plaintext_file_records - Found {len(plaintext_records)} plaintext records to update"
        )

        normalized = 0
        for fr in plaintext_records:
            try:
                expected_key = store._get_s3_key(fr.file_id)
                if fr.object_key == expected_key:
                    continue

                if fr.bucket_name is None:
                    task_logger.warning(f"id={fr.file_id} - Bucket name is None")
                    continue

                if fr.object_key is None:
                    task_logger.warning(f"id={fr.file_id} - Object key is None")
                    continue

                # Copy old object to new key
                copy_source = f"{fr.bucket_name}/{fr.object_key}"
                s3_client.copy_object(
                    CopySource=copy_source,
                    Bucket=bucket_name,
                    Key=expected_key,
                    MetadataDirective="COPY",
                )

                # Delete old object (best-effort)
                try:
                    s3_client.delete_object(Bucket=fr.bucket_name, Key=fr.object_key)
                except Exception:
                    pass

                # Update DB record with new key
                fr.object_key = expected_key
                db_session.add(fr)
                normalized += 1
            except Exception as e:
                task_logger.warning(f"id={fr.file_id} - {e.__class__.__name__}")

        if normalized:
            db_session.commit()
            task_logger.info(
                f"user_file_docid_migration_task normalized {normalized} plaintext objects"
            )


@shared_task(
    name=OnyxCeleryTask.USER_FILE_DOCID_MIGRATION,
    ignore_result=True,
    bind=True,
)
def user_file_docid_migration_task(self: Task, *, tenant_id: str) -> bool:

    task_logger.info(
        f"user_file_docid_migration_task - Starting for tenant={tenant_id}"
    )

    redis_client = get_redis_client(tenant_id=tenant_id)
    lock: RedisLock = redis_client.lock(
        OnyxRedisLocks.USER_FILE_DOCID_MIGRATION_LOCK,
        timeout=CELERY_USER_FILE_DOCID_MIGRATION_LOCK_TIMEOUT,
    )

    if not lock.acquire(blocking=False):
        task_logger.info(
            f"user_file_docid_migration_task - Lock held, skipping tenant={tenant_id}"
        )
        return False

    updated_count = 0
    try:
        update_legacy_plaintext_file_records()
        # Track lock renewal
        last_lock_time = time.monotonic()
        with get_session_with_current_tenant() as db_session:

            # 20 is the documented default for httpx max_keepalive_connections
            if MANAGED_VESPA:
                httpx_init_vespa_pool(
                    20, ssl_cert=VESPA_CLOUD_CERT_PATH, ssl_key=VESPA_CLOUD_KEY_PATH
                )
            else:
                httpx_init_vespa_pool(20)

            active_settings = get_active_search_settings(db_session)
            document_index = get_default_document_index(
                search_settings=active_settings.primary,
                secondary_search_settings=active_settings.secondary,
                httpx_client=HttpxPool.get("vespa"),
            )

            retry_index = RetryDocumentIndex(document_index)

            # Select user files with a legacy doc id that have not been migrated
            user_files = (
                db_session.execute(
                    sa.select(UserFile).where(
                        sa.and_(
                            UserFile.document_id.is_not(None),
                            UserFile.document_id_migrated.is_(False),
                        )
                    )
                )
                .scalars()
                .all()
            )

            task_logger.info(
                f"user_file_docid_migration_task - Found {len(user_files)} user files to migrate"
            )

            # Query all SearchDocs that need updating
            search_docs = (
                db_session.execute(
                    sa.select(SearchDoc).where(
                        SearchDoc.document_id.like("%FILE_CONNECTOR__%")
                    )
                )
                .scalars()
                .all()
            )
            task_logger.info(
                f"user_file_docid_migration_task - Found {len(search_docs)} search docs to update"
            )

            # Build a map of normalized doc IDs to SearchDocs
            search_doc_map: dict[str, list[SearchDoc]] = {}
            for sd in search_docs:
                doc_id = sd.document_id
                if search_doc_map.get(doc_id) is None:
                    search_doc_map[doc_id] = []
                search_doc_map[doc_id].append(sd)

            task_logger.debug(
                f"user_file_docid_migration_task - Built search doc map with {len(search_doc_map)} entries"
            )

            ids_preview = list(search_doc_map.keys())[:5]
            task_logger.debug(
                f"user_file_docid_migration_task - First few search_doc_map ids: {ids_preview if ids_preview else 'No ids found'}"
            )
            task_logger.debug(
                f"user_file_docid_migration_task - search_doc_map total items: "
                f"{sum(len(docs) for docs in search_doc_map.values())}"
            )
            for user_file in user_files:
                # Periodically renew the Redis lock to prevent expiry mid-run
                current_time = time.monotonic()
                if current_time - last_lock_time >= (
                    CELERY_USER_FILE_DOCID_MIGRATION_LOCK_TIMEOUT / 4
                ):
                    renewed = False
                    try:
                        # extend lock ttl to full timeout window
                        lock.extend(CELERY_USER_FILE_DOCID_MIGRATION_LOCK_TIMEOUT)
                        renewed = True
                    except Exception:
                        # if extend fails, best-effort reacquire as a fallback
                        try:
                            lock.reacquire()
                            renewed = True
                        except Exception:
                            renewed = False
                    last_lock_time = current_time
                    if not renewed or not lock.owned():
                        task_logger.error(
                            "user_file_docid_migration_task - Lost lock ownership or failed to renew; aborting for safety"
                        )
                        return False

                try:
                    clean_old_doc_id = replace_invalid_doc_id_characters(
                        user_file.document_id
                    )
                    normalized_doc_id = _normalize_legacy_user_file_doc_id(
                        clean_old_doc_id
                    )
                    user_project_ids = [project.id for project in user_file.projects]
                    task_logger.info(
                        f"user_file_docid_migration_task - Migrating user file {user_file.id} with doc_id {normalized_doc_id}"
                    )

                    index_name = active_settings.primary.index_name

                    # First find the chunks count using direct Vespa query
                    selection = f"{index_name}.document_id=='{normalized_doc_id}'"

                    # Count all chunks for this document
                    chunk_count = _get_document_chunk_count(
                        index_name=index_name,
                        selection=selection,
                    )

                    task_logger.info(
                        f"Found {chunk_count} chunks for document {normalized_doc_id}"
                    )

                    # Now update Vespa chunks with the found chunk count using retry_index
                    updated_chunks = retry_index.update_single(
                        doc_id=str(normalized_doc_id),
                        tenant_id=tenant_id,
                        chunk_count=chunk_count,
                        fields=VespaDocumentFields(document_id=str(user_file.id)),
                        user_fields=VespaDocumentUserFields(
                            user_projects=user_project_ids
                        ),
                    )
                    user_file.chunk_count = updated_chunks

                    # Update the SearchDocs
                    actual_doc_id = str(user_file.document_id)
                    normalized_actual_doc_id = _normalize_legacy_user_file_doc_id(
                        actual_doc_id
                    )
                    if (
                        normalized_doc_id in search_doc_map
                        or normalized_actual_doc_id in search_doc_map
                    ):
                        to_update = (
                            search_doc_map[normalized_doc_id]
                            if normalized_doc_id in search_doc_map
                            else search_doc_map[normalized_actual_doc_id]
                        )
                        task_logger.debug(
                            f"user_file_docid_migration_task - Updating {len(to_update)} search docs for user file {user_file.id}"
                        )
                        for search_doc in to_update:
                            search_doc.document_id = str(user_file.id)
                            db_session.add(search_doc)

                    user_file.document_id_migrated = True
                    db_session.add(user_file)
                    db_session.commit()
                    updated_count += 1
                except Exception as per_file_exc:
                    # Rollback the current transaction and continue with the next file
                    db_session.rollback()
                    task_logger.exception(
                        f"user_file_docid_migration_task - Error migrating user file {user_file.id} - "
                        f"{per_file_exc.__class__.__name__}"
                    )

            task_logger.info(
                f"user_file_docid_migration_task - Updated {updated_count} user files"
            )

        task_logger.info(
            f"user_file_docid_migration_task - Completed for tenant={tenant_id} (updated={updated_count})"
        )
        return True
    except Exception as e:
        task_logger.exception(
            f"user_file_docid_migration_task - Error during execution for tenant={tenant_id} "
            f"(updated={updated_count}) exception={e.__class__.__name__}"
        )
        return False
    finally:
        if lock.owned():
            lock.release()
