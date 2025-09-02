from collections.abc import Sequence
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import TypeVarTuple

from sqlalchemy import and_
from sqlalchemy import delete
from sqlalchemy import desc
from sqlalchemy import func
from sqlalchemy import Select
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.orm import joinedload
from sqlalchemy.orm import Session

from onyx.connectors.models import ConnectorFailure
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import IndexingStatus
from onyx.db.enums import IndexModelStatus
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import IndexAttempt
from onyx.db.models import IndexAttemptError
from onyx.db.models import SearchSettings
from onyx.server.documents.models import ConnectorCredentialPairIdentifier
from onyx.utils.logger import setup_logger
from onyx.utils.telemetry import optional_telemetry
from onyx.utils.telemetry import RecordType

# from sqlalchemy.sql.selectable import Select

# Comment out unused imports that cause mypy errors
# from onyx.auth.models import UserRole
# from onyx.configs.constants import MAX_LAST_VALID_CHECKPOINT_AGE_SECONDS
# from onyx.db.connector_credential_pair import ConnectorCredentialPairIdentifier
# from onyx.db.engine import async_query_for_dms

logger = setup_logger()


def get_last_attempt_for_cc_pair(
    cc_pair_id: int,
    search_settings_id: int,
    db_session: Session,
) -> IndexAttempt | None:
    return (
        db_session.query(IndexAttempt)
        .filter(
            IndexAttempt.connector_credential_pair_id == cc_pair_id,
            IndexAttempt.search_settings_id == search_settings_id,
        )
        .order_by(IndexAttempt.time_updated.desc())
        .first()
    )


def get_recent_completed_attempts_for_cc_pair(
    cc_pair_id: int,
    search_settings_id: int,
    limit: int,
    db_session: Session,
) -> list[IndexAttempt]:
    """Most recent to least recent."""
    return (
        db_session.query(IndexAttempt)
        .filter(
            IndexAttempt.connector_credential_pair_id == cc_pair_id,
            IndexAttempt.search_settings_id == search_settings_id,
            IndexAttempt.status.notin_(
                [IndexingStatus.NOT_STARTED, IndexingStatus.IN_PROGRESS]
            ),
        )
        .order_by(IndexAttempt.time_updated.desc())
        .limit(limit)
        .all()
    )


def get_recent_attempts_for_cc_pair(
    cc_pair_id: int,
    search_settings_id: int,
    limit: int,
    db_session: Session,
) -> list[IndexAttempt]:
    """Most recent to least recent."""
    return (
        db_session.query(IndexAttempt)
        .filter(
            IndexAttempt.connector_credential_pair_id == cc_pair_id,
            IndexAttempt.search_settings_id == search_settings_id,
        )
        .order_by(IndexAttempt.time_updated.desc())
        .limit(limit)
        .all()
    )


def get_index_attempt(
    db_session: Session,
    index_attempt_id: int,
    eager_load_cc_pair: bool = False,
    eager_load_search_settings: bool = False,
) -> IndexAttempt | None:
    stmt = select(IndexAttempt).where(IndexAttempt.id == index_attempt_id)
    if eager_load_cc_pair:
        stmt = stmt.options(
            joinedload(IndexAttempt.connector_credential_pair).joinedload(
                ConnectorCredentialPair.connector
            )
        )
        stmt = stmt.options(
            joinedload(IndexAttempt.connector_credential_pair).joinedload(
                ConnectorCredentialPair.credential
            )
        )
    if eager_load_search_settings:
        stmt = stmt.options(joinedload(IndexAttempt.search_settings))
    return db_session.scalars(stmt).first()


def count_error_rows_for_index_attempt(
    index_attempt_id: int,
    db_session: Session,
) -> int:
    return (
        db_session.query(IndexAttemptError)
        .filter(IndexAttemptError.index_attempt_id == index_attempt_id)
        .count()
    )


