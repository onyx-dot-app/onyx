"""Permission sync attempt CRUD operations and utilities.

This module contains all CRUD operations for both DocPermissionSyncAttempt
and ExternalGroupPermissionSyncAttempt models, along with shared utilities.
"""

from typing import Any
from typing import cast

from sqlalchemy import delete
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.engine.cursor import CursorResult
from sqlalchemy.orm import joinedload
from sqlalchemy.orm import Session

from onyx.db.enums import PermissionSyncStatus
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import DocPermissionSyncAttempt
from onyx.db.models import ExternalGroupPermissionSyncAttempt
from onyx.utils.logger import setup_logger
from onyx.utils.telemetry import optional_telemetry
from onyx.utils.telemetry import RecordType

logger = setup_logger()


# =============================================================================
# DOC PERMISSION SYNC ATTEMPT CRUD
# =============================================================================


def create_doc_permission_sync_attempt(
    connector_credential_pair_id: int,
    db_session: Session,
) -> int:
    """Create a new doc permission sync attempt.

    Args:
        connector_credential_pair_id: The ID of the connector credential pair
        db_session: The database session

    Returns:
        The ID of the created attempt
    """
    attempt = DocPermissionSyncAttempt(
        connector_credential_pair_id=connector_credential_pair_id,
        status=PermissionSyncStatus.NOT_STARTED,
    )
    db_session.add(attempt)
    db_session.commit()

    return attempt.id


def get_doc_permission_sync_attempt(
    db_session: Session,
    attempt_id: int,
    eager_load_connector: bool = False,
) -> DocPermissionSyncAttempt | None:
    """Get a doc permission sync attempt by ID.

    Args:
        db_session: The database session
        attempt_id: The ID of the attempt
        eager_load_connector: If True, eagerly loads the connector and cc_pair relationships

    Returns:
        The attempt if found, None otherwise
    """
    stmt = select(DocPermissionSyncAttempt).where(
        DocPermissionSyncAttempt.id == attempt_id
    )

    if eager_load_connector:
        stmt = stmt.options(
            joinedload(DocPermissionSyncAttempt.connector_credential_pair).joinedload(
                ConnectorCredentialPair.connector
            )
        )

    return db_session.scalars(stmt).first()


def get_latest_doc_permission_sync_attempt_for_cc_pair(
    db_session: Session,
    connector_credential_pair_id: int,
) -> DocPermissionSyncAttempt | None:
    """Get the latest doc permission sync attempt for a connector credential pair."""
    return db_session.execute(
        select(DocPermissionSyncAttempt)
        .where(
            DocPermissionSyncAttempt.connector_credential_pair_id
            == connector_credential_pair_id
        )
        .order_by(DocPermissionSyncAttempt.time_created.desc())
        .limit(1)
    ).scalar_one_or_none()


def get_recent_doc_permission_sync_attempts_for_cc_pair(
    cc_pair_id: int,
    limit: int,
    db_session: Session,
) -> list[DocPermissionSyncAttempt]:
    """Get recent doc permission sync attempts for a cc pair, most recent first."""
    return list(
        db_session.execute(
            select(DocPermissionSyncAttempt)
            .where(DocPermissionSyncAttempt.connector_credential_pair_id == cc_pair_id)
            .order_by(DocPermissionSyncAttempt.time_created.desc())
            .limit(limit)
        ).scalars()
    )


def mark_doc_permission_sync_attempt_in_progress(
    attempt_id: int,
    db_session: Session,
) -> DocPermissionSyncAttempt:
    """Mark a doc permission sync attempt as IN_PROGRESS.
    Locks the row during update."""
    try:
        attempt = db_session.execute(
            select(DocPermissionSyncAttempt)
            .where(DocPermissionSyncAttempt.id == attempt_id)
            .with_for_update()
        ).scalar_one()

        if attempt.status != PermissionSyncStatus.NOT_STARTED:
            raise RuntimeError(
                f"Doc permission sync attempt with ID '{attempt_id}' is not in NOT_STARTED status. "
                f"Current status is '{attempt.status}'."
            )

        attempt.status = PermissionSyncStatus.IN_PROGRESS
        attempt.time_started = func.now()  # type: ignore
        db_session.commit()
        return attempt
    except Exception:
        db_session.rollback()
        logger.exception("mark_doc_permission_sync_attempt_in_progress exceptioned.")
        raise


def mark_doc_permission_sync_attempt_failed(
    attempt_id: int,
    db_session: Session,
    error_message: str,
) -> None:
    """Mark a doc permission sync attempt as failed."""
    try:
        attempt = db_session.execute(
            select(DocPermissionSyncAttempt)
            .where(DocPermissionSyncAttempt.id == attempt_id)
            .with_for_update()
        ).scalar_one()

        if not attempt.time_started:
            attempt.time_started = func.now()  # type: ignore
        attempt.status = PermissionSyncStatus.FAILED
        attempt.time_finished = func.now()  # type: ignore
        attempt.error_message = error_message
        db_session.commit()

        # Add telemetry for permission sync attempt status change
        optional_telemetry(
            record_type=RecordType.PERMISSION_SYNC_COMPLETE,
            data={
                "doc_permission_sync_attempt_id": attempt_id,
                "status": PermissionSyncStatus.FAILED.value,
                "cc_pair_id": attempt.connector_credential_pair_id,
            },
        )
    except Exception:
        db_session.rollback()
        raise


