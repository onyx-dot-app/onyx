"""External dependency unit tests for the reindex hold (onyx.db.reindex_hold).

Once every seeded connector's port is SUCCESS the reindex is finalizing: PRESENT
indexing stops and FUTURE catches up. A cc_pair needs catch-up when PRESENT wrote
after the reindex began (its seed) and no successful FUTURE poll has a window end
past both the port's completion and PRESENT's last end. A pair whose FUTURE
attempts keep failing is abandoned; a paused pair cannot catch up at all; both get
their hashes cleared at the swap.
"""

from collections.abc import Generator
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.db import reindex_hold as reindex_hold_db
from onyx.db.connector_edit_requests import request_retry_delay
from onyx.db.engine.time_utils import get_db_current_time
from onyx.db.enums import (
    ConnectorCredentialPairStatus,
    IndexingStatus,
    PortAttemptStatus,
    SwitchoverType,
)
from onyx.db.index_attempt import create_synthetic_seed_attempt
from onyx.db.models import (
    ConnectorCredentialPair,
    IndexAttempt,
    PortAttempt,
    SearchSettings,
)
from onyx.db.port_attempt import (
    create_port_attempt,
    mark_port_in_progress,
    mark_port_terminal,
    reindex_finalizing,
)
from onyx.db.reindex_hold import (
    PairCatchUpState,
    get_pair_catch_up_states,
    get_reindex_hold_state,
)
from onyx.db.search_settings import get_current_search_settings
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    cleanup_cc_pair_and_future,
    make_cc_pair,
    make_future_search_settings,
)

_DOC_PREFIX = "holddoc-"


