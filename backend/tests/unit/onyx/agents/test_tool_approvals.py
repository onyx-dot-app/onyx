"""The runtime asks the coordinator's approvals only for calls that require it."""

import threading
import time

import pytest

from onyx.agents.agent_coordination import AgentCoordinator, ToolApprovals
from onyx.agents.runtime import Agent, Run
from onyx.agents.tools import (
    AgentTool,
    HumanToolAnswer,
    InputDecision,
    InputMode,
    PendingToolInput,
    ToolInvocation,
)
from onyx.llm.interfaces import GenerationContext
from onyx.llm.models import (
    AssistantMessage,
    TextContent,
    ToolCall,
    ToolDefinition,
    ToolResult,
)
from onyx.tracing.flows import LLMFlow
from tests.unit.onyx.agents.fakes import FakeModelClient

Outcome = PendingToolInput | ToolResult | None


class Approvals(ToolApprovals):
    """Answers each requiring call with the outcome set for its name."""

    def __init__(self, outcomes: dict[str, Outcome]) -> None:
        self.outcomes = outcomes
        self.requested: list[str] = []
        self.withdrawn: list[str] = []
        self._lock = threading.Lock()

    def request_approval(self, run: Run, call: ToolCall) -> Outcome:  # noqa: ARG002
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


def _run(
    calls: list[ToolCall],
    tools: list[AgentTool],
    approvals: ToolApprovals | None,
) -> Run:
    replies = iter(
        [
            AssistantMessage(content=list(calls)),
            AssistantMessage(content=[TextContent(text="done")]),
        ]
    )
    return Agent(
        FakeModelClient(lambda *_: next(replies)),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        tools=tools,
    ).start(max_steps=2, coordinator=AgentCoordinator(approvals=approvals))


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


@pytest.mark.parametrize("nested", [False, True], ids=["direct", "program_call"])
def test_input_wait_time_counts_the_time_calls_waited(nested: bool) -> None:
    approvals = Approvals({"send": _request("send-request")})

    def program(invocation: ToolInvocation) -> ToolResult:
        gate = invocation.nested_calls
        assert gate is not None
        inner = ToolCall(id="inner-call", name="send", arguments={})
        request = gate.decide(inner)
        assert isinstance(request, PendingToolInput)
        gate.wait_for_input(inner, request, invocation.cancellation)
        return ToolResult(content="program ran")

    started = time.monotonic()
    run = _run(
        [ToolCall(id="call", name="program" if nested else "send", arguments={})],
        [
            AgentTool(
                definition=ToolDefinition(
                    name="program", description="", parameters={}
                ),
                execute=program,
                approval_required=["send"],
            )
            if nested
            else _recording_tool("send", [], approval_required=True)
        ],
        approvals,
    )
    try:
        deadline = time.monotonic() + 5
        while not run.pending_inputs:
            assert time.monotonic() < deadline
            time.sleep(0.01)
        time.sleep(0.3)
        assert run.input_wait_seconds >= 0.3

        run.submit(_approve("send-request"))

        assert run.result(timeout=5).output.text == "done"
        waited = run.input_wait_seconds
        assert 0.3 <= waited <= time.monotonic() - started
        time.sleep(0.1)
        # The clock stops when the answer arrives.
        assert run.input_wait_seconds == waited
    finally:
        run.cancel()
        assert run.wait_for_idle(5)
