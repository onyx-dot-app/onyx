"""The listing's pause for the conversion stage, with fake stub batch
counters and a fake clock. Conversion goes on at ``drain_per_minute`` while
the listing sleeps."""

import pytest

from onyx.background.indexing import listing_backpressure as backpressure_module
from onyx.background.indexing.listing_backpressure import (
    LISTING_BACKPRESSURE_CHECK_INTERVAL_SECONDS,
    LISTING_BACKPRESSURE_MAX_PAUSE_SECONDS,
    LISTING_BACKPRESSURE_MIN_DRAIN_DOCS_PER_MINUTE,
    LISTING_BACKPRESSURE_POLL_SECONDS,
    LISTING_BACKPRESSURE_TARGET_SECONDS,
    LISTING_BACKPRESSURE_WARMUP_BATCHES,
    ListingBackpressure,
)
from onyx.configs.constants import DocumentSource
from onyx.connectors.models import ConnectorStopSignal
from onyx.db.indexing_coordination import StubBatchProgress

_MINUTE = 60.0
_BATCH_SIZE = 16
_WARMUP = LISTING_BACKPRESSURE_WARMUP_BATCHES


class _FakeCounters:
    """The attempt's stub batches stored and converted. Without
    ``stored_documents``, each stored batch is full."""

    def __init__(self) -> None:
        self.stored = 0
        self.converted = 0.0
        self.stored_documents: int | None = None
        # The conversion rate while the listing sleeps.
        self.drain_per_minute = 0.0
        self.pauses = 0
        self.paused_seconds: list[float] = []

    def read(self, _index_attempt_id: int) -> StubBatchProgress:
        return StubBatchProgress(
            stored=self.stored,
            converted=int(self.converted),
            stored_documents=(
                self.stored * _BATCH_SIZE
                if self.stored_documents is None
                else self.stored_documents
            ),
        )

    def record_pause(self, _source: str) -> None:
        self.pauses += 1

    def record_paused_seconds(self, _source: str, seconds: float) -> None:
        self.paused_seconds.append(seconds)


class _FakeClock:
    def __init__(self, counters: _FakeCounters) -> None:
        self.now = 1_000.0
        self.slept = 0.0
        self._counters = counters

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds
        self.slept += seconds
        self._counters.converted = min(
            self._counters.converted
            + self._counters.drain_per_minute * seconds / _MINUTE,
            self._counters.stored,
        )


@pytest.fixture
def counters(monkeypatch: pytest.MonkeyPatch) -> _FakeCounters:
    fake = _FakeCounters()
    monkeypatch.setattr(backpressure_module, "_read_stub_batch_progress", fake.read)
    monkeypatch.setattr(backpressure_module, "INDEX_BATCH_SIZE", _BATCH_SIZE)
    # The process-wide pause counters stay unchanged.
    monkeypatch.setattr(backpressure_module, "record_listing_pause", fake.record_pause)
    monkeypatch.setattr(
        backpressure_module,
        "record_listing_paused_seconds",
        fake.record_paused_seconds,
    )
    return fake


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch, counters: _FakeCounters) -> _FakeClock:
    fake = _FakeClock(counters)
    monkeypatch.setattr(backpressure_module, "time", fake)
    return fake


def _no_stop() -> None:
    return None


def _check_after(
    clock: _FakeClock, backpressure: ListingBackpressure, minutes: float
) -> float:
    clock.now += minutes * _MINUTE
    return backpressure.maybe_pause(_no_stop)


def _warmed(
    clock: _FakeClock, counters: _FakeCounters, stored: int
) -> ListingBackpressure:
    """A listing whose first check saw ``stored`` batches and none
    converted, and whose next check, one minute later, saw the warm-up
    batches converted. That check is the baseline of the rate."""
    backpressure = ListingBackpressure(1, DocumentSource.SHAREPOINT)
    counters.stored = stored
    assert backpressure.maybe_pause(_no_stop) == 0
    counters.converted = _WARMUP
    assert _check_after(clock, backpressure, 1) == 0
    return backpressure


