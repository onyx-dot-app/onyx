"""A call that a tool makes for the model waits for its answer inside the tool."""

import threading
from concurrent.futures import CancelledError, Future

import pytest

from onyx.agents import runtime
from onyx.agents.agent_coordination import AgentCoordinator, ToolApprovals
from onyx.agents.events import (
    AgentEndEvent,
    AgentEvent,
    InputEndedEvent,
    InputRequiredEvent,
)
from onyx.agents.runtime import Agent, Run
from onyx.agents.tools import (
    AgentTool,
    HumanToolAnswer,
    InputDecision,
    InputMode,
    PendingToolInput,
    ToolInvocation,
)
from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.llm.interfaces import GenerationContext
from onyx.llm.models import (
    AssistantMessage,
    GenerationRequest,
    TextContent,
    ToolCall,
    ToolDefinition,
    ToolResult,
    ToolResultMessage,
)
from onyx.tracing.flows import LLMFlow
from tests.unit.onyx.agents.fakes import FakeModelClient

NESTED = ToolCall(id="nested", name="send", arguments={"to": "team"})
REQUEST = PendingToolInput(
    request_id="approval", prompt="Allow send?", mode=InputMode.EXECUTE
)
# The runtime marks the requests that the approvals owner opens.
OPENED = REQUEST.model_copy(update={"approval": True})


class Approvals(ToolApprovals):
    """Asks for the approval of every `send` call, and records withdrawals."""

    def __init__(self) -> None:
        self.withdrawn: list[str] = []

    def request_approval(self, run: Run, call: ToolCall) -> PendingToolInput:  # noqa: ARG002
        return REQUEST

    def withdraw_approval(self, request_id: str) -> None:
        self.withdrawn.append(request_id)


class ProgramRun:
    """A run whose `program` tool makes two nested calls: one that needs no
    approval, then a `send` call that waits for its answer.

    The tool reports the answer, or that its scope stopped the wait."""

    def __init__(self, hook_request: PendingToolInput | None = None) -> None:
        self.scope = CancellationSignal()
        self.waiting = threading.Event()
        self.events: list[AgentEvent] = []
        self.approvals = Approvals()
        self.decided_other: object = "undecided"

        def program(invocation: ToolInvocation) -> ToolResult:
            gate = invocation.nested_calls
            assert gate is not None
            self.decided_other = gate.decide(
                ToolCall(id="other", name="other", arguments={})
            )
            request = gate.decide(NESTED)
            assert isinstance(request, PendingToolInput)
            self.waiting.set()
            try:
                result = gate.wait_for_input(NESTED, request, self.scope)
            except AgentCancelled:
                if not self.scope.cancelled:
                    raise
                return ToolResult(content="scope stopped")
            return result or ToolResult(content="approved")

        def reply(
            request: GenerationRequest, _signal: CancellationSignal
        ) -> AssistantMessage:
            if request.messages and isinstance(request.messages[-1], ToolResultMessage):
                return AssistantMessage(content=[TextContent(text="done")])
            return AssistantMessage(
                content=[ToolCall(id="program", name="program", arguments={})]
            )

        self.run: Run = Agent(
            FakeModelClient(reply),
            generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
            before_tool_call=lambda context: (
                hook_request if context.call.name == NESTED.name else None
            ),
            tools=[
                AgentTool(
                    definition=ToolDefinition(
                        name="program", description="", parameters={}
                    ),
                    execute=program,
                    approval_required=[NESTED.name],
                )
            ],
        ).start(
            max_steps=2,
            on_event=self.events.append,
            coordinator=AgentCoordinator(approvals=self.approvals),
        )
        assert self.waiting.wait(5)

    def program_result(self) -> str:
        result = self.run.snapshot().steps[0].tools["program"].result
        assert result is not None
        return result.text


