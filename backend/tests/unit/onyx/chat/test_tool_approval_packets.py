"""How a tool call that waits for approval ends, as its card shows it."""

from datetime import UTC, datetime
from uuid import UUID

import pytest

from onyx.agents.agent_coordination import AgentCoordinator, ToolApprovals
from onyx.agents.models import RunStatus
from onyx.agents.runtime import Agent, Run
from onyx.agents.tools import (
    AgentTool,
    HumanToolAnswer,
    InputDecision,
    InputMode,
    PendingToolInput,
    ToolInvocation,
)
from onyx.chat.emitter import Emitter
from onyx.chat.presentation import ResponsePresenter
from onyx.chat.tool_approvals import tool_answer
from onyx.db.approval_request import SavedDecision
from onyx.db.enums import ApprovalDecidedVia, ApprovalDecision
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
from onyx.server.query_and_chat.streaming_models import (
    CustomToolStart,
    Packet,
    ToolApprovalOutcome,
    ToolApprovalRequest,
    ToolApprovalResolved,
)
from onyx.tracing.flows import LLMFlow
from tests.unit.onyx.agents.fakes import FakeModelClient
from tests.unit.onyx.tools.code_mode.fakes import until

CALL = ToolCall(id="send-call", name="send_email", arguments={"to": "team"})


APPROVAL_ID = UUID("8f9a6a52-4c4e-4d55-9a0e-2f43e7d1c001")


class _Approvals(ToolApprovals):
    def request_approval(self, run: Run, call: ToolCall) -> PendingToolInput:  # noqa: ARG002
        return PendingToolInput(
            request_id=str(APPROVAL_ID),
            prompt="Allow?",
            mode=InputMode.EXECUTE,
            expires_at=datetime.now(UTC),
        )

    def withdraw_approval(self, request_id: str) -> None:
        pass


@pytest.mark.parametrize(
    ("saved", "ends"),
    [
        ((ApprovalDecision.EXPIRED, None, CALL.name), "expired"),
        (
            (ApprovalDecision.REJECTED, ApprovalDecidedVia.POLICY, CALL.name),
            "disabled",
        ),
        # The request's row was deleted with its tool's server.
        (None, "disabled"),
    ],
)
def test_a_program_call_that_ends_without_a_decision_reports_how(
    saved: SavedDecision | None,
    ends: ToolApprovalOutcome,
) -> None:
    """Integration covers decided direct calls, and external dependency tests
    a stopped program; a request can also expire or lose its row."""
    scope = CancellationSignal()

    def program(invocation: ToolInvocation) -> ToolResult:
        gate = invocation.nested_calls
        assert gate is not None
        request = gate.decide(CALL)
        assert isinstance(request, PendingToolInput)
        try:
            gate.wait_for_input(CALL, request, scope)
        except AgentCancelled:
            return ToolResult(content="stopped", is_error=True)
        return ToolResult(content="answered")

    def reply(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        if request.messages and isinstance(request.messages[-1], ToolResultMessage):
            return AssistantMessage(content=[TextContent(text="done")])
        return AssistantMessage(
            content=[ToolCall(id="program", name="execute_code", arguments={})]
        )

    live: list[Packet] = []
    run = Agent(
        FakeModelClient(reply),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        tools=[
            AgentTool(
                definition=ToolDefinition(
                    name="execute_code", description="", parameters={}
                ),
                execute=program,
                approval_required=[CALL.name],
            )
        ],
    ).start(
        max_steps=3,
        coordinator=AgentCoordinator(approvals=_Approvals()),
        on_event=ResponsePresenter(Emitter(live.append)).consume,
    )
    try:
        # The nested request is open once the program waits on it.
        until(lambda: bool(run.pending_inputs), timeout=5)
        run.submit(tool_answer(APPROVAL_ID, saved))
        assert run.result(timeout=5).output.text == "done"
        assert run.wait_for_idle(5)
    finally:
        run.cancel()
        assert run.wait_for_idle(5)

    # The program's call waits and ends inside the program's card.
    approval = [
        packet
        for packet in live
        if isinstance(packet.obj, (ToolApprovalRequest, ToolApprovalResolved))
    ]
    assert [type(packet.obj) for packet in approval] == [
        ToolApprovalRequest,
        ToolApprovalResolved,
    ]
    assert approval[0].placement == approval[1].placement
    assert approval[1].obj == ToolApprovalResolved(
        approval_id=str(APPROVAL_ID), outcome=ends
    )


def test_a_question_for_the_user_streams_no_approval_packets() -> None:
    """A tool that asks the user for its result is not an approval request."""

    def reply(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        if request.messages and isinstance(request.messages[-1], ToolResultMessage):
            return AssistantMessage(content=[TextContent(text="done")])
        return AssistantMessage(content=[CALL])

    live: list[Packet] = []
    run = Agent(
        FakeModelClient(reply),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        tools=[
            AgentTool(
                definition=ToolDefinition(
                    name=CALL.name, description="", parameters={}
                ),
                execute=lambda _invocation: PendingToolInput(
                    request_id="question", prompt="Which?", mode=InputMode.RESULT
                ),
            )
        ],
    ).start(max_steps=3, on_event=ResponsePresenter(Emitter(live.append)).consume)
    try:
        assert run.wait_until_settled(5).status == RunStatus.SUSPENDED
        run.submit(
            HumanToolAnswer(
                request_id="question",
                decision=InputDecision.RESULT,
                result=ToolResult(content="the team"),
            )
        )
        assert run.result(timeout=5).output.text == "done"
    finally:
        run.cancel()
        assert run.wait_for_idle(5)

    assert any(isinstance(packet.obj, CustomToolStart) for packet in live)
    assert not any(
        isinstance(packet.obj, (ToolApprovalRequest, ToolApprovalResolved))
        for packet in live
    )
