"""Celery tasks for migrating documents from Vespa to OpenSearch."""

import time

from celery import shared_task
from celery import Task
from redis.lock import Lock as RedisLock

from onyx.background.celery.apps.app_base import task_logger
from onyx.background.celery.tasks.opensearch_migration.constants import (
    MIGRATION_TASK_LOCK_BLOCKING_TIMEOUT_S,
)
from onyx.background.celery.tasks.opensearch_migration.constants import (
    MIGRATION_TASK_LOCK_TIMEOUT_S,
)
from onyx.background.celery.tasks.opensearch_migration.constants import (
    MIGRATION_TASK_SOFT_TIME_LIMIT_S,
)
from onyx.background.celery.tasks.opensearch_migration.constants import (
    MIGRATION_TASK_TIME_LIMIT_S,
)
from onyx.background.celery.tasks.opensearch_migration.transformer import (
    transform_vespa_chunks_to_opensearch_chunks,
)
from onyx.configs.app_configs import ENABLE_OPENSEARCH_INDEXING_FOR_ONYX
from onyx.configs.constants import OnyxCeleryTask
from onyx.configs.constants import OnyxRedisLocks
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.opensearch_migration import build_sanitized_to_original_doc_id_mapping
from onyx.db.opensearch_migration import get_vespa_visit_state
from onyx.db.opensearch_migration import (
    mark_migration_completed_time_if_not_set_with_commit,
)
from onyx.db.opensearch_migration import (
    try_insert_opensearch_tenant_migration_record_with_commit,
)
from onyx.db.opensearch_migration import update_vespa_visit_progress_with_commit
from onyx.db.search_settings import get_current_search_settings
from onyx.document_index.interfaces_new import TenantState
from onyx.document_index.opensearch.opensearch_document_index import (
    OpenSearchDocumentIndex,
)
from onyx.document_index.opensearch.schema import DocumentChunk
from onyx.document_index.vespa.vespa_document_index import VespaDocumentIndex
from onyx.redis.redis_pool import get_redis_client
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import get_current_tenant_id


GET_VESPA_CHUNKS_PAGE_SIZE = 1000


