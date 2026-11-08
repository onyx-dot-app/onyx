"""Fake tools for code mode tests."""

import time
from collections.abc import Callable


def until(condition: Callable[[], bool], timeout: float = 10.0) -> None:
    """Wait for `condition`; fails the test after `timeout` seconds."""
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "the condition did not hold in time"
        time.sleep(0.01)
