"""Guards the event inbox's receipt contract: a redelivered webhook writes no
second row, and a provider that sends no delivery id still dedupes.

These run against a real PostgreSQL because the guarantee is the unique
constraint, which a mock cannot show.
"""

from collections.abc import Generator

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.event_models import ParsedEvent
from onyx.connectors.models import InputType
from onyx.db.connector_event_inbox import (
    count_events_by_status,
    get_event_by_key,
    get_pending_events,
    record_events,
)
from onyx.db.enums import (
    AccessType,
    ConnectorCredentialPairStatus,
    ConnectorEventStatus,
    ConnectorEventType,
)
from onyx.db.models import Connector, ConnectorCredentialPair, Credential

SOURCE = DocumentSource.MOCK_CONNECTOR


@pytest.fixture
def cc_pair_id(db_session: Session) -> Generator[int, None, None]:
    """A throwaway pair. Deleting it cascades to the inbox rows."""
    connector = Connector(
        name="event-inbox-test",
        source=SOURCE,
        input_type=InputType.POLL,
        connector_specific_config={},
    )
    credential = Credential(credential_json={}, source=SOURCE, admin_public=True)
    db_session.add_all([connector, credential])
    db_session.flush()
    pair = ConnectorCredentialPair(
        connector_id=connector.id,
        credential_id=credential.id,
        name=f"event-inbox-pair-{connector.id}",
        status=ConnectorCredentialPairStatus.ACTIVE,
        access_type=AccessType.PUBLIC,
        total_docs_indexed=0,
    )
    db_session.add(pair)
    db_session.commit()
    try:
        yield pair.id
    finally:
        db_session.delete(pair)
        db_session.delete(connector)
        db_session.delete(credential)
        db_session.commit()


def test_redelivery_writes_no_second_row(db_session: Session, cc_pair_id: int) -> None:
    events = [ParsedEvent(document_id="doc-1", event_key="delivery-a")]

    first = record_events(db_session, cc_pair_id, SOURCE, events)
    db_session.commit()
    second = record_events(db_session, cc_pair_id, SOURCE, events)
    db_session.commit()

    assert len(first) == 1
    assert second == []
    assert count_events_by_status(db_session, cc_pair_id) == {
        ConnectorEventStatus.PENDING: 1
    }


def test_partial_batch_records_only_the_new_events(
    db_session: Session, cc_pair_id: int
) -> None:
    seen = [ParsedEvent(document_id=f"doc-{i}", event_key=f"k-{i}") for i in range(3)]
    record_events(db_session, cc_pair_id, SOURCE, seen)
    db_session.commit()

    mixed = seen + [ParsedEvent(document_id="doc-new", event_key="k-new")]
    created = record_events(db_session, cc_pair_id, SOURCE, mixed)
    db_session.commit()

    assert len(created) == 1
    stored = get_event_by_key(db_session, cc_pair_id, "k-new")
    assert stored is not None
    assert stored.document_id == "doc-new"


def test_events_without_a_delivery_id_still_dedupe(
    db_session: Session, cc_pair_id: int
) -> None:
    """A provider that sends no id gets a derived one, so a replay of the same
    change collapses while a later change on the same document does not."""
    same = ParsedEvent(document_id="doc-1")
    assert record_events(db_session, cc_pair_id, SOURCE, [same])
    db_session.commit()
    assert record_events(db_session, cc_pair_id, SOURCE, [same]) == []
    db_session.commit()

    changed_again = ParsedEvent(
        document_id="doc-1", event_type=ConnectorEventType.DELETE
    )
    assert record_events(db_session, cc_pair_id, SOURCE, [changed_again])
    db_session.commit()

    assert count_events_by_status(db_session, cc_pair_id) == {
        ConnectorEventStatus.PENDING: 2
    }


def test_empty_batch_is_a_no_op(db_session: Session, cc_pair_id: int) -> None:
    assert record_events(db_session, cc_pair_id, SOURCE, []) == []


def test_pending_events_are_oldest_first(db_session: Session, cc_pair_id: int) -> None:
    record_events(
        db_session,
        cc_pair_id,
        SOURCE,
        [ParsedEvent(document_id=f"doc-{i}", event_key=f"k-{i}") for i in range(3)],
    )
    db_session.commit()

    pending = get_pending_events(db_session, cc_pair_id, limit=10)
    assert [event.document_id for event in pending] == ["doc-0", "doc-1", "doc-2"]