def create_index_attempt(
    connector_credential_pair_id: int,
    search_settings_id: int,
    db_session: Session,
    from_beginning: bool = False,
    celery_task_id: str | None = None,
) -> int:
    new_attempt = IndexAttempt(
        connector_credential_pair_id=connector_credential_pair_id,
        search_settings_id=search_settings_id,
        from_beginning=from_beginning,
        status=IndexingStatus.NOT_STARTED,
        celery_task_id=celery_task_id,
    )
    db_session.add(new_attempt)
    db_session.commit()

    return new_attempt.id


def delete_index_attempt(db_session: Session, index_attempt_id: int) -> None:
    index_attempt = get_index_attempt(db_session, index_attempt_id)
    if index_attempt:
        db_session.delete(index_attempt)
        db_session.commit()


def mock_successful_index_attempt(
    connector_credential_pair_id: int,
    search_settings_id: int,
    docs_indexed: int,
    db_session: Session,
) -> int:
    """Should not be used in any user triggered flows"""
    db_time = func.now()
    new_attempt = IndexAttempt(
        connector_credential_pair_id=connector_credential_pair_id,
        search_settings_id=search_settings_id,
        from_beginning=True,
        status=IndexingStatus.SUCCESS,
        total_docs_indexed=docs_indexed,
        new_docs_indexed=docs_indexed,
        # Need this to be some convincing random looking value and it can't be 0
        # or the indexing rate would calculate out to infinity
        time_started=db_time - timedelta(seconds=1.92),
        time_updated=db_time,
    )
    db_session.add(new_attempt)
    db_session.commit()

    return new_attempt.id


def get_in_progress_index_attempts(
    connector_id: int | None,
    db_session: Session,
) -> list[IndexAttempt]:
    stmt = select(IndexAttempt)
    if connector_id is not None:
        stmt = stmt.where(
            IndexAttempt.connector_credential_pair.has(connector_id=connector_id)
        )
    stmt = stmt.where(IndexAttempt.status == IndexingStatus.IN_PROGRESS)

    incomplete_attempts = db_session.scalars(stmt)
    return list(incomplete_attempts.all())


def get_all_index_attempts_by_status(
    status: IndexingStatus, db_session: Session
) -> list[IndexAttempt]:
    """Returns index attempts with the given status.
    Only recommend calling this with non-terminal states as the full list of
    terminal statuses may be quite large.

    Results are ordered by time_created (oldest to newest)."""
    stmt = select(IndexAttempt)
    stmt = stmt.where(IndexAttempt.status == status)
    stmt = stmt.order_by(IndexAttempt.time_created)
    new_attempts = db_session.scalars(stmt)
    return list(new_attempts.all())


def transition_attempt_to_in_progress(
    index_attempt_id: int,
    db_session: Session,
) -> IndexAttempt:
    """Locks the row when we try to update"""
    try:
        attempt = db_session.execute(
            select(IndexAttempt)
            .where(IndexAttempt.id == index_attempt_id)
            .with_for_update()
        ).scalar_one()

        if attempt is None:
            raise RuntimeError(
                f"Unable to find IndexAttempt for ID '{index_attempt_id}'"
            )

        if attempt.status != IndexingStatus.NOT_STARTED:
            raise RuntimeError(
                f"Indexing attempt with ID '{index_attempt_id}' is not in NOT_STARTED status. "
                f"Current status is '{attempt.status}'."
            )

        attempt.status = IndexingStatus.IN_PROGRESS
        attempt.time_started = attempt.time_started or func.now()  # type: ignore
        db_session.commit()
        return attempt
    except Exception:
        db_session.rollback()
        logger.exception("transition_attempt_to_in_progress exceptioned.")
        raise


