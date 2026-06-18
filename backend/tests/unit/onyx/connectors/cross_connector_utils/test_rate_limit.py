import time
from typing import Any
from typing import cast

import pytest
import requests

from onyx.connectors.cross_connector_utils.rate_limit_wrapper import rate_limit_builder
from onyx.connectors.cross_connector_utils.rate_limit_wrapper import (
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