def complete_doc_permission_sync_attempt(
    db_session: Session,
    attempt_id: int,
    total_docs_synced: int,
    docs_with_permission_errors: int,
) -> DocPermissionSyncAttempt:
    """Complete a doc permission sync attempt by updating progress and setting final status.

    This combines the progress update and final status marking into a single operation.
    If there were permission errors, the attempt is marked as COMPLETED_WITH_ERRORS,
    otherwise it's marked as SUCCESS.

    Args:
        db_session: The database session
        attempt_id: The ID of the attempt
        total_docs_synced: Total number of documents synced
        docs_with_permission_errors: Number of documents that had permission errors

    Returns:
        The completed attempt
    """
    try:
        attempt = db_session.execute(
            select(DocPermissionSyncAttempt)
            .where(DocPermissionSyncAttempt.id == attempt_id)
            .with_for_update()
        ).scalar_one()

        # Update progress counters
        attempt.total_docs_synced = (attempt.total_docs_synced or 0) + total_docs_synced
        attempt.docs_with_permission_errors = (
            attempt.docs_with_permission_errors or 0
        ) + docs_with_permission_errors

        # Set final status based on whether there were errors
        if docs_with_permission_errors > 0:
            attempt.status = PermissionSyncStatus.COMPLETED_WITH_ERRORS
        else:
            attempt.status = PermissionSyncStatus.SUCCESS

        attempt.time_finished = func.now()  # type: ignore
        db_session.commit()

        # Add telemetry
        optional_telemetry(
            record_type=RecordType.PERMISSION_SYNC_COMPLETE,
            data={
                "doc_permission_sync_attempt_id": attempt_id,
                "status": attempt.status.value,
                "cc_pair_id": attempt.connector_credential_pair_id,
            },
        )
        return attempt
    except Exception:
        db_session.rollback()
        logger.exception("complete_doc_permission_sync_attempt exceptioned.")
        raise


# =============================================================================
# EXTERNAL GROUP PERMISSION SYNC ATTEMPT CRUD
# =============================================================================


def create_external_group_sync_attempt(
    connector_credential_pair_id: int | None,
    db_session: Session,
) -> int:
    """Create a new external group sync attempt.

    Args:
        connector_credential_pair_id: The ID of the connector credential pair, or None for global syncs
        db_session: The database session

    Returns:
        The ID of the created attempt
    """
    attempt = ExternalGroupPermissionSyncAttempt(
        connector_credential_pair_id=connector_credential_pair_id,
        status=PermissionSyncStatus.NOT_STARTED,
    )
    db_session.add(attempt)
    db_session.commit()

    return attempt.id


def get_external_group_sync_attempt(
    db_session: Session,
    attempt_id: int,
    eager_load_connector: bool = False,
) -> ExternalGroupPermissionSyncAttempt | None:
    """Get an external group sync attempt by ID.

    Args:
        db_session: The database session
        attempt_id: The ID of the attempt
        eager_load_connector: If True, eagerly loads the connector and cc_pair relationships

    Returns:
        The attempt if found, None otherwise
    """
    stmt = select(ExternalGroupPermissionSyncAttempt).where(
        ExternalGroupPermissionSyncAttempt.id == attempt_id
    )

    if eager_load_connector:
        stmt = stmt.options(
            joinedload(
                ExternalGroupPermissionSyncAttempt.connector_credential_pair
            ).joinedload(ConnectorCredentialPair.connector)
        )

    return db_session.scalars(stmt).first()


def get_recent_external_group_sync_attempts_for_cc_pair(
    cc_pair_id: int | None,
    limit: int,
    db_session: Session,
) -> list[ExternalGroupPermissionSyncAttempt]:
    """Get recent external group sync attempts for a cc pair, most recent first.
    If cc_pair_id is None, gets global group sync attempts."""
    stmt = select(ExternalGroupPermissionSyncAttempt)

    if cc_pair_id is not None:
        stmt = stmt.where(
            ExternalGroupPermissionSyncAttempt.connector_credential_pair_id
            == cc_pair_id
        )
    else:
        stmt = stmt.where(
            ExternalGroupPermissionSyncAttempt.connector_credential_pair_id.is_(None)
        )

    return list(
        db_session.execute(
            stmt.order_by(ExternalGroupPermissionSyncAttempt.time_created.desc()).limit(
                limit
            )
        ).scalars()
    )


def mark_external_group_sync_attempt_in_progress(
    attempt_id: int,
    db_session: Session,
) -> ExternalGroupPermissionSyncAttempt:
    """Mark an external group sync attempt as IN_PROGRESS.
    Locks the row during update."""
    try:
        attempt = db_session.execute(
            select(ExternalGroupPermissionSyncAttempt)
            .where(ExternalGroupPermissionSyncAttempt.id == attempt_id)
            .with_for_update()
        ).scalar_one()

        if attempt.status != PermissionSyncStatus.NOT_STARTED:
            raise RuntimeError(
                f"External group sync attempt with ID '{attempt_id}' is not in NOT_STARTED status. "
                f"Current status is '{attempt.status}'."
            )

        attempt.status = PermissionSyncStatus.IN_PROGRESS
        attempt.time_started = func.now()  # type: ignore
        db_session.commit()
        return attempt
    except Exception:
        db_session.rollback()
        logger.exception("mark_external_group_sync_attempt_in_progress exceptioned.")
        raise


