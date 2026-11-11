"""The conversion stage claims stub batches with one UPDATE on the attempt row.
Concurrent claimers must never get the same batch number, never keep more
than the window in flight, and never claim a batch that is not stored."""

import contextvars
import threading
from collections.abc import Generator
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.connectors.models import SlimDocumentStub
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import IndexingStatus
from onyx.db.indexing_coordination import IndexingCoordination
from onyx.db.models import ConnectorCredentialPair, IndexAttempt
from onyx.db.search_settings import get_current_search_settings
from onyx.file_store.document_batch_storage import (
    get_document_batch_storage,
    get_stub_batch_storage,
)
from onyx.redis.redis_docprocessing import BatchStage, RedisDocprocessing
from onyx.redis.redis_pool import get_redis_client
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
    make_doc,
)

_CLAIMER_COUNT = 8
_CLAIMS_PER_CLAIMER = 25


@pytest.fixture
def cc_pair(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[ConnectorCredentialPair, None, None]:
    pair = make_cc_pair(db_session)
    try:
        yield pair
    finally:
        db_session.rollback()
        get_document_batch_storage(pair.id, 0, is_backfill=False).cleanup_all_batches()
        db_session.query(IndexAttempt).filter(
            IndexAttempt.connector_credential_pair_id == pair.id
        ).delete(synchronize_session="fetch")
        db_session.commit()
        cleanup_cc_pair(db_session, pair)


@pytest.fixture
def attempt_id(db_session: Session, cc_pair: ConnectorCredentialPair) -> int:
    attempt = IndexAttempt(
        connector_credential_pair_id=cc_pair.id,
        search_settings_id=get_current_search_settings(db_session).id,
        from_beginning=False,
        status=IndexingStatus.IN_PROGRESS,
    )
    db_session.add(attempt)
    db_session.commit()
    return attempt.id


def _store(db_session: Session, attempt_id: int, count: int) -> None:
    stored = db_session.get(IndexAttempt, attempt_id)
    assert stored is not None
    db_session.refresh(stored)
    for batch_num in range(
        stored.stub_batches_stored, stored.stub_batches_stored + count
    ):
        IndexingCoordination.record_stub_batch_stored(db_session, attempt_id, batch_num)


def test_claim_stops_at_stored_and_window(db_session: Session, attempt_id: int) -> None:
    assert IndexingCoordination.claim_stub_batches(db_session, attempt_id, 4) == []

    _store(db_session, attempt_id, 3)
    assert IndexingCoordination.claim_stub_batches(db_session, attempt_id, 4) == [
        0,
        1,
        2,
    ]
    # Nothing more is stored.
    assert IndexingCoordination.claim_stub_batches(db_session, attempt_id, 4) == []

    _store(db_session, attempt_id, 5)
    # Three in flight and a window of 4: one more.
    assert IndexingCoordination.claim_stub_batches(db_session, attempt_id, 4) == [3]
    assert IndexingCoordination.claim_stub_batches(db_session, attempt_id, 4) == []

    IndexingCoordination.record_stub_batch_converted(db_session, attempt_id)
    IndexingCoordination.record_stub_batch_converted(db_session, attempt_id)
    assert IndexingCoordination.claim_stub_batches(db_session, attempt_id, 4) == [
        4,
        5,
    ]


def test_out_of_order_store_is_refused(db_session: Session, attempt_id: int) -> None:
    IndexingCoordination.record_stub_batch_stored(db_session, attempt_id, 0)
    with pytest.raises(RuntimeError):
        IndexingCoordination.record_stub_batch_stored(db_session, attempt_id, 2)
    with pytest.raises(RuntimeError):
        IndexingCoordination.record_stub_batch_stored(db_session, attempt_id, 0)


def test_converted_never_passes_sent(db_session: Session, attempt_id: int) -> None:
    _store(db_session, attempt_id, 2)
    assert IndexingCoordination.claim_stub_batches(db_session, attempt_id, 1) == [0]
    assert IndexingCoordination.record_stub_batch_converted(db_session, attempt_id) == 1
    # A redelivered task counts nothing.
    assert IndexingCoordination.record_stub_batch_converted(db_session, attempt_id) == 1
    assert IndexingCoordination.claim_stub_batches(db_session, attempt_id, 1) == [1]


def test_concurrent_claims_never_double_claim_or_pass_window(
    db_session: Session, attempt_id: int
) -> None:
    window = 5
    total = _CLAIMER_COUNT * _CLAIMS_PER_CLAIMER
    _store(db_session, attempt_id, total)

    claimed: list[int] = []
    in_flight_peaks: list[int] = []
    errors: list[BaseException] = []
    lock = threading.Lock()
    in_flight = 0
    start = threading.Barrier(_CLAIMER_COUNT)

    def claimer() -> None:
        nonlocal in_flight
        try:
            start.wait()
            for _ in range(_CLAIMS_PER_CLAIMER * 4):
                with get_session_with_current_tenant() as session:
                    numbers = IndexingCoordination.claim_stub_batches(
                        session, attempt_id, window
                    )
                with lock:
                    claimed.extend(numbers)
                    in_flight += len(numbers)
                    in_flight_peaks.append(in_flight)
                for _ in numbers:
                    # Lower the local count first: the row frees a slot as
                    # soon as it commits, and another claimer can take it.
                    with lock:
                        in_flight -= 1
                    with get_session_with_current_tenant() as session:
                        IndexingCoordination.record_stub_batch_converted(
                            session, attempt_id
                        )
        except BaseException as e:
            errors.append(e)

    threads = [
        threading.Thread(target=contextvars.copy_context().run, args=(claimer,))
        for _ in range(_CLAIMER_COUNT)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)

    assert not errors
    assert len(claimed) == len(set(claimed))
    assert max(in_flight_peaks) <= window
    # Drain what is left after the threads stop.
    while numbers := IndexingCoordination.claim_stub_batches(
        db_session, attempt_id, window
    ):
        claimed.extend(numbers)
        for _ in numbers:
            IndexingCoordination.record_stub_batch_converted(db_session, attempt_id)
    assert sorted(claimed) == list(range(total))

    attempt = db_session.get(IndexAttempt, attempt_id)
    assert attempt is not None
    db_session.refresh(attempt)
    assert attempt.stub_batches_sent == total
    assert attempt.stub_batches_converted == total


def test_stub_batches_store_apart_and_clean_up_with_doc_batches(
    cc_pair: ConnectorCredentialPair, attempt_id: int
) -> None:
    stubs = get_stub_batch_storage(cc_pair.id, attempt_id, is_backfill=False)
    docs = get_document_batch_storage(cc_pair.id, attempt_id, is_backfill=False)

    stub = SlimDocumentStub(id="stub-doc-0", mime_type="text/plain", size_bytes=3)
    stubs.store_batch(0, [stub])
    docs.store_batch(0, [make_doc("stub-doc-0")])

    assert stubs.get_batch(0) == [stub]
    assert stubs.get_all_batches_for_cc_pair() == [
        f"isb/{cc_pair.id}/{attempt_id}/0.json"
    ]
    assert docs.get_all_batches_for_cc_pair() == [
        f"iab/{cc_pair.id}/{attempt_id}/0.json"
    ]
    with pytest.raises(RuntimeError):
        stubs.store_batch(0, [stub])

    docs.cleanup_all_batches()
    assert stubs.get_all_batches_for_cc_pair() == []
    assert docs.get_all_batches_for_cc_pair() == []


@pytest.mark.usefixtures("tenant_context")
def test_stage_counters_are_apart_and_clean_up_together() -> None:
    # A random attempt id keeps the keys apart from other runs.
    attempt_id = uuid4().int % 10**12
    r = get_redis_client()
    conversion = RedisDocprocessing(attempt_id, r, BatchStage.DOCCONVERSION)
    processing = RedisDocprocessing(attempt_id, r)
    try:
        conversion.incr_pending()
        conversion.incr_pending()
        conversion.decr_pending_incr_in_flight()
        processing.incr_pending()

        assert (conversion.pending(), conversion.in_flight()) == (1, 1)
        assert (processing.pending(), processing.in_flight()) == (1, 0)
        assert processing.pending_key == f"docprocessing_pending_{attempt_id}"

        processing.cleanup()
        assert (conversion.pending(), conversion.in_flight()) == (0, 0)
        assert processing.pending() == 0
    finally:
        processing.cleanup()
