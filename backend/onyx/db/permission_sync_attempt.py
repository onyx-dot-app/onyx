"""Permission sync attempt CRUD operations and utilities.

This module contains all CRUD operations for both DocPermissionSyncAttempt
and ExternalGroupPermissionSyncAttempt models, along with shared utilities.
"""

from sqlalchemy import func
from sqlalchemy import select
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
# SHARED UTILITIES
# =============================================================================


def _mark_doc_permission_sync_attempt_failed_impl(
    attempt_id: int,
    db_session: Session,
    error_message: str,
) -> None:
    """Mark a doc permission sync attempt as failed with error message."""
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


def _mark_external_group_sync_attempt_failed_impl(
    attempt_id: int,
    db_session: Session,
    error_message: str,
) -> None:
    """Mark an external group sync attempt as failed with error message."""
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


def _mark_doc_permission_sync_attempt_succeeded_impl(
    attempt_id: int,
    db_session: Session,
) -> DocPermissionSyncAttempt:
    """Mark a doc permission sync attempt as successful."""
    try:
        attempt = db_session.execute(
            select(DocPermissionSyncAttempt)
            .where(DocPermissionSyncAttempt.id == attempt_id)
            .with_for_update()
        ).scalar_one()

        attempt.status = PermissionSyncStatus.SUCCESS
        attempt.time_finished = func.now()  # type: ignore
        db_session.commit()

        # Add telemetry for permission sync attempt status change
        optional_telemetry(
            record_type=RecordType.PERMISSION_SYNC_COMPLETE,
            data={
                "doc_permission_sync_attempt_id": attempt_id,
                "status": PermissionSyncStatus.SUCCESS.value,
                "cc_pair_id": attempt.connector_credential_pair_id,
            },
        )
        return attempt
    except Exception:
        db_session.rollback()
        raise


def _mark_external_group_sync_attempt_succeeded_impl(
    attempt_id: int,
    db_session: Session,
) -> ExternalGroupPermissionSyncAttempt:
    """Mark an external group sync attempt as successful."""
    try:
        attempt = db_session.execute(
            select(ExternalGroupPermissionSyncAttempt)
            .where(ExternalGroupPermissionSyncAttempt.id == attempt_id)
            .with_for_update()
        ).scalar_one()

        attempt.status = PermissionSyncStatus.SUCCESS
        attempt.time_finished = func.now()  # type: ignore
        db_session.commit()

        # Add telemetry for permission sync attempt status change
        optional_telemetry(
            record_type=RecordType.PERMISSION_SYNC_COMPLETE,
            data={
                "external_group_sync_attempt_id": attempt_id,
                "status": PermissionSyncStatus.SUCCESS.value,
                "cc_pair_id": attempt.connector_credential_pair_id,
            },
        )
        return attempt
    except Exception:
        db_session.rollback()
        raise


def _mark_doc_permission_sync_attempt_completed_with_errors_impl(
    attempt_id: int,
    db_session: Session,
) -> DocPermissionSyncAttempt:
    """Mark a doc permission sync attempt as completed with errors."""
    try:
        attempt = db_session.execute(
            select(DocPermissionSyncAttempt)
            .where(DocPermissionSyncAttempt.id == attempt_id)
            .with_for_update()
        ).scalar_one()

        attempt.status = PermissionSyncStatus.COMPLETED_WITH_ERRORS
        attempt.time_finished = func.now()  # type: ignore
        # No error_message set - completed with errors is still a successful completion
        db_session.commit()

        # Add telemetry for permission sync attempt status change
        optional_telemetry(
            record_type=RecordType.PERMISSION_SYNC_COMPLETE,
            data={
                "doc_permission_sync_attempt_id": attempt_id,
                "status": PermissionSyncStatus.COMPLETED_WITH_ERRORS.value,
                "cc_pair_id": attempt.connector_credential_pair_id,
            },
        )
        return attempt
    except Exception:
        db_session.rollback()
        raise


def _mark_external_group_sync_attempt_completed_with_errors_impl(
    attempt_id: int,
    db_session: Session,
) -> ExternalGroupPermissionSyncAttempt:
    """Mark an external group sync attempt as completed with errors."""
    try:
        attempt = db_session.execute(
            select(ExternalGroupPermissionSyncAttempt)
            .where(ExternalGroupPermissionSyncAttempt.id == attempt_id)
            .with_for_update()
        ).scalar_one()

        attempt.status = PermissionSyncStatus.COMPLETED_WITH_ERRORS
        attempt.time_finished = func.now()  # type: ignore
        # No error_message set - completed with errors is still a successful completion
        db_session.commit()

        # Add telemetry for permission sync attempt status change
        optional_telemetry(
            record_type=RecordType.PERMISSION_SYNC_COMPLETE,
            data={
                "external_group_sync_attempt_id": attempt_id,
                "status": PermissionSyncStatus.COMPLETED_WITH_ERRORS.value,
                "cc_pair_id": attempt.connector_credential_pair_id,
            },
        )
        return attempt
    except Exception:
        db_session.rollback()
        raise


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
    eager_load_cc_pair: bool = False,
) -> DocPermissionSyncAttempt | None:
    """Get a doc permission sync attempt by ID."""
    stmt = select(DocPermissionSyncAttempt).where(
        DocPermissionSyncAttempt.id == attempt_id
    )

    if eager_load_cc_pair:
        stmt = stmt.options(
            joinedload(DocPermissionSyncAttempt.connector_credential_pair).joinedload(
                ConnectorCredentialPair.connector
            )
        )

    return db_session.scalars(stmt).first()


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


