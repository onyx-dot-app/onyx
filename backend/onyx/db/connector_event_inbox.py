"""Reads and writes for `connector_event_inbox`.

The webhook server records events here; a later drain claims them inside an
ordinary docfetching run. This module owns the queries, so neither side builds
SQL of its own.
"""

from collections.abc import Sequence
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.event_models import ParsedEvent
from onyx.db.enums import ConnectorEventStatus
from onyx.db.models import ConnectorEventInbox
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Keeps one unbounded traceback from bloating the row.
_MAX_ERROR_CHARS = 2000


def record_events(
    db_session: Session,
    cc_pair_id: int,
    source: DocumentSource,
    events: Sequence[ParsedEvent],
) -> list[int]:
    """Store events for one pair, skipping ones already recorded.

    Returns the ids of the rows this call created. A redelivered webhook
    conflicts on (pair, event_key) and is dropped, so the caller can answer
    200 either way and the ids tell it what was genuinely new.

    Does not commit: the caller decides the transaction boundary, so a route
    that also writes the body to the file store can keep both in one unit.
    """
    if not events:
        return []

    rows = [
        {
            "connector_credential_pair_id": cc_pair_id,
            "source": source,
            "document_id": event.document_id,
            "event_type": event.event_type,
            "event_key": event.resolved_event_key(),
            "file_id": event.file_id,
            "payload": event.payload,
            "occurred_at": event.occurred_at,
            "status": ConnectorEventStatus.PENDING,
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
    """The row a given delivery produced.

    `event_key` is the stored key, which is scoped to one document, so a
    caller holding a provider's delivery id builds it with
    `ParsedEvent.resolved_event_key()` rather than passing the id alone.
    """
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
    """Pending rows for one pair, oldest first.

    A read, not a claim: it takes no lock and sets no status. The drain adds
    the locking claim when it lands.
    """
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


def mark_events_failed(
    db_session: Session, failures: Sequence[tuple[int, str]]
) -> None:
    """Settle rows whose handler rejected them, recording why.

    A payload the handler cannot read fails the same way on every retry, so
    the row stops here rather than returning to the queue. `attempt_count`
    already records that it was tried. Does not commit.
    """
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
