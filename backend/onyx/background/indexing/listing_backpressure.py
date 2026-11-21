"""Coarse flow control between a listing and the conversion stage.

The listing of a conversion-stage connector can store stub batches much faster
than conversion drains them. A stub that waits long goes stale (a SharePoint
download link expires after about one hour), and the backlog fills the stub
store. So, at an interval, the listing compares the backlog of its attempt
with the rate at which conversion drained it recently. When the backlog needs
more than ``LISTING_BACKPRESSURE_TARGET_SECONDS`` to drain, the listing pauses
in steps of the check interval. After each step it measures again, and the
pause ends when the drain time is under the target, or after
``LISTING_BACKPRESSURE_MAX_PAUSE_SECONDS`` in all.

It pauses only when conversion is fast: at or above
``LISTING_BACKPRESSURE_MIN_DRAIN_DOCS_PER_MINUTE``. Slow conversion usually
means that other connectors load the conversion workers. Then the extra source
calls of stale stubs (for SharePoint, 1 RU for each Graph ``/content``
fallback) are few, and a pause only makes the run longer. It also pauses only
after conversion converted ``LISTING_BACKPRESSURE_WARMUP_BATCHES`` batches of
the attempt. The rate counts only the batches converted after that point, so
the slow start of conversion is not in the rate.

The pause is flow control, not a time limit. The docfetching heartbeat runs in
its own thread, so the watchdog sees the attempt alive during a pause, and the
pause checks for a stop or a cancel at each poll.
"""

