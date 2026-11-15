"""The runtime asks the coordinator's approvals only for calls that require it,
and saves the requests that calls wait for, direct or made by a tool."""

import threading
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from functools import partial

import pytest
from pydantic import JsonValue

from onyx.agents.agent_coordination import AgentCoordinator, ToolApprovals
from onyx.agents.events import AgentEvent, InputEndedEvent, InputRequiredEvent
from onyx.agents.models import AgentState, RunState, RunStatus, ToolCallContext
from onyx.agents.runtime import Agent, Run
from onyx.agents.tool_execution import UNAVAILABLE_CALL_MESSAGE
from onyx.agents.tools import (
    AgentTool,
    HumanToolAnswer,
    InputDecision,
    InputMode,
    NestedInputAnswer,
    NestedInputRequest,
    NestedInputWait,
    PendingToolInput,
    ToolInvocation,
    ToolOutcome,
)
from onyx.llm.interfaces import GenerationContext
from onyx.llm.models import (
    AssistantMessage,
    TextContent,
    ToolCall,
    ToolDefinition,
    ToolResult,
    UserMessage,
)
from onyx.tools.interface import merge_tool_arguments
from onyx.tracing.flows import LLMFlow
from tests.unit.onyx.agents.fakes import FakeModelClient

Outcome = PendingToolInput | ToolResult | None


class Approvals(ToolApprovals):
    """Answers each requiring call with the outcome set for its name, and
    records the requests that tools withdraw."""

    def __init__(self, outcomes: dict[str, Outcome]) -> None:
        self.outcomes = outcomes
        self.requested: list[str] = []
        self.withdrawn: list[str] = []
        self._lock = threading.Lock()

    def request_approval(
        self,
        run: Run,  # noqa: ARG002
        tool_call: ToolCall,
        nested_call: ToolCall | None,
    ) -> Outcome:
        call = nested_call or tool_call
        with self._lock:
            self.requested.append(call.id)
        return self.outcomes[call.name]

    def withdraw_approval(self, request_id: str) -> None:
        with self._lock:
            self.withdrawn.append(request_id)


def _request(request_id: str) -> PendingToolInput:
    return PendingToolInput(
        request_id=request_id, prompt="Allow?", mode=InputMode.EXECUTE
    )


def _approve(request_id: str) -> HumanToolAnswer:
    return HumanToolAnswer(request_id=request_id, decision=InputDecision.APPROVE)


def _agent(
    calls: list[ToolCall],
    tools: list[AgentTool],
    before_tool_call: Callable[[ToolCallContext], Outcome] | None = None,
    state: AgentState | None = None,
) -> Agent:
    """Asks for `calls`, then answers "done" once their results arrive."""

    def reply(*_: object) -> AssistantMessage:
        nonlocal answered
        if answered:
            return AssistantMessage(content=[TextContent(text="done")])
        answered = True
        return AssistantMessage(content=list(calls))

    answered = state is not None
    return Agent(
        FakeModelClient(reply),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        agent_id="agent",
        state=state,
        tools=tools,
        before_tool_call=before_tool_call,
    )


def _run(
    calls: list[ToolCall],
    tools: list[AgentTool],
    approvals: ToolApprovals | None,
    before_tool_call: Callable[[ToolCallContext], Outcome] | None = None,
    on_event: Callable[[AgentEvent], None] | None = None,
) -> Run:
    return _agent(calls, tools, before_tool_call).start(
        max_steps=2,
        messages=[UserMessage(content="Go")],
        coordinator=AgentCoordinator(approvals=approvals),
        on_event=on_event,
    )


def _recording_tool(
    name: str, executed: list[str], *, approval_required: bool
) -> AgentTool:
    def execute(invocation: ToolInvocation) -> ToolResult:
        executed.append(invocation.call_id)
        return ToolResult(content=f"{name} ran")

    return AgentTool(
        definition=ToolDefinition(name=name, description="", parameters={}),
        execute=execute,
        approval_required=[name] if approval_required else [],
    )


