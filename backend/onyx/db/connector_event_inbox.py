"""Reads and writes for `connector_event_inbox`."""

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    BigInteger,
    ColumnElement,
    and_,
    any_,
    bindparam,
    case,
    func,
    or_,
    select,
    update,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.event_models import ParsedEvent
from onyx.connectors.models import InputType
from onyx.db.enums import (
    ConnectorCredentialPairStatus,
    ConnectorEventStatus,
    IndexingStatus,
)
from onyx.db.models import (
    Connector,
    ConnectorCredentialPair,
    ConnectorEventInbox,
    IndexAttempt,
    IndexAttemptError,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

# A network fetch in a handler can fail for a reason the next run will not see.
MAX_EVENT_ATTEMPTS = 5
_RETRY_BACKOFF_SECONDS = 60

_MAX_ERROR_CHARS = 2000

# First key of the two-key advisory lock that serializes one pair's claims.
_CLAIM_LOCK_NAMESPACE = 7_310_142


def record_events(
    db_session: Session,
    cc_pair_id: int,
    source: DocumentSource,
    events: Sequence[ParsedEvent],
) -> list[int]:
    """Store events for one pair, skipping redeliveries. Returns the ids of
    the new rows. Does not commit."""
    if not events:
        return []

    rows = [
        {
            ConnectorEventInbox.connector_credential_pair_id: cc_pair_id,
            ConnectorEventInbox.source: source,
            ConnectorEventInbox.document_id: event.document_id,
            ConnectorEventInbox.event_type: event.event_type,
            ConnectorEventInbox.event_key: event.resolved_event_key(),
            ConnectorEventInbox.file_id: event.file_id,
            ConnectorEventInbox.payload: event.payload,
            ConnectorEventInbox.occurred_at: event.occurred_at,
            ConnectorEventInbox.status: ConnectorEventStatus.PENDING,
        }
        for event in events
    ]

    stmt = (
        insert(ConnectorEventInbox)
        .values(rows)
        .on_conflict_do_nothing(
            constraint="uq_connector_event_inbox_pair_event_key",
        )
        .returning(ConnectorEventInbox.id)
    )
    inserted = list(db_session.scalars(stmt))

    duplicates = len(rows) - len(inserted)
    if duplicates:
        logger.info(
            "Skipped %s duplicate event(s) for cc_pair %s", duplicates, cc_pair_id
        )
    return inserted


def get_event_by_key(
    db_session: Session, cc_pair_id: int, event_key: str
) -> ConnectorEventInbox | None:
    """`event_key` is `ParsedEvent.resolved_event_key()`, not a raw delivery
    id."""
    return db_session.scalars(
        select(ConnectorEventInbox).where(
            ConnectorEventInbox.connector_credential_pair_id == cc_pair_id,
            ConnectorEventInbox.event_key == event_key,
        )
    ).one_or_none()


def count_events_by_status(
    db_session: Session, cc_pair_id: int
) -> dict[ConnectorEventStatus, int]:
    """Backlog for one pair, keyed by status. Absent statuses are omitted."""
    rows = (
        db_session.execute(
            select(ConnectorEventInbox.status, func.count())
            .where(ConnectorEventInbox.connector_credential_pair_id == cc_pair_id)
            .group_by(ConnectorEventInbox.status)
        )
        .tuples()
        .all()
    )
    return dict(rows)


def get_pending_events(
    db_session: Session, cc_pair_id: int, limit: int
) -> list[ConnectorEventInbox]:
    """Pending rows for one pair, oldest first. Takes no lock."""
    return list(
        db_session.scalars(
            select(ConnectorEventInbox)
            .where(
                ConnectorEventInbox.connector_credential_pair_id == cc_pair_id,
                ConnectorEventInbox.status == ConnectorEventStatus.PENDING,
                ConnectorEventInbox.available_at <= func.now(),
            )
            .order_by(ConnectorEventInbox.id)
            .limit(limit)
        )
    )


def superseded_by_newer_events(
    db_session: Session,
    cc_pair_id: int,
    events: Sequence[ConnectorEventInbox],
    claimed_ids: Sequence[int],
) -> set[int]:
    """Ids of these events that a change taken by an earlier claim overtakes.
    `claimed_ids` is every row of the current claim, which does not count.

    Uses the same order as a batch: event time, then id, when every taken row
    for the document has a time; otherwise arrival order.
    """
    documents = {event.document_id for event in events}
    if not documents:
        return set()

    taken = (
        ConnectorEventInbox.connector_credential_pair_id == cc_pair_id,
        ConnectorEventInbox.document_id.in_(documents),
        ConnectorEventInbox.status.in_(
            [ConnectorEventStatus.IN_PROGRESS, ConnectorEventStatus.COMPLETED]
        ),
        ~_id_in(claimed_ids),
    )
    summary = {
        row.document_id: row
        for row in db_session.execute(
            select(
                ConnectorEventInbox.document_id,
                func.max(ConnectorEventInbox.id).label("latest_id"),
                func.count()
                .filter(ConnectorEventInbox.occurred_at.is_(None))
                .label("undated"),
            )
            .where(*taken)
            .group_by(ConnectorEventInbox.document_id)
        )
    }
    newest_dated = {
        row.document_id: (row.occurred_at, row.id)
        for row in db_session.execute(
            select(
                ConnectorEventInbox.document_id,
                ConnectorEventInbox.occurred_at,
                ConnectorEventInbox.id,
            )
            .where(*taken, ConnectorEventInbox.occurred_at.is_not(None))
            .distinct(ConnectorEventInbox.document_id)
            .order_by(
                ConnectorEventInbox.document_id,
                ConnectorEventInbox.occurred_at.desc(),
                ConnectorEventInbox.id.desc(),
            )
        )
    }

    superseded: set[int] = set()
    for event in events:
        row = summary.get(event.document_id)
        if row is None:
            continue
        if event.occurred_at is not None and not row.undated:
            if newest_dated[event.document_id] > (event.occurred_at, event.id):
                superseded.add(event.id)
        elif row.latest_id > event.id:
            superseded.add(event.id)
    return superseded


def claim_events(
    db_session: Session,
    cc_pair_id: int,
    index_attempt_id: int,
    limit: int,
) -> tuple[list[ConnectorEventInbox], list[int]]:
    """Claim the due rows of the documents among the first `limit` due rows,
    so one document is never split across batches or attempts.

    Returns each claimed document's winning change and the ids of every row
    claimed. Only the winners are loaded, so a document with a long backlog
    costs one row in memory. The winner is the newest by event time when
    every change has one, else the latest to arrive.

    Claims for one pair are serialized until the caller commits. Marks each
    row IN_PROGRESS and stamps the attempt, which later settles it.
    """
    db_session.execute(
        select(func.pg_advisory_xact_lock(_CLAIM_LOCK_NAMESPACE, cc_pair_id))
    )
    due = (
        ConnectorEventInbox.connector_credential_pair_id == cc_pair_id,
        ConnectorEventInbox.status == ConnectorEventStatus.PENDING,
        ConnectorEventInbox.available_at <= func.now(),
    )
    documents = set(
        db_session.scalars(
            select(ConnectorEventInbox.document_id)
            .where(*due)
            .order_by(ConnectorEventInbox.id)
            .limit(limit)
        )
    )
    if not documents:
        return [], []

    claimed_ids = list(
        db_session.scalars(
            update(ConnectorEventInbox)
            .where(*due, ConnectorEventInbox.document_id.in_(documents))
            .values(
                status=ConnectorEventStatus.IN_PROGRESS,
                index_attempt_id=index_attempt_id,
                attempt_count=ConnectorEventInbox.attempt_count + 1,
            )
            .returning(ConnectorEventInbox.id)
        )
    )

    claimed = (
        select(
            ConnectorEventInbox.id,
            ConnectorEventInbox.document_id,
            ConnectorEventInbox.occurred_at,
            func.bool_and(ConnectorEventInbox.occurred_at.is_not(None))
            .over(partition_by=ConnectorEventInbox.document_id)
            .label("all_dated"),
        )
        .where(_id_in(claimed_ids))
        .subquery()
    )
    ranked = select(
        claimed.c.id,
        func.row_number()
        .over(
            partition_by=claimed.c.document_id,
            order_by=(
                case((claimed.c.all_dated, claimed.c.occurred_at)).desc().nulls_last(),
                claimed.c.id.desc(),
            ),
        )
        .label("rank"),
    ).subquery()
    winners = list(
        db_session.scalars(
            select(ConnectorEventInbox)
            .where(
                ConnectorEventInbox.id.in_(
                    select(ranked.c.id).where(ranked.c.rank == 1)
                )
            )
            .order_by(ConnectorEventInbox.id)
        )
    )
    return winners, claimed_ids


def _id_in(ids: Sequence[int]) -> ColumnElement[bool]:
    """`id = ANY(:ids)`: one array parameter, however many ids."""
    return ConnectorEventInbox.id == any_(
        bindparam("ids", list(ids), type_=postgresql.ARRAY(BigInteger))
    )


def mark_events_completed(db_session: Session, event_ids: Sequence[int]) -> None:
    """Settle rows whose attempt indexed them. Does not commit."""
    if not event_ids:
        return
    db_session.execute(
        update(ConnectorEventInbox)
        .where(ConnectorEventInbox.id.in_(event_ids))
        .values(
            status=ConnectorEventStatus.COMPLETED,
            processed_at=func.now(),
            last_error=None,
        )
    )


def release_events_to_pending(
    db_session: Session, event_ids: Sequence[int], error: str | None = None
) -> None:
    """Return claimed rows to the queue, keeping `attempt_count`. Does not
    commit."""
    if not event_ids:
        return
    db_session.execute(
        update(ConnectorEventInbox)
        .where(ConnectorEventInbox.id.in_(event_ids))
        .values(
            status=ConnectorEventStatus.PENDING,
            index_attempt_id=None,
            last_error=error,
        )
    )


def retry_or_fail_events(
    db_session: Session,
    failures: Sequence[tuple[int, str]],
    max_attempts: int = MAX_EVENT_ATTEMPTS,
) -> None:
    """Return each row to the queue with backoff, or fail it after
    `max_attempts` tries. Does not commit."""
    if not failures:
        return

    now = datetime.now(timezone.utc)
    errors = dict(failures)
    rows = db_session.scalars(
        select(ConnectorEventInbox).where(ConnectorEventInbox.id.in_(errors))
    ).all()
    for row in rows:
        row.last_error = errors[row.id][:_MAX_ERROR_CHARS]
        if row.attempt_count < max_attempts:
            row.status = ConnectorEventStatus.PENDING
            row.index_attempt_id = None
            row.available_at = now + timedelta(
                seconds=_RETRY_BACKOFF_SECONDS * row.attempt_count
            )
        else:
            row.status = ConnectorEventStatus.FAILED
            row.processed_at = now


def mark_events_failed(
    db_session: Session, failures: Sequence[tuple[int, str]]
) -> None:
    """Fail rows for good, for a payload no retry can fix. Does not commit."""
    if not failures:
        return
    now = datetime.now(timezone.utc)
    db_session.execute(
        update(ConnectorEventInbox),
        [
            {
                "id": event_id,
                "status": ConnectorEventStatus.FAILED,
                "processed_at": now,
                "last_error": error[:_MAX_ERROR_CHARS],
            }
            for event_id, error in failures
        ],
    )


def settle_events_from_finished_attempts(
    db_session: Session, cc_pair_id: int
) -> tuple[int, int]:
    """Settle claimed rows on their attempt's outcome.

    Rows of a successful attempt complete. A COMPLETED_WITH_ERRORS attempt
    completes the rows whose documents stored, and retries the rest with the
    usual attempt limit and backoff, so one bad document cannot loop the
    pair. Rows of an attempt that ended otherwise, or no longer exists, go
    back to the queue.

    The run cannot settle its own rows, because the runner stores documents
    after the generator returns. Returns (completed, released). Does not
    commit.
    """
    # Skip what another sweep holds, so two sweeps never release one claim.
    claimed = (
        select(
            ConnectorEventInbox.id,
            ConnectorEventInbox.document_id,
            IndexAttempt.id,
            IndexAttempt.status,
        )
        .outerjoin(
            IndexAttempt, ConnectorEventInbox.index_attempt_id == IndexAttempt.id
        )
        .where(
            ConnectorEventInbox.connector_credential_pair_id == cc_pair_id,
            ConnectorEventInbox.status == ConnectorEventStatus.IN_PROGRESS,
        )
        .with_for_update(skip_locked=True, of=ConnectorEventInbox)
    )
    rows = db_session.execute(claimed).tuples().all()

    partial_attempts = {
        attempt_id
        for _, _, attempt_id, status in rows
        if status == IndexingStatus.COMPLETED_WITH_ERRORS
    }
    failed_documents = _failed_documents(db_session, partial_attempts)

    to_complete: list[int] = []
    to_retry: list[tuple[int, str]] = []
    to_release: list[int] = []
    orphaned: list[int] = []
    for event_id, document_id, attempt_id, attempt_status in rows:
        if attempt_status is None or attempt_id is None:
            orphaned.append(event_id)
        elif attempt_status == IndexingStatus.SUCCESS:
            to_complete.append(event_id)
        elif attempt_status == IndexingStatus.COMPLETED_WITH_ERRORS:
            failed = failed_documents.get(attempt_id, set())
            if None in failed or document_id in failed:
                to_retry.append((event_id, "the document failed to index"))
            else:
                to_complete.append(event_id)
        elif attempt_status.is_terminal():
            to_release.append(event_id)

    mark_events_completed(db_session, to_complete)
    retry_or_fail_events(db_session, to_retry)
    release_events_to_pending(
        db_session, to_release, error="the claiming attempt did not finish"
    )
    release_events_to_pending(
        db_session, orphaned, error="the claiming attempt no longer exists"
    )
    return len(to_complete), len(to_retry) + len(to_release) + len(orphaned)


def _failed_documents(
    db_session: Session, attempt_ids: set[int]
) -> dict[int, set[str | None]]:
    """Per attempt, the documents it recorded an error for. None stands for
    an error tied to no document, which could be any of them."""
    failed: dict[int, set[str | None]] = {}
    if not attempt_ids:
        return failed
    for attempt_id, document_id in db_session.execute(
        select(IndexAttemptError.index_attempt_id, IndexAttemptError.document_id)
        .where(IndexAttemptError.index_attempt_id.in_(attempt_ids))
        .distinct()
    ).tuples():
        failed.setdefault(attempt_id, set()).add(document_id)
    return failed


def event_pair_has_work(db_session: Session, cc_pair_id: int) -> bool:
    """A due PENDING row to claim, or an IN_PROGRESS row whose attempt has
    ended, which the next run settles. Schedules an event pair, which has no
    poll interval. A row a live attempt holds is not work for another run."""
    attempt_ended = or_(
        IndexAttempt.id.is_(None),
        IndexAttempt.status.in_(
            [status for status in IndexingStatus if status.is_terminal()]
        ),
    )
    return (
        db_session.scalar(
            select(
                select(ConnectorEventInbox.id)
                .outerjoin(
                    IndexAttempt,
                    ConnectorEventInbox.index_attempt_id == IndexAttempt.id,
                )
                .where(
                    ConnectorEventInbox.connector_credential_pair_id == cc_pair_id,
                    or_(
                        and_(
                            ConnectorEventInbox.status == ConnectorEventStatus.PENDING,
                            ConnectorEventInbox.available_at <= func.now(),
                        ),
                        and_(
                            ConnectorEventInbox.status
                            == ConnectorEventStatus.IN_PROGRESS,
                            attempt_ended,
                        ),
                    ),
                )
                .exists()
            )
        )
        is True
    )


def get_active_event_cc_pairs(
    db_session: Session, source: DocumentSource
) -> list[ConnectorCredentialPair]:
    """The pairs that may receive pushed events for one source. With none,
    the source's endpoint accepts nothing."""
    return list(
        db_session.scalars(
            select(ConnectorCredentialPair)
            .join(Connector, ConnectorCredentialPair.connector_id == Connector.id)
            .where(
                Connector.source == source,
                Connector.input_type == InputType.EVENT,
                # Not just ACTIVE: a pair is SCHEDULED until its first run
                # finishes, and a provider validates the callback URL during
                # setup, before any run has happened.
                ConnectorCredentialPair.status.in_(
                    ConnectorCredentialPairStatus.active_statuses()
                ),
            )
            .order_by(ConnectorCredentialPair.id)
        )
    )