# shared_task allows this task to be shared across celery app instances.
@shared_task(
    name=OnyxCeleryTask.MIGRATE_CHUNKS_FROM_VESPA_TO_OPENSEARCH_TASK,
    # Does not store the task's return value in the result backend.
    ignore_result=True,
    # WARNING: This is here just for rigor but since we use threads for Celery
    # this config is not respected and timeout logic must be implemented in the
    # task.
    soft_time_limit=MIGRATION_TASK_SOFT_TIME_LIMIT_S,
    # WARNING: This is here just for rigor but since we use threads for Celery
    # this config is not respected and timeout logic must be implemented in the
    # task.
    time_limit=MIGRATION_TASK_TIME_LIMIT_S,
    # Passed in self to the task to get task metadata.
    bind=True,
)
def migrate_chunks_from_vespa_to_opensearch_task(
    self: Task,  # noqa: ARG001
    *,
    tenant_id: str,
) -> bool | None:
    """
    Periodic task to migrate chunks from Vespa to OpenSearch via the Visit API.

    Uses Vespa's Visit API to iterate through ALL chunks in bulk (not
    per-document), transform them, and index them into OpenSearch. Progress is
    tracked via a continuation token stored in the
    OpenSearchTenantMigrationRecord.

    The first time we see no continuation token and non-zero chunks migrated, we
    consider the migration complete and all subsequent invocations are no-ops.

    Returns:
        None if OpenSearch migration is not enabled, or if the lock could not be
            acquired; effectively a no-op. True if the task completed
            successfully. False if the task errored.
    """
    if not ENABLE_OPENSEARCH_INDEXING_FOR_ONYX:
        task_logger.warning(
            "OpenSearch migration is not enabled, skipping chunk migration task."
        )
        return None

    task_logger.info("Starting chunk-level migration from Vespa to OpenSearch.")
    task_start_time = time.monotonic()
    r = get_redis_client()
    lock: RedisLock = r.lock(
        name=OnyxRedisLocks.OPENSEARCH_MIGRATION_BEAT_LOCK,
        # The maximum time the lock can be held for. Will automatically be
        # released after this time.
        timeout=MIGRATION_TASK_LOCK_TIMEOUT_S,
        # .acquire will block until the lock is acquired.
        blocking=True,
        # Time to wait to acquire the lock.
        blocking_timeout=MIGRATION_TASK_LOCK_BLOCKING_TIMEOUT_S,
    )
    if not lock.acquire():
        task_logger.warning(
            "The OpenSearch migration task timed out waiting for the lock."
        )
        return None
    else:
        task_logger.info(
            f"Acquired the OpenSearch migration lock. Took {time.monotonic() - task_start_time:.3f} seconds. "
            f"Token: {lock.local.token}"
        )

    total_chunks_migrated_this_task = 0
    try:
        # Double check that tenant info is correct.
        if tenant_id != get_current_tenant_id():
            err_str = (
                f"Tenant ID mismatch in the OpenSearch migration task: "
                f"{tenant_id} != {get_current_tenant_id()}. This should never happen."
            )
            task_logger.error(err_str)
            return False

        with get_session_with_current_tenant() as db_session:
            try_insert_opensearch_tenant_migration_record_with_commit(db_session)
            search_settings = get_current_search_settings(db_session)
            tenant_state = TenantState(tenant_id=tenant_id, multitenant=MULTI_TENANT)
            opensearch_document_index = OpenSearchDocumentIndex(
                index_name=search_settings.index_name, tenant_state=tenant_state
            )
            vespa_document_index = VespaDocumentIndex(
                index_name=search_settings.index_name,
                tenant_state=tenant_state,
                large_chunks_enabled=False,
            )

            sanitized_doc_start_time = time.monotonic()
            # We reconstruct this mapping for every task invocation because a
            # document may have been added in the time between two tasks.
            sanitized_to_original_doc_id_mapping = (
                build_sanitized_to_original_doc_id_mapping(db_session)
            )
            task_logger.debug(
                f"Built sanitized_to_original_doc_id_mapping with {len(sanitized_to_original_doc_id_mapping)} entries "
                f"in {time.monotonic() - sanitized_doc_start_time:.3f} seconds."
            )

            while (
                time.monotonic() - task_start_time < MIGRATION_TASK_SOFT_TIME_LIMIT_S
                and lock.owned()
            ):
                (
                    continuation_token,
                    total_chunks_migrated,
                ) = get_vespa_visit_state(db_session)
                if continuation_token is None and total_chunks_migrated > 0:
                    task_logger.info(
                        f"OpenSearch migration COMPLETED for tenant {tenant_id}. "
                        f"Total chunks migrated: {total_chunks_migrated}."
                    )
                    mark_migration_completed_time_if_not_set_with_commit(db_session)
                    return True
                task_logger.debug(
                    f"Read the tenant migration record. Total chunks migrated: {total_chunks_migrated}. "
                    f"Continuation token: {continuation_token}"
                )

                get_vespa_chunks_start_time = time.monotonic()
                raw_vespa_chunks, next_continuation_token = (
                    vespa_document_index.get_all_raw_document_chunks_paginated(
                        continuation_token=continuation_token,
                        page_size=GET_VESPA_CHUNKS_PAGE_SIZE,
                    )
                )
                task_logger.debug(
                    f"Read {len(raw_vespa_chunks)} chunks from Vespa in {time.monotonic() - get_vespa_chunks_start_time:.3f} "
                    f"seconds. Next continuation token: {next_continuation_token}"
                )

                opensearch_document_chunks: list[DocumentChunk] = (
                    transform_vespa_chunks_to_opensearch_chunks(
                        raw_vespa_chunks,
                        tenant_state,
                        sanitized_to_original_doc_id_mapping,
                    )
                )
                if len(opensearch_document_chunks) != len(raw_vespa_chunks):
                    raise RuntimeError(
                        f"Bug: Number of candidate chunks to migrate ({len(opensearch_document_chunks)}) does not match "
                        f"number of chunks in Vespa ({len(raw_vespa_chunks)})."
                    )

                index_opensearch_chunks_start_time = time.monotonic()
                opensearch_document_index.index_raw_chunks(
                    chunks=opensearch_document_chunks
                )
                task_logger.debug(
                    f"Indexed {len(opensearch_document_chunks)} chunks into OpenSearch in "
                    f"{time.monotonic() - index_opensearch_chunks_start_time:.3f} seconds."
                )

                total_chunks_migrated_this_task += len(opensearch_document_chunks)
                update_vespa_visit_progress_with_commit(
                    db_session,
                    continuation_token=next_continuation_token,
                    chunks_processed=len(opensearch_document_chunks),
                )

                if next_continuation_token is None and len(raw_vespa_chunks) == 0:
                    task_logger.info("Vespa reported no more chunks to migrate.")
                    break
    except Exception:
        task_logger.exception("Error in the OpenSearch migration task.")
        return False
    finally:
        if lock.owned():
            lock.release()
        else:
            task_logger.warning(
                "The OpenSearch migration lock was not owned on completion of the migration task."
            )

    task_logger.info(
        f"OpenSearch chunk migration task pausing (time limit reached). "
        f"Total chunks migrated this task: {total_chunks_migrated_this_task}. "
        f"Elapsed: {time.monotonic() - task_start_time:.3f}s. "
        "Will resume from continuation token on next invocation."
    )

    return True
