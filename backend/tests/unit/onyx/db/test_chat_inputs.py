from itertools import product
from uuid import uuid4

import pytest

from onyx.agents.models import MessageDelivery, RunStatus
from onyx.chat.models import AgentResultState
from onyx.db.chat_inputs import can_start_input, wakes_for_results

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


@pytest.mark.parametrize(
    ("status", "result_statuses", "expected"),
    [
        (RunStatus.COMPLETE, [RunStatus.COMPLETE], True),
        (RunStatus.LIMIT, [RunStatus.RUNNING, RunStatus.ERROR], True),
        # A late Stop or a failure keeps finished results from waking the agent.
        (RunStatus.CANCELLED, [RunStatus.COMPLETE], False),
        (RunStatus.ERROR, [RunStatus.COMPLETE], False),
        (RunStatus.RUNNING, [RunStatus.COMPLETE], False),
        (None, [RunStatus.COMPLETE], False),
        (RunStatus.COMPLETE, [RunStatus.RUNNING], False),
        (RunStatus.COMPLETE, [], False),
    ],
)
def test_wakes_for_results(
    status: RunStatus | None, result_statuses: list[RunStatus], expected: bool
) -> None:
    results = [
        AgentResultState(recipient_id=uuid4(), response_id=index, status=result)
        for index, result in enumerate(result_statuses)
    ]
    assert wakes_for_results(status, results) is expected
