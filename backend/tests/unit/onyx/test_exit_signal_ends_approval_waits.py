"""uvicorn waits for open responses before the lifespan shutdown, so its exit
signal, not the lifespan, ends chat turns that wait for the user's approval."""

import signal
from collections.abc import Generator
from types import FrameType

import pytest

from onyx.chat.tool_approvals import approval_waits_ending, reset_approval_waits
from onyx.main import _end_approval_waits_on_exit_signal


@pytest.fixture
def server_handlers() -> Generator[list[int], None, None]:
    """Exit signal handlers that stand in for uvicorn's, which record the
    signals they receive."""
    received: list[int] = []

    def server_handler(signum: int, _frame: FrameType | None) -> None:
        received.append(signum)

    previous = {
        exit_signal: signal.signal(exit_signal, server_handler)
        for exit_signal in (signal.SIGINT, signal.SIGTERM)
    }
    try:
        yield received
    finally:
        for exit_signal, handler in previous.items():
            signal.signal(exit_signal, handler)
        reset_approval_waits()


def test_an_exit_signal_ends_approval_waits_then_reaches_the_server(
    server_handlers: list[int],
) -> None:
    _end_approval_waits_on_exit_signal()
    assert not approval_waits_ending()

    signal.raise_signal(signal.SIGTERM)

    assert approval_waits_ending()
    assert server_handlers == [signal.SIGTERM]