def mark_attempt_in_progress(
    index_attempt: IndexAttempt,
    db_session: Session,
) -> None:
    try:
        attempt = db_session.execute(
            select(IndexAttempt)
            .where(IndexAttempt.id == index_attempt.id)
            .with_for_update()
        ).scalar_one()

        attempt.status = IndexingStatus.IN_PROGRESS
        attempt.time_started = index_attempt.time_started or func.now()  # type: ignore
        db_session.commit()

        # Add telemetry for index attempt status change
        optional_telemetry(
            record_type=RecordType.INDEX_ATTEMPT_STATUS,
            data={
                "index_attempt_id": index_attempt.id,
                "status": IndexingStatus.IN_PROGRESS.value,
                "cc_pair_id": index_attempt.connector_credential_pair_id,
            },
        )
    except Exception:
        db_session.rollback()
        raise


def mark_attempt_succeeded(
    index_attempt_id: int,
    db_session: Session,
) -> IndexAttempt:
    try:
        attempt = db_session.execute(
            select(IndexAttempt)
            .where(IndexAttempt.id == index_attempt_id)
            .with_for_update()
        ).scalar_one()

        attempt.status = IndexingStatus.SUCCESS
        attempt.celery_task_id = None
        db_session.commit()

        # Add telemetry for index attempt status change
        optional_telemetry(
            record_type=RecordType.INDEX_ATTEMPT_STATUS,
            data={
                "index_attempt_id": index_attempt_id,
                "status": IndexingStatus.SUCCESS.value,
                "cc_pair_id": attempt.connector_credential_pair_id,
            },
        )
        return attempt
    except Exception:
        db_session.rollback()
        raise


def mark_attempt_partially_succeeded(
    index_attempt_id: int,
    db_session: Session,
) -> IndexAttempt:
    try:
        attempt = db_session.execute(
            select(IndexAttempt)
            .where(IndexAttempt.id == index_attempt_id)
            .with_for_update()
        ).scalar_one()

        attempt.status = IndexingStatus.COMPLETED_WITH_ERRORS
        attempt.celery_task_id = None
        db_session.commit()

        # Add telemetry for index attempt status change
        optional_telemetry(
            record_type=RecordType.INDEX_ATTEMPT_STATUS,
            data={
                "index_attempt_id": index_attempt_id,
                "status": IndexingStatus.COMPLETED_WITH_ERRORS.value,
                "cc_pair_id": attempt.connector_credential_pair_id,
            },
        )
        return attempt
    except Exception:
        db_session.rollback()
        raise


def mark_attempt_canceled(
    index_attempt_id: int,
    db_session: Session,
    reason: str = "Unknown",
) -> None:
    try:
        attempt = db_session.execute(
            select(IndexAttempt)
            .where(IndexAttempt.id == index_attempt_id)
            .with_for_update()
        ).scalar_one()

        if not attempt.time_started:
            attempt.time_started = datetime.now(timezone.utc)
        attempt.status = IndexingStatus.CANCELED
        attempt.error_msg = reason
        db_session.commit()

        # Add telemetry for index attempt status change
        optional_telemetry(
            record_type=RecordType.INDEX_ATTEMPT_STATUS,
            data={
                "index_attempt_id": index_attempt_id,
                "status": IndexingStatus.CANCELED.value,
                "cc_pair_id": attempt.connector_credential_pair_id,
            },
        )
    except Exception:
        db_session.rollback()
        raise


def mark_attempt_failed(
    index_attempt_id: int,
    db_session: Session,
    failure_reason: str = "Unknown",
    full_exception_trace: str | None = None,
) -> None:
    try:
        attempt = db_session.execute(
            select(IndexAttempt)
            .where(IndexAttempt.id == index_attempt_id)
            .with_for_update()
        ).scalar_one()

        if not attempt.time_started:
            attempt.time_started = datetime.now(timezone.utc)
        attempt.status = IndexingStatus.FAILED
        attempt.error_msg = failure_reason
        attempt.full_exception_trace = full_exception_trace
        attempt.celery_task_id = None
        db_session.commit()

        # Add telemetry for index attempt status change
        optional_telemetry(
            record_type=RecordType.INDEX_ATTEMPT_STATUS,
            data={
                "index_attempt_id": index_attempt_id,
                "status": IndexingStatus.FAILED.value,
                "cc_pair_id": attempt.connector_credential_pair_id,
            },
        )
    except Exception:
        db_session.rollback()
        raise


