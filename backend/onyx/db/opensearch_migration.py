"""Database operations for OpenSearch migration tracking.

This module provides functions to track the progress of migrating documents
from Vespa to OpenSearch.
"""

from datetime import datetime
from datetime import timezone

from sqlalchemy import select
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.opensearch_migration.constants import (
    TOTAL_ALLOWABLE_DOC_MIGRATION_ATTEMPTS_BEFORE_PERMANENT_FAILURE,
)
from onyx.db.enums import OpenSearchDocumentMigrationStatus
from onyx.db.models import Document
from onyx.db.models import OpenSearchDocumentMigrationRecord
from onyx.db.models import OpenSearchTenantMigrationRecord
from onyx.document_index.vespa.shared_utils.utils import (
    replace_invalid_doc_id_characters,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


def get_paginated_document_batch(
    db_session: Session,
    limit: int,
    prev_ending_document_id: str | None = None,
) -> list[str]:
    """Gets a paginated batch of document IDs from the Document table.

    We need some deterministic ordering to ensure that we don't miss any
    documents when paginating. This function uses the document ID. It is
    possible a document is inserted above a spot this function has already
    passed. In that event we assume that the document will be indexed into
    OpenSearch anyway and we don't need to migrate.
    TODO(andrei): Consider ordering on last_modified in addition to ID to better
    match get_opensearch_migration_records_needing_migration.

    Args:
        db_session: SQLAlchemy session.
        limit: Number of document IDs to fetch.
        prev_ending_document_id: Document ID to start after (for pagination). If
            None, returns the first batch of documents. If not None, this should
            be the last ordered ID which was fetched in a previous batch.
            Defaults to None.

    Returns:
        List of document IDs.
    """
    stmt = select(Document.id).order_by(Document.id.asc()).limit(limit)
    if prev_ending_document_id is not None:
        stmt = stmt.where(Document.id > prev_ending_document_id)
    return list(db_session.scalars(stmt).all())


def get_last_opensearch_migration_document_id(
    db_session: Session,
) -> str | None:
    """
    Gets the last document ID in the OpenSearchDocumentMigrationRecord table.

    Returns None if no records are found.
    """
    stmt = (
        select(OpenSearchDocumentMigrationRecord.document_id)
        .order_by(OpenSearchDocumentMigrationRecord.document_id.desc())
        .limit(1)
    )
    return db_session.scalars(stmt).first()


def create_opensearch_migration_records_with_commit(
    db_session: Session,
    document_ids: list[str],
) -> None:
    """Creates new OpenSearchDocumentMigrationRecord records.

    Silently skips any document IDs that already have records.
    """
    if not document_ids:
        return

    values = [
        {
            "document_id": document_id,
            "status": OpenSearchDocumentMigrationStatus.PENDING,
        }
        for document_id in document_ids
    ]

    stmt = insert(OpenSearchDocumentMigrationRecord).values(values)
    stmt = stmt.on_conflict_do_nothing(index_elements=["document_id"])

    db_session.execute(stmt)
    db_session.commit()


def get_opensearch_migration_records_needing_migration(
    db_session: Session,
    limit: int,
) -> list[OpenSearchDocumentMigrationRecord]:
    """Gets records of documents that need to be migrated.

    Properties:
    - First tries documents with status PENDING.
    - Of these, orders documents with the oldest last_modified to prioritize
      documents that were modified a long time ago, as they are presumed to be
      stable. This column is modified in many flows so is not a guarantee of the
      document having been indexed.
    - Then if there's room in the result, tries documents with status FAILED.
    - Of these, first orders documents on the least attempts_count so as to have
      a backoff for recently-failed docs. Then orders on last_modified as
      before.
    """
    result: list[OpenSearchDocumentMigrationRecord] = []

    # Step 1: Fetch as many PENDING status records as possible ordered by
    # last_modified (oldest first). last_modified lives on Document, so we join.
    stmt_pending = (
        select(OpenSearchDocumentMigrationRecord)
        .join(Document, OpenSearchDocumentMigrationRecord.document_id == Document.id)
        .where(
            OpenSearchDocumentMigrationRecord.status
            == OpenSearchDocumentMigrationStatus.PENDING
        )
        .order_by(Document.last_modified.asc())
        .limit(limit)
    )
    result.extend(list(db_session.scalars(stmt_pending).all()))
    remaining = limit - len(result)

    # Step 2: If more are needed, fetch records with status FAILED, ordered by
    # attempts_count (lowest first), then last_modified (oldest first).
    if remaining > 0:
        stmt_failed = (
            select(OpenSearchDocumentMigrationRecord)
            .join(
                Document,
                OpenSearchDocumentMigrationRecord.document_id == Document.id,
            )
            .where(
                OpenSearchDocumentMigrationRecord.status
                == OpenSearchDocumentMigrationStatus.FAILED
            )
            .order_by(
                OpenSearchDocumentMigrationRecord.attempts_count.asc(),
                Document.last_modified.asc(),
            )
            .limit(remaining)
        )
        result.extend(list(db_session.scalars(stmt_failed).all()))

    return result


def get_total_opensearch_migration_record_count(
    db_session: Session,
) -> int:
    """Gets the total number of OpenSearch migration records.

    Used to check whether every document has been tracked for migration.
    """
    return db_session.query(OpenSearchDocumentMigrationRecord).count()


def get_total_document_count(db_session: Session) -> int:
    """Gets the total number of documents.

    Used to check whether every document has been tracked for migration.
    """
    return db_session.query(Document).count()


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


def increment_num_times_observed_no_additional_docs_to_migrate_with_commit(
    db_session: Session,
) -> None:
    """Increments the number of times observed no additional docs to migrate.

    Requires the OpenSearchTenantMigrationRecord to exist.

    Used to track when to stop the migration task.
    """
    record = db_session.query(OpenSearchTenantMigrationRecord).first()
    if record is None:
        raise RuntimeError("OpenSearchTenantMigrationRecord not found.")
    record.num_times_observed_no_additional_docs_to_migrate += 1
    db_session.commit()


def increment_num_times_observed_no_additional_docs_to_populate_migration_table_with_commit(
    db_session: Session,
) -> None:
    """
    Increments the number of times observed no additional docs to populate the
    migration table.

    Requires the OpenSearchTenantMigrationRecord to exist.

    Used to track when to stop the migration check task.
    """
    record = db_session.query(OpenSearchTenantMigrationRecord).first()
    if record is None:
        raise RuntimeError("OpenSearchTenantMigrationRecord not found.")
    record.num_times_observed_no_additional_docs_to_populate_migration_table += 1
    db_session.commit()


def should_document_migration_be_permanently_failed(
    opensearch_document_migration_record: OpenSearchDocumentMigrationRecord,
) -> bool:
    return (
        opensearch_document_migration_record.status
        == OpenSearchDocumentMigrationStatus.PERMANENTLY_FAILED
        or (
            opensearch_document_migration_record.status
            == OpenSearchDocumentMigrationStatus.FAILED
            and opensearch_document_migration_record.attempts_count
            >= TOTAL_ALLOWABLE_DOC_MIGRATION_ATTEMPTS_BEFORE_PERMANENT_FAILURE
        )
    )


def get_vespa_visit_state(
    db_session: Session,
) -> tuple[str | None, int]:
    """Gets the current Vespa migration state from the tenant migration record.

    Requires the OpenSearchTenantMigrationRecord to exist.

    Returns:
        Tuple of (continuation_token, total_chunks_migrated). continuation_token
            is None if not started or completed.
    """
    record = db_session.query(OpenSearchTenantMigrationRecord).first()
    if record is None:
        raise RuntimeError("OpenSearchTenantMigrationRecord not found.")
    return (
        record.vespa_visit_continuation_token,
        record.total_chunks_migrated,
    )


def update_vespa_visit_progress_with_commit(
    db_session: Session,
    continuation_token: str | None,
    chunks_processed: int,
) -> None:
    """Updates the Vespa migration progress and commits.

    Requires the OpenSearchTenantMigrationRecord to exist.

    Args:
        db_session: SQLAlchemy session.
        continuation_token: The new continuation token. None means the visit
            is complete.
        chunks_processed: Number of chunks processed in this batch (added to
            the running total).
    """
    record = db_session.query(OpenSearchTenantMigrationRecord).first()
    if record is None:
        raise RuntimeError("OpenSearchTenantMigrationRecord not found.")
    record.vespa_visit_continuation_token = continuation_token
    record.total_chunks_migrated += chunks_processed
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