@pytest.mark.parametrize(
    "answer, result",
    [
        (
            HumanToolAnswer(request_id="approval", decision=InputDecision.APPROVE),
            "approved",
        ),
        (
            HumanToolAnswer(
                request_id="approval",
                decision=InputDecision.DENY,
                result=ToolResult(content="not approved", is_error=True),
            ),
            "not approved",
        ),
    ],
)
def test_submit_answers_the_waiting_nested_call(
    answer: HumanToolAnswer, result: str
) -> None:
    program = ProgramRun()
    try:
        assert [request.request_id for request in program.run.pending_inputs] == [
            "approval"
        ]

        program.run.submit(answer)

        assert program.run.result(timeout=5).output.text == "done"
        assert program.program_result() == result
        assert program.run.pending_inputs == []
        # Events reach the listener after the result.
        assert program.run.wait_for_idle(5)
        required = [e for e in program.events if isinstance(e, InputRequiredEvent)]
        answered = [e for e in program.events if isinstance(e, InputEndedEvent)]
        assert [(e.tool_call.id, e.nested_call, e.request) for e in required] == [
            ("program", NESTED, OPENED)
        ]
        assert [(e.tool_call.id, e.nested_call, e.answer) for e in answered] == [
            ("program", NESTED, answer)
        ]
        # A call that needs no approval runs; an answered request is not withdrawn.
        assert program.decided_other is None
        assert program.approvals.withdrawn == []
    finally:
        program.run.cancel()
        assert program.run.wait_for_idle(5)


def test_cancelling_the_run_ends_the_nested_request_before_the_run_ends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The waiting call can wake after its run has ended; the run still reports
    the end of its request, once, before its own end."""
    run_ended = threading.Event()

    class LateWakingFuture(Future[HumanToolAnswer]):
        def result(self, timeout: float | None = None) -> HumanToolAnswer:
            try:
                return super().result(timeout)
            except CancelledError:
                run_ended.wait(5)
                raise

    monkeypatch.setattr(runtime, "Future", LateWakingFuture)
    program = ProgramRun()
    program.run.subscribe(
        lambda event: run_ended.set() if isinstance(event, AgentEndEvent) else None
    )

    program.run.cancel()

    with pytest.raises(AgentCancelled):
        program.run.result(timeout=5)
    assert program.run.wait_for_idle(5)
    ended = [
        (type(e), e.answer if isinstance(e, InputEndedEvent) else None)
        for e in program.events
        if isinstance(e, (InputEndedEvent, AgentEndEvent))
    ]
    assert ended == [(InputEndedEvent, None), (AgentEndEvent, None)]


def test_cancelling_the_calls_scope_stops_only_its_wait() -> None:
    program = ProgramRun()
    try:
        program.scope.cancel()

        assert program.run.result(timeout=5).output.text == "done"
        assert program.program_result() == "scope stopped"
        assert program.run.pending_inputs == []
        assert program.run.wait_for_idle(5)
        ended = [e for e in program.events if isinstance(e, InputEndedEvent)]
        assert [(e.request.request_id, e.nested_call, e.answer) for e in ended] == [
            ("approval", NESTED, None)
        ]
        assert program.approvals.withdrawn == ["approval"]
    finally:
        program.run.cancel()
        assert program.run.wait_for_idle(5)


def test_the_approvals_owner_withdraws_only_its_own_requests() -> None:
    hook_request = PendingToolInput(
        request_id="hook", prompt="Allow send?", mode=InputMode.EXECUTE
    )
    program = ProgramRun(hook_request)
    try:
        program.scope.cancel()

        assert program.run.result(timeout=5).output.text == "done"
        assert program.run.wait_for_idle(5)
        ended = [e for e in program.events if isinstance(e, InputEndedEvent)]
        assert [(e.request, e.answer) for e in ended] == [(hook_request, None)]
        assert program.approvals.withdrawn == []
    finally:
        program.run.cancel()
        assert program.run.wait_for_idle(5)


def test_an_answer_that_arrives_after_the_wait_stopped_is_ignored() -> None:
    program = ProgramRun()
    try:
        # Holding the lock keeps the stopped wait from removing its request.
        with program.run.execution_lock:
            program.scope.cancel()
            program.run.submit(
                HumanToolAnswer(request_id="approval", decision=InputDecision.APPROVE)
            )

        assert program.run.result(timeout=5).output.text == "done"
        assert program.program_result() == "scope stopped"
    finally:
        program.run.cancel()
        assert program.run.wait_for_idle(5)
