"""Celery tasks for migrating documents from Vespa to OpenSearch."""

import time
import traceback

from celery import shared_task
from celery import Task
from redis.lock import Lock as RedisLock

from onyx.background.celery.apps.app_base import task_logger
from onyx.background.celery.tasks.opensearch_migration.constants import (
    FINISHED_VISITING_SLICE_CONTINUATION_TOKEN,
)
from onyx.background.celery.tasks.opensearch_migration.constants import (
    GET_VESPA_CHUNKS_PAGE_SIZE,
)
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
from onyx.configs.app_configs import VESPA_MIGRATION_REQUEST_TIMEOUT_S
from onyx.configs.constants import OnyxCeleryTask
from onyx.configs.constants import OnyxRedisLocks
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.opensearch_migration import build_sanitized_to_original_doc_id_mapping
from onyx.db.opensearch_migration import get_vespa_visit_state
from onyx.db.opensearch_migration import is_migration_completed
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
from onyx.document_index.vespa.shared_utils.utils import get_vespa_http_client
from onyx.document_index.vespa.vespa_document_index import VespaDocumentIndex
from onyx.indexing.models import IndexingSetting
from onyx.redis.redis_pool import get_redis_client
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import get_current_tenant_id


def is_continuation_token_done_for_all_slices(
    continuation_token_map: dict[int, str | None],
) -> bool:
    return all(
        continuation_token == FINISHED_VISITING_SLICE_CONTINUATION_TOKEN
        for continuation_token in continuation_token_map.values()
    )


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
    tracked via a continuation token map stored in the
    OpenSearchTenantMigrationRecord.

    The first time we see no continuation token map and non-zero chunks
    migrated, we consider the migration complete and all subsequent invocations
    are no-ops.

    We divide the index into GET_VESPA_CHUNKS_SLICE_COUNT independent slices
    where progress is tracked for each slice.

    Returns:
        None if OpenSearch migration is not enabled, or if the lock could not be
            acquired; effectively a no-op. True if the task completed
            successfully. False if the task errored.
    """
    # 1. Check if we should run the task.
    # 1.a. If OpenSearch indexing is disabled, we don't run the task.
    if not ENABLE_OPENSEARCH_INDEXING_FOR_ONYX:
        task_logger.warning(
            "OpenSearch migration is not enabled, skipping chunk migration task."
        )
        return None
    task_logger.info("Starting chunk-level migration from Vespa to OpenSearch.")
    task_start_time = time.monotonic()

    # 1.b. Only one instance per tenant of this task may run concurrently at
    # once. If we fail to acquire a lock, we assume it is because another task
    # has one and we exit.
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

    # 2. Prepare to migrate.
    total_chunks_migrated_this_task = 0
    total_chunks_errored_this_task = 0
    try:
        # 2.a. Double-check that tenant info is correct.
        if tenant_id != get_current_tenant_id():
            err_str = (
                f"Tenant ID mismatch in the OpenSearch migration task: "
                f"{tenant_id} != {get_current_tenant_id()}. This should never happen."
            )
            task_logger.error(err_str)
            return False

        # Do as much as we can with a DB session in one spot to not hold a
        # session during a migration batch.
        with get_session_with_current_tenant() as db_session:
            # 2.b. Immediately check to see if this tenant is done, to save
            # having to do any other work. This function does not require a
            # migration record to necessarily exist.
            if is_migration_completed(db_session):
                return True

            # 2.c. Try to insert the OpenSearchTenantMigrationRecord table if it
            # does not exist.
            try_insert_opensearch_tenant_migration_record_with_commit(db_session)

            # 2.d. Get search settings.
            search_settings = get_current_search_settings(db_session)
            indexing_setting = IndexingSetting.from_db_model(search_settings)

            # 2.e. Build sanitized to original doc ID mapping to check for
            # conflicts in the event we sanitize a doc ID to an
            # already-existing doc ID.
            # We reconstruct this mapping for every task invocation because
            # a document may have been added in the time between two tasks.
            sanitized_doc_start_time = time.monotonic()
            sanitized_to_original_doc_id_mapping = (
                build_sanitized_to_original_doc_id_mapping(db_session)
            )
            task_logger.debug(
                f"Built sanitized_to_original_doc_id_mapping with {len(sanitized_to_original_doc_id_mapping)} entries "
                f"in {time.monotonic() - sanitized_doc_start_time:.3f} seconds."
            )

            # 2.f. Get the current migration state.
            continuation_token_map, total_chunks_migrated = get_vespa_visit_state(
                db_session
            )
            # 2.f.1. Double-check that the migration state does not imply
            # completion. Really we should never have to enter this block as we
            # would expect is_migration_completed to return True, but in the
            # strange event that the migration is complete but the migration
            # completed time was never stamped, we do so here.
            if is_continuation_token_done_for_all_slices(continuation_token_map):
                task_logger.info(
                    f"OpenSearch migration COMPLETED for tenant {tenant_id}. Total chunks migrated: {total_chunks_migrated}."
                )
                mark_migration_completed_time_if_not_set_with_commit(db_session)
                return True
        task_logger.debug(
            f"Read the tenant migration record. Total chunks migrated: {total_chunks_migrated}. "
            f"Continuation token map: {continuation_token_map}"
        )

        with get_vespa_http_client(
            timeout=VESPA_MIGRATION_REQUEST_TIMEOUT_S
        ) as vespa_client:
            # 2.g. Create the OpenSearch and Vespa document indexes.
            tenant_state = TenantState(tenant_id=tenant_id, multitenant=MULTI_TENANT)
            opensearch_document_index = OpenSearchDocumentIndex(
                tenant_state=tenant_state,
                index_name=search_settings.index_name,
                embedding_dim=indexing_setting.final_embedding_dim,
                embedding_precision=indexing_setting.embedding_precision,
            )
            vespa_document_index = VespaDocumentIndex(
                index_name=search_settings.index_name,
                tenant_state=tenant_state,
                large_chunks_enabled=False,
                httpx_client=vespa_client,
            )

            # 2.h. Get the approximate chunk count in Vespa as of this time to
            # update the migration record.
            approx_chunk_count_in_vespa: int | None = None
            get_chunk_count_start_time = time.monotonic()
            try:
                approx_chunk_count_in_vespa = vespa_document_index.get_chunk_count()
            except Exception:
                # This failure should not be blocking.
                task_logger.exception(
                    "Error getting approximate chunk count in Vespa. Moving on..."
                )
            task_logger.debug(
                f"Took {time.monotonic() - get_chunk_count_start_time:.3f} seconds to attempt to get "
                f"approximate chunk count in Vespa. Got {approx_chunk_count_in_vespa}."
            )

            # 3. Do the actual migration in batches until we run out of time.
            while (
                time.monotonic() - task_start_time < MIGRATION_TASK_SOFT_TIME_LIMIT_S
                and lock.owned()
            ):
                # 3.a. Get the next batch of raw chunks from Vespa.
                get_vespa_chunks_start_time = time.monotonic()
                raw_vespa_chunks, next_continuation_token_map = (
                    vespa_document_index.get_all_raw_document_chunks_paginated(
                        continuation_token_map=continuation_token_map,
                        page_size=GET_VESPA_CHUNKS_PAGE_SIZE,
                    )
                )
                task_logger.debug(
                    f"Read {len(raw_vespa_chunks)} chunks from Vespa in {time.monotonic() - get_vespa_chunks_start_time:.3f} "
                    f"seconds. Next continuation token map: {next_continuation_token_map}"
                )

                # 3.b. Transform the raw chunks to OpenSearch chunks in memory.
                opensearch_document_chunks, errored_chunks = (
                    transform_vespa_chunks_to_opensearch_chunks(
                        raw_vespa_chunks,
                        tenant_state,
                        sanitized_to_original_doc_id_mapping,
                    )
                )
                if len(opensearch_document_chunks) != len(raw_vespa_chunks):
                    task_logger.error(
                        f"Migration task error: Number of candidate chunks to migrate ({len(opensearch_document_chunks)}) does "
                        f"not match number of chunks in Vespa ({len(raw_vespa_chunks)}). {len(errored_chunks)} chunks "
                        "errored."
                    )

                # 3.c. Index the OpenSearch chunks into OpenSearch.
                index_opensearch_chunks_start_time = time.monotonic()
                opensearch_document_index.index_raw_chunks(
                    chunks=opensearch_document_chunks
                )
                task_logger.debug(
                    f"Indexed {len(opensearch_document_chunks)} chunks into OpenSearch in "
                    f"{time.monotonic() - index_opensearch_chunks_start_time:.3f} seconds."
                )

                total_chunks_migrated_this_task += len(opensearch_document_chunks)
                total_chunks_errored_this_task += len(errored_chunks)

                # Do as much as we can with a DB session in one spot to not hold a
                # session during a migration batch.
                with get_session_with_current_tenant() as db_session:
                    # 3.d. Update the migration state.
                    update_vespa_visit_progress_with_commit(
                        db_session,
                        continuation_token_map=next_continuation_token_map,
                        chunks_processed=len(opensearch_document_chunks),
                        chunks_errored=len(errored_chunks),
                        approx_chunk_count_in_vespa=approx_chunk_count_in_vespa,
                    )

                    # 3.e. Get the current migration state. Even thought we
                    # technically have it in-memory since we just wrote it, we
                    # want to reference the DB as the source of truth at all
                    # times.
                    continuation_token_map, total_chunks_migrated = (
                        get_vespa_visit_state(db_session)
                    )
                    # 3.e.1. Check if the migration is done.
                    if is_continuation_token_done_for_all_slices(
                        continuation_token_map
                    ):
                        task_logger.info(
                            f"OpenSearch migration COMPLETED for tenant {tenant_id}. Total chunks migrated: {total_chunks_migrated}."
                        )
                        mark_migration_completed_time_if_not_set_with_commit(db_session)
                        return True
                task_logger.debug(
                    f"Read the tenant migration record. Total chunks migrated: {total_chunks_migrated}. "
                    f"Continuation token map: {continuation_token_map}"
                )
    except Exception:
        traceback.print_exc()
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
        f"Total chunks errored this task: {total_chunks_errored_this_task}. "
        f"Elapsed: {time.monotonic() - task_start_time:.3f}s. "
        "Will resume from continuation token on next invocation."
    )

    return True
