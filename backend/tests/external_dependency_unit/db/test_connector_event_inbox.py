"""Guards the event inbox's receipt contract: a redelivered webhook writes no
second row, and a provider that sends no delivery id still dedupes.

These run against a real PostgreSQL because the guarantee is the unique
constraint, which a mock cannot show.
"""

import threading
from collections.abc import Generator
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.event_models import ParsedEvent
from onyx.connectors.models import InputType
from onyx.db.connector_event_inbox import (
    MAX_EVENT_ATTEMPTS,
    claim_events,
    count_events_by_status,
    get_event_by_key,
    get_pending_events,
    mark_events_completed,
    record_events,
    settle_events_from_finished_attempts,
)
from onyx.db.engine.sql_engine import SqlEngine
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
    IndexAttemptError,
)

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
        # A failed test leaves the session unusable, and the deletes below
        # would then raise and mask it.
        db_session.rollback()
        # Errors, then attempts: the pair's FK on index_attempt is NOT NULL,
        # so the ORM's SET NULL on delete would fail instead of cascading.
        db_session.query(IndexAttemptError).filter_by(
            connector_credential_pair_id=pair.id
        ).delete()
        db_session.query(IndexAttempt).filter_by(
            connector_credential_pair_id=pair.id
        ).delete()
        db_session.delete(pair)
        db_session.delete(connector)
        db_session.delete(credential)
        db_session.commit()


def _attempt(db_session: Session, cc_pair_id: int) -> int:
    attempt = IndexAttempt(
        connector_credential_pair_id=cc_pair_id,
        from_beginning=False,
        status="in_progress",
    )
    db_session.add(attempt)
    db_session.commit()
    return attempt.id


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
    new_event = mixed[-1]
    stored = get_event_by_key(db_session, cc_pair_id, new_event.resolved_event_key())
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


def test_one_delivery_covering_several_documents_keeps_them_all(
    db_session: Session, cc_pair_id: int
) -> None:
    """A provider's delivery id covers the POST, not one document. Without
    the document in the key a batch would collapse to a single row."""
    created = record_events(
        db_session,
        cc_pair_id,
        SOURCE,
        [
            ParsedEvent(document_id="doc-1", event_key="delivery-a"),
            ParsedEvent(document_id="doc-2", event_key="delivery-a"),
            ParsedEvent(document_id="doc-3", event_key="delivery-a"),
        ],
    )
    db_session.commit()

    assert len(created) == 3
    assert count_events_by_status(db_session, cc_pair_id) == {
        ConnectorEventStatus.PENDING: 3
    }


def test_successive_changes_to_one_document_are_both_kept(
    db_session: Session, cc_pair_id: int
) -> None:
    """With no delivery id and no timestamp, the change itself distinguishes
    the rows. Collapsing them would drop the second update silently."""
    first = ParsedEvent(document_id="doc-1", payload={"revision": 1})
    second = ParsedEvent(document_id="doc-1", payload={"revision": 2})

    assert record_events(db_session, cc_pair_id, SOURCE, [first])
    db_session.commit()
    assert record_events(db_session, cc_pair_id, SOURCE, [second])
    db_session.commit()
    # The same change again is a redelivery, and still collapses.
    assert record_events(db_session, cc_pair_id, SOURCE, [second]) == []
    db_session.commit()

    assert count_events_by_status(db_session, cc_pair_id) == {
        ConnectorEventStatus.PENDING: 2
    }


def test_a_delimiter_in_a_delivery_id_does_not_merge_two_changes(
    db_session: Session, cc_pair_id: int
) -> None:
    """The key holds two free-form strings. Joined by a delimiter they would
    be ambiguous, and one of these two changes would be dropped."""
    created = record_events(
        db_session,
        cc_pair_id,
        SOURCE,
        [
            ParsedEvent(document_id="doc", event_key="delivery:part"),
            ParsedEvent(document_id="part:doc", event_key="delivery"),
        ],
    )
    db_session.commit()

    assert len(created) == 2