def test_no_pause_before_the_warmup_batches(
    clock: _FakeClock, counters: _FakeCounters
) -> None:
    """A large backlog does not pause the listing before conversion
    converted the warm-up batches, nor at the check that reaches them."""
    backpressure = ListingBackpressure(1, DocumentSource.SHAREPOINT)
    counters.stored = 10_000
    assert backpressure.maybe_pause(_no_stop) == 0
    counters.converted = _WARMUP - 1
    assert _check_after(clock, backpressure, 1) == 0
    counters.converted = _WARMUP
    assert _check_after(clock, backpressure, 1) == 0
    assert clock.slept == 0

    counters.converted = _WARMUP + 20
    assert _check_after(clock, backpressure, 1) > 0


def test_the_warmup_batches_are_not_in_the_rate(
    clock: _FakeClock, counters: _FakeCounters
) -> None:
    """Conversion starts slowly: the warm-up took 20 minutes. Then it drains
    20 batches per minute, and the 400 batches that wait need 20 minutes.
    The slow start does not make a pause."""
    backpressure = ListingBackpressure(1, DocumentSource.SHAREPOINT)
    counters.stored = 435
    assert backpressure.maybe_pause(_no_stop) == 0
    counters.converted = _WARMUP
    assert _check_after(clock, backpressure, 20) == 0
    counters.converted = _WARMUP + 20

    assert _check_after(clock, backpressure, 1) == 0
    assert clock.slept == 0


def test_no_pause_below_the_minimum_drain_rate(
    clock: _FakeClock, counters: _FakeCounters
) -> None:
    """Slow conversion gets no pause, whatever the backlog."""
    backpressure = _warmed(clock, counters, stored=10_000)
    # 2 batches per minute: 32 documents per minute.
    counters.converted += 20
    assert 2 * _BATCH_SIZE < LISTING_BACKPRESSURE_MIN_DRAIN_DOCS_PER_MINUTE

    assert _check_after(clock, backpressure, 10) == 0
    assert clock.slept == 0


def test_no_pause_below_the_minimum_rate_of_documents(
    clock: _FakeClock, counters: _FakeCounters
) -> None:
    """The minimum rate counts the documents in the batches, not full
    batches: an incremental listing stores small batches."""
    backpressure = ListingBackpressure(1, DocumentSource.SHAREPOINT)
    counters.stored = _WARMUP
    counters.stored_documents = _WARMUP
    assert backpressure.maybe_pause(_no_stop) == 0
    counters.converted = _WARMUP
    assert _check_after(clock, backpressure, 1) == 0
    # 10 batches per minute and 400 waiting: 40 minutes to drain. One
    # document in each batch: 10 documents per minute.
    counters.converted += 100
    counters.stored = int(counters.converted) + 400
    counters.stored_documents = counters.stored

    assert _check_after(clock, backpressure, 10) == 0
    assert clock.slept == 0


def test_the_pause_ends_when_the_drain_time_is_under_the_target(
    clock: _FakeClock, counters: _FakeCounters
) -> None:
    """400 batches wait at 10 batches per minute: 40 minutes. Conversion
    goes on during the pause, so after about 10 minutes the drain time is 30
    minutes and the pause ends. The paused time is recorded as it goes."""
    backpressure = _warmed(clock, counters, stored=_WARMUP)
    counters.converted += 100
    counters.stored = int(counters.converted) + 400
    counters.drain_per_minute = 10

    paused = _check_after(clock, backpressure, 10)

    assert paused == pytest.approx(
        40 * _MINUTE - LISTING_BACKPRESSURE_TARGET_SECONDS, abs=_MINUTE
    )
    assert paused < LISTING_BACKPRESSURE_MAX_PAUSE_SECONDS
    assert counters.pauses == 1
    assert len(counters.paused_seconds) > 1
    assert sum(counters.paused_seconds) == pytest.approx(paused)