@pytest.fixture
def pair_and_future(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[tuple[ConnectorCredentialPair, SearchSettings], None, None]:
    pair = make_cc_pair(db_session)
    future = make_future_search_settings(db_session, use_port_flow=True)
    try:
        yield pair, future
    finally:
        cleanup_cc_pair_and_future(db_session, pair, future.id, doc_prefix=_DOC_PREFIX)


def _seed(
    db_session: Session, pair: ConnectorCredentialPair, future_id: int
) -> datetime:
    """Seeds the pair like set_new_search_settings does; returns the seed's creation
    time, which is when the reindex began for the pair."""
    seed_id = create_synthetic_seed_attempt(pair.id, future_id, db_session, 0.0)
    db_session.commit()
    seed = db_session.get(IndexAttempt, seed_id)
    assert seed is not None
    return seed.time_created


def _success_port(
    db_session: Session, pair: ConnectorCredentialPair, future_id: int
) -> PortAttempt:
    attempt = create_port_attempt(db_session, pair.id, future_id)
    mark_port_in_progress(db_session, attempt.id)
    mark_port_terminal(db_session, attempt.id, PortAttemptStatus.SUCCESS)
    db_session.expire_all()
    row = db_session.get(PortAttempt, attempt.id)
    assert row is not None and row.time_completed is not None
    return row


def _attempt(
    db_session: Session,
    pair: ConnectorCredentialPair,
    search_settings_id: int,
    *,
    status: IndexingStatus,
    ended: datetime | None = None,
    created: datetime | None = None,
    poll_range_end: datetime | None = None,
    celery_task_id: str | None = None,
    from_beginning: bool = False,
    is_backfill: bool = False,
) -> IndexAttempt:
    """An index attempt row with explicit times. `ended` sets time_started and
    time_finished, so end_time is well-defined for a terminal status."""
    row = IndexAttempt(
        connector_credential_pair_id=pair.id,
        search_settings_id=search_settings_id,
        status=status,
        from_beginning=from_beginning,
        is_backfill=is_backfill,
        celery_task_id=celery_task_id,
        poll_range_end=poll_range_end,
        time_started=ended,
        time_finished=ended if status.is_terminal() else None,
    )
    if created is not None:
        row.time_created = created
    db_session.add(row)
    db_session.commit()
    return row


def _present_id(db_session: Session) -> int:
    return get_current_search_settings(db_session).id


def _state(
    db_session: Session, pair: ConnectorCredentialPair, future: SearchSettings
) -> PairCatchUpState:
    db_session.expire_all()
    future_row = db_session.get(SearchSettings, future.id)
    assert future_row is not None
    return get_pair_catch_up_states(db_session, future_row, [pair.id])[pair.id]


def test_hold_state_is_empty_without_a_port_flow_reindex(
    db_session: Session, pair_and_future: tuple[ConnectorCredentialPair, SearchSettings]
) -> None:
    pair, future = pair_and_future
    assert get_reindex_hold_state(db_session, None).finalizing is False

    with patch.object(
        reindex_hold_db, "reindex_port_cc_pair_ids", lambda *_: [pair.id]
    ):
        future.use_port_flow = False
        db_session.commit()
        legacy = get_reindex_hold_state(db_session, future)
        assert legacy.finalizing is False and legacy.pairs == {}

        future.use_port_flow = True
        future.switchover_type = SwitchoverType.INSTANT
        db_session.commit()
        instant = get_reindex_hold_state(db_session, future)
        assert instant.finalizing is False and instant.pairs == {}


def test_hold_needs_every_seeded_port_success(
    db_session: Session, pair_and_future: tuple[ConnectorCredentialPair, SearchSettings]
) -> None:
    """A pair created after the reindex began has no seed: its port still gates the
    swap, but it does not end the finalizing phase."""
    pair, future = pair_and_future
    _seed(db_session, pair, future.id)
    late_pair = make_cc_pair(db_session)
    try:
        with patch.object(
            reindex_hold_db,
            "reindex_port_cc_pair_ids",
            lambda *_: [pair.id, late_pair.id],
        ):
            assert get_reindex_hold_state(db_session, future).finalizing is False

            _success_port(db_session, pair, future.id)
            state = get_reindex_hold_state(db_session, future)
            assert state.finalizing is True
            assert set(state.pairs) == {pair.id, late_pair.id}
        with patch(
            "onyx.db.port_attempt.fetch_indexable_standard_connector_credential_pair_ids",
            lambda *_, **__: [pair.id, late_pair.id],
        ):
            assert reindex_finalizing(db_session, future) is True
    finally:
        cleanup_cc_pair(db_session, late_pair)


def test_pair_needs_catch_up_when_present_wrote_after_the_reindex_began(
    db_session: Session, pair_and_future: tuple[ConnectorCredentialPair, SearchSettings]
) -> None:
    pair, future = pair_and_future
    since = _seed(db_session, pair, future.id)
    port = _success_port(db_session, pair, future.id)
    assert port.time_completed is not None

    _attempt(
        db_session,
        pair,
        _present_id(db_session),
        status=IndexingStatus.SUCCESS,
        ended=since - timedelta(minutes=5),
    )
    state = _state(db_session, pair, future)
    assert state.since == since
    assert state.wrote_after_since is False
    assert state.needs_catch_up is False

    _attempt(
        db_session,
        pair,
        _present_id(db_session),
        status=IndexingStatus.FAILED,
        ended=port.time_completed + timedelta(minutes=1),
    )
    state = _state(db_session, pair, future)
    assert state.wrote_after_since is True
    assert state.needs_catch_up is True
    assert state.abandoned is False
    assert state.catch_up_due is True


def test_push_based_pair_never_needs_catch_up(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    pair = make_cc_pair(db_session, source=DocumentSource.INGESTION_API)
    future = make_future_search_settings(db_session, use_port_flow=True)
    try:
        since = _seed(db_session, pair, future.id)
        _success_port(db_session, pair, future.id)
        _attempt(
            db_session,
            pair,
            _present_id(db_session),
            status=IndexingStatus.SUCCESS,
            ended=since + timedelta(minutes=5),
        )
        state = _state(db_session, pair, future)
        assert state.push_based is True
        assert state.needs_catch_up is False
        assert state.reset_hashes_at_swap is False
    finally:
        cleanup_cc_pair_and_future(db_session, pair, future.id)


def test_active_present_attempt_counts_as_writer(
    db_session: Session, pair_and_future: tuple[ConnectorCredentialPair, SearchSettings]
) -> None:
    pair, future = pair_and_future
    _seed(db_session, pair, future.id)
    _success_port(db_session, pair, future.id)
    present_id = _present_id(db_session)

    waiting = _attempt(db_session, pair, present_id, status=IndexingStatus.NOT_STARTED)
    state = _state(db_session, pair, future)
    assert state.present_active is False

    waiting.celery_task_id = "queued"
    db_session.commit()
    state = _state(db_session, pair, future)
    assert state.present_active is True
    assert state.needs_catch_up is True
    # The beat waits for the writer instead of starting a catch-up it would repeat.
    assert state.catch_up_due is False

    waiting.status = IndexingStatus.IN_PROGRESS
    db_session.commit()
    assert _state(db_session, pair, future).present_active is True


def test_future_success_past_the_watermark_clears_catch_up(
    db_session: Session, pair_and_future: tuple[ConnectorCredentialPair, SearchSettings]
) -> None:
    pair, future = pair_and_future
    _seed(db_session, pair, future.id)
    port = _success_port(db_session, pair, future.id)
    assert port.time_completed is not None
    present_end = port.time_completed + timedelta(minutes=10)
    _attempt(
        db_session,
        pair,
        _present_id(db_session),
        status=IndexingStatus.SUCCESS,
        ended=present_end,
    )

    # A poll whose window ended before PRESENT's last run may have missed its writes.
    _attempt(
        db_session,
        pair,
        future.id,
        status=IndexingStatus.SUCCESS,
        ended=present_end + timedelta(minutes=5),
        poll_range_end=present_end - timedelta(seconds=1),
    )
    assert _state(db_session, pair, future).needs_catch_up is True

    # A backfill's window says nothing about the catch-up.
    _attempt(
        db_session,
        pair,
        future.id,
        status=IndexingStatus.SUCCESS,
        ended=present_end + timedelta(minutes=6),
        poll_range_end=present_end + timedelta(hours=1),
        is_backfill=True,
    )
    assert _state(db_session, pair, future).needs_catch_up is True

    _attempt(
        db_session,
        pair,
        future.id,
        status=IndexingStatus.COMPLETED_WITH_ERRORS,
        ended=present_end + timedelta(minutes=7),
        poll_range_end=present_end,
    )
    state = _state(db_session, pair, future)
    assert state.caught_up is True
    assert state.needs_catch_up is False
    assert state.reset_hashes_at_swap is False


def test_paused_pair_is_not_caught_up_and_resets_hashes_at_the_swap(
    db_session: Session, pair_and_future: tuple[ConnectorCredentialPair, SearchSettings]
) -> None:
    pair, future = pair_and_future
    since = _seed(db_session, pair, future.id)
    _success_port(db_session, pair, future.id)
    _attempt(
        db_session,
        pair,
        _present_id(db_session),
        status=IndexingStatus.SUCCESS,
        ended=since + timedelta(minutes=5),
    )
    pair.status = ConnectorCredentialPairStatus.PAUSED
    db_session.commit()

    state = _state(db_session, pair, future)
    assert state.active is False
    assert state.needs_catch_up is False
    assert state.abandoned is False
    assert state.reset_hashes_at_swap is True


def test_abandon_after_failed_future_attempts_since_the_port(
    db_session: Session, pair_and_future: tuple[ConnectorCredentialPair, SearchSettings]
) -> None:
    pair, future = pair_and_future
    _seed(db_session, pair, future.id)
    port = _success_port(db_session, pair, future.id)
    assert port.time_completed is not None
    completed = port.time_completed
    _attempt(
        db_session,
        pair,
        _present_id(db_session),
        status=IndexingStatus.SUCCESS,
        ended=completed + timedelta(minutes=1),
    )
    # A failure from before the port completed does not count.
    _attempt(
        db_session,
        pair,
        future.id,
        status=IndexingStatus.FAILED,
        created=completed - timedelta(hours=1),
        ended=completed - timedelta(minutes=50),
    )
    for n in (1, 2):
        _attempt(
            db_session,
            pair,
            future.id,
            status=IndexingStatus.FAILED if n == 1 else IndexingStatus.CANCELED,
            created=completed + timedelta(minutes=n),
            ended=completed + timedelta(minutes=n, seconds=30),
        )
    state = _state(db_session, pair, future)
    assert state.future_failed_streak == 2
    assert state.abandoned is False
    assert state.retry_after == completed + timedelta(
        minutes=2, seconds=30
    ) + request_retry_delay(2)

    _attempt(
        db_session,
        pair,
        future.id,
        status=IndexingStatus.INTERRUPTED,
        created=completed + timedelta(minutes=3),
        ended=completed + timedelta(minutes=3, seconds=30),
    )
    state = _state(db_session, pair, future)
    assert state.future_failed_streak == 3
    assert state.abandoned is True
    assert state.reset_hashes_at_swap is True
    assert state.catch_up_due is False

    # A later success, even one that does not cover the watermark, ends the streak.
    _attempt(
        db_session,
        pair,
        future.id,
        status=IndexingStatus.SUCCESS,
        created=completed + timedelta(minutes=4),
        ended=completed + timedelta(minutes=4, seconds=30),
        poll_range_end=completed - timedelta(hours=2),
    )
    state = _state(db_session, pair, future)
    assert state.future_failed_streak == 0
    assert state.needs_catch_up is True
    assert state.abandoned is False
    assert state.retry_after is None


def test_abandon_after_the_hold_age_cap(
    db_session: Session, pair_and_future: tuple[ConnectorCredentialPair, SearchSettings]
) -> None:
    pair, future = pair_and_future
    since = _seed(db_session, pair, future.id)
    _success_port(db_session, pair, future.id)
    _attempt(
        db_session,
        pair,
        _present_id(db_session),
        status=IndexingStatus.SUCCESS,
        ended=since + timedelta(minutes=1),
    )
    assert _state(db_session, pair, future).abandoned is False
    # The cap is read when the property is evaluated, so assert under the patch.
    with patch.object(reindex_hold_db, "REINDEX_HOLD_MAX_SECONDS", 0):
        state = _state(db_session, pair, future)
        assert state.abandoned is True
        assert state.reset_hashes_at_swap is True


def test_running_catch_up_attempt_is_not_abandoned(
    db_session: Session, pair_and_future: tuple[ConnectorCredentialPair, SearchSettings]
) -> None:
    """An attempt that still runs may catch up, and the swap waits for it, so
    the pair is not abandoned, or alerted, until the attempt ends."""
    pair, future = pair_and_future
    _seed(db_session, pair, future.id)
    port = _success_port(db_session, pair, future.id)
    assert port.time_completed is not None
    completed = port.time_completed
    _attempt(
        db_session,
        pair,
        _present_id(db_session),
        status=IndexingStatus.SUCCESS,
        ended=completed + timedelta(minutes=1),
    )
    for n in (1, 2, 3):
        _attempt(
            db_session,
            pair,
            future.id,
            status=IndexingStatus.FAILED,
            created=completed + timedelta(minutes=n),
            ended=completed + timedelta(minutes=n, seconds=30),
        )
    assert _state(db_session, pair, future).abandoned is True

    running = _attempt(
        db_session,
        pair,
        future.id,
        status=IndexingStatus.IN_PROGRESS,
        created=completed + timedelta(minutes=4),
        celery_task_id="catch-up",
    )
    state = _state(db_session, pair, future)
    assert state.future_active is True
    assert state.abandoned is False
    assert state.catch_up_due is False
    with patch.object(reindex_hold_db, "REINDEX_HOLD_MAX_SECONDS", 0):
        assert _state(db_session, pair, future).abandoned is False

    running.status = IndexingStatus.FAILED
    running.time_finished = completed + timedelta(minutes=5)
    db_session.commit()
    state = _state(db_session, pair, future)
    assert state.future_active is False
    assert state.abandoned is True


def test_retry_after_backs_off_from_the_last_failure(
    db_session: Session, pair_and_future: tuple[ConnectorCredentialPair, SearchSettings]
) -> None:
    pair, future = pair_and_future
    _seed(db_session, pair, future.id)
    port = _success_port(db_session, pair, future.id)
    assert port.time_completed is not None
    now = get_db_current_time(db_session)
    _attempt(
        db_session,
        pair,
        _present_id(db_session),
        status=IndexingStatus.SUCCESS,
        ended=port.time_completed + timedelta(seconds=1),
    )
    _attempt(
        db_session,
        pair,
        future.id,
        status=IndexingStatus.FAILED,
        created=now,
        ended=now,
    )
    state = _state(db_session, pair, future)
    assert state.future_failed_streak == 1
    assert state.retry_after == now + request_retry_delay(1)
    assert state.needs_catch_up is True
    assert state.catch_up_due is False
