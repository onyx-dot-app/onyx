"""Unit tests for retry_builder (tenacity-backed retry decorator)."""

import pytest

from onyx.utils.retry_wrapper import retry_builder


def test_retry_builder_succeeds_after_transient_failures() -> None:
    """A function failing twice then succeeding returns the success value
    and is called exactly 3 times."""
    call_count = 0

    @retry_builder(tries=3, delay=0.01, backoff=1, jitter=0)
    def flaky() -> str:
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise RuntimeError("transient failure")
        return "success"

    assert flaky() == "success"
    assert call_count == 3


def test_retry_builder_reraises_original_exception() -> None:
    """A function that always raises re-raises the original exception type
    (not tenacity's RetryError) after exhausting all tries."""
    call_count = 0

    @retry_builder(tries=2, delay=0.01, backoff=1, jitter=0)
    def always_fails() -> None:
        nonlocal call_count
        call_count += 1
        raise ValueError("permanent failure")

    with pytest.raises(ValueError, match="permanent failure"):
        always_fails()
    assert call_count == 2


def test_retry_builder_does_not_retry_unlisted_exceptions() -> None:
    """A function raising an exception type outside `exceptions=` raises
    immediately, with no retries."""
    call_count = 0

    @retry_builder(tries=3, delay=0.01, backoff=1, jitter=0, exceptions=KeyError)
    def raises_unlisted() -> None:
        nonlocal call_count
        call_count += 1
        raise ValueError("not retryable")

    with pytest.raises(ValueError, match="not retryable"):
        raises_unlisted()
    assert call_count == 1
