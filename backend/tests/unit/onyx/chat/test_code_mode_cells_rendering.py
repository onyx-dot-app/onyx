"""Cells render one card per observation, plus the closing record."""

from collections.abc import Callable, Generator
from typing import Literal

import pytest

from onyx.agents.events import ToolResultAmendedEvent
from onyx.agents.models import (
    RunStatus,
    ToolResultAmendment,
)
from onyx.agents.runtime import Agent
from onyx.agents.tools import AgentTool, ToolInvocation
from onyx.chat.emitter import Emitter
from onyx.chat.presentation import (
    ResponsePresenter,
    project_response,
    replay_response,
)
from onyx.context.search.models import SearchDocsResponse
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.interfaces import GenerationContext
from onyx.llm.models import (
    AssistantMessage,
    GenerationEvent,
    GenerationRequest,
    GenerationStartEvent,
    TextContent,
    TextDeltaEvent,
    ToolCall,
    ToolDefinition,
    ToolResult,
    ToolResultMessage,
)
from onyx.server.query_and_chat import streaming_models as packets
from onyx.tools.constants import CODE_MODE_TOOL_NAME, WAIT_CODE_TOOL_NAME
from onyx.tools.tool_implementations.code_mode.models import (
    UNFINISHED_CALL_MESSAGE,
    CellClosing,
    CodeModeCall,
    CodeModeExecutionResult,
)
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tracing.flows import LLMFlow
from tests.unit.onyx.agents.fakes import FakeModelClient, message_events
from tests.unit.onyx.tools.code_mode.fakes import search_doc

DOC = search_doc("alpha")
SLOW_CALL = CodeModeCall(
    id="exec:0",
    index=0,
    tool_name="lookup",
    function_name="lookup",
    arguments={"id": 1},
    state="running",
)
SEARCH_CALL = CodeModeCall(
    id="exec:1",
    state="ok",
    index=1,
    tool_name=SearchTool.NAME,
    function_name=SearchTool.NAME,
    arguments={"queries": ["q"]},
    content="search results",
    details=SearchDocsResponse(
        queries=["q"], search_docs=[DOC], citation_mapping={3: DOC.document_id}
    ),
)
OBSERVATIONS = {
    "exec": CodeModeExecutionResult(
        cell_id=1, observation=0, code="work()", status="running", stdout="first\n"
    ),
    "wait": CodeModeExecutionResult(
        cell_id=1,
        observation=1,
        status="running",
        stdout="second\n",
        calls=[SLOW_CALL],
        tool_call_count=1,
    ),
}
CLOSING = CellClosing(
    reason="response_ended",
    status="terminated",
    stdout="third\n",
    calls=[
        SLOW_CALL.model_copy(update={"state": "ok", "content": "found"}),
        SEARCH_CALL,
    ],
    tool_call_count=2,
)


