"""Database operations for OpenSearch migration tracking.

This module provides functions to track the progress of migrating documents
from Vespa to OpenSearch.
"""

from sqlalchemy import select
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from onyx.db.enums import OpenSearchDocumentMigrationStatus
from onyx.db.models import Document
from onyx.db.models import OpenSearchDocumentMigrationRecord
from onyx.db.models import OpenSearchTenantMigrationRecord
from onyx.utils.logger import setup_logger

logger = setup_logger()


TOTAL_ALLOWABLE_DOC_MIGRATION_ATTEMPTS_BEFORE_PERMANENT_FAILURE = 15
DEFAULT_BATCH_SIZE_OF_DOCUMENTS_TO_MIGRATE = 500
DEFAULT_BATCH_SIZE_OF_DOCUMENTS_TO_CHECK_FOR_MIGRATION = 2000


def get_paginated_document_batch(
    db_session: Session,
    limit: int = DEFAULT_BATCH_SIZE_OF_DOCUMENTS_TO_CHECK_FOR_MIGRATION,
    prev_ending_document_id: str | None = None,
) -> list[str]:
    """Gets a paginated batch of document IDs from the Document table.

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
    limit: int = DEFAULT_BATCH_SIZE_OF_DOCUMENTS_TO_MIGRATE,
) -> list[OpenSearchDocumentMigrationRecord]:
    """Gets records of documents that need to be migrated.

    Priority order:
     1. Documents with status PENDING, prioritizing those which were created
        first.
     2. Documents with status FAILED, prioritizing those with the fewest
        attempts first.
    """
    result: list[OpenSearchDocumentMigrationRecord] = []
    stmt = (
        select(OpenSearchDocumentMigrationRecord)
        .where(
            OpenSearchDocumentMigrationRecord.status
            == OpenSearchDocumentMigrationStatus.PENDING
        )
        .order_by(OpenSearchDocumentMigrationRecord.created_at.asc())
        .limit(limit)
    )
    result.extend(list(db_session.scalars(stmt).all()))
    remaining = limit - len(result)

    if remaining > 0:
        stmt = (
            select(OpenSearchDocumentMigrationRecord)
            .where(
                OpenSearchDocumentMigrationRecord.status
                == OpenSearchDocumentMigrationStatus.FAILED
            )
            .order_by(OpenSearchDocumentMigrationRecord.attempts_count.asc())
            .limit(remaining)
        )
        result.extend(list(db_session.scalars(stmt).all()))

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


def increment_num_times_observed_no_additional_docs_to_migrate_with_commit(
    db_session: Session,
) -> None:
    """Increments the number of times observed no additional docs to migrate.

    Tries to insert the singleton row on OpenSearchTenantMigrationRecord with a
    starting count, and if the row already exists, increments the count.

    Used to track when to stop the migration task.
    """
    stmt = (
        insert(OpenSearchTenantMigrationRecord)
        .values(num_times_observed_no_additional_docs_to_migrate=1)
        .on_conflict_do_update(
            index_elements=[text("(true)")],
            set_={
                "num_times_observed_no_additional_docs_to_migrate": (
                    OpenSearchTenantMigrationRecord.num_times_observed_no_additional_docs_to_migrate
                    + 1
                )
            },
        )
    )
    db_session.execute(stmt)
    db_session.commit()


def increment_num_times_observed_no_additional_docs_to_populate_migration_table_with_commit(
    db_session: Session,
) -> None:
    """
    Increments the number of times observed no additional docs to populate the
    migration table.

    Tries to insert the singleton row on OpenSearchTenantMigrationRecord with a
    starting count, and if the row already exists, increments the count.

    Used to track when to stop the migration check task.
    """
    stmt = (
        insert(OpenSearchTenantMigrationRecord)
        .values(num_times_observed_no_additional_docs_to_populate_migration_table=1)
        .on_conflict_do_update(
            index_elements=[text("(true)")],
            set_={
                "num_times_observed_no_additional_docs_to_populate_migration_table": (
                    OpenSearchTenantMigrationRecord.num_times_observed_no_additional_docs_to_populate_migration_table
                    + 1
                )
            },
        )
    )
    db_session.execute(stmt)
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
