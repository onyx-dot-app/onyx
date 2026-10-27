from contextlib import ExitStack
from functools import partial

import pytest

from onyx.llm.cancellation import AgentCancelled, CancellationSignal


@pytest.mark.parametrize("already_cancelled", [False, True])
@pytest.mark.parametrize("failure", [AgentCancelled, RuntimeError])
def test_callback_failure_does_not_interrupt_notifications(
    already_cancelled: bool, failure: type[BaseException]
) -> None:
    signal = CancellationSignal()
    observed: list[int] = []
    if already_cancelled:
        signal.cancel()

    def notify(index: int) -> None:
        observed.append(index)
        assert signal.cancelled
        if failure is AgentCancelled:
            signal.check()
        raise failure()

    with ExitStack() as callbacks:
        for index in range(3):
            callbacks.enter_context(signal.on_cancel(partial(notify, index)))
        signal.cancel()
        signal.cancel()

    assert sorted(observed) == [0, 1, 2]
    with pytest.raises(AgentCancelled):
        signal.check()


@pytest.mark.parametrize("already_cancelled", [False, True])
def test_callback_can_register_another_listener_during_cancellation(
    already_cancelled: bool,
) -> None:
    signal = CancellationSignal()
    observed: list[str] = []
    if already_cancelled:
        signal.cancel()

    def notify() -> None:
        with signal.on_cancel(signal.check):
            with signal.on_cancel(lambda: observed.append("nested")):
                signal.cancel()
        observed.append("outer")

    with signal.on_cancel(notify):
        signal.cancel()

    assert observed == ["nested", "outer"]