def update_docs_indexed(
    db_session: Session,
    index_attempt_id: int,
    total_docs_indexed: int,
    new_docs_indexed: int,
    docs_removed_from_index: int,
) -> None:
    """Updates the docs_indexed and new_docs_indexed fields of an index attempt.
    Adds the given values to the current values in the db"""
    try:
        attempt = db_session.execute(
            select(IndexAttempt)
            .where(IndexAttempt.id == index_attempt_id)
            .with_for_update()  # Locks the row when we try to update
        ).scalar_one()

        attempt.total_docs_indexed = (
            attempt.total_docs_indexed or 0
        ) + total_docs_indexed
        attempt.new_docs_indexed = (attempt.new_docs_indexed or 0) + new_docs_indexed
        attempt.docs_removed_from_index = (
            attempt.docs_removed_from_index or 0
        ) + docs_removed_from_index
        db_session.commit()
    except Exception:
        db_session.rollback()
        logger.exception("update_docs_indexed exceptioned.")
        raise


def get_last_attempt(
    connector_id: int,
    credential_id: int,
    search_settings_id: int | None,
    db_session: Session,
) -> IndexAttempt | None:
    stmt = (
        select(IndexAttempt)
        .join(ConnectorCredentialPair)
        .where(
            ConnectorCredentialPair.connector_id == connector_id,
            ConnectorCredentialPair.credential_id == credential_id,
            IndexAttempt.search_settings_id == search_settings_id,
        )
    )

    # Note, the below is using time_created instead of time_updated
    stmt = stmt.order_by(desc(IndexAttempt.time_created))

    return db_session.execute(stmt).scalars().first()


def get_latest_index_attempts_by_status(
    secondary_index: bool,
    db_session: Session,
    status: IndexingStatus,
) -> Sequence[IndexAttempt]:
    """
    Retrieves the most recent index attempt with the specified status for each connector_credential_pair.
    Filters attempts based on the secondary_index flag to get either future or present index attempts.
    Returns a sequence of IndexAttempt objects, one for each unique connector_credential_pair.
    """
    latest_failed_attempts = (
        select(
            IndexAttempt.connector_credential_pair_id,
            func.max(IndexAttempt.id).label("max_failed_id"),
        )
        .join(SearchSettings, IndexAttempt.search_settings_id == SearchSettings.id)
        .where(
            SearchSettings.status
            == (
                IndexModelStatus.FUTURE if secondary_index else IndexModelStatus.PRESENT
            ),
            IndexAttempt.status == status,
        )
        .group_by(IndexAttempt.connector_credential_pair_id)
        .subquery()
    )

    stmt = select(IndexAttempt).join(
        latest_failed_attempts,
        (
            IndexAttempt.connector_credential_pair_id
            == latest_failed_attempts.c.connector_credential_pair_id
        )
        & (IndexAttempt.id == latest_failed_attempts.c.max_failed_id),
    )

    return db_session.execute(stmt).scalars().all()


T = TypeVarTuple("T")


def _add_only_finished_clause(stmt: Select[tuple[*T]]) -> Select[tuple[*T]]:
    return stmt.where(
        IndexAttempt.status.not_in(
            [IndexingStatus.NOT_STARTED, IndexingStatus.IN_PROGRESS]
        ),
    )


