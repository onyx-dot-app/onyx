"""Sending published files to the search index, and deleting them from it.

Each artifact (db/models.py:ChatArtifact) is one document, `str(artifact.id)`,
with source CHAT_ARTIFACT and its owner's email as the only ACL entry. Its
indexing task (background/celery/tasks/chat_artifact_indexing) writes the
newest available version.
"""

from collections.abc import Sequence
from uuid import UUID

from celery import Celery

from onyx.background.celery.versioned_apps.client import app as client_app
from onyx.cache.factory import get_cache_backend
from onyx.configs.app_configs import DISABLE_VECTOR_DB
from onyx.configs.constants import (
    CELERY_USER_FILE_PROCESSING_TASK_EXPIRES,
    OnyxCeleryPriority,
    OnyxCeleryQueues,
    OnyxCeleryTask,
    OnyxRedisLocks,
)
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.search_settings import get_current_search_settings
from onyx.document_index.factory import build_opensearch_document_index
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()


def chat_artifact_queued_key(artifact_id: UUID) -> str:
    """The cache key that a queued indexing task of the artifact holds until a
    worker takes it."""
    return f"{OnyxRedisLocks.CHAT_ARTIFACT_INDEXING_QUEUED_PREFIX}:{artifact_id}"


def send_chat_artifact_index_tasks(
    artifact_ids: Sequence[UUID],
    *,
    tenant_id: str | None = None,
    priority: OnyxCeleryPriority = OnyxCeleryPriority.HIGH,
    celery_app: Celery = client_app,
) -> int:
    """Send the indexing task of each artifact that has none in the queue,
    on the user file processing queue; returns how many it sent. Callers send
    after the commit that made the artifacts PENDING. `tenant_id` defaults to
    the current tenant. Best effort: a failed send is logged and ends the
    sends, and the indexing beat sends the rest."""
    if DISABLE_VECTOR_DB or not artifact_ids:
        return 0
    tenant_id = tenant_id or get_current_tenant_id()
    cache = get_cache_backend(tenant_id=tenant_id)
    sent = 0
    for artifact_id in artifact_ids:
        queued_key = chat_artifact_queued_key(artifact_id)
        try:
            if not cache.set_if_absent(
                queued_key, b"1", ex=CELERY_USER_FILE_PROCESSING_TASK_EXPIRES
            ):
                continue
            try:
                celery_app.send_task(
                    OnyxCeleryTask.PROCESS_SINGLE_CHAT_ARTIFACT,
                    kwargs={"artifact_id": str(artifact_id), "tenant_id": tenant_id},
                    queue=OnyxCeleryQueues.USER_FILE_PROCESSING,
                    priority=priority,
                    expires=CELERY_USER_FILE_PROCESSING_TASK_EXPIRES,
                )
            except Exception:
                cache.delete(queued_key)
                raise
        except Exception:
            logger.exception(
                "chat_artifact_index_send_failed artifact=%s; the beat retries",
                artifact_id,
            )
            break
        sent += 1
    return sent


def delete_chat_artifacts_from_index(artifact_ids: Sequence[UUID]) -> None:
    """Delete the artifacts' documents from the search index. Run it after
    the commit that removes their rows, deletes their chat or deletes their
    owner. Best effort: a failure is logged, and the leftover chunks reach
    only the owner's ordinary search, whose link then opens nothing. A write
    that committed within the second before the delete may not be searchable
    yet, so the delete can miss it and leave the same owner-only chunks."""
    if DISABLE_VECTOR_DB or not artifact_ids:
        return
    try:
        with get_session_with_current_tenant() as db_session:
            search_settings = get_current_search_settings(db_session)
        # Only PRESENT gets these documents.
        build_opensearch_document_index(search_settings).delete_documents(
            [str(artifact_id) for artifact_id in artifact_ids]
        )
    except Exception:
        logger.exception(
            "chat_artifact_index_delete_failed artifacts=%s",
            [str(artifact_id) for artifact_id in artifact_ids],
        )
