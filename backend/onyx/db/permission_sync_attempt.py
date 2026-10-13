"""Permission sync attempt CRUD operations and utilities.

This module contains all CRUD operations for both DocPermissionSyncAttempt
and ExternalGroupPermissionSyncAttempt models, along with shared utilities.
"""

from datetime import datetime, timedelta
from typing import Any, cast

from sqlalchemy import ColumnElement, delete, func, or_, select, update
from sqlalchemy.engine.cursor import CursorResult
from sqlalchemy.orm import Session, joinedload

from onyx.configs.constants import DocumentSource
from onyx.db.connector_edit_requests import request_retry_delay
from onyx.db.enums import PermissionSyncStatus
from onyx.db.models import (
    Connector,
    ConnectorCredentialPair,
    DocPermissionSyncAttempt,
    ExternalGroupPermissionSyncAttempt,
)
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import fetch_ee_implementation_or_noop

logger = setup_logger()

# Enough consecutive failures to reach the longest retry delay.
_GROUP_SYNC_BACKOFF_LOOKBACK = 8

_FAILURE_STATUSES = (PermissionSyncStatus.FAILED, PermissionSyncStatus.CANCELED)

_AttemptModel = (
    type[DocPermissionSyncAttempt] | type[ExternalGroupPermissionSyncAttempt]
)


class PermissionSyncAttemptLostError(RuntimeError):
    """The attempt is no longer IN_PROGRESS, e.g. the reaper failed it after its
    lease expired. The worker that ran it must stop."""


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
        attempt.time_started = func.now()
        attempt.heartbeat_at = func.now()
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
    full_exception_trace: str | None = None,
    total_docs_synced: int = 0,
    docs_with_permission_errors: int = 0,
) -> None:
    """Mark a doc permission sync attempt as failed.

    ``full_exception_trace`` is optional so call sites that fail with a
    synthesized error message (e.g. fence missing, payload invalid) and
    have no live exception in scope can omit it. When the failure
    originates from an ``except`` block, callers should pass
    ``traceback.format_exc()`` so the full stack is persisted alongside
    the short ``error_message``.

    A sync that fails partway through keeps the work it already committed, so
    callers pass the counts they reached. These assign rather than accumulate:
    a failure raised after ``complete_doc_permission_sync_attempt`` has already
    committed would otherwise count the same documents twice.
    """
    try:
        attempt = db_session.execute(
            select(DocPermissionSyncAttempt)
            .where(DocPermissionSyncAttempt.id == attempt_id)
            .with_for_update()
        ).scalar_one()

        if attempt.status in _FAILURE_STATUSES:
            # The reaper or a cancel already closed it; keep that reason.
            db_session.commit()
            return

        if not attempt.time_started:
            attempt.time_started = func.now()
        attempt.status = PermissionSyncStatus.FAILED
        attempt.time_finished = func.now()
        attempt.error_message = error_message
        attempt.full_exception_trace = full_exception_trace
        attempt.total_docs_synced = total_docs_synced
        attempt.docs_with_permission_errors = docs_with_permission_errors
        db_session.commit()
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

        if attempt.status != PermissionSyncStatus.IN_PROGRESS:
            raise PermissionSyncAttemptLostError(
                f"Doc permission sync attempt {attempt_id} is {attempt.status}, not IN_PROGRESS"
            )

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

        attempt.time_finished = func.now()
        db_session.commit()
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


def get_external_group_sync_retry_after(
    cc_pair_id: int,
    db_session: Session,
) -> datetime | None:
    """The time before which the beat must not start the pair's group sync
    again, from its consecutive FAILED attempts. None when the latest finished
    attempt did not fail. A manual sync ignores this, and its success clears
    it."""
    attempts = get_recent_external_group_sync_attempts_for_cc_pair(
        cc_pair_id=cc_pair_id,
        limit=_GROUP_SYNC_BACKOFF_LOOKBACK,
        db_session=db_session,
    )
    failure_count = 0
    last_failed_at: datetime | None = None
    for attempt in attempts:
        if not attempt.status.is_terminal():
            continue
        if attempt.status != PermissionSyncStatus.FAILED:
            break
        failure_count += 1
        if last_failed_at is None:
            last_failed_at = attempt.time_finished or attempt.time_created

    if last_failed_at is None:
        return None
    return last_failed_at + request_retry_delay(failure_count)