def mark_doc_permission_sync_attempt_succeeded(
    attempt_id: int,
    db_session: Session,
) -> DocPermissionSyncAttempt:
    """Mark a doc permission sync attempt as successful."""
    return _mark_doc_permission_sync_attempt_succeeded_impl(
        attempt_id,
        db_session,
    )


def mark_doc_permission_sync_attempt_completed_with_errors(
    attempt_id: int,
    db_session: Session,
) -> DocPermissionSyncAttempt:
    """Mark a doc permission sync attempt as completed with errors."""
    return _mark_doc_permission_sync_attempt_completed_with_errors_impl(
        attempt_id,
        db_session,
    )


def mark_doc_permission_sync_attempt_failed(
    attempt_id: int,
    db_session: Session,
    error_message: str,
) -> None:
    """Mark a doc permission sync attempt as failed."""
    _mark_doc_permission_sync_attempt_failed_impl(
        attempt_id,
        db_session,
        error_message,
    )


def update_doc_permission_sync_progress(
    db_session: Session,
    attempt_id: int,
    total_docs_synced: int,
    docs_with_permission_errors: int,
) -> None:
    """Update the progress of a doc permission sync attempt."""
    try:
        attempt = db_session.execute(
            select(DocPermissionSyncAttempt)
            .where(DocPermissionSyncAttempt.id == attempt_id)
            .with_for_update()
        ).scalar_one()

        attempt.total_docs_synced = (attempt.total_docs_synced or 0) + total_docs_synced
        attempt.docs_with_permission_errors = (
            attempt.docs_with_permission_errors or 0
        ) + docs_with_permission_errors
        db_session.commit()
    except Exception:
        db_session.rollback()
        logger.exception("update_doc_permission_sync_progress exceptioned.")
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
    eager_load_cc_pair: bool = False,
) -> ExternalGroupPermissionSyncAttempt | None:
    """Get an external group sync attempt by ID."""
    stmt = select(ExternalGroupPermissionSyncAttempt).where(
        ExternalGroupPermissionSyncAttempt.id == attempt_id
    )

    if eager_load_cc_pair:
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


def mark_external_group_sync_attempt_succeeded(
    attempt_id: int,
    db_session: Session,
) -> ExternalGroupPermissionSyncAttempt:
    """Mark an external group sync attempt as successful."""
    return _mark_external_group_sync_attempt_succeeded_impl(
        attempt_id,
        db_session,
    )


def mark_external_group_sync_attempt_completed_with_errors(
    attempt_id: int,
    db_session: Session,
) -> ExternalGroupPermissionSyncAttempt:
    """Mark an external group sync attempt as completed with errors."""
    return _mark_external_group_sync_attempt_completed_with_errors_impl(
        attempt_id,
        db_session,
    )


def mark_external_group_sync_attempt_failed(
    attempt_id: int,
    db_session: Session,
    error_message: str,
) -> None:
    """Mark an external group sync attempt as failed."""
    _mark_external_group_sync_attempt_failed_impl(
        attempt_id,
        db_session,
        error_message,
    )


def update_external_group_sync_progress(
    db_session: Session,
    attempt_id: int,
    total_users_processed: int,
    total_groups_processed: int,
    total_group_memberships_synced: int,
) -> None:
    """Update the progress of an external group sync attempt."""
    try:
        attempt = db_session.execute(
            select(ExternalGroupPermissionSyncAttempt)
            .where(ExternalGroupPermissionSyncAttempt.id == attempt_id)
            .with_for_update()
        ).scalar_one()

        attempt.total_users_processed = (
            attempt.total_users_processed or 0
        ) + total_users_processed
        attempt.total_groups_processed = (
            attempt.total_groups_processed or 0
        ) + total_groups_processed
        attempt.total_group_memberships_synced = (
            attempt.total_group_memberships_synced or 0
        ) + total_group_memberships_synced
        db_session.commit()
    except Exception:
        db_session.rollback()
        logger.exception("update_external_group_sync_progress exceptioned.")
        raise