def mark_external_group_sync_attempt_failed(
    attempt_id: int,
    db_session: Session,
    error_message: str,
) -> None:
    """Mark an external group sync attempt as failed."""
    try:
        attempt = db_session.execute(
            select(ExternalGroupPermissionSyncAttempt)
            .where(ExternalGroupPermissionSyncAttempt.id == attempt_id)
            .with_for_update()
        ).scalar_one()

        if not attempt.time_started:
            attempt.time_started = func.now()  # type: ignore
        attempt.status = PermissionSyncStatus.FAILED
        attempt.time_finished = func.now()  # type: ignore
        attempt.error_message = error_message
        db_session.commit()

        # Add telemetry for permission sync attempt status change
        optional_telemetry(
            record_type=RecordType.PERMISSION_SYNC_COMPLETE,
            data={
                "external_group_sync_attempt_id": attempt_id,
                "status": PermissionSyncStatus.FAILED.value,
                "cc_pair_id": attempt.connector_credential_pair_id,
            },
        )
    except Exception:
        db_session.rollback()
        raise


def complete_external_group_sync_attempt(
    db_session: Session,
    attempt_id: int,
    total_users_processed: int,
    total_groups_processed: int,
    total_group_memberships_synced: int,
    errors_encountered: int = 0,
) -> ExternalGroupPermissionSyncAttempt:
    """Complete an external group sync attempt by updating progress and setting final status.

    This combines the progress update and final status marking into a single operation.
    If there were errors, the attempt is marked as COMPLETED_WITH_ERRORS,
    otherwise it's marked as SUCCESS.

    Args:
        db_session: The database session
        attempt_id: The ID of the attempt
        total_users_processed: Total users processed
        total_groups_processed: Total groups processed
        total_group_memberships_synced: Total group memberships synced
        errors_encountered: Number of errors encountered (determines if COMPLETED_WITH_ERRORS)

    Returns:
        The completed attempt
    """
    try:
        attempt = db_session.execute(
            select(ExternalGroupPermissionSyncAttempt)
            .where(ExternalGroupPermissionSyncAttempt.id == attempt_id)
            .with_for_update()
        ).scalar_one()

        # Update progress counters
        attempt.total_users_processed = (
            attempt.total_users_processed or 0
        ) + total_users_processed
        attempt.total_groups_processed = (
            attempt.total_groups_processed or 0
        ) + total_groups_processed
        attempt.total_group_memberships_synced = (
            attempt.total_group_memberships_synced or 0
        ) + total_group_memberships_synced

        # Set final status based on whether there were errors
        if errors_encountered > 0:
            attempt.status = PermissionSyncStatus.COMPLETED_WITH_ERRORS
        else:
            attempt.status = PermissionSyncStatus.SUCCESS

        attempt.time_finished = func.now()  # type: ignore
        db_session.commit()

        # Add telemetry
        optional_telemetry(
            record_type=RecordType.PERMISSION_SYNC_COMPLETE,
            data={
                "external_group_sync_attempt_id": attempt_id,
                "status": attempt.status.value,
                "cc_pair_id": attempt.connector_credential_pair_id,
            },
        )
        return attempt
    except Exception:
        db_session.rollback()
        logger.exception("complete_external_group_sync_attempt exceptioned.")
        raise


# =============================================================================
# DELETION FUNCTIONS
# =============================================================================


def delete_doc_permission_sync_attempts__no_commit(
    db_session: Session,
    cc_pair_id: int,
) -> int:
    """Delete all doc permission sync attempts for a connector credential pair.

    This does not commit the transaction. It should be used within an existing transaction.

    Args:
        db_session: The database session
        cc_pair_id: The connector credential pair ID

    Returns:
        The number of attempts deleted
    """
    stmt = delete(DocPermissionSyncAttempt).where(
        DocPermissionSyncAttempt.connector_credential_pair_id == cc_pair_id
    )
    result = cast(CursorResult[Any], db_session.execute(stmt))
    return result.rowcount or 0


def delete_external_group_permission_sync_attempts__no_commit(
    db_session: Session,
    cc_pair_id: int,
) -> int:
    """Delete all external group permission sync attempts for a connector credential pair.

    This does not commit the transaction. It should be used within an existing transaction.

    Args:
        db_session: The database session
        cc_pair_id: The connector credential pair ID

    Returns:
        The number of attempts deleted
    """
    stmt = delete(ExternalGroupPermissionSyncAttempt).where(
        ExternalGroupPermissionSyncAttempt.connector_credential_pair_id == cc_pair_id
    )
    result = cast(CursorResult[Any], db_session.execute(stmt))
    return result.rowcount or 0