def _until_pending(run: Run, request_id: str) -> None:
    deadline = time.monotonic() + 5
    while request_id not in {request.request_id for request in run.pending_inputs}:
        assert run.snapshot().failure is None
        assert time.monotonic() < deadline
        time.sleep(0.01)


def _program_tool(
    executed: list[str],
    *,
    keeps_waiting: bool = True,
    started: list[str] | None = None,
) -> AgentTool:
    """A tool that makes one `send` call for the model. The call waits in a
    NestedInputWait, and the tool continues with the answer; without
    `keeps_waiting`, the tool withdraws the request and returns at once.
    `started` records each start of the tool."""
    inner = ToolCall(id="inner-call", name="send", arguments={})

    def program(invocation: ToolInvocation) -> ToolOutcome:
        gate = invocation.nested_calls
        assert gate is not None
        if started is not None:
            started.append(invocation.call_id)
        decision = gate.decide(inner)
        assert isinstance(decision, NestedInputRequest)
        if not keeps_waiting:
            gate.withdraw(decision)
            return ToolResult(content="program stopped waiting")
        return NestedInputWait(requests=[decision])

    def resume_with_input(
        invocation: ToolInvocation, answers: list[NestedInputAnswer]
    ) -> ToolOutcome:
        gate = invocation.nested_calls
        assert gate is not None
        (answered,) = answers
        if answered.answer.decision != InputDecision.APPROVE:
            assert answered.answer.result is not None
            return answered.answer.result
        executed.append(inner.id)
        return ToolResult(content="send ran")

    return AgentTool(
        definition=ToolDefinition(name="program", description="", parameters={}),
        execute=program,
        resume_with_input=resume_with_input,
        approval_required=["send"],
    )


def _until_suspended(run: Run) -> RunState:
    state = run.wait_until_settled(timeout=5)
    assert state.status == RunStatus.SUSPENDED, state.failure
    assert run.wait_for_idle(5)
    return state


def _results(run: Run) -> dict[str, str]:
    results: dict[str, str] = {}
    for call_id, record in run.snapshot().steps[0].tools.items():
        assert record.result is not None
        results[call_id] = record.result.text
    return results


@pytest.mark.parametrize(
    "outcome, result",
    [
        (None, "send ran"),
        (ToolResult(content="blocked", is_error=True), "blocked"),
    ],
    ids=["approved_by_grant", "final_result"],
)
def test_only_calls_that_require_approval_are_asked(
    outcome: Outcome, result: str
) -> None:
    executed: list[str] = []
    approvals = Approvals({"send": outcome})
    run = _run(
        [
            ToolCall(id="send-1", name="send", arguments={}),
            ToolCall(id="read-1", name="read", arguments={}),
        ],
        [
            _recording_tool("send", executed, approval_required=True),
            _recording_tool("read", executed, approval_required=False),
        ],
        approvals,
    )

    assert run.result(timeout=5).output.text == "done"
    assert run.wait_for_idle(5)
    assert approvals.requested == ["send-1"]
    assert _results(run) == {"send-1": result, "read-1": "read ran"}
    assert sorted(executed) == (["read-1", "send-1"] if outcome is None else ["read-1"])


def test_a_run_without_approvals_cannot_ask() -> None:
    executed: list[str] = []
    run = _run(
        [ToolCall(id="send-1", name="send", arguments={})],
        [_recording_tool("send", executed, approval_required=True)],
        None,
    )

    assert run.result(timeout=5).output.text == "done"
    assert run.wait_for_idle(5)
    assert "this run cannot ask for it" in _results(run)["send-1"]
    assert executed == []