def _reply() -> Callable[[GenerationRequest, CancellationSignal], AssistantMessage]:
    turns = iter(
        [
            ToolCall(id="exec", name=CODE_MODE_TOOL_NAME, arguments={"code": "work()"}),
            ToolCall(id="wait", name=WAIT_CODE_TOOL_NAME, arguments={"cell_id": 1}),
        ]
    )

    def reply(
        _request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        call = next(turns, None)
        if call is None:
            return AssistantMessage(content=[TextContent(text="answer")])
        return AssistantMessage(content=[call])

    return reply


class StoppedAnswerClient(FakeModelClient):
    """Streams part of the answer, then the user stops the response."""

    def stream(
        self, request: GenerationRequest, context: GenerationContext | None = None
    ) -> Generator[GenerationEvent, None, None]:
        message = self.invoke(request, context)
        if not message.text or context is None or context.cancellation is None:
            yield from message_events(message)
            return
        yield GenerationStartEvent()
        yield TextDeltaEvent(content_index=0, text="part")
        context.cancellation.cancel()
        context.cancellation.check()


def _observe(invocation: ToolInvocation) -> ToolResult:
    details = OBSERVATIONS[invocation.call_id]
    return ToolResult(
        content=f"Execution running in cell 1 ({invocation.call_id})", details=details
    )


def _close(results: list[ToolResultMessage]) -> list[ToolResultAmendment]:
    last = results[-1]
    assert isinstance(last.details, CodeModeExecutionResult)
    return [
        ToolResultAmendment(
            call_id=last.tool_call_id,
            result=ToolResult(
                content=f"{last.content}\nCell 1 stopped when the response ended.",
                details=last.details.model_copy(update={"closing": CLOSING}),
            ),
        )
    ]


def _tool(name: str) -> AgentTool:
    return AgentTool(
        definition=ToolDefinition(name=name, description="", parameters={}),
        execute=_observe,
    )


def _shape(output: list[packets.Packet]) -> list[tuple[str, int, int | None]]:
    return [
        (packet.obj.type, packet.placement.turn_index, packet.placement.sub_turn_index)
        for packet in output
    ]


@pytest.mark.parametrize("stopped", [False, True])
def test_cell_observations_and_closing_render_in_call_order(
    stopped: bool,
) -> None:
    live: list[packets.Packet] = []
    agent = Agent(
        (StoppedAnswerClient if stopped else FakeModelClient)(_reply()),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        tools=[_tool(CODE_MODE_TOOL_NAME), _tool(WAIT_CODE_TOOL_NAME)],
        on_finish=_close,
    )
    run = agent.start(
        max_steps=10,
        on_event=ResponsePresenter(Emitter(live.append)).consume,
    )
    run.wait_for_completion(timeout=10)
    assert run.wait_for_idle(timeout=10)
    assert run.status == (RunStatus.CANCELLED if stopped else RunStatus.COMPLETE)
    assert len(run.snapshot().steps) == 3

    starts = [p.obj for p in live if isinstance(p.obj, packets.CodeModeStart)]
    assert [(s.code, s.cell_id, s.observation) for s in starts] == [
        ("work()", None, 0),
        ("", 1, 1),
    ]
    deltas = [
        (p.placement.turn_index, p.obj)
        for p in live
        if isinstance(p.obj, packets.CodeModeDelta)
    ]
    finals = [
        (turn, delta.status, delta.observation, delta.response_ended)
        for turn, delta in deltas
        if delta.status is not None
    ]
    # Each observation is its own card; the closing record follows the last one.
    assert finals == [
        (0, "running", 0, False),
        (1, "running", 1, False),
        (1, "terminated", None, True),
    ]
    wait_card = [p for p in live if p.placement.turn_index == 1]
    shape = _shape(wait_card)
    # The running call stays open in the observation and the closing completes it.
    first_end = shape.index(("section_end", 1, None))
    assert ("section_end", 1, 0) not in shape[:first_end]
    assert shape[first_end + 1 :] == [
        ("custom_tool_delta", 1, 0),
        ("section_end", 1, 0),
        ("search_tool_start", 1, 1),
        ("search_tool_queries_delta", 1, 1),
        ("search_tool_filter_delta", 1, 1),
        ("search_tool_documents_delta", 1, 1),
        ("section_end", 1, 1),
        ("code_mode_delta", 1, None),
        ("code_mode_delta", 1, None),
    ]
    closing_stdout = deltas[-2][1]
    assert closing_stdout.stdout == "third\n" and closing_stdout.status is None
    # The card counts the calls the cell started.
    assert deltas[-1][1].tool_call_count == 2

    # Replay renders the saved closing record once, after the card's section
    # end, as live does.
    projected = project_response(run.snapshot(), tool_ids={})
    assert projected.response is not None
    replayed = replay_response(projected.response, {}, {}, {})
    assert [
        (p.placement.turn_index, p.obj.status, p.obj.observation, p.obj.response_ended)
        for p in replayed
        if isinstance(p.obj, packets.CodeModeDelta) and p.obj.status is not None
    ] == finals
    replayed_wait = [p for p in replayed if p.placement.turn_index == 1]
    for card in (wait_card, replayed_wait):
        assert [
            p.obj.status if isinstance(p.obj, packets.CodeModeDelta) else "end"
            for p in card
            if p.placement.sub_turn_index is None
            and (
                isinstance(p.obj, packets.SectionEnd)
                or isinstance(p.obj, packets.CodeModeDelta)
                and p.obj.status is not None
            )
        ] == ["running", "end", "terminated"]


def test_closing_of_a_call_from_before_a_restore_renders_in_a_new_card() -> None:
    live: list[packets.Packet] = []
    presenter = ResponsePresenter(Emitter(live.append))
    observation = OBSERVATIONS["wait"].model_copy(update={"closing": CLOSING})
    presenter.consume(
        ToolResultAmendedEvent(
            run_id="restored",
            message_id="earlier-message",
            step_index=0,
            tool_call=ToolCall(
                id="wait", name=WAIT_CODE_TOOL_NAME, arguments={"cell_id": 1}
            ),
            result=ToolResult(
                content="Execution running in cell 1", details=observation
            ),
        )
    )
    starts = [p.obj for p in live if isinstance(p.obj, packets.CodeModeStart)]
    assert [(s.cell_id, s.observation) for s in starts] == [(1, 1)]
    finals = [
        (delta.status, delta.response_ended, delta.tool_call_count)
        for delta in (p.obj for p in live)
        if isinstance(delta, packets.CodeModeDelta) and delta.status is not None
    ]
    assert finals == [("running", False, 1), ("terminated", True, 2)]
    assert {p.placement.turn_index for p in live} == {0}


@pytest.mark.parametrize(
    ("status", "result", "error"),
    [
        ("completed", "42", None),
        ("failed", None, "ZeroDivisionError: division by zero"),
    ],
)
def test_closing_record_reports_how_the_program_ended(
    status: Literal["completed", "failed"], result: str | None, error: str | None
) -> None:
    live: list[packets.Packet] = []
    presenter = ResponsePresenter(Emitter(live.append))
    closing = CellClosing(
        reason="response_ended", status=status, result=result, error=error
    )
    presenter.consume(
        ToolResultAmendedEvent(
            run_id="run",
            message_id="message",
            step_index=0,
            tool_call=ToolCall(
                id="wait", name=WAIT_CODE_TOOL_NAME, arguments={"cell_id": 1}
            ),
            result=ToolResult(
                content="Execution running in cell 1",
                details=OBSERVATIONS["wait"].model_copy(update={"closing": closing}),
            ),
        )
    )
    closing_delta = next(
        p.obj
        for p in live
        if isinstance(p.obj, packets.CodeModeDelta) and p.obj.response_ended
    )
    assert (closing_delta.status, closing_delta.result, closing_delta.error) == (
        status,
        result,
        error,
    )


def test_a_call_left_unfinished_renders_as_failed() -> None:
    live: list[packets.Packet] = []
    presenter = ResponsePresenter(Emitter(live.append))
    closing = CellClosing(
        reason="response_ended",
        status="completed",
        calls=[SLOW_CALL.unfinished()],
        tool_call_count=1,
    )
    presenter.consume(
        ToolResultAmendedEvent(
            run_id="run",
            message_id="message",
            step_index=0,
            tool_call=ToolCall(
                id="wait", name=WAIT_CODE_TOOL_NAME, arguments={"cell_id": 1}
            ),
            result=ToolResult(
                content="Execution running in cell 1",
                details=OBSERVATIONS["wait"].model_copy(update={"closing": closing}),
            ),
        )
    )
    errors = [
        (p.placement.sub_turn_index, str(p.obj.exception))
        for p in live
        if isinstance(p.obj, packets.PacketException)
    ]
    assert errors == [(0, UNFINISHED_CALL_MESSAGE)]
