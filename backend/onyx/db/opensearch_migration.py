"""Database operations for OpenSearch migration tracking.

This module provides functions to track the progress of migrating documents
from Vespa to OpenSearch.
"""

import json
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.opensearch_migration.constants import (
    GET_VESPA_CHUNKS_SLICE_COUNT,
)
from onyx.configs.app_configs import (
    ENABLE_OPENSEARCH_RETRIEVAL_FOR_ONYX,
    ONYX_DISABLE_VESPA,
)
from onyx.db.models import (
    Document,
    OpenSearchTenantMigrationRecord,
)
from onyx.document_index.vespa.shared_utils.utils import (
    replace_invalid_doc_id_characters,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


def try_insert_opensearch_tenant_migration_record_with_commit(
    db_session: Session,
) -> None:
    """Tries to insert the singleton row on OpenSearchTenantMigrationRecord.

    Does nothing if the row already exists.
    """
    stmt = insert(OpenSearchTenantMigrationRecord).on_conflict_do_nothing(
        index_elements=[text("(true)")]
    )
    db_session.execute(stmt)
    db_session.commit()


def get_vespa_visit_state(
    db_session: Session,
) -> tuple[dict[int, str | None], int]:
    """Gets the current Vespa migration state from the tenant migration record.

    Requires the OpenSearchTenantMigrationRecord to exist.

    Returns:
        Tuple of (continuation_token_map, total_chunks_migrated).
    """
    record = db_session.query(OpenSearchTenantMigrationRecord).first()
    if record is None:
        raise RuntimeError("OpenSearchTenantMigrationRecord not found.")
    if record.vespa_visit_continuation_token is None:
        continuation_token_map: dict[int, str | None] = {
            slice_id: None for slice_id in range(GET_VESPA_CHUNKS_SLICE_COUNT)
        }
    else:
        json_loaded_continuation_token_map = json.loads(
            record.vespa_visit_continuation_token
        )
        continuation_token_map = {
            int(key): value for key, value in json_loaded_continuation_token_map.items()
        }
    return continuation_token_map, record.total_chunks_migrated


def update_vespa_visit_progress_with_commit(
    db_session: Session,
    continuation_token_map: dict[int, str | None],
    chunks_processed: int,
    chunks_errored: int,
    approx_chunk_count_in_vespa: int | None,
) -> None:
    """Updates the Vespa migration progress and commits.

    Requires the OpenSearchTenantMigrationRecord to exist.

    Args:
        db_session: SQLAlchemy session.
        continuation_token_map: The new continuation token map. None entry means
            the visit is complete for that slice.
        chunks_processed: Number of chunks processed in this batch (added to
            the running total).
        chunks_errored: Number of chunks errored in this batch (added to the
            running errored total).
        approx_chunk_count_in_vespa: Approximate number of chunks in Vespa. If
            None, the existing value is used.
    """
    record = db_session.query(OpenSearchTenantMigrationRecord).first()
    if record is None:
        raise RuntimeError("OpenSearchTenantMigrationRecord not found.")
    record.vespa_visit_continuation_token = json.dumps(continuation_token_map)
    record.total_chunks_migrated += chunks_processed
    record.total_chunks_errored += chunks_errored
    record.approx_chunk_count_in_vespa = (
        approx_chunk_count_in_vespa
        if approx_chunk_count_in_vespa is not None
        else record.approx_chunk_count_in_vespa
    )
    db_session.commit()


def mark_migration_completed_time_if_not_set_with_commit(
    db_session: Session,
) -> None:
    """Marks the migration completed time if not set.

    Requires the OpenSearchTenantMigrationRecord to exist.
    """
    record = db_session.query(OpenSearchTenantMigrationRecord).first()
    if record is None:
        raise RuntimeError("OpenSearchTenantMigrationRecord not found.")
    if record.migration_completed_at is not None:
        return
    record.migration_completed_at = datetime.now(timezone.utc)
    db_session.commit()


def is_migration_completed(db_session: Session) -> bool:
    """Returns True if the migration is completed.

    Can be run even if the migration record does not exist.
    """
    record = db_session.query(OpenSearchTenantMigrationRecord).first()
    return record is not None and record.migration_completed_at is not None


def build_sanitized_to_original_doc_id_mapping(
    db_session: Session,
) -> dict[str, str]:
    """Pre-computes a mapping of sanitized -> original document IDs.

    Only includes documents whose ID contains single quotes (the only character
    that gets sanitized by replace_invalid_doc_id_characters). For all other
    documents, sanitized == original and no mapping entry is needed.

    Scans over all documents.

    Checks if the sanitized ID already exists as a genuine separate document in
    the Document table. If so, raises as there is no way of resolving the
    conflict in the migration. The user will need to reindex.

    Args:
        db_session: SQLAlchemy session.

    Returns:
        Dict mapping sanitized_id -> original_id, only for documents where
        the IDs differ. Empty dict means no documents have single quotes
        in their IDs.
    """
    # Find all documents with single quotes in their ID.
    stmt = select(Document.id).where(Document.id.contains("'"))
    ids_with_quotes = list(db_session.scalars(stmt).all())

    result: dict[str, str] = {}
    for original_id in ids_with_quotes:
        sanitized_id = replace_invalid_doc_id_characters(original_id)
        if sanitized_id != original_id:
            result[sanitized_id] = original_id

    # See if there are any documents whose ID is a sanitized ID of another
    # document. If there is even one match, we cannot proceed.
    stmt = select(Document.id).where(Document.id.in_(result.keys()))
    ids_with_matches = list(db_session.scalars(stmt).all())
    if ids_with_matches:
        raise RuntimeError(
            f"Documents with IDs {ids_with_matches} have sanitized IDs that match other documents. "
            "This is not supported and the user will need to reindex."
        )

    return result


def get_opensearch_migration_state(
    db_session: Session,
) -> tuple[int, datetime | None, datetime | None, int | None]:
    """Returns the state of the Vespa to OpenSearch migration.

    If the tenant migration record is not found, returns defaults of 0, None,
    None, None.

    Args:
        db_session: SQLAlchemy session.

    Returns:
        Tuple of (total_chunks_migrated, created_at, migration_completed_at,
            approx_chunk_count_in_vespa).
    """
    record = db_session.query(OpenSearchTenantMigrationRecord).first()
    if record is None:
        return 0, None, None, None
    return (
        record.total_chunks_migrated,
        record.created_at,
        record.migration_completed_at,
        record.approx_chunk_count_in_vespa,
    )


def get_opensearch_retrieval_state(
    db_session: Session,
) -> bool:
    """Returns the state of the OpenSearch retrieval.

    If the tenant migration record is not found, defaults to
    ENABLE_OPENSEARCH_RETRIEVAL_FOR_ONYX.

    If ONYX_DISABLE_VESPA is True, always returns True.
    """
    if ONYX_DISABLE_VESPA:
        return True
    record = db_session.query(OpenSearchTenantMigrationRecord).first()
    if record is None:
        return ENABLE_OPENSEARCH_RETRIEVAL_FOR_ONYX
    return record.enable_opensearch_retrieval


def set_enable_opensearch_retrieval_with_commit(
    db_session: Session,
    enable: bool,
) -> None:
    """Sets the enable_opensearch_retrieval flag on the singleton record.

    Creates the record if it doesn't exist yet.
    """
    try_insert_opensearch_tenant_migration_record_with_commit(db_session)
    record = db_session.query(OpenSearchTenantMigrationRecord).first()
    if record is None:
        raise RuntimeError("OpenSearchTenantMigrationRecord not found.")
    record.enable_opensearch_retrieval = enable
    db_session.commit()
