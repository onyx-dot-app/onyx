"""Indexing published files (chat artifacts) for search, on the user file
processing queue. A publish sends the task of each artifact it made PENDING
(indexing/chat_artifact_index.py); the beat sends the rest: lost sends,
retries, and every artifact after an embedding model swap."""

from uuid import UUID

from celery import Task, shared_task

from onyx.background.celery.apps.app_base import task_logger
from onyx.background.celery.celery_redis import (
    celery_get_broker_client,
    celery_get_queue_length,
)
from onyx.cache.factory import get_cache_backend
from onyx.configs.constants import (
    CELERY_GENERIC_BEAT_LOCK_TIMEOUT,
    CELERY_USER_FILE_PROCESSING_LOCK_TIMEOUT,
    USER_FILE_PROCESSING_MAX_QUEUE_DEPTH,
    DocumentSource,
    OnyxCeleryPriority,
    OnyxCeleryQueues,
    OnyxCeleryTask,
    OnyxRedisLocks,
)
from onyx.connectors.models import Document, TextSection
from onyx.db.chat import fetch_pending_chat_artifact_ids, start_chat_artifact_indexing
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.search_settings import get_current_search_settings
from onyx.document_index.factory import get_default_document_index
from onyx.file_store.utils import get_or_extract_artifact_text
from onyx.indexing.adapters.chat_artifact_indexing_adapter import (
    ChatArtifactIndexingAdapter,
    ChatArtifactIndexSkip,
)
from onyx.indexing.chat_artifact_index import (
    chat_artifact_queued_key,
    delete_chat_artifacts_from_index,
    send_chat_artifact_index_tasks,
)
from onyx.indexing.embedder import DefaultIndexingEmbedder
from onyx.indexing.indexing_pipeline import run_indexing_pipeline


@shared_task(  # ty: ignore[invalid-argument-type]
    name=OnyxCeleryTask.CHECK_FOR_CHAT_ARTIFACT_INDEXING,
    soft_time_limit=300,
    bind=True,
    ignore_result=True,
)
def check_for_chat_artifact_indexing(self: Task, *, tenant_id: str) -> None:
    """Send the indexing task of each PENDING artifact at LOW priority, so a
    rebuild after a model swap never delays fresh publishes or uploads. Sends
    at most the queue's room below USER_FILE_PROCESSING_MAX_QUEUE_DEPTH, and
    skips an artifact whose task is still queued."""
    cache = get_cache_backend(tenant_id=tenant_id)
    lock = cache.lock(
        OnyxRedisLocks.CHAT_ARTIFACT_INDEXING_BEAT_LOCK,
        timeout=CELERY_GENERIC_BEAT_LOCK_TIMEOUT,
    )
    if not lock.acquire(blocking=False):
        return
    try:
        queue_length = celery_get_queue_length(
            OnyxCeleryQueues.USER_FILE_PROCESSING, celery_get_broker_client(self.app)
        )
        # The queue is shared with user files, so the beat fills only its room.
        room = USER_FILE_PROCESSING_MAX_QUEUE_DEPTH - queue_length
        if room <= 0:
            task_logger.warning(
                "check_for_chat_artifact_indexing - queue depth %s, skipping tenant=%s",
                queue_length,
                tenant_id,
            )
            return
        with get_session_with_current_tenant() as db_session:
            artifact_ids = fetch_pending_chat_artifact_ids(db_session, limit=room)
        sent = send_chat_artifact_index_tasks(
            artifact_ids,
            tenant_id=tenant_id,
            priority=OnyxCeleryPriority.LOW,
            celery_app=self.app,
        )
        task_logger.info(
            "check_for_chat_artifact_indexing - sent %s of %s tenant=%s",
            sent,
            len(artifact_ids),
            tenant_id,
        )
    finally:
        if lock.owned():
            lock.release()


@shared_task(  # ty: ignore[invalid-argument-type]
    name=OnyxCeleryTask.PROCESS_SINGLE_CHAT_ARTIFACT,
    bind=True,
    ignore_result=True,
)
def process_single_chat_artifact(
    self: Task,  # noqa: ARG001
    *,
    artifact_id: str,
    tenant_id: str,
) -> None:
    """Index the newest available version of one artifact. One pickup is
    counted before the slow work. A failure raises and leaves the artifact
    PENDING for the beat, until its pickups run out and it is FAILED."""
    artifact_uuid = UUID(artifact_id)
    cache = get_cache_backend(tenant_id=tenant_id)
    cache.delete(chat_artifact_queued_key(artifact_uuid))
    # A beat send while this runs finds the lock and counts no second pickup.
    lock = cache.lock(
        f"{OnyxRedisLocks.CHAT_ARTIFACT_INDEXING_LOCK_PREFIX}:{artifact_id}",
        timeout=CELERY_USER_FILE_PROCESSING_LOCK_TIMEOUT,
    )
    if not lock.acquire(blocking=False):
        return
    try:
        with get_session_with_current_tenant() as db_session:
            indexed = start_chat_artifact_indexing(db_session, artifact_uuid)
        if indexed == "remove":
            delete_chat_artifacts_from_index([artifact_uuid])
            return
        if indexed == "skip":
            return

        text = get_or_extract_artifact_text(
            indexed.file_id, indexed.file_name, indexed.file_size
        )
        name = (
            f"{indexed.file_name} - {indexed.title}"
            if indexed.title
            else indexed.file_name
        )
        document = Document(
            id=artifact_id,
            source=DocumentSource.CHAT_ARTIFACT,
            semantic_identifier=name,
            title=name,
            # A file too large to extract is found by its name and title.
            sections=[
                TextSection(text=page, link=indexed.link)
                for page in (text.pages if text is not None else [""])
            ],
            metadata={},
            doc_updated_at=indexed.updated_at,
            doc_created_at=indexed.created_at,
        )

        with get_session_with_current_tenant() as db_session:
            search_settings = get_current_search_settings(db_session)
            try:
                result = run_indexing_pipeline(
                    embedder=DefaultIndexingEmbedder.from_db_search_settings(
                        search_settings=search_settings
                    ),
                    document_index=get_default_document_index(search_settings, None),
                    ignore_time_skip=True,
                    db_session=db_session,
                    tenant_id=tenant_id,
                    document_batch=[document],
                    adapter=ChatArtifactIndexingAdapter(
                        tenant_id=tenant_id, db_session=db_session, indexed=indexed
                    ),
                    # There is no document row to write or stamp.
                    skip_document_row_writes=True,
                    stamp_content_hash=False,
                    written_search_settings_id=search_settings.id,
                )
            except ChatArtifactIndexSkip as skip:
                task_logger.info(
                    "process_single_chat_artifact - skipped %s: %s", artifact_id, skip
                )
                return
        if result.failures or result.total_docs != 1:
            raise RuntimeError(
                f"Indexing published file {artifact_id} failed: {result.failures}"
            )
    finally:
        if lock.owned():
            lock.release()
