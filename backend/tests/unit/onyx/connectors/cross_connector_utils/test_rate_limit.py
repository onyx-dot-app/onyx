import threading
import time
from types import SimpleNamespace
from typing import Any, cast

import pytest
import requests

from onyx.connectors.cross_connector_utils import rate_limit_wrapper
from onyx.connectors.cross_connector_utils.rate_limit_wrapper import (
    RateLimitTriedTooManyTimesError,
    rate_limit_builder,
    wrap_request_to_handle_ratelimiting,
)


def test_rate_limit_basic() -> None:
    call_cnt = 0

    @rate_limit_builder(max_calls=2, period=5)
    def func() -> None:
        nonlocal call_cnt
        call_cnt += 1

    start = time.time()

    # Make calls that shouldn't be rate-limited
    func()
    func()
    time_to_finish_non_ratelimited = time.time() - start

    # Make a call which SHOULD be rate-limited
    func()
    time_to_finish_ratelimited = time.time() - start

    assert call_cnt == 3
    assert time_to_finish_non_ratelimited < 1
    assert time_to_finish_ratelimited > 5


def test_rate_limit_holds_across_threads(monkeypatch: pytest.MonkeyPatch) -> None:
    """Parallel callers never pass the limit. Each caller's second clock read
    records its call; the barrier there holds every caller that passed the
    limit check, so without a lock all of them record. Callers past the limit
    give up, since the period outlasts the test."""
    max_calls = 2
    callers = 16
    records_meet = threading.Barrier(callers, timeout=0.5)
    clock_reads = threading.local()

    def monotonic() -> float:
        clock_reads.count = vars(clock_reads).get("count", 0) + 1
        if clock_reads.count == 2:
            try:
                records_meet.wait()
            except threading.BrokenBarrierError:
                pass
        return time.monotonic()

    monkeypatch.setattr(
        rate_limit_wrapper,
        "time",
        SimpleNamespace(monotonic=monotonic, sleep=time.sleep),
    )
    calls = 0
    refused = 0
    counts_lock = threading.Lock()

    @rate_limit_builder(max_calls=max_calls, period=60, sleep_time=0, max_num_sleep=1)
    def func() -> None:
        nonlocal calls
        with counts_lock:
            calls += 1

    all_started = threading.Barrier(callers, timeout=10)

    def call() -> None:
        nonlocal refused
        all_started.wait()
        try:
            func()
        except RateLimitTriedTooManyTimesError:
            with counts_lock:
                refused += 1

    threads = [threading.Thread(target=call) for _ in range(callers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert calls == max_calls
    assert refused == callers - max_calls


class _FakeResponse:
    def __init__(self, status_code: int, retry_after: str | None = None) -> None:
        self.status_code = status_code
        self.headers: dict[str, str] = {}
        if retry_after is not None:
            self.headers["Retry-After"] = retry_after


def test_wrap_request_caps_absurd_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A finite-but-huge Retry-After would make `time.sleep` raise OverflowError;
    # the wrapper must cap it so the request can still recover.
    responses = iter([_FakeResponse(429, retry_after="1e300"), _FakeResponse(200)])
    slept: list[float] = []

    monkeypatch.setattr(time, "sleep", lambda s: slept.append(s))

    def _request_fn(*args: Any, **kwargs: Any) -> requests.Response:  # noqa: ARG001
        return cast(requests.Response, next(responses))

    wrapped = wrap_request_to_handle_ratelimiting(
        _request_fn,
        max_wait_time_sec=300,
    )

    result = wrapped()

    assert result.status_code == 200
    assert slept == [300]
