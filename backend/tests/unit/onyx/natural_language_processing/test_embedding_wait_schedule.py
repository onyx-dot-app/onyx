"""The retry schedule of a blocked embedding request, on a fake clock."""

from collections.abc import Iterator
from unittest.mock import patch

import pytest

from onyx.natural_language_processing.embedding_rate_limit import (
    EmbeddingWaitTimeoutError,
    wait_sleeps,
)

_MODULE = "onyx.natural_language_processing.embedding_rate_limit"


class _FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def monotonic(self) -> float:
        return self.now


def _waits_until_timeout(clock: _FakeClock) -> list[float]:
    """Runs retries from now until the time limit; returns each wait."""
    started_at = clock.now
    waits: list[float] = []
    with pytest.raises(EmbeddingWaitTimeoutError):
        for attempt in range(1000):
            before = clock.now
            for sleep_seconds in wait_sleeps("full", attempt, started_at, None):
                clock.now += sleep_seconds
            waits.append(clock.now - before)
    return waits


@pytest.fixture
def clock() -> Iterator[_FakeClock]:
    fake = _FakeClock()
    with patch(f"{_MODULE}.time.monotonic", fake.monotonic):
        yield fake


def test_self_hosted_retries_about_once_a_minute_for_six_hours(
    clock: _FakeClock,
) -> None:
    with (
        patch(f"{_MODULE}.MULTI_TENANT", False),
        patch(f"{_MODULE}._MAX_TOTAL_WAIT_SECONDS", 6 * 60 * 60),
    ):
        waits = _waits_until_timeout(clock)

    assert all(50 <= wait <= 70 for wait in waits[:-1])
    assert sum(waits) == pytest.approx(6 * 60 * 60)


def test_cloud_backs_off_exponentially_for_one_minute(clock: _FakeClock) -> None:
    with (
        patch(f"{_MODULE}.MULTI_TENANT", True),
        patch(f"{_MODULE}._MAX_TOTAL_WAIT_SECONDS", 60.0),
    ):
        waits = _waits_until_timeout(clock)

    for attempt, wait in enumerate(waits[:5]):
        assert 2**attempt <= wait <= 2**attempt * 1.1
    # The last wait is cut short so the total stops at the time limit.
    assert sum(waits) == pytest.approx(60.0)
