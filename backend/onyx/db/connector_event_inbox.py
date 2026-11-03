"""Reads and writes for `connector_event_inbox`."""

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.event_models import ParsedEvent
from onyx.db.enums import ConnectorEventStatus
from onyx.db.models import ConnectorEventInbox
from onyx.utils.logger import setup_logger

logger = setup_logger()


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
