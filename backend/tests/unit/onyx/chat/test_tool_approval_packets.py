"""How a tool call that waits for approval ends, as its card shows it."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from onyx.agents.agent_coordination import AgentCoordinator, ToolApprovals
from onyx.agents.models import ExecutionStatus, RunStatus, StepRecord
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
from onyx.chat.models import ResponseRecord, SavedToolApproval
from onyx.chat.presentation import ResponsePresenter, replay_response
from onyx.chat.tool_approvals import TOOL_APPROVAL_TIMEOUT, tool_answer
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
    def request_approval(
        self,
        run: Run,  # noqa: ARG002
        tool_call: ToolCall,  # noqa: ARG002
        nested_call: ToolCall | None,  # noqa: ARG002
    ) -> PendingToolInput:
        return PendingToolInput(
            request_id=str(APPROVAL_ID),
            prompt="Allow?",
            mode=InputMode.EXECUTE,
            expires_at=datetime.now(UTC),
        )

    def withdraw_approval(self, request_id: str) -> None:  # noqa: ARG002
        return None


def _saved(
    decision: ApprovalDecision | None,
    decided_via: ApprovalDecidedVia | None = None,
    *,
    decided_after: timedelta = timedelta(minutes=1),
    approval_id: UUID = APPROVAL_ID,
) -> SavedToolApproval:
    created_at = datetime(2026, 11, 13, tzinfo=UTC)
    return SavedToolApproval(
        id=approval_id,
        chat_message_id=1,
        tool_call_id=CALL.id,
        tool_name=CALL.name,
        display_name="Send email",
        created_at=created_at,
        decision=decision,
        decided_via=decided_via,
        decided_at=created_at + decided_after if decision is not None else None,
    )


@pytest.mark.parametrize(
    ("saved", "ends"),
    [
        (
            _saved(ApprovalDecision.EXPIRED, decided_after=TOOL_APPROVAL_TIMEOUT),
            "expired",
        ),
        (_saved(ApprovalDecision.REJECTED, ApprovalDecidedVia.POLICY), "disabled"),
        # The request's row was deleted with its tool's server.
        (None, "disabled"),
    ],
)
def test_a_program_call_that_ends_without_a_decision_reports_how(
    saved: SavedToolApproval | None,
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


@pytest.mark.parametrize(
    "saved, outcome",
    [
        (_saved(ApprovalDecision.APPROVED, ApprovalDecidedVia.USER), "approved"),
        (
            _saved(ApprovalDecision.APPROVED, ApprovalDecidedVia.SESSION_GRANT),
            "approved_for_chat",
        ),
        (_saved(ApprovalDecision.REJECTED, ApprovalDecidedVia.USER), "rejected"),
        (_saved(ApprovalDecision.REJECTED, ApprovalDecidedVia.POLICY), "disabled"),
        (
            _saved(ApprovalDecision.EXPIRED, decided_after=TOOL_APPROVAL_TIMEOUT),
            "expired",
        ),
        # The call stopped waiting before the deadline, or the response ended
        # while the request waited.
        (_saved(ApprovalDecision.EXPIRED), "cancelled"),
        (_saved(None), "cancelled"),
    ],
    ids=[
        "approved",
        "approved_for_chat",
        "rejected",
        "disabled",
        "expired",
        "withdrawn",
        "undecided",
    ],
)
def test_a_saved_response_shows_each_request_as_its_stream_ended_it(
    saved: SavedToolApproval, outcome: ToolApprovalOutcome
) -> None:
    response = ResponseRecord(
        run_id="1",
        status=RunStatus.CANCELLED,
        steps=[
            StepRecord(
                message=AssistantMessage(id="message", content=[CALL]),
                generation_status=ExecutionStatus.COMPLETE,
            )
        ],
    )

    packets = replay_response(response, {}, {}, {}, approvals={("1", CALL.id): [saved]})

    card = [
        packet
        for packet in packets
        if isinstance(
            packet.obj, (CustomToolStart, ToolApprovalRequest, ToolApprovalResolved)
        )
    ]
    assert [type(packet.obj) for packet in card] == [
        CustomToolStart,
        ToolApprovalRequest,
        ToolApprovalResolved,
    ]
    assert card[0].placement == card[1].placement == card[2].placement
    assert card[1].obj == ToolApprovalRequest(
        approval_id=str(APPROVAL_ID),
        tool_call_id=CALL.id,
        tool_name=CALL.name,
        display_name="Send email",
        arguments={"to": "team"},
        expires_at=saved.created_at + TOOL_APPROVAL_TIMEOUT,
    )
    assert card[2].obj == ToolApprovalResolved(
        approval_id=str(APPROVAL_ID), outcome=outcome
    )