def test_calls_that_require_approval_are_not_merged() -> None:
    executed: list[dict[str, JsonValue]] = []

    class PerCallApprovals(Approvals):
        def request_approval(
            self, run: Run, tool_call: ToolCall, nested_call: ToolCall | None
        ) -> Outcome:
            super().request_approval(run, tool_call, nested_call)
            return _request(f"{tool_call.id}-request")

    def execute(invocation: ToolInvocation) -> ToolResult:
        executed.append(invocation.arguments)
        return ToolResult(content="searched")

    approvals = PerCallApprovals({"search": None})
    run = _run(
        [
            ToolCall(id="a", name="search", arguments={"queries": ["a"]}),
            ToolCall(id="b", name="search", arguments={"queries": ["b"]}),
        ],
        [
            AgentTool(
                definition=ToolDefinition(name="search", description="", parameters={}),
                execute=execute,
                merge_arguments=partial(merge_tool_arguments, field="queries"),
                approval_required=["search"],
            )
        ],
        approvals,
    )
    try:
        deadline = time.monotonic() + 5
        while len(run.pending_inputs) < 2:
            assert run.snapshot().failure is None
            assert time.monotonic() < deadline
            time.sleep(0.01)
        assert sorted(approvals.requested) == ["a", "b"]

        run.submit(_approve("a-request"))
        run.submit(_approve("b-request"))

        assert run.result(timeout=5).output.text == "done"
        assert run.wait_for_idle(5)
        assert sorted(executed, key=str) == [{"queries": ["a"]}, {"queries": ["b"]}]
    finally:
        run.cancel()
        assert run.wait_for_idle(5)


def _blocking_program_tool(opened: threading.Event) -> AgentTool:
    """A tool that opens a request for one `send` call and keeps it open until
    the run stops, as a program that waits on a sibling call does."""

    def program(invocation: ToolInvocation) -> ToolOutcome:
        gate = invocation.nested_calls
        assert gate is not None
        decision = gate.decide(ToolCall(id="inner-call", name="send", arguments={}))
        assert isinstance(decision, NestedInputRequest)
        opened.set()
        while not invocation.cancellation.cancelled:
            time.sleep(0.01)
        gate.withdraw(decision)
        return ToolResult(content="program stopped", is_error=True)

    return AgentTool(
        definition=ToolDefinition(name="program", description="", parameters={}),
        execute=program,
        approval_required=["send"],
    )


@pytest.mark.parametrize("nested", [False, True], ids=["direct", "program_call"])
@pytest.mark.parametrize("rejected", [False, True], ids=["unanswered", "rejected"])
def test_a_stopped_run_ends_its_requests_with_the_recorded_answers(
    rejected: bool, nested: bool
) -> None:
    """A Stop submits its rejection before it cancels: the requests end with
    that answer, and a direct call keeps the denial as its result, so later
    runs see it. The run withdraws no request when it ends; its application
    closes them."""
    approvals = Approvals({"send": _request("send-request")})
    opened = threading.Event()
    ends: list[HumanToolAnswer | None] = []
    run = _run(
        [ToolCall(id="call", name="program" if nested else "send", arguments={})],
        [
            _blocking_program_tool(opened)
            if nested
            else _recording_tool("send", [], approval_required=True)
        ],
        approvals,
        on_event=lambda event: (
            ends.append(event.answer) if isinstance(event, InputEndedEvent) else None
        ),
    )
    rejection = HumanToolAnswer(
        request_id="send-request",
        decision=InputDecision.DENY,
        result=ToolResult(content="rejected on Stop", is_error=True),
    )
    if nested:
        assert opened.wait(5)
    else:
        _until_suspended(run)

    # The run applies the answer only after it sees the Stop.
    with run.execution_lock:
        if rejected:
            run.submit(rejection)
        run.cancel("user")

    assert run.wait_for_idle(5)
    assert run.snapshot().status == RunStatus.CANCELLED
    assert ends == [rejection if rejected else None]
    if not nested:
        # The application closes a direct call's request when the run ends.
        assert approvals.withdrawn == []
    saved = run.snapshot().steps[0].tools["call"].result
    expected = "rejected on Stop" if rejected and not nested else None
    assert (saved.text if saved is not None else None) == expected


