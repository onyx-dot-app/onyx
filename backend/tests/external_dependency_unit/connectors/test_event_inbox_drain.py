"""Guards the drain: claimed rows become documents, and every claimed row
settles.

A row that is claimed but never settled is invisible — it is IN_PROGRESS, so
no later attempt claims it, and the change the source reported is silently
lost. These tests pin that no path leaves one behind.
"""

from collections.abc import Generator

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.event_inbox.connector import (
    EventInboxCheckpoint,
    EventInboxConnector,
)
from onyx.connectors.event_inbox.handlers import (
    get_event_handler,
    register_event_handler,
    unregister_event_handler,
)
from onyx.connectors.event_models import ParsedEvent
from onyx.connectors.models import ConnectorFailure, Document, InputType, TextSection
from onyx.db.connector_event_inbox import count_events_by_status, record_events
from onyx.db.enums import (
    AccessType,
    ConnectorCredentialPairStatus,
    ConnectorEventStatus,
    ConnectorEventType,
    IndexingStatus,
)
from onyx.db.models import (
    Connector,
    ConnectorCredentialPair,
    ConnectorEventInbox,
    Credential,
    IndexAttempt,
)

SOURCE = DocumentSource.MOCK_CONNECTOR
BAD_DOCUMENT = "doc-that-cannot-be-read"


@pytest.fixture
def pair_and_attempt(db_session: Session) -> Generator[tuple[int, int], None, None]:
    connector = Connector(
        name="drain-test",
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
        name=f"drain-pair-{connector.id}",
        status=ConnectorCredentialPairStatus.ACTIVE,
        access_type=AccessType.PUBLIC,
        total_docs_indexed=0,
    )
    db_session.add(pair)
    db_session.flush()
    attempt = IndexAttempt(
        connector_credential_pair_id=pair.id,
        from_beginning=False,
        status="in_progress",
    )
    db_session.add(attempt)
    db_session.commit()
    try:
        yield pair.id, attempt.id
    finally:
        # A failed test leaves the session unusable, and the deletes below
        # would then raise and mask it.
        db_session.rollback()
        # Attempts first: the pair's FK on index_attempt is NOT NULL, so the
        # ORM's SET NULL on delete would fail instead of cascading.
        db_session.query(IndexAttempt).filter_by(
            connector_credential_pair_id=pair.id
        ).delete()
        db_session.delete(pair)
        db_session.delete(connector)
        db_session.delete(credential)
        db_session.commit()


def _handler(event: ConnectorEventInbox) -> Document | None:
    if event.event_type == ConnectorEventType.DELETE:
        # Nothing to index; the row still settles because it was handled.
        return None
    if event.document_id == BAD_DOCUMENT:
        raise ValueError("payload could not be read")
    return Document(
        id=event.document_id,
        source=SOURCE,
        semantic_identifier=event.document_id,
        metadata={},
        sections=[TextSection(text="body", link=None)],
    )


@pytest.fixture(autouse=True)
def registered_handler() -> Generator[None, None, None]:
    previous = get_event_handler(SOURCE)
    register_event_handler(SOURCE, _handler)
    try:
        yield
    finally:
        if previous is None:
            unregister_event_handler(SOURCE)
        else:
            register_event_handler(SOURCE, previous)


def _drain(
    connector: EventInboxConnector, checkpoint: EventInboxCheckpoint
) -> tuple[list[Document], list[ConnectorFailure], EventInboxCheckpoint]:
    documents: list[Document] = []
    failures: list[ConnectorFailure] = []
    generator = connector.load_from_checkpoint(0, 0, checkpoint)
    while True:
        try:
            item = next(generator)
        except StopIteration as stop:
            return documents, failures, stop.value
        if isinstance(item, Document):
            documents.append(item)
        elif isinstance(item, ConnectorFailure):
            failures.append(item)


def _connector(pair_id: int, attempt_id: int, batch_size: int) -> EventInboxConnector:
    connector = EventInboxConnector(batch_size=batch_size)
    connector.set_event_context(cc_pair_id=pair_id, index_attempt_id=attempt_id)
    return connector


