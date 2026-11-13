from itertools import product
from uuid import uuid4

import pytest

from onyx.agents.models import MessageDelivery, RunStatus
from onyx.chat.models import AgentResultState
from onyx.db.chat_inputs import agent_queue_paused, can_start_input, wakes_for_results

_TARGETED = 7
# Stop and failure hold the queue; only interrupts and untargeted sends start.
_STARTS_AFTER_PAUSE = {
    (MessageDelivery.INTERRUPT, None),
    (MessageDelivery.INTERRUPT, _TARGETED),
    (MessageDelivery.SEND, None),
}


@pytest.mark.parametrize(
    ("status", "delivery", "target", "paused"),
    product(
        [None, *RunStatus],
        [None, *MessageDelivery],
        [None, _TARGETED],
        [False, True],
    ),
)
def test_can_start_input(
    status: RunStatus | None,
    delivery: MessageDelivery | None,
    target: int | None,
    paused: bool,
) -> None:
    if status in (RunStatus.RUNNING, RunStatus.SUSPENDED):
        expected = False
    elif paused or status == RunStatus.ERROR:
        expected = (delivery, target) in _STARTS_AFTER_PAUSE
    else:
        # A finished, limited, or cancelled run leaves an unpaused queue open.
        expected = True
    assert can_start_input(delivery, target, status, queue_paused=paused) is expected


@pytest.mark.parametrize(
    ("status", "result_statuses", "expected"),
    [
        (RunStatus.COMPLETE, [RunStatus.COMPLETE], True),
        (RunStatus.LIMIT, [RunStatus.RUNNING, RunStatus.ERROR], True),
        # A failure keeps finished results from waking the recipient.
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
    assert wakes_for_results(status, results, queue_paused=False) is expected


def test_a_paused_queue_keeps_finished_results_from_waking_the_recipient() -> None:
    results = [
        AgentResultState(recipient_id=uuid4(), response_id=1, status=RunStatus.COMPLETE)
    ]
    assert not wakes_for_results(RunStatus.COMPLETE, results, queue_paused=True)
    assert agent_queue_paused(RunStatus.CANCELLED)
    assert not agent_queue_paused(RunStatus.COMPLETE)
