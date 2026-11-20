"""The listing's pause for the conversion stage, with fake stub batch
counters and a fake clock."""

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

_MINUTE = 60.0
_BATCH_SIZE = 16


class _FakeClock:
    def __init__(self) -> None:
        self.now = 1_000.0
        self.slept = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds
        self.slept += seconds


class _FakeCounters:
    """The attempt's stub batches stored and converted."""

    def __init__(self) -> None:
        self.stored = 0
        self.converted = 0

    def read(self, _index_attempt_id: int) -> tuple[int, int]:
        return self.stored, self.converted


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> _FakeClock:
    fake = _FakeClock()
    monkeypatch.setattr(backpressure_module, "time", fake)
    return fake


@pytest.fixture
def counters(monkeypatch: pytest.MonkeyPatch) -> _FakeCounters:
    fake = _FakeCounters()
    monkeypatch.setattr(backpressure_module, "_read_stub_batch_progress", fake.read)
    monkeypatch.setattr(backpressure_module, "INDEX_BATCH_SIZE", _BATCH_SIZE)
    return fake


def _no_stop() -> None:
    return None


def _check_after(
    clock: _FakeClock, backpressure: ListingBackpressure, minutes: float
) -> float:
    clock.now += minutes * _MINUTE
    return backpressure.maybe_pause(_no_stop)


def _started(counters: _FakeCounters, stored: int) -> ListingBackpressure:
    """A listing whose first check saw ``stored`` batches and none
    converted."""
    backpressure = ListingBackpressure(1, DocumentSource.SHAREPOINT)
    counters.stored = stored
    assert backpressure.maybe_pause(_no_stop) == 0
    return backpressure


def test_no_pause_before_the_warmup_batches(
    clock: _FakeClock, counters: _FakeCounters
) -> None:
    """A large backlog and a fast conversion do not pause the listing before
    conversion converted the warm-up batches of the attempt."""
    backpressure = _started(counters, stored=10_000)
    counters.converted = LISTING_BACKPRESSURE_WARMUP_BATCHES - 1
    assert _check_after(clock, backpressure, 1) == 0
    assert clock.slept == 0

    counters.converted = LISTING_BACKPRESSURE_WARMUP_BATCHES
    assert _check_after(clock, backpressure, 1) > 0


def test_no_pause_below_the_minimum_drain_rate(
    clock: _FakeClock, counters: _FakeCounters
) -> None:
    """Slow conversion gets no pause, whatever the backlog."""
    backpressure = _started(counters, stored=10_000)
    # 2 batches per minute: 32 documents per minute.
    counters.converted = 20
    assert 2 * _BATCH_SIZE < LISTING_BACKPRESSURE_MIN_DRAIN_DOCS_PER_MINUTE

    assert _check_after(clock, backpressure, 10) == 0
    assert clock.slept == 0


def test_the_pause_is_capped_at_twenty_minutes(
    clock: _FakeClock, counters: _FakeCounters
) -> None:
    backpressure = _started(counters, stored=10_000)
    # 10 batches per minute and 9,950 waiting: about 16 hours to drain.
    counters.converted = 50

    paused = _check_after(clock, backpressure, 5)

    assert paused == LISTING_BACKPRESSURE_MAX_PAUSE_SECONDS == 20 * _MINUTE
    assert clock.slept == paused


def test_the_pause_is_what_the_backlog_needs_over_the_target(
    clock: _FakeClock, counters: _FakeCounters
) -> None:
    backpressure = _started(counters, stored=0)
    # 10 batches per minute and 400 waiting: 40 minutes to drain.
    counters.converted = 100
    counters.stored = 500

    paused = _check_after(clock, backpressure, 10)

    assert paused == pytest.approx(40 * _MINUTE - LISTING_BACKPRESSURE_TARGET_SECONDS)


def test_no_pause_when_conversion_drains_fast(
    clock: _FakeClock, counters: _FakeCounters
) -> None:
    backpressure = _started(counters, stored=0)
    # 20 batches per minute and 200 waiting: 10 minutes to drain.
    counters.converted = 100
    counters.stored = 300

    assert _check_after(clock, backpressure, 5) == 0
    assert clock.slept == 0


def test_the_listing_checks_once_per_interval(
    clock: _FakeClock, counters: _FakeCounters
) -> None:
    backpressure = _started(counters, stored=10_000)
    counters.converted = 50

    early = LISTING_BACKPRESSURE_CHECK_INTERVAL_SECONDS / 2 / _MINUTE
    assert _check_after(clock, backpressure, early) == 0
    assert _check_after(clock, backpressure, early) > 0
    # After a pause, the next check waits one interval.
    assert _check_after(clock, backpressure, early) == 0


def test_a_stop_during_a_pause_ends_it(
    clock: _FakeClock, counters: _FakeCounters
) -> None:
    backpressure = _started(counters, stored=10_000)
    counters.converted = 50
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