def test_a_long_delivery_id_still_stores_and_dedupes(
    db_session: Session, cc_pair_id: int
) -> None:
    """The unique index has a size limit per entry. A provider id longer than
    that must still store, and its redelivery must still collapse."""
    event = ParsedEvent(document_id="doc-1", event_key="d" * 10_000)

    assert record_events(db_session, cc_pair_id, SOURCE, [event])
    db_session.commit()
    assert record_events(db_session, cc_pair_id, SOURCE, [event]) == []
    db_session.commit()

    stored = get_event_by_key(db_session, cc_pair_id, event.resolved_event_key())
    assert stored is not None
    assert len(stored.event_key) < 100


def test_a_second_claim_waits_and_never_splits_a_document(
    db_session: Session, cc_pair_id: int
) -> None:
    """Two attempts on one pair overlap during a model swap. Their claims are
    serialized, so neither takes a row the other holds, and a document's rows
    all go to one of them."""
    record_events(
        db_session,
        cc_pair_id,
        SOURCE,
        [
            ParsedEvent(document_id="doc-a", event_key="k-1"),
            ParsedEvent(document_id="doc-b", event_key="k-2"),
            ParsedEvent(document_id="doc-a", event_key="k-3"),
        ],
    )
    first_attempt = _attempt(db_session, cc_pair_id)
    second_attempt = _attempt(db_session, cc_pair_id)
    db_session.commit()

    engine = SqlEngine.get_engine()
    claimed_b: list[tuple[list[str], int]] = []
    with Session(engine) as session_a:
        winners_a, ids_a = claim_events(session_a, cc_pair_id, first_attempt, limit=1)
        claimed_a = ([event.document_id for event in winners_a], len(ids_a))

        def claim_second() -> None:
            with Session(engine) as session_b:
                winners_b, ids_b = claim_events(
                    session_b, cc_pair_id, second_attempt, limit=10
                )
                claimed_b.append(
                    ([event.document_id for event in winners_b], len(ids_b))
                )
                session_b.commit()

        waiter = threading.Thread(target=claim_second)
        waiter.start()
        waiter.join(timeout=1)
        assert waiter.is_alive(), "the second claim did not wait for the first"
        session_a.commit()
        waiter.join(timeout=10)
        assert not waiter.is_alive()

    # Both of doc-a's rows go to the first attempt, which yields one.
    assert claimed_a == (["doc-a"], 2)
    assert claimed_b == [(["doc-b"], 1)]


def test_claiming_stamps_the_attempt_and_counts_the_try(
    db_session: Session, cc_pair_id: int
) -> None:
    record_events(
        db_session,
        cc_pair_id,
        SOURCE,
        [ParsedEvent(document_id="doc-1", event_key="k-1")],
    )
    attempt_id = _attempt(db_session, cc_pair_id)
    db_session.commit()

    claimed, claimed_ids = claim_events(db_session, cc_pair_id, attempt_id, limit=10)
    db_session.commit()

    assert len(claimed) == 1
    assert claimed_ids == [claimed[0].id]
    assert claimed[0].status == ConnectorEventStatus.IN_PROGRESS
    assert claimed[0].index_attempt_id == attempt_id
    assert claimed[0].attempt_count == 1

    # A claimed row is no longer available to the next claimer.
    assert claim_events(db_session, cc_pair_id, attempt_id, limit=10) == ([], [])


def test_completing_a_row_stamps_when_it_settled(
    db_session: Session, cc_pair_id: int
) -> None:
    record_events(
        db_session,
        cc_pair_id,
        SOURCE,
        [ParsedEvent(document_id="doc-1", event_key="k-1")],
    )
    attempt_id = _attempt(db_session, cc_pair_id)
    db_session.commit()

    claimed, _ = claim_events(db_session, cc_pair_id, attempt_id, limit=10)
    mark_events_completed(db_session, [event.id for event in claimed])
    db_session.commit()

    settled = get_event_by_key(db_session, cc_pair_id, claimed[0].event_key)
    assert settled is not None
    assert settled.status == ConnectorEventStatus.COMPLETED
    assert settled.processed_at is not None


