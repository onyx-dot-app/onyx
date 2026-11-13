from itertools import count, product
from uuid import UUID, uuid4

import pytest

from onyx.agents.models import MessageDelivery, RunFailure, RunFailureKind, RunStatus
from onyx.chat.models import AgentResultState, AgentWait
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
        AgentResultState(
            recipient_id=uuid4(),
            agent_id=uuid4(),
            response_id=index,
            root_response_id=1,
            status=result,
        )
        for index, result in enumerate(result_statuses)
    ]
    assert wakes_for_results(status, results, queue_paused=False) is expected


def test_a_paused_queue_keeps_finished_results_from_waking_the_recipient() -> None:
    results = [
        AgentResultState(
            recipient_id=uuid4(),
            agent_id=uuid4(),
            response_id=1,
            root_response_id=1,
            status=RunStatus.COMPLETE,
        )
    ]
    assert not wakes_for_results(RunStatus.COMPLETE, results, queue_paused=True)
    assert agent_queue_paused(RunStatus.CANCELLED)
    assert not agent_queue_paused(RunStatus.COMPLETE)


_ROOT = uuid4()
_ALPHA, _BETA = uuid4(), uuid4()
_WAIT_RESPONSE = 10
_RUN_IDS = count(100)


def _result(
    agent: UUID,
    status: RunStatus,
    *,
    root: int = _WAIT_RESPONSE,
    stopped: bool = False,
) -> AgentResultState:
    return AgentResultState(
        recipient_id=_ROOT,
        agent_id=agent,
        response_id=next(_RUN_IDS),
        root_response_id=root,
        status=status,
        failure=RunFailure(kind=RunFailureKind.STOPPED_BY_USER, message="Stopped")
        if stopped
        else None,
    )


def _wait(agents: set[UUID] | None, *, queued: bool = False) -> AgentWait:
    return AgentWait(
        response_id=_WAIT_RESPONSE,
        agent_ids=frozenset(agents) if agents is not None else None,
        queued=queued,
    )


_DONE, _RUNNING = RunStatus.COMPLETE, RunStatus.RUNNING


@pytest.mark.parametrize(
    ("results", "waits", "expected"),
    [
        # A wait holds a finished result while one of its agents runs.
        ([_result(_ALPHA, _DONE), _result(_BETA, _RUNNING)], [_wait(None)], False),
        # A result that no wait holds wakes the root at once.
        ([_result(_ALPHA, _DONE), _result(_BETA, _RUNNING)], [_wait({_BETA})], True),
        # Runs of a later root response are not held.
        (
            [_result(_ALPHA, _DONE, root=11), _result(_BETA, _RUNNING)],
            [_wait(None)],
            True,
        ),
        # When none of its runs is active, a failure counts as finished.
        (
            [_result(_ALPHA, _DONE), _result(_BETA, RunStatus.ERROR)],
            [_wait(None)],
            True,
        ),
        # An interrupted run left no result, so it holds nothing back.
        ([_result(_ALPHA, _DONE)], [_wait({_ALPHA, _BETA})], True),
        # A queued message to a held agent will start a run.
        ([_result(_ALPHA, _DONE)], [_wait(None, queued=True)], False),
        # A result wakes the root only when every wait that holds it is released.
        (
            [_result(_ALPHA, _DONE), _result(_BETA, _RUNNING)],
            [_wait({_ALPHA}), _wait(None)],
            False,
        ),
        # Stopped runs wake nobody, with or without a wait.
        ([_result(_ALPHA, RunStatus.CANCELLED, stopped=True)], [_wait(None)], False),
    ],
    ids=[
        "held",
        "unawaited",
        "later_turn",
        "failed",
        "interrupted",
        "queued",
        "overlapping",
        "stopped",
    ],
)
def test_a_wait_holds_its_results_until_its_agents_finish(
    results: list[AgentResultState], waits: list[AgentWait], expected: bool
) -> None:
    assert (
        wakes_for_results(
            RunStatus.COMPLETE, results, queue_paused=False, waits=lambda: waits
        )
        is expected
    )
    # A Stop pauses the queue, so nothing wakes during a wait either.
    assert not wakes_for_results(
        RunStatus.COMPLETE, results, queue_paused=True, waits=lambda: waits
    )
