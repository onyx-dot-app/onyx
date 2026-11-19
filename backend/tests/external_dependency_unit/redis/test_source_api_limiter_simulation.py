"""The source-API limiter against a simulated Google, at 40 times speed.

In run R5 on idxbench, the Drive budget was 600 requests a second and Google
accepted about 150 a second, a share of 0.25. The budget made a sawtooth:
it grew from the floor of 0.1 to 0.45-0.65, Google refused a burst, and 3-4
storm cuts in a row took it back to the floor. Group sync starved behind
the conversion threads.

This simulation keeps the shares. Time is 40 times faster: the limiter's
times are 40 times shorter, and Google's minute is 1.5 s. Google accepts at
most its quota in any minute and refuses the rest. A refusal reaches the
caller after the request's latency, so a burst sends refusals after the cut
that it caused.
"""

import collections
import statistics
import threading
import time
from collections.abc import Iterator
from uuid import uuid4

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors import source_api_limiter
from onyx.connectors.source_api_limiter import RedisSourceApiLimiter, SourceApiBudget
from onyx.redis import redis_rate_window
from onyx.redis.redis_pool import get_redis_client

_API = "drive"
_SPEED = 40.0
# Real seconds for each second of the bench.
_SCALE = 1 / _SPEED
# The budget: 400 requests a second, in windows of 10 bench seconds.
_BUDGET_PER_SECOND = 400
# Google accepts a share of 0.25 of the budget, in any bench minute.
_GOOGLE_SHARE = 0.25
_GOOGLE_MINUTE = 60 * _SCALE
# The time that a request takes, 2 bench seconds.
_LATENCY = 2 * _SCALE
_CONVERSION_THREADS = 32
_RUN_SECONDS = 24.0
# The last part of the run, when the budget must have settled.
_SETTLED_SECONDS = 12.0


class _Google:
    """Accepts at most its quota of requests in any minute."""

    def __init__(self, per_minute: int) -> None:
        self._per_minute = per_minute
        self._accepted: collections.deque[float] = collections.deque()
        self._lock = threading.Lock()
        self.answers: list[tuple[float, bool]] = []

    def send(self) -> bool:
        now = time.monotonic()
        with self._lock:
            while self._accepted and self._accepted[0] <= now - _GOOGLE_MINUTE:
                self._accepted.popleft()
            accepted = len(self._accepted) < self._per_minute
            if accepted:
                self._accepted.append(now)
            self.answers.append((now, accepted))
        return accepted


@pytest.fixture
def tenant_id() -> Iterator[str]:
    tenant = f"tenant_test_{uuid4().hex[:12]}"
    yield tenant
    client = get_redis_client(tenant_id=tenant)
    for key in client.scan_iter("*"):
        client.delete(key)


@pytest.fixture
def fast_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    """The limiter's times, 40 times shorter."""
    module = redis_rate_window
    for name, seconds in (
        ("REFUSAL_WINDOW_SECONDS", module.REFUSAL_WINDOW_SECONDS),
        ("CUT_HOLD_SECONDS", module.CUT_HOLD_SECONDS),
        ("STORM_RECUT_SECONDS", module.STORM_RECUT_SECONDS),
        ("GROW_INTERVAL_SECONDS", module.GROW_INTERVAL_SECONDS),
    ):
        monkeypatch.setattr(module, name, seconds * _SCALE)


def test_the_budget_settles_near_the_rate_that_google_accepts(
    tenant_id: str, fast_limiter: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ = fast_limiter
    budget = SourceApiBudget(
        per_credential=int(_BUDGET_PER_SECOND * 60 * _SCALE),
        period_seconds=60 * _SCALE,
        window_seconds=10 * _SCALE,
        count_requests=True,
    )
    limiter = RedisSourceApiLimiter(
        tenant_id,
        f"google_drive:{uuid4().hex}",
        {_API: budget},
        source=DocumentSource.GOOGLE_DRIVE,
    )
    window = limiter.credential_window(_API)
    assert window is not None
    google = _Google(int(_BUDGET_PER_SECOND * _GOOGLE_SHARE * 60 * _SCALE))

    cuts: list[float] = []
    record_cut = source_api_limiter.record_limiter_cut

    def recording_cut(
        source: str, api: str, scope: source_api_limiter.LimiterScope
    ) -> None:
        cuts.append(time.monotonic())
        record_cut(source, api, scope)

    monkeypatch.setattr(source_api_limiter, "record_limiter_cut", recording_cut)

    started = time.monotonic()
    stop = threading.Event()
    sync_waits: list[float] = []
    conversion_waits: list[float] = []

    def request() -> None:
        accepted = google.send()
        time.sleep(_LATENCY)  # test-flakes: allow the request's latency
        if not accepted:
            limiter.report_rate_limit(_API, None, user_scope=False)

    def conversion() -> None:
        while not stop.is_set():
            asked = time.monotonic()
            limiter.acquire(_API, 1, bulk=True)
            conversion_waits.append(time.monotonic() - asked)
            request()

    def group_sync() -> None:
        # One thread of listing calls, one after the other, as group sync.
        while not stop.is_set():
            asked = time.monotonic()
            limiter.acquire(_API, 1)
            sync_waits.append(time.monotonic() - asked)
            request()

    factors: list[tuple[float, float]] = []
    client = get_redis_client(tenant_id=tenant_id)

    def sample() -> None:
        while not stop.is_set():
            factor = client.hget(f"{window.key}:meta", "factor")
            factors.append(
                (time.monotonic(), float(factor) if factor is not None else 1.0)
            )
            stop.wait(0.05)

    threads = [
        threading.Thread(target=conversion) for _ in range(_CONVERSION_THREADS)
    ] + [threading.Thread(target=group_sync), threading.Thread(target=sample)]
    for thread in threads:
        thread.start()
    # The simulation runs for 16 bench minutes.
    stop.wait(_RUN_SECONDS)
    stop.set()
    for thread in threads:
        thread.join(timeout=30)

    settled_from = started + _RUN_SECONDS - _SETTLED_SECONDS
    settled = [factor for at, factor in factors if at >= settled_from]
    mean = statistics.mean(settled)
    summary = (mean, min(settled), max(settled), [at - started for at in cuts])
    # R5 swung between 0.1 and 0.65 with a mean of 0.19. The budget now stays
    # near Google's share of 0.25.
    assert 0.2 <= mean <= 0.32, summary
    assert min(settled) >= 0.15, summary
    assert max(settled) <= 0.4, summary

    # One burst gives one cut: after the burst at the start, no cut follows
    # another in the same hold.
    settled_cuts = [at for at in cuts if at >= settled_from]
    gaps = [
        later - earlier
        for earlier, later in zip(settled_cuts, settled_cuts[1:], strict=False)
    ]
    assert all(gap >= redis_rate_window.CUT_HOLD_SECONDS for gap in gaps), summary

    answers = [accepted for at, accepted in google.answers if at >= settled_from]
    refused_share = answers.count(False) / len(answers)
    assert refused_share < 0.05, (refused_share, summary)

    # Group sync gets its slots while 32 conversion threads wait for theirs.
    assert len(sync_waits) > 100
    assert statistics.median(sync_waits) < _SCALE, statistics.median(sync_waits)
    assert statistics.mean(sync_waits) * 5 < statistics.mean(conversion_waits), (
        statistics.mean(sync_waits),
        statistics.mean(conversion_waits),
    )
