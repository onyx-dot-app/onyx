from collections.abc import Sequence

from sqlalchemy import and_
from sqlalchemy import delete
from sqlalchemy import desc
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.orm import joinedload
from sqlalchemy.orm import Session

from danswer.connectors.models import Document
from danswer.connectors.models import DocumentErrorSummary
from danswer.db.models import IndexAttempt
from danswer.db.models import IndexAttemptError
from danswer.db.models import IndexingStatus
from danswer.db.models import IndexModelStatus
from danswer.db.models import SearchSettings
from danswer.server.documents.models import ConnectorCredentialPair
from danswer.server.documents.models import ConnectorCredentialPairIdentifier
from danswer.utils.logger import setup_logger
from danswer.utils.telemetry import optional_telemetry
from danswer.utils.telemetry import RecordType

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


def get_index_attempt(
    db_session: Session, index_attempt_id: int
) -> IndexAttempt | None:
    stmt = select(IndexAttempt).where(IndexAttempt.id == index_attempt_id)
    return db_session.scalars(stmt).first()


def create_index_attempt(
    connector_credential_pair_id: int,
    search_settings_id: int,
    db_session: Session,
    from_beginning: bool = False,
) -> int:
    new_attempt = IndexAttempt(
        connector_credential_pair_id=connector_credential_pair_id,
        search_settings_id=search_settings_id,
        from_beginning=from_beginning,
        status=IndexingStatus.NOT_STARTED,
    )
    db_session.add(new_attempt)
    db_session.commit()

    return new_attempt.id


def get_inprogress_index_attempts(
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


def get_not_started_index_attempts(db_session: Session) -> list[IndexAttempt]:
    """This eagerly loads the connector and credential so that the db_session can be expired
    before running long-living indexing jobs, which causes increasing memory usage.

    Results are ordered by time_created (oldest to newest)."""
    stmt = select(IndexAttempt)
    stmt = stmt.where(IndexAttempt.status == IndexingStatus.NOT_STARTED)
    stmt = stmt.order_by(IndexAttempt.time_created)
    stmt = stmt.options(
        joinedload(IndexAttempt.connector_credential_pair).joinedload(
            ConnectorCredentialPair.connector
        ),
        joinedload(IndexAttempt.connector_credential_pair).joinedload(
            ConnectorCredentialPair.credential
        ),
    )
    new_attempts = db_session.scalars(stmt)
    return list(new_attempts.all())


def mark_attempt_in_progress(
    index_attempt: IndexAttempt,
    db_session: Session,
) -> None:
    index_attempt.status = IndexingStatus.IN_PROGRESS
    index_attempt.time_started = index_attempt.time_started or func.now()  # type: ignore
    db_session.commit()


def mark_attempt_succeeded(
    index_attempt: IndexAttempt,
    db_session: Session,
) -> None:
    index_attempt.status = IndexingStatus.SUCCESS
    db_session.add(index_attempt)
    db_session.commit()


def mark_attempt_partially_succeeded(
    index_attempt: IndexAttempt,
    db_session: Session,
) -> None:
    index_attempt.status = IndexingStatus.COMPLETED_WITH_ERRORS
    db_session.add(index_attempt)
    db_session.commit()


def mark_attempt_failed(
    index_attempt: IndexAttempt,
    db_session: Session,
    failure_reason: str = "Unknown",
    full_exception_trace: str | None = None,
) -> None:
    index_attempt.status = IndexingStatus.FAILED
    index_attempt.error_msg = failure_reason
    index_attempt.full_exception_trace = full_exception_trace
    db_session.add(index_attempt)
    db_session.commit()

    source = index_attempt.connector_credential_pair.connector.source
    optional_telemetry(record_type=RecordType.FAILURE, data={"connector": source})


def update_docs_indexed(
    db_session: Session,
    index_attempt: IndexAttempt,
    total_docs_indexed: int,
    new_docs_indexed: int,
    docs_removed_from_index: int,
) -> None:
    index_attempt.total_docs_indexed = total_docs_indexed
    index_attempt.new_docs_indexed = new_docs_indexed
    index_attempt.docs_removed_from_index = docs_removed_from_index

    db_session.add(index_attempt)
    db_session.commit()


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


def get_latest_index_attempts(
    secondary_index: bool,
    db_session: Session,
) -> Sequence[IndexAttempt]:
    ids_stmt = select(
        IndexAttempt.connector_credential_pair_id,
        func.max(IndexAttempt.id).label("max_id"),
    ).join(SearchSettings, IndexAttempt.search_settings_id == SearchSettings.id)

    if secondary_index:
        ids_stmt = ids_stmt.where(SearchSettings.status == IndexModelStatus.FUTURE)
    else:
        ids_stmt = ids_stmt.where(SearchSettings.status == IndexModelStatus.PRESENT)

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

    return db_session.execute(stmt).scalars().all()


def count_index_attempts_for_connector(
    db_session: Session,
    connector_id: int,
    only_current: bool = True,
    disinclude_finished: bool = False,
) -> int:
    stmt = (
        select(IndexAttempt)
        .join(ConnectorCredentialPair)
        .where(ConnectorCredentialPair.connector_id == connector_id)
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
    connector_id: int,
    page: int,
    page_size: int,
    only_current: bool = True,
    disinclude_finished: bool = False,
) -> list[IndexAttempt]:
    stmt = (
        select(IndexAttempt)
        .join(ConnectorCredentialPair)
        .where(ConnectorCredentialPair.connector_id == connector_id)
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
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)

    return list(db_session.execute(stmt).scalars().all())


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
        stmt = stmt.where(
            IndexAttempt.status.not_in(
                [IndexingStatus.NOT_STARTED, IndexingStatus.IN_PROGRESS]
            ),
        )
    if secondary_index:
        stmt = stmt.join(SearchSettings).where(
            SearchSettings.status == IndexModelStatus.FUTURE
        )
    else:
        stmt = stmt.join(SearchSettings).where(
            SearchSettings.status == IndexModelStatus.PRESENT
        )
    stmt = stmt.order_by(desc(IndexAttempt.time_created))
    stmt = stmt.limit(1)
    return db_session.execute(stmt).scalar_one_or_none()


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
    delete_query = (
        delete(IndexAttempt)
        .where(IndexAttempt.search_settings_id == search_settings_id)
        .where(IndexAttempt.status == IndexingStatus.NOT_STARTED)
    )
    db_session.execute(delete_query)

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
        delete(IndexAttempt)
        .where(IndexAttempt.connector_credential_pair_id == cc_pair_id)
        .where(IndexAttempt.status == IndexingStatus.NOT_STARTED)
    )

    if not include_secondary_index:
        subquery = select(SearchSettings.id).where(
            SearchSettings.status != IndexModelStatus.FUTURE
        )
        stmt = stmt.where(IndexAttempt.search_settings_id.in_(subquery))

    db_session.execute(stmt)

    db_session.commit()


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

    db_session.commit()


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
    batch: int | None,
    docs: list[Document],
    exception_msg: str,
    exception_traceback: str,
    db_session: Session,
) -> int:
    doc_summaries = []
    for doc in docs:
        doc_summary = DocumentErrorSummary.from_document(doc)
        doc_summaries.append(doc_summary.to_dict())

    new_error = IndexAttemptError(
        index_attempt_id=index_attempt_id,
        batch=batch,
        doc_summaries=doc_summaries,
        error_msg=exception_msg,
        traceback=exception_traceback,
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
