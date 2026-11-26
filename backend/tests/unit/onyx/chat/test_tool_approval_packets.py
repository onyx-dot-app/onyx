"""How a tool call that waits for approval ends, as its card shows it."""

from collections.abc import Iterator
from concurrent.futures import Future
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from onyx.agents.agent_coordination import AgentCoordinator, ToolApprovals
from onyx.agents.models import ExecutionStatus, RunStatus, StepRecord
from onyx.agents.runtime import Agent, Run
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
from onyx.chat.emitter import Emitter
from onyx.chat.models import (
    AnswerStreamPart,
    ChatResponseOutcome,
    ChatResponseSnapshot,
    PersistenceStatus,
    ResponseRecord,
    SavedToolApproval,
)
from onyx.chat.presentation import ResponsePresenter, replay_response
from onyx.chat.process_message import gather_stream_full
from onyx.chat.renderer import ToolRenderer
from onyx.chat.tool_approvals import tool_answer
from onyx.db.enums import ApprovalDecidedVia, ApprovalDecision
from onyx.llm.cancellation import CancellationSignal
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
from onyx.server.query_and_chat.models import MessageResponseIDInfo
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import (
    CustomToolStart,
    OverallStop,
    Packet,
    SectionEnd,
    ToolApprovalOutcome,
    ToolApprovalRequest,
    ToolApprovalResolved,
)
from onyx.tracing.flows import LLMFlow
from tests.unit.onyx.agents.fakes import FakeModelClient

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
        )

    def withdraw_approval(self, request_id: str) -> None:  # noqa: ARG002
        return None


def _saved(
    decision: ApprovalDecision | None,
    decided_via: ApprovalDecidedVia | None = None,
    *,
    approval_id: UUID = APPROVAL_ID,
) -> SavedToolApproval:
    created_at = datetime(2026, 11, 13, tzinfo=UTC)
    return SavedToolApproval(
        id=approval_id,
        chat_message_id=1,
        tool_call_id=CALL.id,
        tool_name=CALL.name,
        display_name="Send email",
        arguments={"to": "team"},
        created_at=created_at,
        decision=decision,
        decided_via=decided_via,
        decided_at=created_at if decision is not None else None,
    )


@pytest.mark.parametrize(
    ("saved", "ends"),
    [
        (_saved(ApprovalDecision.REJECTED, ApprovalDecidedVia.POLICY), "disabled"),
        # The request's row was deleted with its tool's server.
        (None, "disabled"),
        # The request ended undecided, which no resume answers.
        (_saved(ApprovalDecision.EXPIRED), "disabled"),
    ],
)
def test_a_program_call_that_ends_without_a_decision_reports_how(
    saved: SavedToolApproval | None,
    ends: ToolApprovalOutcome,
) -> None:
    """Integration covers decided calls; a request can also lose its row or be
    blocked by the policy when the user approves it."""

    def program(invocation: ToolInvocation) -> ToolOutcome:
        gate = invocation.nested_calls
        assert gate is not None
        request = gate.decide(CALL)
        assert isinstance(request, NestedInputRequest)
        return NestedInputWait(requests=[request])

    def resume_with_input(
        _invocation: ToolInvocation, answers: list[NestedInputAnswer]
    ) -> ToolOutcome:
        (answered,) = answers
        assert answered.answer.result is not None
        return answered.answer.result

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
                resume_with_input=resume_with_input,
                approval_required=[CALL.name],
            )
        ],
    ).start(
        max_steps=3,
        coordinator=AgentCoordinator(approvals=_Approvals()),
        on_event=ResponsePresenter(Emitter(live.append)).consume,
    )
    try:
        assert run.wait_until_settled(5).status == RunStatus.SUSPENDED
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


def _response(status: RunStatus) -> ResponseRecord:
    return ResponseRecord(
        run_id="1",
        status=status,
        steps=[
            StepRecord(
                message=AssistantMessage(id="message", content=[CALL]),
                generation_status=ExecutionStatus.COMPLETE,
            )
        ],
    )


