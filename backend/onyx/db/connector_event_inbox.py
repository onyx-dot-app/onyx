"""Reads and writes for `connector_event_inbox`."""

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
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
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

# A handler that fetches over the network fails for reasons the next run may
# not see, so a row gets this many tries before it settles as failed.
MAX_EVENT_ATTEMPTS = 5
_RETRY_BACKOFF_SECONDS = 60

# Keeps one unbounded traceback from bloating the row.
_MAX_ERROR_CHARS = 2000


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
) -> set[int]:
    """Of these, the ids a newer change to the same document has overtaken.

    The drain compares a batch against itself, which is not enough: a change
    can arrive late, or fail and wait out a retry while a newer one is
    indexed. Only IN_PROGRESS and COMPLETED rows count as taken; the batch's
    own rows are excluded, since the claim has already marked them
    IN_PROGRESS and the caller compares those itself.

    Event time decides only when every taken row for the document carries
    one, as within a batch: a missing timestamp means the provider sent
    none, not that the change is old. Otherwise arrival order decides.
    """
    documents = {event.document_id for event in events}
    if not documents:
        return set()

    claimed_here = [event.id for event in events]
    taken = (
        select(
            ConnectorEventInbox.document_id,
            func.max(ConnectorEventInbox.occurred_at).label("newest"),
            func.max(ConnectorEventInbox.id).label("latest_id"),
            func.count()
            .filter(ConnectorEventInbox.occurred_at.is_(None))
            .label("undated"),
        )
        .where(
            ConnectorEventInbox.connector_credential_pair_id == cc_pair_id,
            ConnectorEventInbox.document_id.in_(documents),
            ConnectorEventInbox.status.in_(
                [ConnectorEventStatus.IN_PROGRESS, ConnectorEventStatus.COMPLETED]
            ),
            ConnectorEventInbox.id.notin_(claimed_here),
        )
        .group_by(ConnectorEventInbox.document_id)
    )

    superseded: set[int] = set()
    by_document = {row.document_id: row for row in db_session.execute(taken)}
    for event in events:
        row = by_document.get(event.document_id)
        if row is None:
            continue
        if event.occurred_at is not None and not row.undated and row.newest:
            if row.newest > event.occurred_at:
                superseded.add(event.id)
        elif row.latest_id > event.id:
            superseded.add(event.id)
    return superseded


def claim_events(
    db_session: Session,
    cc_pair_id: int,
    index_attempt_id: int,
    limit: int,
) -> list[ConnectorEventInbox]:
    """Take ownership of up to `limit` pending rows for one attempt.

    Locks with FOR UPDATE SKIP LOCKED, so two attempts on the same pair never
    claim the same row. Marks each row IN_PROGRESS and stamps the attempt that
    took it; that stamp is how the row is later settled against the attempt's
    outcome. Does not commit.
    """
    rows = list(
        db_session.scalars(
            select(ConnectorEventInbox)
            .where(
                ConnectorEventInbox.connector_credential_pair_id == cc_pair_id,
                ConnectorEventInbox.status == ConnectorEventStatus.PENDING,
                ConnectorEventInbox.available_at <= func.now(),
            )
            .order_by(ConnectorEventInbox.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    )

    for row in rows:
        row.status = ConnectorEventStatus.IN_PROGRESS
        row.index_attempt_id = index_attempt_id
        row.attempt_count += 1

    db_session.flush()
    return rows


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
    """Return claimed rows to the queue so a later attempt retries them.

    Used when an attempt ends without indexing what it claimed. Keeps
    `attempt_count`, which a caller can use to stop retrying. Does not commit.
    """
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
    """Return each row to the queue with backoff, or fail it once it has had
    enough tries.

    A handler can fail because a provider timed out, and the next run may
    not. Failing on the first exception would lose the document for good:
    `claim_events` only reads PENDING rows, and there is no reindex path
    that can reach a settled one. Does not commit.
    """
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
    """Settle rows for good, recording why. For a payload no retry can fix.
    Does not commit."""
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
    """Resolve rows whose claiming attempt has since finished.

    A row is claimed inside a run but cannot be completed there: the runner
    buffers documents and flushes them after the generator returns, so a row
    marked COMPLETED while the generator is still going would be settled
    before its document was stored, and a failed store would lose the change
    with no way to claim it again.

    So completion waits for the attempt's own outcome, which the next run of
    the pair observes. An attempt that succeeded completes its rows; one that
    failed, was canceled or was interrupted returns them to the queue. Rows
    of an attempt still running belong to it and are left alone.

    Returns (completed, released). Does not commit.
    """
    # Locked, and skipping what another sweep holds: two runs reading the
    # same rows would both release them, and the second would undo a claim
    # the first had already made and handed to its handler.
    claimed = (
        select(ConnectorEventInbox.id, IndexAttempt.status)
        .join(IndexAttempt, ConnectorEventInbox.index_attempt_id == IndexAttempt.id)
        .where(
            ConnectorEventInbox.connector_credential_pair_id == cc_pair_id,
            ConnectorEventInbox.status == ConnectorEventStatus.IN_PROGRESS,
        )
        .with_for_update(skip_locked=True, of=ConnectorEventInbox)
    )

    to_complete: list[int] = []
    to_release: list[int] = []
    for event_id, attempt_status in db_session.execute(claimed).tuples().all():
        if attempt_status == IndexingStatus.SUCCESS:
            to_complete.append(event_id)
        elif attempt_status.is_terminal():
            to_release.append(event_id)

    mark_events_completed(db_session, to_complete)
    release_events_to_pending(
        db_session, to_release, error="the claiming attempt did not finish"
    )
    return len(to_complete), len(to_release)


def get_active_event_cc_pairs(
    db_session: Session, source: DocumentSource
) -> list[ConnectorCredentialPair]:
    """The pairs that may receive pushed events for one source.

    This is what makes a source's endpoint live: with no active EVENT pair,
    the webhook server has nowhere to attribute a delivery, so setting the
    connector up is what opens the endpoint and pausing or deleting it is
    what closes it again.
    """
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
