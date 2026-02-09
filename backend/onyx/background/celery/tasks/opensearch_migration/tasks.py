"""Celery tasks for migrating documents from Vespa to OpenSearch."""

import time
import traceback
from datetime import datetime
from datetime import timezone
from typing import Any

from celery import shared_task
from celery import Task
from redis.lock import Lock as RedisLock

from onyx.background.celery.apps.app_base import task_logger
from onyx.background.celery.tasks.opensearch_migration.constants import (
    CHECK_FOR_DOCUMENTS_TASK_LOCK_BLOCKING_TIMEOUT_S,
)
from onyx.background.celery.tasks.opensearch_migration.constants import (
    CHECK_FOR_DOCUMENTS_TASK_LOCK_TIMEOUT_S,
)
from onyx.background.celery.tasks.opensearch_migration.constants import (
    CHECK_FOR_DOCUMENTS_TASK_SOFT_TIME_LIMIT_S,
)
from onyx.background.celery.tasks.opensearch_migration.constants import (
    CHECK_FOR_DOCUMENTS_TASK_TIME_LIMIT_S,
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
from onyx.configs.constants import OnyxCeleryTask
from onyx.configs.constants import OnyxRedisLocks
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import OpenSearchDocumentMigrationStatus
from onyx.db.opensearch_migration import create_opensearch_migration_records_with_commit
from onyx.db.opensearch_migration import get_last_opensearch_migration_document_id
from onyx.db.opensearch_migration import (
    get_opensearch_migration_records_needing_migration,
)
from onyx.db.opensearch_migration import get_paginated_document_batch
from onyx.db.opensearch_migration import (
    increment_num_times_observed_no_additional_docs_to_migrate_with_commit,
)
from onyx.db.opensearch_migration import (
    increment_num_times_observed_no_additional_docs_to_populate_migration_table_with_commit,
)
from onyx.db.opensearch_migration import should_document_migration_be_permanently_failed
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


def _migrate_single_document(
    document_id: str,
    opensearch_document_index: OpenSearchDocumentIndex,
    vespa_document_index: VespaDocumentIndex,
    tenant_state: TenantState,
) -> int:
    """Migrates a single document from Vespa to OpenSearch.

    Args:
        document_id: The ID of the document to migrate.
        opensearch_document_index: The OpenSearch document index to use.
        vespa_document_index: The Vespa document index to use.
        tenant_state: The tenant state to use.

    Raises:
        RuntimeError: If no chunks are found for the document in Vespa, or if
            the number of candidate chunks to migrate does not match the number
            of chunks in Vespa.

    Returns:
        The number of chunks migrated.
    """
    vespa_document_chunks: list[dict[str, Any]] = (
        vespa_document_index.get_raw_document_chunks(document_id=document_id)
    )
    if not vespa_document_chunks:
        raise RuntimeError(f"No chunks found for document {document_id} in Vespa.")

    opensearch_document_chunks: list[DocumentChunk] = (
        transform_vespa_chunks_to_opensearch_chunks(
            vespa_document_chunks, tenant_state, document_id
        )
    )
    if len(opensearch_document_chunks) != len(vespa_document_chunks):
        raise RuntimeError(
            f"Bug: Number of candidate chunks to migrate ({len(opensearch_document_chunks)}) does not match "
            f"number of chunks in Vespa ({len(vespa_document_chunks)})."
        )

    opensearch_document_index.index_raw_chunks(chunks=opensearch_document_chunks)

    return len(opensearch_document_chunks)


# shared_task allows this task to be shared across celery app instances.
@shared_task(
    name=OnyxCeleryTask.CHECK_FOR_DOCUMENTS_FOR_OPENSEARCH_MIGRATION_TASK,
    # Does not store the task's return value in the result backend.
    ignore_result=True,
    # WARNING: This is here just for rigor but since we use threads for Celery
    # this config is not respected and timeout logic must be implemented in the
    # task.
    soft_time_limit=CHECK_FOR_DOCUMENTS_TASK_SOFT_TIME_LIMIT_S,
    # WARNING: This is here just for rigor but since we use threads for Celery
    # this config is not respected and timeout logic must be implemented in the
    # task.
    time_limit=CHECK_FOR_DOCUMENTS_TASK_TIME_LIMIT_S,
    # Passed in self to the task to get task metadata.
    bind=True,
)
def check_for_documents_for_opensearch_migration_task(
    self: Task, *, tenant_id: str  # noqa: ARG001
) -> bool | None:
    """
    Periodic task to check for and add documents to the OpenSearch migration
    table.

    Should not execute meaningful logic at the same time as
    migrate_documents_from_vespa_to_opensearch_task.

    Effectively tries to populate as many migration records as possible within
    CHECK_FOR_DOCUMENTS_TASK_SOFT_TIME_LIMIT_S seconds. Does so in batches of
    1000 documents.

    Returns:
        None if OpenSearch migration is not enabled, or if the lock could not be
            acquired; effectively a no-op. True if the task completed
            successfully. False if the task failed.
    """
    if not ENABLE_OPENSEARCH_INDEXING_FOR_ONYX:
        task_logger.warning(
            "OpenSearch migration is not enabled, skipping check for documents for the OpenSearch migration task."
        )
        return None

    task_logger.info("Checking for documents for OpenSearch migration.")
    task_start_time = time.monotonic()
    r = get_redis_client()
    # Use a lock to prevent overlapping tasks. Only this task or
    # migrate_documents_from_vespa_to_opensearch_task can interact with the
    # OpenSearchMigration table at once.
    lock: RedisLock = r.lock(
        name=OnyxRedisLocks.OPENSEARCH_MIGRATION_BEAT_LOCK,
        # The maximum time the lock can be held for. Will automatically be
        # released after this time.
        timeout=CHECK_FOR_DOCUMENTS_TASK_LOCK_TIMEOUT_S,
        # .acquire will block until the lock is acquired.
        blocking=True,
        # Time to wait to acquire the lock.
        blocking_timeout=CHECK_FOR_DOCUMENTS_TASK_LOCK_BLOCKING_TIMEOUT_S,
    )
    if not lock.acquire():
        task_logger.warning(
            "The OpenSearch migration check task timed out waiting for the lock."
        )
        return None
    else:
        task_logger.info(
            f"Acquired the OpenSearch migration check lock. Took {time.monotonic() - task_start_time:.3f} seconds. "
            f"Token: {lock.local.token}"
        )

    num_documents_found_for_record_creation = 0
    try:
        # Double check that tenant info is correct.
        if tenant_id != get_current_tenant_id():
            err_str = (
                f"Tenant ID mismatch in the OpenSearch migration check task: "
                f"{tenant_id} != {get_current_tenant_id()}. This should never happen."
            )
            task_logger.error(err_str)
            return False
        while (
            time.monotonic() - task_start_time
            < CHECK_FOR_DOCUMENTS_TASK_SOFT_TIME_LIMIT_S
            and lock.owned()
        ):
            with get_session_with_current_tenant() as db_session:
                # For pagination, get the last ID we've inserted into
                # OpenSearchMigration.
                last_opensearch_migration_document_id = (
                    get_last_opensearch_migration_document_id(db_session)
                )
                # Now get the next batch of doc IDs starting after the last ID.
                # We'll do 1000 documents per transaction/timeout check.
                document_ids = get_paginated_document_batch(
                    db_session,
                    limit=1000,
                    prev_ending_document_id=last_opensearch_migration_document_id,
                )

                if not document_ids:
                    task_logger.info(
                        "No more documents to insert for OpenSearch migration."
                    )
                    increment_num_times_observed_no_additional_docs_to_populate_migration_table_with_commit(
                        db_session
                    )
                    # TODO(andrei): Once we've done this enough times and the
                    # number of documents matches the number of migration
                    # records, we can be done with this task and update
                    # document_migration_record_table_population_status.
                    return True

                # Create the migration records for the next batch of documents
                # with status PENDING.
                create_opensearch_migration_records_with_commit(
                    db_session, document_ids
                )
                num_documents_found_for_record_creation += len(document_ids)
    except Exception:
        task_logger.exception("Error in the OpenSearch migration check task.")
        return False
    finally:
        if lock.owned():
            lock.release()
        else:
            task_logger.warning(
                "The OpenSearch migration lock was not owned on completion of the check task."
            )

    task_logger.info(
        f"Finished checking for documents for OpenSearch migration. Found {num_documents_found_for_record_creation} documents "
        f"to create migration records for in {time.monotonic() - task_start_time:.3f} seconds. However, this may include "
        "documents for which there already exist records."
    )

    return True


# shared_task allows this task to be shared across celery app instances.
@shared_task(
    name=OnyxCeleryTask.MIGRATE_DOCUMENTS_FROM_VESPA_TO_OPENSEARCH_TASK,
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
def migrate_documents_from_vespa_to_opensearch_task(
    self: Task,  # noqa: ARG001
    *,
    tenant_id: str,
) -> bool | None:
    """Periodic task to migrate documents from Vespa to OpenSearch.

    Should not execute meaningful logic at the same time as
    check_for_documents_for_opensearch_migration_task.

    Effectively tries to migrate as many documents as possible within
    MIGRATION_TASK_SOFT_TIME_LIMIT_S seconds. Does so in batches of 5 documents.

    Returns:
        None if OpenSearch migration is not enabled, or if the lock could not be
            acquired; effectively a no-op. True if the task completed
            successfully. False if the task errored.
    """
    if not ENABLE_OPENSEARCH_INDEXING_FOR_ONYX:
        task_logger.warning(
            "OpenSearch migration is not enabled, skipping trying to migrate documents from Vespa to OpenSearch."
        )
        return None

    task_logger.info("Trying a migration batch from Vespa to OpenSearch.")
    task_start_time = time.monotonic()
    r = get_redis_client()
    # Use a lock to prevent overlapping tasks. Only this task or
    # check_for_documents_for_opensearch_migration_task can interact with the
    # OpenSearchMigration table at once.
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

    num_documents_migrated = 0
    num_chunks_migrated = 0
    num_documents_failed = 0
    try:
        # Double check that tenant info is correct.
        if tenant_id != get_current_tenant_id():
            err_str = (
                f"Tenant ID mismatch in the OpenSearch migration task: "
                f"{tenant_id} != {get_current_tenant_id()}. This should never happen."
            )
            task_logger.error(err_str)
            return False
        while (
            time.monotonic() - task_start_time < MIGRATION_TASK_SOFT_TIME_LIMIT_S
            and lock.owned()
        ):
            with get_session_with_current_tenant() as db_session:
                # We'll do 5 documents per transaction/timeout check.
                records_needing_migration = (
                    get_opensearch_migration_records_needing_migration(
                        db_session, limit=5
                    )
                )
                if not records_needing_migration:
                    task_logger.info(
                        "No documents found that need to be migrated from Vespa to OpenSearch."
                    )
                    increment_num_times_observed_no_additional_docs_to_migrate_with_commit(
                        db_session
                    )
                    # TODO(andrei): Once we've done this enough times and
                    # document_migration_record_table_population_status is done, we
                    # can be done with this task and update
                    # overall_document_migration_status accordingly. Note that this
                    # includes marking connectors as needing reindexing if some
                    # migrations failed.
                    return True

                search_settings = get_current_search_settings(db_session)
                tenant_state = TenantState(
                    tenant_id=tenant_id, multitenant=MULTI_TENANT
                )
                opensearch_document_index = OpenSearchDocumentIndex(
                    index_name=search_settings.index_name, tenant_state=tenant_state
                )
                vespa_document_index = VespaDocumentIndex(
                    index_name=search_settings.index_name,
                    tenant_state=tenant_state,
                    large_chunks_enabled=False,
                )

                for record in records_needing_migration:
                    try:
                        # If the Document's chunk count is not known, it was
                        # probably just indexed so fail here to give it a chance to
                        # sync. If in the rare event this Document has not been
                        # re-indexed in a very long time and is still under the
                        # "old" embedding/indexing logic where chunk count was never
                        # stored, we will eventually permanently fail and thus force
                        # a re-index of this doc, which is a desireable outcome.
                        if record.document.chunk_count is None:
                            raise RuntimeError(
                                f"Document {record.document_id} has no chunk count."
                            )

                        chunks_migrated = _migrate_single_document(
                            document_id=record.document_id,
                            opensearch_document_index=opensearch_document_index,
                            vespa_document_index=vespa_document_index,
                            tenant_state=tenant_state,
                        )

                        # If the number of chunks in Vespa is not in sync with the
                        # Document table for this doc let's not consider this
                        # completed and let's let a subsequent run take care of it.
                        if chunks_migrated != record.document.chunk_count:
                            raise RuntimeError(
                                f"Number of chunks migrated ({chunks_migrated}) does not match number of expected chunks "
                                f"in Vespa ({record.document.chunk_count}) for document {record.document_id}."
                            )

                        record.status = OpenSearchDocumentMigrationStatus.COMPLETED
                        num_documents_migrated += 1
                        num_chunks_migrated += chunks_migrated
                    except Exception:
                        record.status = OpenSearchDocumentMigrationStatus.FAILED
                        record.error_message = f"Attempt {record.attempts_count + 1}:\n{traceback.format_exc()}"
                        task_logger.exception(
                            f"Error migrating document {record.document_id} from Vespa to OpenSearch."
                        )
                        num_documents_failed += 1
                    finally:
                        record.attempts_count += 1
                        record.last_attempt_at = datetime.now(timezone.utc)
                        if should_document_migration_be_permanently_failed(record):
                            record.status = (
                                OpenSearchDocumentMigrationStatus.PERMANENTLY_FAILED
                            )
                            # TODO(andrei): Not necessarily here but if this happens
                            # we'll need to mark the connector as needing reindex.

                db_session.commit()
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
        f"Finished a migration batch from Vespa to OpenSearch. Migrated {num_chunks_migrated} chunks "
        f"from {num_documents_migrated} documents in {time.monotonic() - task_start_time:.3f} seconds. "
        f"Failed to migrate {num_documents_failed} documents."
    )

    return True