def test_a_failed_withdrawal_still_ends_the_request_and_the_run() -> None:
    class FailingApprovals(Approvals):
        def withdraw_approval(self, request_id: str) -> None:
            super().withdraw_approval(request_id)
            raise RuntimeError("approval store unavailable")

    approvals = FailingApprovals({"send": _request("send-request")})
    ends: list[str] = []
    run = _run(
        [ToolCall(id="call", name="program", arguments={})],
        [_program_tool([], keeps_waiting=False)],
        approvals,
        # Attached before the run starts, so no event is missed.
        on_event=lambda event: (
            ends.append(event.request.request_id)
            if isinstance(event, InputEndedEvent)
            else None
        ),
    )
    try:
        # The program's wait stops while the run continues.
        assert run.result(timeout=5).output.text == "done"
        # Idle once the run's events are delivered.
        assert run.wait_for_idle(5)
        assert _results(run) == {"call": "program stopped waiting"}
        assert approvals.withdrawn == ["send-request"]
        assert ends == ["send-request"]
        assert run.pending_inputs == []
    finally:
        run.cancel()
        assert run.wait_for_idle(5)


@pytest.mark.parametrize("approved", [True, False], ids=["approved", "rejected"])
@pytest.mark.parametrize("restored", [False, True], ids=["resident", "restored"])
def test_a_program_call_waits_in_the_saved_run(restored: bool, approved: bool) -> None:
    """The waiting call's request is saved with the suspended run, which a
    fresh agent can resume; the tool continues without running again."""
    approvals = Approvals({"send": _request("send-request")})
    executed: list[str] = []
    started: list[str] = []
    events: list[AgentEvent] = []
    run = _run(
        [ToolCall(id="call", name="program", arguments={})],
        [_program_tool(executed, started=started)],
        approvals,
        on_event=events.append,
    )
    saved = _until_suspended(run)
    assert [request.request_id for request in run.pending_inputs] == ["send-request"]
    shown = [event for event in events if isinstance(event, InputRequiredEvent)]
    assert [(event.tool_call.id, event.nested_call) for event in shown] == [
        ("call", ToolCall(id="inner-call", name="send", arguments={}))
    ]
    answer = (
        _approve("send-request")
        if approved
        else HumanToolAnswer(
            request_id="send-request",
            decision=InputDecision.DENY,
            result=ToolResult(content="rejected", is_error=True),
        )
    )
    if restored:
        history = run.capture().agent_state
        tools = [_program_tool(executed, started=started)]
        run = _agent([], tools, state=history).resume(
            saved,
            answers=[answer],
            coordinator=AgentCoordinator(approvals=approvals),
            on_event=events.append,
        )
    else:
        run.submit(answer)

    assert run.result(timeout=5).output.text == "done"
    assert run.wait_for_idle(5)
    assert started == ["call"]
    assert executed == (["inner-call"] if approved else [])
    assert _results(run) == {"call": "send ran" if approved else "rejected"}
    ended = [event for event in events if isinstance(event, InputEndedEvent)]
    assert [(event.tool_call.id, event.answer) for event in ended] == [("call", answer)]
    assert approvals.withdrawn == []


def test_open_requests_that_no_wait_saved_end_when_the_run_suspends() -> None:
    """A request that a tool opened and did not return in a NestedInputWait,
    such as one of a program that runs in the background, is not saved."""

    class OneRequestEach(Approvals):
        def request_approval(
            self, run: Run, tool_call: ToolCall, nested_call: ToolCall | None
        ) -> Outcome:
            super().request_approval(run, tool_call, nested_call)
            return _request(f"{(nested_call or tool_call).id}-request")

    approvals = OneRequestEach({"send": None})

    def background(invocation: ToolInvocation) -> ToolResult:
        gate = invocation.nested_calls
        assert gate is not None
        assert isinstance(
            gate.decide(ToolCall(id="background-send", name="send", arguments={})),
            NestedInputRequest,
        )
        return ToolResult(content="still running")

    ends: list[tuple[str, HumanToolAnswer | None]] = []
    run = _run(
        [
            ToolCall(id="program", name="program", arguments={}),
            ToolCall(id="send-1", name="send", arguments={}),
        ],
        [
            AgentTool(
                definition=ToolDefinition(
                    name="program", description="", parameters={}
                ),
                execute=background,
                approval_required=["send"],
            ),
            _recording_tool("send", [], approval_required=True),
        ],
        approvals,
        on_event=lambda event: (
            ends.append((event.request.request_id, event.answer))
            if isinstance(event, InputEndedEvent)
            else None
        ),
    )
    try:
        _until_suspended(run)
        assert approvals.withdrawn == ["background-send-request"]
        assert ends == [("background-send-request", None)]
        assert [request.request_id for request in run.pending_inputs] == [
            "send-1-request"
        ]
    finally:
        run.cancel()
        assert run.wait_for_idle(5)