import time
from collections import deque
from collections.abc import Callable

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.indexing_coordination import IndexingCoordination, StubBatchProgress
from onyx.server.metrics.listing_backpressure_metrics import (
    record_listing_pause,
    record_listing_paused_seconds,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

# The listing checks the backlog at most this often, between checkpoints.
LISTING_BACKPRESSURE_CHECK_INTERVAL_SECONDS = 60.0
# The drain rate is the conversions over about this much recent time.
LISTING_BACKPRESSURE_RATE_WINDOW_SECONDS = 10 * 60.0
# The listing pauses when the backlog needs longer than this to drain.
LISTING_BACKPRESSURE_TARGET_SECONDS = 30 * 60.0
LISTING_BACKPRESSURE_MAX_PAUSE_SECONDS = 20 * 60.0
# How often a pause checks for a stop or a cancel.
LISTING_BACKPRESSURE_POLL_SECONDS = 10.0
# No pause while conversion is slower than this. At 100 documents per minute,
# a /content fallback for every SharePoint file adds 100 RU per minute, 8 % of
# the lowest Microsoft tier (1,250 RU per minute). Below it the extra calls
# do not matter.
LISTING_BACKPRESSURE_MIN_DRAIN_DOCS_PER_MINUTE = 100.0
# No pause before conversion converted this many batches of the attempt.
LISTING_BACKPRESSURE_WARMUP_BATCHES = 15


def _read_stub_batch_progress(index_attempt_id: int) -> StubBatchProgress:
    with get_session_with_current_tenant() as db_session:
        return IndexingCoordination.get_stub_batch_progress(
            db_session, index_attempt_id
        )


class ListingBackpressure:
    """Pauses one attempt's listing while conversion is far behind it."""

    def __init__(self, index_attempt_id: int, source: DocumentSource) -> None:
        self._index_attempt_id = index_attempt_id
        self._source = source
        self._last_check: float | None = None
        # The converted count at the first check, the start of the warm-up.
        self._first_converted: int | None = None
        # (stub batches stored, documents in them) at the first check. The
        # stored count starts at the attempt's first batch number and holds
        # batches taken over from an earlier attempt, and the document count
        # does not, so only the change from this check gives a batch size.
        self._first_stored: tuple[int, int] | None = None
        # (monotonic time, stub batches converted) at each recent check.
        self._samples: deque[tuple[float, int]] = deque()

    def maybe_pause(self, raise_if_stopped: Callable[[], None]) -> float:
        """Checks the backlog when the interval has passed, and pauses while
        conversion is far behind. Returns the seconds paused.
        ``raise_if_stopped`` raises when the attempt must stop; a pause calls
        it at each poll and lets its exception through."""
        now = time.monotonic()
        if (
            self._last_check is not None
            and now - self._last_check < LISTING_BACKPRESSURE_CHECK_INTERVAL_SECONDS
        ):
            return 0.0
        self._last_check = now
        over_target = self._seconds_over_target(now)
        if over_target <= 0:
            return 0.0

        record_listing_pause(self._source.value)
        paused = 0.0
        while over_target > 0 and paused < LISTING_BACKPRESSURE_MAX_PAUSE_SECONDS:
            step = min(
                LISTING_BACKPRESSURE_CHECK_INTERVAL_SECONDS,
                over_target,
                LISTING_BACKPRESSURE_MAX_PAUSE_SECONDS - paused,
            )
            paused += self._pause(step, raise_if_stopped)
            over_target = self._seconds_over_target(time.monotonic())
        logger.info(
            "Listing paused for conversion: attempt=%s source=%s paused_s=%.0f",
            self._index_attempt_id,
            self._source.value,
            paused,
        )
        # The next check is one interval after the pause.
        self._last_check = time.monotonic()
        return paused

    def _seconds_over_target(self, now: float) -> float:
        """Reads the attempt's progress and returns how much longer than the
        target the backlog needs to drain, or 0 for no pause."""
        progress = _read_stub_batch_progress(self._index_attempt_id)
        stored, converted = progress.stored, progress.converted
        if self._first_converted is None:
            self._first_converted = converted
        if self._first_stored is None:
            self._first_stored = (stored, progress.stored_documents)
        first_stored, first_documents = self._first_stored
        if converted - self._first_converted < LISTING_BACKPRESSURE_WARMUP_BATCHES:
            return 0.0
        # The first sample after the warm-up is the baseline, so the batches
        # of the warm-up are not in the rate.
        self._samples.append((now, converted))
        # The baseline is the newest sample at or before the window start,
        # so a check after a long step still has a rate.
        while (
            len(self._samples) > 2
            and now - self._samples[1][0] >= LISTING_BACKPRESSURE_RATE_WINDOW_SECONDS
        ):
            self._samples.popleft()
        first_time, first_converted = self._samples[0]
        elapsed = now - first_time
        drained = converted - first_converted
        backlog = stored - converted
        if elapsed <= 0 or drained <= 0 or backlog <= 0:
            return 0.0

        drain_rate = drained / elapsed
        # A stub batch holds up to INDEX_BATCH_SIZE documents, and fewer when
        # the listing dropped unchanged documents from it.
        new_batches = stored - first_stored
        documents_per_batch = (
            min(
                (progress.stored_documents - first_documents) / new_batches,
                INDEX_BATCH_SIZE,
            )
            if new_batches > 0
            else INDEX_BATCH_SIZE
        )
        if (
            drain_rate * 60 * documents_per_batch
            < LISTING_BACKPRESSURE_MIN_DRAIN_DOCS_PER_MINUTE
        ):
            return 0.0
        drain_seconds = backlog / drain_rate
        logger.debug(
            "Listing backlog: attempt=%s backlog_batches=%s "
            "drain_batches_per_min=%.2f drain_min=%.1f",
            self._index_attempt_id,
            backlog,
            drain_rate * 60,
            drain_seconds / 60,
        )
        return max(0.0, drain_seconds - LISTING_BACKPRESSURE_TARGET_SECONDS)

    def _pause(self, seconds: float, raise_if_stopped: Callable[[], None]) -> float:
        """Sleeps for one step and adds each poll's time to the metric. The
        polls add up to the step, so the step always ends."""
        slept = 0.0
        while True:
            raise_if_stopped()
            if slept >= seconds:
                return slept
            poll = min(LISTING_BACKPRESSURE_POLL_SECONDS, seconds - slept)
            time.sleep(poll)
            slept += poll
            record_listing_paused_seconds(self._source.value, poll)
