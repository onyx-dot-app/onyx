"""Guards the drain: claimed rows become documents, and no path leaves a row
claimed with nothing to settle it."""

from collections.abc import Generator, Mapping
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.event_inbox import connector as connector_module
from onyx.connectors.event_inbox.connector import (
    EventInboxCheckpoint,
    EventInboxConnector,
)
from onyx.connectors.event_inbox.registration import unregister_event_source
from onyx.connectors.event_models import ParsedEvent
from onyx.connectors.models import ConnectorFailure, Document, InputType, TextSection
from onyx.db.connector_event_inbox import (
    MAX_EVENT_ATTEMPTS,
    count_events_by_status,
    record_events,
    settle_events_from_finished_attempts,
)
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
from tests.utils.event_sources import declare_event_source, event_source_registered

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


def _handler(
    event: ConnectorEventInbox,
    secrets: Mapping[str, str],  # noqa: ARG001
) -> Document | None:
    if event.event_type == ConnectorEventType.DELETE:
        return None
    if event.document_id == BAD_DOCUMENT:
        raise ValueError("payload could not be read")
    payload = event.payload if isinstance(event.payload, Mapping) else {}
    title = payload.get("title")
    return Document(
        id=event.document_id,
        source=SOURCE,
        semantic_identifier=title if isinstance(title, str) else event.document_id,
        metadata={},
        sections=[TextSection(text="body", link=None)],
    )


@pytest.fixture(autouse=True)
def registered_handler() -> Generator[None, None, None]:
    with event_source_registered(SOURCE, handler=_handler):
        yield


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