def test_the_pause_is_capped_at_twenty_minutes(
    clock: _FakeClock, counters: _FakeCounters
) -> None:
    backpressure = _warmed(clock, counters, stored=10_000)
    # 10 batches per minute and about 9,900 waiting: about 16 hours.
    counters.converted += 50
    counters.drain_per_minute = 10

    paused = _check_after(clock, backpressure, 5)

    assert paused == LISTING_BACKPRESSURE_MAX_PAUSE_SECONDS == 20 * _MINUTE
    assert clock.slept == paused
    assert counters.pauses == 1


def test_no_pause_when_conversion_drains_fast(
    clock: _FakeClock, counters: _FakeCounters
) -> None:
    backpressure = _warmed(clock, counters, stored=_WARMUP)
    # 20 batches per minute and 200 waiting: 10 minutes to drain.
    counters.converted += 100
    counters.stored = int(counters.converted) + 200

    assert _check_after(clock, backpressure, 5) == 0
    assert clock.slept == 0


def test_the_listing_checks_once_per_interval(
    clock: _FakeClock, counters: _FakeCounters
) -> None:
    backpressure = _warmed(clock, counters, stored=10_000)
    counters.converted += 50
    counters.drain_per_minute = 10

    early = LISTING_BACKPRESSURE_CHECK_INTERVAL_SECONDS / 2 / _MINUTE
    assert _check_after(clock, backpressure, early) == 0
    assert _check_after(clock, backpressure, early) > 0
    # After a pause, the next check waits one interval.
    assert _check_after(clock, backpressure, early) == 0


def test_a_stop_during_a_pause_ends_it(
    clock: _FakeClock, counters: _FakeCounters
) -> None:
    backpressure = _warmed(clock, counters, stored=10_000)
    counters.converted += 50
    counters.drain_per_minute = 10
    clock.now += 5 * _MINUTE
    polls = 0

    def stop_on_third_poll() -> None:
        nonlocal polls
        polls += 1
        if polls == 3:
            raise ConnectorStopSignal("Connector stop signal detected")

    with pytest.raises(ConnectorStopSignal):
        backpressure.maybe_pause(stop_on_third_poll)

    assert clock.slept == 2 * LISTING_BACKPRESSURE_POLL_SECONDS
    assert counters.paused_seconds == [LISTING_BACKPRESSURE_POLL_SECONDS] * 2


def test_a_check_after_a_long_step_still_has_a_rate(
    clock: _FakeClock, counters: _FakeCounters
) -> None:
    """A check more than one rate window after the last one measures the
    rate from that check."""
    backpressure = _warmed(clock, counters, stored=_WARMUP)
    # 10 batches per minute over 15 minutes, and 450 waiting: 45 minutes
    # to drain.
    counters.converted += 150
    counters.stored = int(counters.converted) + 450
    counters.drain_per_minute = 10

    paused = _check_after(clock, backpressure, 15)

    assert paused == pytest.approx(
        45 * _MINUTE - LISTING_BACKPRESSURE_TARGET_SECONDS, abs=_MINUTE
    )
    assert counters.pauses == 1


def test_a_resumed_attempt_measures_its_batches_from_the_first_check(
    clock: _FakeClock, counters: _FakeCounters
) -> None:
    """A resumed attempt counts its batches from its first batch number, and
    its documents from zero. The batch size comes from the change since the
    first check."""
    backpressure = ListingBackpressure(1, DocumentSource.SHAREPOINT)
    counters.stored = 10_000
    counters.converted = 10_000
    counters.stored_documents = 0
    assert backpressure.maybe_pause(_no_stop) == 0
    counters.converted = 10_000 + _WARMUP
    counters.stored = 10_000 + _WARMUP
    counters.stored_documents = _WARMUP * _BATCH_SIZE
    assert _check_after(clock, backpressure, 1) == 0
    # 100 converted in 10 minutes and 400 waiting: 40 minutes to drain at
    # 160 documents per minute.
    counters.converted += 100
    counters.stored = int(counters.converted) + 400
    counters.stored_documents = (counters.stored - 10_000) * _BATCH_SIZE
    counters.drain_per_minute = 10

    paused = _check_after(clock, backpressure, 10)

    assert paused == pytest.approx(
        40 * _MINUTE - LISTING_BACKPRESSURE_TARGET_SECONDS, abs=_MINUTE
    )