def test_drain_yields_documents_and_settles_them(
    db_session: Session, pair_and_attempt: tuple[int, int]
) -> None:
    pair_id, attempt_id = pair_and_attempt
    record_events(
        db_session,
        pair_id,
        SOURCE,
        [ParsedEvent(document_id=f"doc-{i}", event_key=f"k-{i}") for i in range(3)],
    )
    db_session.commit()

    documents, failures, checkpoint = _drain(
        _connector(pair_id, attempt_id, batch_size=10),
        EventInboxCheckpoint(has_more=True),
    )

    assert [document.id for document in documents] == ["doc-0", "doc-1", "doc-2"]
    assert failures == []
    assert checkpoint.has_more is False
    assert checkpoint.drained == 3
    # Claimed, not completed: the runner has not stored these documents yet,
    # so the rows wait for this attempt's outcome.
    assert count_events_by_status(db_session, pair_id) == {
        ConnectorEventStatus.IN_PROGRESS: 3
    }


def test_a_full_batch_asks_for_another_round(
    db_session: Session, pair_and_attempt: tuple[int, int]
) -> None:
    pair_id, attempt_id = pair_and_attempt
    record_events(
        db_session,
        pair_id,
        SOURCE,
        [ParsedEvent(document_id=f"doc-{i}", event_key=f"k-{i}") for i in range(5)],
    )
    db_session.commit()
    connector = _connector(pair_id, attempt_id, batch_size=2)

    first, _, checkpoint = _drain(connector, EventInboxCheckpoint(has_more=True))
    assert len(first) == 2
    assert checkpoint.has_more is True

    second, _, checkpoint = _drain(connector, checkpoint)
    third, _, checkpoint = _drain(connector, checkpoint)

    assert checkpoint.drained == 5
    assert len(second) == 2
    assert len(third) == 1
    assert checkpoint.has_more is False


def test_a_delete_settles_without_a_document(
    db_session: Session, pair_and_attempt: tuple[int, int]
) -> None:
    pair_id, attempt_id = pair_and_attempt
    record_events(
        db_session,
        pair_id,
        SOURCE,
        [
            ParsedEvent(
                document_id="gone",
                event_type=ConnectorEventType.DELETE,
                event_key="k-del",
            )
        ],
    )
    db_session.commit()

    documents, failures, _ = _drain(
        _connector(pair_id, attempt_id, batch_size=10),
        EventInboxCheckpoint(has_more=True),
    )

    assert documents == []
    assert failures == []
    assert count_events_by_status(db_session, pair_id) == {
        ConnectorEventStatus.IN_PROGRESS: 1
    }


def test_a_rejected_event_fails_its_row_and_spares_the_batch(
    db_session: Session, pair_and_attempt: tuple[int, int]
) -> None:
    """The regression this suite exists for.

    A handler that raises used to leave its row IN_PROGRESS, where no later
    attempt could claim it, so the event was lost without a trace.
    """
    pair_id, attempt_id = pair_and_attempt
    bad_event = ParsedEvent(document_id=BAD_DOCUMENT, event_key="k-bad")
    record_events(
        db_session,
        pair_id,
        SOURCE,
        [
            ParsedEvent(document_id="doc-ok", event_key="k-ok"),
            bad_event,
        ],
    )
    db_session.commit()

    documents, failures, _ = _drain(
        _connector(pair_id, attempt_id, batch_size=10),
        EventInboxCheckpoint(has_more=True),
    )

    assert [document.id for document in documents] == ["doc-ok"]
    assert len(failures) == 1
    assert failures[0].failed_document is not None
    assert failures[0].failed_document.document_id == BAD_DOCUMENT

    assert count_events_by_status(db_session, pair_id) == {
        ConnectorEventStatus.IN_PROGRESS: 1,
        ConnectorEventStatus.FAILED: 1,
    }
    rejected = (
        db_session.query(ConnectorEventInbox)
        .filter_by(
            connector_credential_pair_id=pair_id,
            event_key=bad_event.resolved_event_key(),
        )
        .one()
    )
    assert rejected.last_error == "payload could not be read"