def get_latest_index_attempts(
    secondary_index: bool,
    db_session: Session,
    eager_load_cc_pair: bool = False,
    only_finished: bool = False,
) -> Sequence[IndexAttempt]:
    ids_stmt = select(
        IndexAttempt.connector_credential_pair_id,
        func.max(IndexAttempt.id).label("max_id"),
    ).join(SearchSettings, IndexAttempt.search_settings_id == SearchSettings.id)

    status = IndexModelStatus.FUTURE if secondary_index else IndexModelStatus.PRESENT
    ids_stmt = ids_stmt.where(SearchSettings.status == status)

    if only_finished:
        ids_stmt = _add_only_finished_clause(ids_stmt)

    ids_stmt = ids_stmt.group_by(IndexAttempt.connector_credential_pair_id)
    ids_subquery = ids_stmt.subquery()

    stmt = (
        select(IndexAttempt)
        .join(
            ids_subquery,
            IndexAttempt.connector_credential_pair_id
            == ids_subquery.c.connector_credential_pair_id,
        )
        .where(IndexAttempt.id == ids_subquery.c.max_id)
    )

    if only_finished:
        stmt = _add_only_finished_clause(stmt)

    if eager_load_cc_pair:
        stmt = stmt.options(
            joinedload(IndexAttempt.connector_credential_pair),
            joinedload(IndexAttempt.error_rows),
        )

    return db_session.execute(stmt).scalars().unique().all()


# For use with our thread-level parallelism utils. Note that any relationships
# you wish to use MUST be eagerly loaded, as the session will not be available
# after this function to allow lazy loading.
def get_latest_index_attempts_parallel(
    secondary_index: bool,
    eager_load_cc_pair: bool = False,
    only_finished: bool = False,
) -> Sequence[IndexAttempt]:
    with get_session_with_current_tenant() as db_session:
        return get_latest_index_attempts(
            secondary_index,
            db_session,
            eager_load_cc_pair,
            only_finished,
        )


def get_latest_index_attempt_for_cc_pair_id(
    db_session: Session,
    connector_credential_pair_id: int,
    secondary_index: bool,
    only_finished: bool = True,
) -> IndexAttempt | None:
    stmt = select(IndexAttempt)
    stmt = stmt.where(
        IndexAttempt.connector_credential_pair_id == connector_credential_pair_id,
    )
    if only_finished:
        stmt = _add_only_finished_clause(stmt)

    status = IndexModelStatus.FUTURE if secondary_index else IndexModelStatus.PRESENT
    stmt = stmt.join(SearchSettings).where(SearchSettings.status == status)
    stmt = stmt.order_by(desc(IndexAttempt.time_created))
    stmt = stmt.limit(1)
    return db_session.execute(stmt).scalar_one_or_none()


def count_index_attempts_for_cc_pair(
    db_session: Session,
    cc_pair_id: int,
    only_current: bool = True,
    disinclude_finished: bool = False,
) -> int:
    stmt = select(IndexAttempt).where(
        IndexAttempt.connector_credential_pair_id == cc_pair_id
    )
    if disinclude_finished:
        stmt = stmt.where(
            IndexAttempt.status.in_(
                [IndexingStatus.NOT_STARTED, IndexingStatus.IN_PROGRESS]
            )
        )
    if only_current:
        stmt = stmt.join(SearchSettings).where(
            SearchSettings.status == IndexModelStatus.PRESENT
        )
    # Count total items for pagination
    count_stmt = stmt.with_only_columns(func.count()).order_by(None)
    total_count = db_session.execute(count_stmt).scalar_one()
    return total_count


def get_paginated_index_attempts_for_cc_pair_id(
    db_session: Session,
    cc_pair_id: int,
    page: int,
    page_size: int,
    only_current: bool = True,
    disinclude_finished: bool = False,
) -> list[IndexAttempt]:
    stmt = select(IndexAttempt).where(
        IndexAttempt.connector_credential_pair_id == cc_pair_id
    )
    if disinclude_finished:
        stmt = stmt.where(
            IndexAttempt.status.in_(
                [IndexingStatus.NOT_STARTED, IndexingStatus.IN_PROGRESS]
            )
        )
    if only_current:
        stmt = stmt.join(SearchSettings).where(
            SearchSettings.status == IndexModelStatus.PRESENT
        )

    stmt = stmt.order_by(IndexAttempt.time_started.desc())

    # Apply pagination
    stmt = stmt.offset(page * page_size).limit(page_size)

    return list(db_session.execute(stmt).scalars().unique().all())


