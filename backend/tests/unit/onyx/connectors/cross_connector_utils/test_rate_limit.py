import time

from onyx.connectors.cross_connector_utils.rate_limit_wrapper import (
    rate_limit_builder,
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