def test_two_sweeps_do_not_undo_each_other(
    db_session: Session, cc_pair_id: int
) -> None:
    """Two runs can settle the same stopped attempt at once.

    Without a lock both read the rows, the first releases and reclaims them,
    and the second releases them again — undoing a claim whose events the
    first run is already handling.
    """
    record_events(
        db_session,
        cc_pair_id,
        SOURCE,
        [ParsedEvent(document_id=f"doc-{i}", event_key=f"k-{i}") for i in range(3)],
    )
    stopped = _attempt(db_session, cc_pair_id)
    db_session.commit()
    claim_events(db_session, cc_pair_id, stopped, limit=10)
    db_session.commit()
    db_session.query(IndexAttempt).filter_by(id=stopped).update(
        {"status": IndexingStatus.FAILED}
    )
    db_session.commit()

    engine = SqlEngine.get_engine()
    with Session(engine) as session_a, Session(engine) as session_b:
        first = settle_events_from_finished_attempts(session_a, cc_pair_id)
        # session_a holds the rows here.
        second = settle_events_from_finished_attempts(session_b, cc_pair_id)
        session_a.commit()
        session_b.commit()

    assert first == (0, 3)
    # The second sweep saw nothing to settle rather than releasing them again.
    assert second == (0, 0)


def test_a_long_backlog_loads_only_its_winner(
    db_session: Session, cc_pair_id: int
) -> None:
    """Every row of the document is claimed, but only the newest is loaded."""
    record_events(
        db_session,
        cc_pair_id,
        SOURCE,
        [ParsedEvent(document_id="doc-1", event_key=f"k-{i}") for i in range(50)],
    )
    attempt_id = _attempt(db_session, cc_pair_id)
    db_session.commit()

    winners, claimed_ids = claim_events(db_session, cc_pair_id, attempt_id, limit=1)
    db_session.commit()

    assert len(claimed_ids) == 50
    assert [event.id for event in winners] == [max(claimed_ids)]
    assert count_events_by_status(db_session, cc_pair_id) == {
        ConnectorEventStatus.IN_PROGRESS: 50
    }


def test_a_partly_failed_attempt_retries_only_its_failed_documents(
    db_session: Session, cc_pair_id: int
) -> None:
    """One bad document must not loop the pair or redo documents that
    stored, and its retries are bounded."""
    record_events(
        db_session,
        cc_pair_id,
        SOURCE,
        [
            ParsedEvent(document_id="doc-ok", event_key="k-ok"),
            ParsedEvent(document_id="doc-bad", event_key="k-bad"),
        ],
    )
    db_session.commit()

    for attempt_number in range(1, MAX_EVENT_ATTEMPTS + 1):
        db_session.query(ConnectorEventInbox).filter_by(
            connector_credential_pair_id=cc_pair_id,
            status=ConnectorEventStatus.PENDING,
        ).update({"available_at": datetime(2020, 1, 1, tzinfo=timezone.utc)})
        attempt_id = _attempt(db_session, cc_pair_id)
        claim_events(db_session, cc_pair_id, attempt_id, limit=10)
        db_session.add(
            IndexAttemptError(
                index_attempt_id=attempt_id,
                connector_credential_pair_id=cc_pair_id,
                document_id="doc-bad",
                failure_message="embedding failed",
            )
        )
        db_session.query(IndexAttempt).filter_by(id=attempt_id).update(
            {"status": IndexingStatus.COMPLETED_WITH_ERRORS}
        )
        db_session.commit()
        settle_events_from_finished_attempts(db_session, cc_pair_id)
        db_session.commit()

        bad = (
            db_session.query(ConnectorEventInbox)
            .filter_by(connector_credential_pair_id=cc_pair_id, document_id="doc-bad")
            .one()
        )
        ok = (
            db_session.query(ConnectorEventInbox)
            .filter_by(connector_credential_pair_id=cc_pair_id, document_id="doc-ok")
            .one()
        )
        assert ok.status == ConnectorEventStatus.COMPLETED
        assert ok.attempt_count == 1
        if attempt_number < MAX_EVENT_ATTEMPTS:
            assert bad.status == ConnectorEventStatus.PENDING
            assert bad.available_at > datetime.now(timezone.utc)
        else:
            assert bad.status == ConnectorEventStatus.FAILED