def _suspended_send(executed: list[str]) -> tuple[Approvals, AgentState, RunState]:
    approvals = Approvals({"send": _request("send-request")})
    run = _run(
        [ToolCall(id="send-1", name="send", arguments={"to": "team"})],
        [_send_tool(executed, parameters={"type": "object"})],
        approvals,
    )
    saved = _until_suspended(run)
    return approvals, run.capture().agent_state, saved


def _send_tool(
    executed: list[str],
    *,
    parameters: dict[str, JsonValue],
    description: str = "",
) -> AgentTool:
    tool = _recording_tool("send", executed, approval_required=True)
    tool.definition = ToolDefinition(
        name="send", description=description, parameters=parameters
    )
    return tool


@pytest.mark.parametrize(
    "change, answer, result",
    [
        ("description", "approve", "send ran"),
        ("parameters", "approve", UNAVAILABLE_CALL_MESSAGE),
        ("removed", "approve", UNAVAILABLE_CALL_MESSAGE),
        ("parameters", "deny", "rejected"),
    ],
)
def test_a_restored_call_runs_only_when_its_tool_keeps_its_parameters(
    change: str, answer: str, result: str
) -> None:
    executed: list[str] = []
    approvals, history, saved = _suspended_send(executed)
    tools = {
        "description": [
            _send_tool(executed, parameters={"type": "object"}, description="new"),
            # Another tool may appear.
            _recording_tool("read", executed, approval_required=False),
        ],
        "parameters": [
            _send_tool(executed, parameters={"type": "object", "required": ["to"]})
        ],
        "removed": [],
    }[change]
    decision = (
        _approve("send-request")
        if answer == "approve"
        else HumanToolAnswer(
            request_id="send-request",
            decision=InputDecision.DENY,
            result=ToolResult(content="rejected", is_error=True),
        )
    )

    run = _agent([], tools, state=history).resume(
        saved,
        answers=[decision],
        coordinator=AgentCoordinator(approvals=approvals),
    )

    assert run.result(timeout=5).output.text == "done"
    assert run.wait_for_idle(5)
    assert _results(run) == {"send-1": result}
    assert executed == (["send-1"] if result == "send ran" else [])


def test_resume_checks_the_answers_and_replaces_the_deadline() -> None:
    executed: list[str] = []
    approvals, history, saved = _suspended_send(executed)
    tools = [_send_tool(executed, parameters={"type": "object"})]
    for wrong in (
        HumanToolAnswer(request_id="unknown", decision=InputDecision.APPROVE),
        HumanToolAnswer(
            request_id="send-request",
            decision=InputDecision.RESULT,
            result=ToolResult(content="made up"),
        ),
    ):
        with pytest.raises(ValueError):
            _agent([], tools, state=history).resume(saved, answers=[wrong])

    deadline = saved.progress.deadline_at if saved.progress else None
    replaced = (deadline or datetime.now(timezone.utc)) + timedelta(hours=1)
    run = _agent([], tools, state=history).resume(
        saved,
        answers=[_approve("send-request")],
        deadline_at=replaced,
        coordinator=AgentCoordinator(approvals=approvals),
    )

    assert run.result(timeout=5).output.text == "done"
    assert run.wait_for_idle(5)
    final = run.snapshot()
    assert final.progress is not None and final.progress.deadline_at == replaced
    assert executed == ["send-1"]