def test_a_delete_yields_no_document_and_stays_claimed(
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
        # Back in the queue with backoff, not settled: the handler may have
        # failed for a reason the next run does not see.
        ConnectorEventStatus.PENDING: 1,
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
    unregister_event_source(SOURCE)
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
    assert "No event source registered" in failures[0].failure_message
    # Returned to the queue: the source may be registered on the next run,
    # and MAX_EVENT_ATTEMPTS stops it retrying for ever.
    assert count_events_by_status(db_session, pair_id) == {
        ConnectorEventStatus.PENDING: 1
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


def test_the_newer_of_two_changes_to_one_document_wins(
    db_session: Session, pair_and_attempt: tuple[int, int]
) -> None:
    """`upsert_documents` keeps the first entry for a document id, so
    yielding both would save the older change's fields and nothing would
    repair them."""
    pair_id, attempt_id = pair_and_attempt
    earlier = datetime(2026, 1, 1, tzinfo=timezone.utc)
    later = datetime(2026, 6, 1, tzinfo=timezone.utc)
    record_events(
        db_session,
        pair_id,
        SOURCE,
        [
            ParsedEvent(
                document_id="doc-1",
                event_key="k-old",
                payload={"title": "old"},
                occurred_at=earlier,
            ),
            ParsedEvent(
                document_id="doc-1",
                event_key="k-new",
                payload={"title": "new"},
                occurred_at=later,
            ),
        ],
    )
    db_session.commit()

    documents, failures, _ = _drain(
        _connector(pair_id, attempt_id, batch_size=10),
        EventInboxCheckpoint(has_more=True),
    )

    assert [document.semantic_identifier for document in documents] == ["new"]
    assert failures == []
    # Both rows settle: the document is indexed from the newer one.
    assert count_events_by_status(db_session, pair_id) == {
        ConnectorEventStatus.IN_PROGRESS: 2
    }


def test_an_untimestamped_change_can_still_be_the_newest(
    db_session: Session, pair_and_attempt: tuple[int, int]
) -> None:
    """A missing timestamp means the provider sent none, not that the change
    is old. Treating it as oldest would drop a change that arrived later."""
    pair_id, attempt_id = pair_and_attempt
    record_events(
        db_session,
        pair_id,
        SOURCE,
        [
            ParsedEvent(
                document_id="doc-1",
                event_key="k-timed",
                payload={"title": "timed"},
                occurred_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
            ),
            ParsedEvent(
                document_id="doc-1",
                event_key="k-untimed",
                payload={"title": "arrived later"},
            ),
        ],
    )
    db_session.commit()

    documents, _, _ = _drain(
        _connector(pair_id, attempt_id, batch_size=10),
        EventInboxCheckpoint(has_more=True),
    )

    assert [document.semantic_identifier for document in documents] == ["arrived later"]


def test_a_rejected_row_settles_even_if_the_run_is_abandoned(
    db_session: Session, pair_and_attempt: tuple[int, int]
) -> None:
    """Docfetching stops reading this generator once enough documents fail.
    A row settled only after the loop would stay claimed, be released by a
    later run, fail again, and keep blocking the queue."""
    pair_id, attempt_id = pair_and_attempt
    unregister_event_source(SOURCE)
    record_events(
        db_session,
        pair_id,
        SOURCE,
        [
            ParsedEvent(document_id="doc-1", event_key="k-1"),
            ParsedEvent(document_id="doc-2", event_key="k-2"),
        ],
    )
    db_session.commit()

    generator = _connector(pair_id, attempt_id, batch_size=10).load_from_checkpoint(
        0, 0, EventInboxCheckpoint(has_more=True)
    )
    first = next(generator)
    assert isinstance(first, ConnectorFailure)
    # Abandon it here, the way docfetching does once the failure ratio trips.
    generator.close()

    # Not left claimed by an attempt that stopped reading: a row nothing
    # releases would block its document for ever.
    assert (
        count_events_by_status(db_session, pair_id)[ConnectorEventStatus.PENDING] == 1
    )


def test_the_claim_session_is_closed_before_a_handler_runs(
    db_session: Session,
    pair_and_attempt: tuple[int, int],
    registered_handler: None,  # noqa: ARG001
) -> None:
    """A handler can fetch a body over the network, and the generator
    suspends at every yield while the runner stores documents. Holding the
    claim session across either keeps a pooled connection for the whole
    batch."""
    pair_id, attempt_id = pair_and_attempt
    open_sessions = 0
    peak_during_handler: list[int] = []
    peak_overall = 0

    real = connector_module.get_session_with_current_tenant

    @contextmanager
    def _counting() -> Generator[Session, None, None]:
        nonlocal open_sessions
        nonlocal peak_overall
        with real() as session:
            open_sessions += 1
            peak_overall = max(peak_overall, open_sessions)
            try:
                yield session
            finally:
                open_sessions -= 1

    def _watching(
        event: ConnectorEventInbox,
        secrets: Mapping[str, str],
    ) -> Document | None:
        peak_during_handler.append(open_sessions)
        return _handler(event, secrets)

    record_events(
        db_session,
        pair_id,
        SOURCE,
        [ParsedEvent(document_id="doc-1", event_key="k-1")],
    )
    db_session.commit()
    declare_event_source(SOURCE, handler=_watching)

    with patch.object(connector_module, "get_session_with_current_tenant", _counting):
        _drain(
            _connector(pair_id, attempt_id, batch_size=10),
            EventInboxCheckpoint(has_more=True),
        )

    # The instrument works -- the claim did open one -- so observing none
    # during dispatch is a real measurement rather than a broken counter.
    assert peak_overall >= 1
    assert peak_during_handler == [0]


def test_an_older_change_in_a_later_batch_does_not_overwrite_a_newer_one(
    db_session: Session,
    pair_and_attempt: tuple[int, int],
    registered_handler: None,  # noqa: ARG001
) -> None:
    """A provider that redelivers late puts an older change in a later batch
    than the newer one it must not replace."""
    pair_id, attempt_id = pair_and_attempt
    newer = datetime(2026, 11, 2, 15, 45, tzinfo=timezone.utc)
    older = datetime(2026, 11, 2, 15, 0, tzinfo=timezone.utc)
    connector = _connector(pair_id, attempt_id, batch_size=1)

    record_events(
        db_session,
        pair_id,
        SOURCE,
        [ParsedEvent(document_id="doc-1", event_key="k-new", occurred_at=newer)],
    )
    db_session.commit()
    first, _failures, checkpoint = _drain(
        connector, EventInboxCheckpoint(has_more=True)
    )
    record_events(
        db_session,
        pair_id,
        SOURCE,
        [ParsedEvent(document_id="doc-1", event_key="k-old", occurred_at=older)],
    )
    db_session.commit()
    second, _failures_2, _checkpoint_2 = _drain(connector, checkpoint)

    assert [document.id for document in first] == ["doc-1"]
    assert second == []
    assert count_events_by_status(db_session, pair_id) == {
        ConnectorEventStatus.IN_PROGRESS: 2
    }


def test_a_later_batch_loses_a_tie_on_event_time_to_a_higher_id(
    db_session: Session, pair_and_attempt: tuple[int, int]
) -> None:
    """Within a batch, id breaks a tie on event time. A retried change with
    the same time and a lower id must lose to the one already taken."""
    pair_id, attempt_id = pair_and_attempt
    same_time = datetime(2026, 11, 2, 15, 0, tzinfo=timezone.utc)
    unregister_event_source(SOURCE)
    record_events(
        db_session,
        pair_id,
        SOURCE,
        [ParsedEvent(document_id="doc-1", event_key="k-low", occurred_at=same_time)],
    )
    db_session.commit()
    _drain(
        _connector(pair_id, attempt_id, batch_size=10),
        EventInboxCheckpoint(has_more=True),
    )
    declare_event_source(SOURCE, handler=_handler)

    record_events(
        db_session,
        pair_id,
        SOURCE,
        [ParsedEvent(document_id="doc-1", event_key="k-high", occurred_at=same_time)],
    )
    db_session.commit()
    taken, _failures, _ = _drain(
        _connector(pair_id, attempt_id, batch_size=10),
        EventInboxCheckpoint(has_more=True),
    )
    assert [document.id for document in taken] == ["doc-1"]

    db_session.query(ConnectorEventInbox).filter_by(
        connector_credential_pair_id=pair_id,
        status=ConnectorEventStatus.PENDING,
    ).update({"available_at": datetime(2020, 1, 1, tzinfo=timezone.utc)})
    db_session.commit()
    retried, _failures_2, _ = _drain(
        _connector(pair_id, attempt_id, batch_size=10),
        EventInboxCheckpoint(has_more=True),
    )

    assert retried == []


def test_a_batch_padded_by_one_document_still_asks_for_more(
    db_session: Session, pair_and_attempt: tuple[int, int]
) -> None:
    """A claim takes all of a document's rows, so it can exceed its limit.
    That is still a full batch, and the next document must not wait for
    another run."""
    pair_id, attempt_id = pair_and_attempt
    record_events(
        db_session,
        pair_id,
        SOURCE,
        [ParsedEvent(document_id="doc-1", event_key=f"k-{i}") for i in range(3)]
        + [ParsedEvent(document_id="doc-2", event_key="k-other")],
    )
    db_session.commit()
    connector = _connector(pair_id, attempt_id, batch_size=2)

    first, _failures, checkpoint = _drain(
        connector, EventInboxCheckpoint(has_more=True)
    )
    assert [document.id for document in first] == ["doc-1"]
    assert checkpoint.has_more is True

    second, _failures_2, _ = _drain(connector, checkpoint)
    assert [document.id for document in second] == ["doc-2"]


def test_a_discarded_sibling_does_not_suppress_the_change_that_won(
    db_session: Session,
    pair_and_attempt: tuple[int, int],
    registered_handler: None,  # noqa: ARG001
) -> None:
    """Three changes to one document in a batch, one of them untimestamped.
    `claim_events` falls back to arrival order and keeps the last, but the
    claim has already marked all three IN_PROGRESS, so a cross-batch check
    that counted them would let the discarded first row suppress the winner
    and the document would never be indexed at all."""
    pair_id, attempt_id = pair_and_attempt
    june = datetime(2026, 6, 1, tzinfo=timezone.utc)
    january = datetime(2026, 1, 1, tzinfo=timezone.utc)

    for event in (
        ParsedEvent(document_id="doc-1", event_key="k-june", occurred_at=june),
        ParsedEvent(document_id="doc-1", event_key="k-none"),
        ParsedEvent(document_id="doc-1", event_key="k-jan", occurred_at=january),
    ):
        record_events(db_session, pair_id, SOURCE, [event])
        db_session.commit()

    documents, failures, _ = _drain(
        _connector(pair_id, attempt_id, batch_size=10),
        EventInboxCheckpoint(has_more=True),
    )

    assert failures == []
    assert [document.id for document in documents] == ["doc-1"]


def test_a_row_that_keeps_failing_eventually_settles(
    db_session: Session, pair_and_attempt: tuple[int, int]
) -> None:
    """Retrying is for a provider that may recover. A row that never does
    must stop, or it blocks its document and the queue for ever."""
    pair_id, attempt_id = pair_and_attempt
    unregister_event_source(SOURCE)
    record_events(
        db_session,
        pair_id,
        SOURCE,
        [ParsedEvent(document_id="doc-1", event_key="k-1")],
    )
    db_session.commit()

    for _ in range(MAX_EVENT_ATTEMPTS + 1):
        db_session.query(ConnectorEventInbox).filter_by(
            connector_credential_pair_id=pair_id
        ).update({"available_at": datetime(2020, 1, 1, tzinfo=timezone.utc)})
        db_session.commit()
        _drain(
            _connector(pair_id, attempt_id, batch_size=10),
            EventInboxCheckpoint(has_more=True),
        )

    assert count_events_by_status(db_session, pair_id) == {
        ConnectorEventStatus.FAILED: 1
    }


def test_a_retried_untimestamped_change_does_not_overwrite_a_newer_one(
    db_session: Session, pair_and_attempt: tuple[int, int]
) -> None:
    """An untimestamped change can fail, wait out its backoff while a later
    change to the same document is indexed, and come back. Comparing only
    timestamps could not discard it, so it would restore the old body."""
    pair_id, attempt_id = pair_and_attempt
    unregister_event_source(SOURCE)
    record_events(
        db_session,
        pair_id,
        SOURCE,
        [ParsedEvent(document_id="doc-1", event_key="k-old")],
    )
    db_session.commit()

    # It fails and returns to the queue.
    _drain(
        _connector(pair_id, attempt_id, batch_size=10),
        EventInboxCheckpoint(has_more=True),
    )
    assert count_events_by_status(db_session, pair_id) == {
        ConnectorEventStatus.PENDING: 1
    }
    declare_event_source(SOURCE, handler=_handler)

    # A later change is indexed while the first waits out its backoff.
    record_events(
        db_session,
        pair_id,
        SOURCE,
        [ParsedEvent(document_id="doc-1", event_key="k-new")],
    )
    db_session.commit()
    newer, _failures, _ = _drain(
        _connector(pair_id, attempt_id, batch_size=10),
        EventInboxCheckpoint(has_more=True),
    )
    assert [document.id for document in newer] == ["doc-1"]

    # The retry comes due. It must not be indexed over the newer change.
    db_session.query(ConnectorEventInbox).filter_by(
        connector_credential_pair_id=pair_id,
        status=ConnectorEventStatus.PENDING,
    ).update({"available_at": datetime(2020, 1, 1, tzinfo=timezone.utc)})
    db_session.commit()

    retried, _failures_2, _ = _drain(
        _connector(pair_id, attempt_id, batch_size=10),
        EventInboxCheckpoint(has_more=True),
    )

    assert retried == []


def test_a_batch_boundary_does_not_split_one_document(
    db_session: Session,
    pair_and_attempt: tuple[int, int],
    registered_handler: None,  # noqa: ARG001
) -> None:
    """Two changes to one document must be compared, not sent to two
    docprocessing tasks racing to write the same document."""
    pair_id, attempt_id = pair_and_attempt
    for key in ("k-1", "k-2"):
        record_events(
            db_session,
            pair_id,
            SOURCE,
            [ParsedEvent(document_id="doc-1", event_key=key)],
        )
        db_session.commit()

    # A batch size of one would otherwise take them one at a time.
    documents, failures, checkpoint = _drain(
        _connector(pair_id, attempt_id, batch_size=1),
        EventInboxCheckpoint(has_more=True),
    )

    assert failures == []
    assert [document.id for document in documents] == ["doc-1"]
    assert count_events_by_status(db_session, pair_id) == {
        ConnectorEventStatus.IN_PROGRESS: 2
    }


def test_a_claim_whose_attempt_was_deleted_returns_to_the_queue(
    db_session: Session,
    pair_and_attempt: tuple[int, int],
    registered_handler: None,  # noqa: ARG001
) -> None:
    """`index_attempt_id` is ON DELETE SET NULL, and deleting a search
    setting deletes its attempts. A claim that loses its owner would never
    be settled and never be claimed again."""
    pair_id, attempt_id = pair_and_attempt
    record_events(
        db_session,
        pair_id,
        SOURCE,
        [ParsedEvent(document_id="doc-1", event_key="k-1")],
    )
    db_session.commit()
    _drain(
        _connector(pair_id, attempt_id, batch_size=10),
        EventInboxCheckpoint(has_more=True),
    )
    assert count_events_by_status(db_session, pair_id) == {
        ConnectorEventStatus.IN_PROGRESS: 1
    }

    db_session.query(ConnectorEventInbox).filter_by(
        connector_credential_pair_id=pair_id
    ).update({"index_attempt_id": None})
    db_session.commit()

    settle_events_from_finished_attempts(db_session, pair_id)
    db_session.commit()

    assert count_events_by_status(db_session, pair_id) == {
        ConnectorEventStatus.PENDING: 1
    }
