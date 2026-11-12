from itertools import product
from uuid import uuid4

import pytest

from onyx.agents.models import MessageDelivery, RunFailure, RunFailureKind, RunStatus
from onyx.chat.models import AgentResultState, AgentWaitState
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


_DONE = RunStatus.COMPLETE
_RUNNING = RunStatus.RUNNING


@pytest.mark.parametrize(
    ("results", "waits", "expected"),
    [
        # A wait holds its finished results while one of its runs is active.
        ({1: _DONE, 2: _RUNNING}, [{1: _DONE, 2: _RUNNING}], False),
        # A finished result that no wait names wakes the root at once.
        ({1: _DONE, 2: _RUNNING, 3: _DONE}, [{1: _DONE, 2: _RUNNING}], True),
        # When every awaited run finishes, its results wake the root together.
        ({1: _DONE, 2: RunStatus.ERROR}, [{1: _DONE, 2: RunStatus.ERROR}], True),
        # An awaited run without a result, as after an interrupt, still counts
        # as finished; the others' results wake the root.
        ({1: _DONE}, [{1: _DONE, 2: RunStatus.CANCELLED}], True),
        # One finished wait wakes the root even if a later wait names its run.
        ({1: _DONE}, [{1: _DONE}, {1: _DONE, 2: _RUNNING}], True),
        # A wait whose runs left no result wakes nobody.
        ({}, [{1: RunStatus.CANCELLED}], False),
    ],
    ids=[
        "held",
        "unawaited",
        "finished",
        "interrupted",
        "overlapping",
        "no_results",
    ],
)
def test_waits_hold_their_results_until_every_awaited_run_finishes(
    results: dict[int, RunStatus],
    waits: list[dict[int, RunStatus]],
    expected: bool,
) -> None:
    assert (
        wakes_for_results(
            RunStatus.COMPLETE,
            [
                AgentResultState(recipient_id=uuid4(), response_id=run, status=status)
                for run, status in results.items()
            ],
            queue_paused=False,
            waits=[AgentWaitState(run_statuses=wait) for wait in waits],
        )
        is expected
    )


def test_a_finished_wait_of_stopped_runs_wakes_nobody() -> None:
    stopped = AgentResultState(
        recipient_id=uuid4(),
        response_id=1,
        status=RunStatus.CANCELLED,
        failure=RunFailure(kind=RunFailureKind.STOPPED_BY_USER, message="Stopped"),
    )
    assert not wakes_for_results(
        RunStatus.COMPLETE,
        [stopped],
        queue_paused=False,
        waits=[AgentWaitState(run_statuses={1: RunStatus.CANCELLED})],
    )
