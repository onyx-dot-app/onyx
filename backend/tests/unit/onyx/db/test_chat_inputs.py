from itertools import product

import pytest

from onyx.agents.models import MessageDelivery, RunStatus
from onyx.db.chat_inputs import can_start_input

_TARGETED = 7
# Stop and failure pause the queue; only interrupts and untargeted sends start.
_STARTS_AFTER_PAUSE = {
    (MessageDelivery.INTERRUPT, None),
    (MessageDelivery.INTERRUPT, _TARGETED),
    (MessageDelivery.SEND, None),
}


@pytest.mark.parametrize(
    ("status", "delivery", "target"),
    product([None, *RunStatus], [None, *MessageDelivery], [None, _TARGETED]),
)
def test_can_start_input(
    status: RunStatus | None, delivery: MessageDelivery | None, target: int | None
) -> None:
    if status in (RunStatus.RUNNING, RunStatus.SUSPENDED):
        expected = False
    elif status in (RunStatus.CANCELLED, RunStatus.ERROR):
        expected = (delivery, target) in _STARTS_AFTER_PAUSE
    else:
        # No previous run, a complete run, and a step limit leave the queue open.
        expected = True
    assert can_start_input(delivery, target, status) is expected