def test_a_source_with_no_handler_fails_its_rows(
    db_session: Session, pair_and_attempt: tuple[int, int]
) -> None:
    pair_id, attempt_id = pair_and_attempt
    unregister_event_handler(SOURCE)
    record_events(
        db_session,
        pair_id,
        SOURCE,
        [ParsedEvent(document_id="doc-1", event_key="k-1")],
    )
    db_session.commit()

    documents, failures, _ = _drain(
        _connector(pair_id, attempt_id, batch_size=10),
        EventInboxCheckpoint(has_more=True),
    )

    assert documents == []
    assert len(failures) == 1
    assert "No event handler registered" in failures[0].failure_message
    # Settled, not stranded: an unregistered source must not fill the queue
    # with rows nothing will ever claim again.
    assert count_events_by_status(db_session, pair_id) == {
        ConnectorEventStatus.FAILED: 1
    }


def test_drain_without_its_context_refuses_to_run(
    db_session: Session, pair_and_attempt: tuple[int, int]
) -> None:
    """The ids come from the run, not stored config, so a connector the
    entrypoint forgot to wire must fail loudly rather than drain nothing."""
    pair_id, _ = pair_and_attempt
    record_events(
        db_session,
        pair_id,
        SOURCE,
        [ParsedEvent(document_id="doc-1", event_key="k-1")],
    )
    db_session.commit()

    with pytest.raises(RuntimeError, match="event context"):
        _drain(EventInboxConnector(), EventInboxCheckpoint(has_more=True))


def test_a_successful_attempt_completes_the_rows_it_claimed(
    db_session: Session, pair_and_attempt: tuple[int, int]
) -> None:
    """Completion waits for the attempt, because the runner stores the last
    documents only after the generator returns."""
    pair_id, attempt_id = pair_and_attempt
    record_events(
        db_session, pair_id, SOURCE, [ParsedEvent(document_id="doc-1", event_key="k-1")]
    )
    db_session.commit()
    _drain(
        _connector(pair_id, attempt_id, batch_size=10),
        EventInboxCheckpoint(has_more=True),
    )

    db_session.query(IndexAttempt).filter_by(id=attempt_id).update(
        {"status": IndexingStatus.SUCCESS}
    )
    db_session.commit()

    # The next run of the pair observes the outcome.
    next_attempt = IndexAttempt(
        connector_credential_pair_id=pair_id, from_beginning=False, status="in_progress"
    )
    db_session.add(next_attempt)
    db_session.commit()
    _drain(
        _connector(pair_id, next_attempt.id, batch_size=10),
        EventInboxCheckpoint(has_more=True),
    )

    assert count_events_by_status(db_session, pair_id) == {
        ConnectorEventStatus.COMPLETED: 1
    }


def test_a_stopped_attempt_returns_its_rows_to_the_queue(
    db_session: Session, pair_and_attempt: tuple[int, int]
) -> None:
    """Without this the rows stay claimed and no later attempt can take
    them, so the change a source reported is lost silently."""
    pair_id, attempt_id = pair_and_attempt
    record_events(
        db_session, pair_id, SOURCE, [ParsedEvent(document_id="doc-1", event_key="k-1")]
    )
    db_session.commit()
    _drain(
        _connector(pair_id, attempt_id, batch_size=10),
        EventInboxCheckpoint(has_more=True),
    )

    db_session.query(IndexAttempt).filter_by(id=attempt_id).update(
        {"status": IndexingStatus.FAILED}
    )
    db_session.commit()

    next_attempt = IndexAttempt(
        connector_credential_pair_id=pair_id, from_beginning=False, status="in_progress"
    )
    db_session.add(next_attempt)
    db_session.commit()
    documents, _, _ = _drain(
        _connector(pair_id, next_attempt.id, batch_size=10),
        EventInboxCheckpoint(has_more=True),
    )

    # Released and then re-claimed by the new attempt in the same pass.
    assert [document.id for document in documents] == ["doc-1"]
    assert count_events_by_status(db_session, pair_id) == {
        ConnectorEventStatus.IN_PROGRESS: 1
    }