_REQUEST = ToolApprovalRequest(
    approval_id=str(APPROVAL_ID),
    tool_call_id=CALL.id,
    tool_name=CALL.name,
    display_name="Send email",
    arguments={"to": "team"},
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
        # The call stopped waiting, or the response ended while it waited.
        (_saved(ApprovalDecision.EXPIRED), "cancelled"),
    ],
    ids=["approved", "approved_for_chat", "rejected", "disabled", "withdrawn"],
)
def test_a_saved_response_shows_each_request_as_its_stream_ended_it(
    saved: SavedToolApproval, outcome: ToolApprovalOutcome
) -> None:
    packets = replay_response(
        _response(RunStatus.CANCELLED), {}, {}, {}, approvals={("1", CALL.id): [saved]}
    )

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
    assert card[1].obj == _REQUEST
    assert card[2].obj == ToolApprovalResolved(
        approval_id=str(APPROVAL_ID), outcome=outcome
    )


@pytest.mark.parametrize("decided", [False, True], ids=["waiting", "decided"])
def test_a_suspended_response_replays_as_its_stream_stopped(decided: bool) -> None:
    """Its waiting call stays open after its request, and the response stops
    to wait for the decisions; a stream that continues it gets the call's
    renderer instead, the saved decision, and no stop."""
    saved = (
        _saved(ApprovalDecision.APPROVED, ApprovalDecidedVia.USER)
        if decided
        else _saved(None)
    )
    approvals = {("1", CALL.id): [saved]}

    loaded = replay_response(
        _response(RunStatus.SUSPENDED), {}, {}, {}, approvals=approvals
    )

    assert [
        packet.obj for packet in loaded if not isinstance(packet.obj, CustomToolStart)
    ][-3 if decided else -2 :] == [
        _REQUEST,
        *(
            [ToolApprovalResolved(approval_id=str(APPROVAL_ID), outcome="approved")]
            if decided
            else []
        ),
        OverallStop(stop_reason="awaiting_user"),
    ]
    assert not any(isinstance(packet.obj, SectionEnd) for packet in loaded[-3:])

    open_calls: dict[tuple[str, str, str], ToolRenderer] = {}
    continued = replay_response(
        _response(RunStatus.SUSPENDED),
        {},
        {},
        {},
        approvals=approvals,
        open_calls=open_calls,
    )

    assert list(open_calls) == [("1", "message", CALL.id)]
    assert [packet.obj for packet in loaded][-3 if decided else -2 : -1] == [
        packet.obj for packet in continued
    ][-2 if decided else -1 :]
    assert not any(isinstance(packet.obj, OverallStop) for packet in continued)


def test_a_non_streaming_response_returns_the_requests_that_wait() -> None:
    """The requests streamed without a resolution before the stop that waits
    for the decisions."""
    approval_ids = [str(uuid4()) for _ in range(3)]
    ended = approval_ids[2]

    def request(approval_id: str) -> Packet:
        return Packet(
            placement=Placement(turn_index=0),
            obj=ToolApprovalRequest(
                approval_id=approval_id,
                tool_call_id=f"call_{approval_id}",
                tool_name=CALL.name,
                display_name="Send email",
                arguments={"to": "team"},
            ),
        )

    def packets() -> Iterator[AnswerStreamPart]:
        yield MessageResponseIDInfo(
            user_message_id=None, reserved_assistant_message_id=1, mentions=[]
        )
        yield request(approval_ids[0])
        # A program's request that ended when its program stopped.
        yield request(ended)
        yield Packet(
            placement=Placement(turn_index=0),
            obj=ToolApprovalResolved(approval_id=ended, outcome="cancelled"),
        )
        yield request(approval_ids[1])
        yield Packet(
            placement=Placement(turn_index=0),
            obj=OverallStop(stop_reason="awaiting_user"),
        )

    outcome = Future[ChatResponseOutcome]()
    outcome.set_result(
        ChatResponseOutcome(
            response=ChatResponseSnapshot(
                answer=None,
                reasoning=None,
                request_params=None,
                citation_to_doc={},
                tool_calls=[],
                is_clarification=False,
                all_search_docs={},
                pre_answer_processing_time=None,
                response=None,
                cancelled=False,
            ),
            persistence_status=PersistenceStatus.SAVED,
        )
    )
    response = gather_stream_full(packets(), outcome)

    assert [
        pending.approval_id for pending in response.pending_tool_approvals
    ] == approval_ids[:2]