def get_index_attempts_for_cc_pair(
    db_session: Session,
    cc_pair_identifier: ConnectorCredentialPairIdentifier,
    only_current: bool = True,
    disinclude_finished: bool = False,
) -> Sequence[IndexAttempt]:
    stmt = (
        select(IndexAttempt)
        .join(ConnectorCredentialPair)
        .where(
            and_(
                ConnectorCredentialPair.connector_id == cc_pair_identifier.connector_id,
                ConnectorCredentialPair.credential_id
                == cc_pair_identifier.credential_id,
            )
        )
    )
    if disinclude_finished:
        stmt = stmt.where(
            IndexAttempt.status.in_(
                [IndexingStatus.NOT_STARTED, IndexingStatus.IN_PROGRESS]
            )
        )
    if only_current:
        stmt = stmt.join(SearchSettings).where(
            SearchSettings.status == IndexModelStatus.PRESENT
        )

    stmt = stmt.order_by(IndexAttempt.time_created.desc())
    return db_session.execute(stmt).scalars().all()


def delete_index_attempts(
    cc_pair_id: int,
    db_session: Session,
) -> None:
    # First, delete related entries in IndexAttemptErrors
    stmt_errors = delete(IndexAttemptError).where(
        IndexAttemptError.index_attempt_id.in_(
            select(IndexAttempt.id).where(
                IndexAttempt.connector_credential_pair_id == cc_pair_id
            )
        )
    )
    db_session.execute(stmt_errors)

    stmt = delete(IndexAttempt).where(
        IndexAttempt.connector_credential_pair_id == cc_pair_id,
    )

    db_session.execute(stmt)


def expire_index_attempts(
    search_settings_id: int,
    db_session: Session,
) -> None:
    not_started_query = (
        update(IndexAttempt)
        .where(IndexAttempt.search_settings_id == search_settings_id)
        .where(IndexAttempt.status == IndexingStatus.NOT_STARTED)
        .values(
            status=IndexingStatus.CANCELED,
            error_msg="Canceled, likely due to model swap",
        )
    )
    db_session.execute(not_started_query)

    update_query = (
        update(IndexAttempt)
        .where(IndexAttempt.search_settings_id == search_settings_id)
        .where(IndexAttempt.status != IndexingStatus.SUCCESS)
        .values(
            status=IndexingStatus.FAILED,
            error_msg="Canceled due to embedding model swap",
        )
    )
    db_session.execute(update_query)

    db_session.commit()


def cancel_indexing_attempts_for_ccpair(
    cc_pair_id: int,
    db_session: Session,
    include_secondary_index: bool = False,
) -> None:
    stmt = (
        update(IndexAttempt)
        .where(IndexAttempt.connector_credential_pair_id == cc_pair_id)
        .where(IndexAttempt.status == IndexingStatus.NOT_STARTED)
        .values(
            status=IndexingStatus.CANCELED,
            error_msg="Canceled by user",
            time_started=datetime.now(timezone.utc),
        )
    )

    if not include_secondary_index:
        subquery = select(SearchSettings.id).where(
            SearchSettings.status != IndexModelStatus.FUTURE
        )
        stmt = stmt.where(IndexAttempt.search_settings_id.in_(subquery))

    db_session.execute(stmt)


def cancel_indexing_attempts_past_model(
    db_session: Session,
) -> None:
    """Stops all indexing attempts that are in progress or not started for
    any embedding model that not present/future"""

    db_session.execute(
        update(IndexAttempt)
        .where(
            IndexAttempt.status.in_(
                [IndexingStatus.IN_PROGRESS, IndexingStatus.NOT_STARTED]
            ),
            IndexAttempt.search_settings_id == SearchSettings.id,
            SearchSettings.status == IndexModelStatus.PAST,
        )
        .values(status=IndexingStatus.FAILED)
    )