def relevant_external_group_sync_attempts_filter(
    cc_pair_id: int, source: DocumentSource
) -> ColumnElement[bool]:
    """A pair's group sync attempts. A source whose group sync covers all its pairs
    logs each run against one pair, so this widens to every pair of that source.
    Two sites of one source therefore share one history."""
    is_agnostic: bool = fetch_ee_implementation_or_noop(
        "onyx.external_permissions.sync_params",
        "source_group_sync_is_cc_pair_agnostic",
        noop_return_value=False,
    )(source)
    if not is_agnostic:
        return (
            ExternalGroupPermissionSyncAttempt.connector_credential_pair_id
            == cc_pair_id
        )
    sibling_cc_pair_ids_stmt = (
        select(ConnectorCredentialPair.id)
        .join(ConnectorCredentialPair.connector)
        .where(Connector.source == source)
    )
    return ExternalGroupPermissionSyncAttempt.connector_credential_pair_id.in_(
        sibling_cc_pair_ids_stmt
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
        attempt.time_started = func.now()
        attempt.heartbeat_at = func.now()
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
    full_exception_trace: str | None = None,
) -> None:
    """Mark an external group sync attempt as failed.

    ``full_exception_trace`` is optional so call sites that fail with a
    synthesized error message (e.g. missing sync config) and have no
    live exception in scope can omit it. When the failure originates
    from an ``except`` block, callers should pass
    ``traceback.format_exc()`` so the full stack is persisted alongside
    the short ``error_message``.
    """
    try:
        attempt = db_session.execute(
            select(ExternalGroupPermissionSyncAttempt)
            .where(ExternalGroupPermissionSyncAttempt.id == attempt_id)
            .with_for_update()
        ).scalar_one()

        if attempt.status in _FAILURE_STATUSES:
            # The reaper or a cancel already closed it; keep that reason.
            db_session.commit()
            return

        if not attempt.time_started:
            attempt.time_started = func.now()
        attempt.status = PermissionSyncStatus.FAILED
        attempt.time_finished = func.now()
        attempt.error_message = error_message
        attempt.full_exception_trace = full_exception_trace
        db_session.commit()
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

        if attempt.status != PermissionSyncStatus.IN_PROGRESS:
            raise PermissionSyncAttemptLostError(
                f"External group sync attempt {attempt_id} is {attempt.status}, not IN_PROGRESS"
            )

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

        attempt.time_finished = func.now()
        db_session.commit()
        return attempt
    except Exception:
        db_session.rollback()
        logger.exception("complete_external_group_sync_attempt exceptioned.")
        raise


# =============================================================================
# LEASES
# =============================================================================


def _renew_lease(model: _AttemptModel, attempt_id: int, db_session: Session) -> bool:
    renewed = db_session.execute(
        update(model)
        .where(model.id == attempt_id)
        .where(model.status == PermissionSyncStatus.IN_PROGRESS)
        .values(heartbeat_at=func.now())
        .returning(model.id)
    ).first()
    db_session.commit()
    return renewed is not None


def _lock_if_owned(model: _AttemptModel, attempt_id: int, db_session: Session) -> None:
    owned = db_session.execute(
        select(model.id)
        .where(model.id == attempt_id)
        .where(model.status == PermissionSyncStatus.IN_PROGRESS)
        .with_for_update(read=True)
    ).first()
    if owned is None:
        raise PermissionSyncAttemptLostError(
            f"{model.__name__} {attempt_id} is no longer IN_PROGRESS"
        )


def lock_doc_permission_sync_attempt_if_owned(
    attempt_id: int, db_session: Session
) -> None:
    """Takes a share lock on a running attempt, or raises
    PermissionSyncAttemptLostError. Call it in the transaction of a sync write:
    the reaper cannot fail the attempt until that write commits, and a write
    after the reaper failed it is refused."""
    _lock_if_owned(DocPermissionSyncAttempt, attempt_id, db_session)


def lock_external_group_sync_attempt_if_owned(
    attempt_id: int, db_session: Session
) -> None:
    """Takes a share lock on a running attempt, or raises
    PermissionSyncAttemptLostError. Call it in the transaction of a sync write:
    the reaper cannot fail the attempt until that write commits, and a write
    after the reaper failed it is refused."""
    _lock_if_owned(ExternalGroupPermissionSyncAttempt, attempt_id, db_session)


def renew_doc_permission_sync_attempt_lease(
    attempt_id: int, db_session: Session
) -> bool:
    """Renews the lease of a running attempt. Returns False when the attempt is
    no longer IN_PROGRESS, which means the caller has lost it."""
    return _renew_lease(DocPermissionSyncAttempt, attempt_id, db_session)


def renew_external_group_sync_attempt_lease(
    attempt_id: int, db_session: Session
) -> bool:
    """Renews the lease of a running attempt. Returns False when the attempt is
    no longer IN_PROGRESS, which means the caller has lost it."""
    return _renew_lease(ExternalGroupPermissionSyncAttempt, attempt_id, db_session)


def _fail_expired_attempts(
    model: _AttemptModel,
    db_session: Session,
    lease_timeout: timedelta,
    not_started_timeout: timedelta,
) -> list[int]:
    now = func.now()
    last_alive = func.coalesce(model.heartbeat_at, model.time_started)
    failed_ids = list(
        db_session.execute(
            update(model)
            .where(
                or_(
                    (model.status == PermissionSyncStatus.IN_PROGRESS)
                    & (last_alive < now - lease_timeout),
                    (model.status == PermissionSyncStatus.NOT_STARTED)
                    & (model.time_created < now - not_started_timeout),
                )
            )
            .values(
                status=PermissionSyncStatus.FAILED,
                time_started=func.coalesce(model.time_started, now),
                time_finished=now,
                error_message=(
                    "The worker running this attempt stopped renewing its lease "
                    "(it crashed, restarted, or lost its task)"
                ),
            )
            .returning(model.id)
        ).scalars()
    )
    db_session.commit()
    return failed_ids


def fail_expired_doc_permission_sync_attempts(
    db_session: Session,
    lease_timeout: timedelta,
    not_started_timeout: timedelta,
) -> list[int]:
    """Fails IN_PROGRESS attempts whose lease expired and NOT_STARTED attempts
    that never started. Returns the IDs it failed."""
    return _fail_expired_attempts(
        DocPermissionSyncAttempt, db_session, lease_timeout, not_started_timeout
    )


def fail_expired_external_group_sync_attempts(
    db_session: Session,
    lease_timeout: timedelta,
    not_started_timeout: timedelta,
) -> list[int]:
    """Fails IN_PROGRESS attempts whose lease expired and NOT_STARTED attempts
    that never started. Returns the IDs it failed."""
    return _fail_expired_attempts(
        ExternalGroupPermissionSyncAttempt,
        db_session,
        lease_timeout,
        not_started_timeout,
    )


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
