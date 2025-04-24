from sqlalchemy import and_
from sqlalchemy import desc
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.orm import Session

from onyx.db.enums import SyncStatus
from onyx.db.enums import SyncType
from onyx.db.models import SyncRecord
from onyx.utils.logger import setup_logger

logger = setup_logger()


def insert_sync_record(
    db_session: Session,
    entity_id: int,
    sync_type: SyncType,
) -> SyncRecord:
    """Insert a new sync record into the database, cancelling any existing in-progress records.

    Args:
        db_session: The database session to use
        entity_id: The ID of the entity being synced (document set ID, user group ID, etc.)
        sync_type: The type of sync operation
    """
    # If an existing in-progress sync record exists, mark as cancelled
    existing_in_progress_sync_record = fetch_latest_sync_record(
        db_session, entity_id, sync_type, sync_status=SyncStatus.IN_PROGRESS
    )

    if existing_in_progress_sync_record is not None:
        logger.info(
            f"Cancelling existing in-progress sync record {existing_in_progress_sync_record.id} "
            f"for entity_id={entity_id} sync_type={sync_type}"
        )
        mark_sync_records_as_cancelled(db_session, entity_id, sync_type)

    return _create_sync_record(db_session, entity_id, sync_type)


def mark_sync_records_as_cancelled(
    db_session: Session,
    entity_id: int | None,
    sync_type: SyncType,
) -> None:
    stmt = (
        update(SyncRecord)
        .where(
            and_(
                SyncRecord.entity_id == entity_id,
                SyncRecord.sync_type == sync_type,
                SyncRecord.sync_status == SyncStatus.IN_PROGRESS,
            )
        )
        .values(sync_status=SyncStatus.CANCELED)
    )
    db_session.execute(stmt)
    db_session.commit()


def _create_sync_record(
    db_session: Session,
    entity_id: int | None,
    sync_type: SyncType,
) -> SyncRecord:
    """Create and insert a new sync record into the database."""
    sync_record = SyncRecord(
        entity_id=entity_id,
        sync_type=sync_type,
        sync_status=SyncStatus.IN_PROGRESS,
        num_docs_synced=0,
        sync_start_time=func.now(),
    )
    db_session.add(sync_record)
    db_session.commit()

    return sync_record


def fetch_latest_sync_record(
    db_session: Session,
    entity_id: int,
    sync_type: SyncType,
    sync_status: SyncStatus | None = None,
) -> SyncRecord | None:
    """Fetch the most recent sync record for a given entity ID and status.

    Args:
        db_session: The database session to use
        entity_id: The ID of the entity to fetch sync record for
        sync_type: The type of sync operation
    """
    stmt = (
        select(SyncRecord)
        .where(
            and_(
                SyncRecord.entity_id == entity_id,
                SyncRecord.sync_type == sync_type,
            )
        )
        .order_by(desc(SyncRecord.sync_start_time))
        .limit(1)
    )

    if sync_status is not None:
        stmt = stmt.where(SyncRecord.sync_status == sync_status)

    result = db_session.execute(stmt)
    return result.scalar_one_or_none()


def update_sync_record_status(
    db_session: Session,
    entity_id: int,
    sync_type: SyncType,
    sync_status: SyncStatus,
    num_docs_synced: int | None = None,
) -> None:
    """Update the status of a sync record.

    Args:
        db_session: The database session to use
        entity_id: The ID of the entity being synced
        sync_type: The type of sync operation
        sync_status: The new status to set
        num_docs_synced: Optional number of documents synced to update
    """
    sync_record = fetch_latest_sync_record(db_session, entity_id, sync_type)
    if sync_record is None:
        raise ValueError(
            f"No sync record found for entity_id={entity_id} sync_type={sync_type}"
        )

    sync_record.sync_status = sync_status
    if num_docs_synced is not None:
        sync_record.num_docs_synced = num_docs_synced

    if sync_status.is_terminal():
        sync_record.sync_end_time = func.now()  # type: ignore

    db_session.commit()


def cleanup_sync_records(
    db_session: Session, entity_id: int, sync_type: SyncType
) -> None:
    """Cleanup sync records for a given entity ID and sync type by marking them as failed."""
    stmt = (
        update(SyncRecord)
        .where(SyncRecord.entity_id == entity_id)
        .where(SyncRecord.sync_type == sync_type)
        .where(SyncRecord.sync_status == SyncStatus.IN_PROGRESS)
        .values(sync_status=SyncStatus.CANCELED, sync_end_time=func.now())
    )
    db_session.execute(stmt)
    db_session.commit()