def cancel_indexing_attempts_for_search_settings(
    search_settings_id: int,
    db_session: Session,
) -> None:
    """Stops all indexing attempts that are in progress or not started for
    the specified search settings."""

    db_session.execute(
        update(IndexAttempt)
        .where(
            IndexAttempt.status.in_(
                [IndexingStatus.IN_PROGRESS, IndexingStatus.NOT_STARTED]
            ),
            IndexAttempt.search_settings_id == search_settings_id,
        )
        .values(status=IndexingStatus.FAILED)
    )


def count_unique_cc_pairs_with_successful_index_attempts(
    search_settings_id: int | None,
    db_session: Session,
) -> int:
    """Collect all of the Index Attempts that are successful and for the specified embedding model
    Then do distinct by connector_id and credential_id which is equivalent to the cc-pair. Finally,
    do a count to get the total number of unique cc-pairs with successful attempts"""
    unique_pairs_count = (
        db_session.query(IndexAttempt.connector_credential_pair_id)
        .join(ConnectorCredentialPair)
        .filter(
            IndexAttempt.search_settings_id == search_settings_id,
            IndexAttempt.status == IndexingStatus.SUCCESS,
        )
        .distinct()
        .count()
    )

    return unique_pairs_count


def create_index_attempt_error(
    index_attempt_id: int | None,
    connector_credential_pair_id: int,
    failure: ConnectorFailure,
    db_session: Session,
) -> int:
    new_error = IndexAttemptError(
        index_attempt_id=index_attempt_id,
        connector_credential_pair_id=connector_credential_pair_id,
        document_id=(
            failure.failed_document.document_id if failure.failed_document else None
        ),
        document_link=(
            failure.failed_document.document_link if failure.failed_document else None
        ),
        entity_id=(failure.failed_entity.entity_id if failure.failed_entity else None),
        failed_time_range_start=(
            failure.failed_entity.missed_time_range[0]
            if failure.failed_entity and failure.failed_entity.missed_time_range
            else None
        ),
        failed_time_range_end=(
            failure.failed_entity.missed_time_range[1]
            if failure.failed_entity and failure.failed_entity.missed_time_range
            else None
        ),
        failure_message=failure.failure_message,
        is_resolved=False,
    )
    db_session.add(new_error)
    db_session.commit()

    return new_error.id


def get_index_attempt_errors(
    index_attempt_id: int,
    db_session: Session,
) -> list[IndexAttemptError]:
    stmt = select(IndexAttemptError).where(
        IndexAttemptError.index_attempt_id == index_attempt_id
    )

    errors = db_session.scalars(stmt)
    return list(errors.all())


def count_index_attempt_errors_for_cc_pair(
    cc_pair_id: int,
    unresolved_only: bool,
    db_session: Session,
) -> int:
    stmt = (
        select(func.count())
        .select_from(IndexAttemptError)
        .where(IndexAttemptError.connector_credential_pair_id == cc_pair_id)
    )
    if unresolved_only:
        stmt = stmt.where(IndexAttemptError.is_resolved.is_(False))

    result = db_session.scalar(stmt)
    return 0 if result is None else result


def get_index_attempt_errors_for_cc_pair(
    cc_pair_id: int,
    unresolved_only: bool,
    db_session: Session,
    page: int | None = None,
    page_size: int | None = None,
) -> list[IndexAttemptError]:
    stmt = select(IndexAttemptError).where(
        IndexAttemptError.connector_credential_pair_id == cc_pair_id
    )
    if unresolved_only:
        stmt = stmt.where(IndexAttemptError.is_resolved.is_(False))

    # Order by most recent first
    stmt = stmt.order_by(desc(IndexAttemptError.time_created))

    if page is not None and page_size is not None:
        stmt = stmt.offset(page * page_size).limit(page_size)

    return list(db_session.scalars(stmt).all())
