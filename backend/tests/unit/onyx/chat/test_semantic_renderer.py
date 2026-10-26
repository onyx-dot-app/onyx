"""The packet view cannot drive model requests or tool execution."""

from collections.abc import Mapping
from queue import Queue

import pytest
from pydantic import BaseModel, JsonValue

from onyx.agents.events import (
    AgentEndEvent,
    MessageEndEvent,
    MessageStartEvent,
    MessageUpdateEvent,
    ToolStartEvent,
)
from onyx.agents.models import (
    ExecutionStatus,
    RunState,
    RunStatus,
    StepRecord,
    ToolExecutionRecord,
)
from onyx.agents.runtime import Agent
from onyx.agents.tools import AgentTool, ToolInvocation
from onyx.chat.emitter import Emitter
from onyx.chat.presentation import ResponsePresenter, project_response, replay_response
from onyx.chat.renderer import MessageRenderer, ResponseLayout, ToolRenderer
from onyx.chat.response_models import (
    ChatMessageMetadata,
    CitationMode,
    MessageRendering,
    ResponseRecord,
)
from onyx.configs.constants import DocumentSource
from onyx.context.search.models import SearchDoc
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.interfaces import GenerationContext
from onyx.llm.model_response import (
    Delta,
    MessageAccumulator,
    ModelResponseStream,
    StreamingChoice,
)
from onyx.llm.models import (
    AssistantMessage,
    GenerationDoneEvent,
    GenerationErrorEvent,
    GenerationRequest,
    GenerationRequestParams,
    GenerationStartEvent,
    Message,
    ReasoningEffort,
    TextContent,
    TextDeltaEvent,
    ToolCall,
    ToolDefinition,
    ToolResult,
    ToolResultMessage,
    UserMessage,
)
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import (
    AgentResponseDelta,
    AgentResponseStart,
    BashToolDelta,
    BashToolStart,
    CitationInfo,
    CustomToolStart,
    OverallStop,
    Packet,
    PacketException,
    SearchToolStart,
    SectionEnd,
    ToolCallDebug,
)
from onyx.tools.results import LlmBashExecutionResult, ToolExecutionError
from onyx.tracing.flows import LLMFlow
from tests.unit.onyx.agents.fakes import FakeModelClient, run_agent


class _PacketQueue(Queue[tuple[int, Packet | Exception | object]]):
    def __init__(self, packets: list[Packet]) -> None:
        super().__init__()
        self.packets = packets

    def put(
        self,
        item: tuple[int, Packet | Exception | object],
        block: bool = True,
        timeout: float | None = None,
    ) -> None:
        del block, timeout
        assert isinstance(item[1], Packet)
        self.packets.append(item[1])


def _emitter(packets: list[Packet]) -> Emitter:
    return Emitter(_PacketQueue(packets))


class _Execution(BaseModel):
    requests: list[GenerationRequest]
    messages: list[Message]
    executed: list[str]


def test_rendering_does_not_change_requests_transcript_or_execution() -> None:
    def run(render: bool) -> _Execution:
        executed: list[str] = []

        def echo(_invocation: ToolInvocation) -> ToolResult:
            executed.append("echo")
            return ToolResult(content="tool value")

        requests: list[GenerationRequest] = []
        responses = iter(
            [
                AssistantMessage(
                    content=[
                        TextContent(text="Let me check."),
                        ToolCall(id="call", name="echo", arguments={}),
                    ],
                ),
                AssistantMessage(content=[TextContent(text="Answer [1].")]),
            ]
        )

        def reply(
            request: GenerationRequest, _signal: CancellationSignal
        ) -> AssistantMessage:
            requests.append(request.model_copy(deep=True))
            return next(responses)

        llm = FakeModelClient(reply)
        agent = Agent(
            llm,
            generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
            tools=[
                AgentTool(
                    definition=ToolDefinition(
                        name="echo", description="", parameters={}
                    ),
                    execute=echo,
                ),
            ],
        )
        listener = None
        if render:
            presentation = ResponsePresenter(Emitter(Queue()))
            listener = presentation.consume
        run_agent(
            agent,
            messages=[UserMessage(content="Question")],
            max_steps=2,
            listener=listener,
        )
        return _Execution(
            requests=requests, messages=agent.state.messages, executed=executed
        )

    rendered = run(True)
    plain = run(False)
    for execution in (rendered, plain):
        for message in execution.messages:
            message.id = None
        for request in execution.requests:
            for message in request.messages:
                message.id = None
    assert rendered == plain


@pytest.mark.parametrize(
    "fragments, expected",
    [
        (["Answer [", "1", "]."], "Answer."),
        (["[1]"], "[1]"),
        (["<unknown>literal XML</unknown>"], "<unknown>literal XML</unknown>"),
        (["unfinished ["], "unfinished ["),
    ],
)
def test_citation_display_keeps_raw_transcript(
    fragments: list[str], expected: str
) -> None:
    accumulator = MessageAccumulator()
    renderer = MessageRenderer(
        MessageRendering(citation_mode=CitationMode.REMOVE),
        {},
        ResponseLayout(),
    )
    packets: list[Packet] = []
    for fragment in fragments:
        for event in accumulator.add(
            ModelResponseStream(
                id="m",
                created="1",
                choice=StreamingChoice(delta=Delta(content=fragment)),
            )
        ):
            if not isinstance(
                event, (GenerationStartEvent, GenerationDoneEvent, GenerationErrorEvent)
            ):
                packets.extend(renderer.consume(event))
    for event in accumulator.end():
        if not isinstance(
            event, (GenerationStartEvent, GenerationDoneEvent, GenerationErrorEvent)
        ):
            packets.extend(renderer.consume(event))
    packets.extend(renderer.complete(accumulator.message))
    assert (
        "".join(p.obj.content for p in packets if isinstance(p.obj, AgentResponseDelta))
        == expected
    )
    assert renderer.answer == expected
    assert accumulator.message.text == "".join(fragments)


def test_snapshot_projects_partial_output_before_observers_receive_it() -> None:
    snapshot = RunState(
        run_id="run",
        status=RunStatus.CANCELLED,
        steps=[
            StepRecord(
                message=AssistantMessage(
                    id="run:0",
                    content=[TextContent(text="partial")],
                    stop_reason="aborted",
                    metadata=ChatMessageMetadata(),
                ),
                generation_status=ExecutionStatus.CANCELLED,
                tools={},
            )
        ],
    )
    snapshot.request_params = GenerationRequestParams(
        model_name="test",
        model_provider="test",
        reasoning_effort=ReasoningEffort.LOW,
        max_tokens=128,
        sent_kwargs={},
    )
    before = snapshot.model_dump()
    response = project_response(
        snapshot,
        tool_ids={},
    )
    assert response.answer == "partial"
    assert response.request_params == snapshot.request_params
    assert snapshot.model_dump() == before


def test_formatting_failure_keeps_accepted_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_formatting(
        _presentation: MessageRendering,
        _documents: Mapping[str, SearchDoc],
        _layout: ResponseLayout,
    ) -> MessageRenderer:
        raise ValueError("Invalid display metadata")

    agent = Agent(
        FakeModelClient(
            lambda _request, _signal: AssistantMessage(
                content=[TextContent(text="Accepted answer")]
            )
        ),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
    )
    run = agent.start(messages=[UserMessage(content="Question")], max_steps=1)
    run.result(timeout=10)
    monkeypatch.setattr("onyx.chat.presentation.MessageRenderer", fail_formatting)
    response = project_response(run.snapshot(), tool_ids={})
    assert response.response is not None
    assert response.response.messages[-1].text == "Accepted answer"
    assert response.answer == "Accepted answer"
    assert (
        response.error
        == "Response formatting failed. The accepted content has been retained."
    )


def test_interrupted_text_is_not_duplicated_and_matches_reload() -> None:
    message = AssistantMessage(content=[TextContent(text="See [1")])
    settings = MessageRendering(citation_mode=CitationMode.HYPERLINK)
    live = MessageRenderer(settings, {}, ResponseLayout())
    output = live.consume(TextDeltaEvent(content_index=0, text="See [1"))
    output += live.complete(message)
    output += live.finish()
    saved = MessageRenderer(settings, {}, ResponseLayout())
    restored = saved.complete(message)
    assert live.answer == saved.answer == "See [1"
    assert (
        "".join(p.obj.content for p in output if isinstance(p.obj, AgentResponseDelta))
        == "See [1"
    )
    assert (
        "".join(
            p.obj.content for p in restored if isinstance(p.obj, AgentResponseDelta)
        )
        == "See [1"
    )
    assert sum(isinstance(p.obj, AgentResponseStart) for p in output) == 1
    assert isinstance(output[-1].obj, SectionEnd)


def test_parallel_child_packets_stay_in_parent_tabs() -> None:
    output: list[Packet] = []
    presenter = ResponsePresenter(_emitter(output))
    calls = [
        ToolCall(id=str(i), name="research_agent", arguments={"task": str(i)})
        for i in range(2)
    ]
    presenter.consume(
        MessageStartEvent(run_id="root", message_id="parent", step_index=0)
    )
    presenter.consume(
        MessageEndEvent(
            run_id="root",
            message_id="parent",
            step_index=0,
            message=AssistantMessage(content=calls),
            status=ExecutionStatus.COMPLETE,
        )
    )
    for i, call in enumerate(calls):
        presenter.consume(
            ToolStartEvent(
                run_id="root", message_id="parent", step_index=0, tool_call=call
            )
        )
        presenter.consume(
            MessageStartEvent(
                run_id=str(i),
                message_id=f"child-{i}",
                step_index=0,
                parent_run_id="root",
                parent_message_id="parent",
                parent_tool_call_id=call.id,
            )
        )
        presenter.consume(
            MessageEndEvent(
                run_id=str(i),
                message_id=f"child-{i}",
                step_index=0,
                parent_run_id="root",
                parent_message_id="parent",
                parent_tool_call_id=call.id,
                message=AssistantMessage(content=[TextContent(text=str(i))]),
                status=ExecutionStatus.COMPLETE,
            )
        )
        presenter.consume(
            AgentEndEvent(
                run_id=str(i), parent_run_id="root", outcome=RunStatus.COMPLETE
            )
        )
    text = [p for p in output if isinstance(p.obj, AgentResponseDelta)]
    assert [
        (p.placement.turn_index, p.placement.tab_index, p.placement.sub_turn_index)
        for p in text
    ] == [(0, 0, 0), (0, 1, 0)]
    assert not any(isinstance(p.obj, OverallStop) for p in output)


def test_citation_recovery_waits_for_completion_and_does_not_duplicate() -> None:
    raw = "[1234567890123456789]"
    renderer = MessageRenderer(
        MessageRendering(citation_mode=CitationMode.HYPERLINK), {}, ResponseLayout()
    )
    early = renderer.consume(TextDeltaEvent(content_index=0, text=raw))
    assert not any(
        isinstance(p.obj, AgentResponseDelta) and p.obj.content for p in early
    )
    final = renderer.complete(AssistantMessage(content=[TextContent(text=raw)]))
    assert (
        "".join(p.obj.content for p in final if isinstance(p.obj, AgentResponseDelta))
        == raw
    )
    assert not any(isinstance(p.obj, AgentResponseDelta) for p in renderer.finish())


def test_root_narration_and_search_use_distinct_render_groups() -> None:
    packets: list[Packet] = []
    presenter = ResponsePresenter(_emitter(packets))
    call = ToolCall(
        id="search", name="internal_search", arguments={"queries": ["topic"]}
    )
    presenter.consume(
        MessageStartEvent(run_id="run", message_id="message", step_index=0)
    )
    presenter.consume(
        MessageUpdateEvent(
            run_id="run",
            message_id="message",
            step_index=0,
            generation_event=TextDeltaEvent(content_index=0, text="Let me search."),
        )
    )
    presenter.consume(
        MessageEndEvent(
            run_id="run",
            message_id="message",
            step_index=0,
            message=AssistantMessage(
                content=[TextContent(text="Let me search."), call]
            ),
            status=ExecutionStatus.COMPLETE,
        )
    )
    presenter.consume(
        ToolStartEvent(run_id="run", message_id="message", step_index=0, tool_call=call)
    )
    narration = [
        p
        for p in packets
        if isinstance(p.obj, (AgentResponseStart, AgentResponseDelta))
    ]
    [search] = [p for p in packets if isinstance(p.obj, SearchToolStart)]
    assert (
        "".join(
            p.obj.content for p in narration if isinstance(p.obj, AgentResponseDelta)
        )
        == "Let me search."
    )
    assert all(
        (p.placement.turn_index, p.placement.tab_index)
        != (search.placement.turn_index, search.placement.tab_index)
        for p in narration
    )


@pytest.mark.parametrize("live", [False, True])
def test_leading_citation_keeps_metadata(live: bool) -> None:
    doc = SearchDoc(
        document_id="doc",
        chunk_ind=0,
        semantic_identifier="Source",
        link="https://example.com",
        blurb="source",
        source_type=DocumentSource.WEB,
        boost=1,
        hidden=False,
        metadata={},
        match_highlights=[],
    )
    renderer = MessageRenderer(
        MessageRendering(
            citation_mode=CitationMode.HYPERLINK, citation_documents={1: "doc"}
        ),
        {"doc": doc},
        ResponseLayout(),
    )
    packets = (
        renderer.consume(TextDeltaEvent(content_index=0, text="[1] Answer"))
        if live
        else []
    )
    packets.extend(
        renderer.complete(AssistantMessage(content=[TextContent(text="[1] Answer")]))
    )
    citations = [p for p in packets if isinstance(p.obj, CitationInfo)]
    starts = [p for p in packets if isinstance(p.obj, AgentResponseStart)]
    assert len(citations) == len(starts) == 1
    assert citations[0].placement == starts[0].placement


@pytest.mark.parametrize("debug", [False, True])
def test_bash_debug_packet_precedes_output_start(
    debug: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("onyx.chat.renderer.INTEGRATION_TESTS_MODE", debug)
    renderer = ToolRenderer(
        ToolCall(id="bash", name="bash", arguments={"cmd": "pwd"}),
        Placement(turn_index=0),
    )
    packets = renderer.start()
    packets.extend(
        renderer.complete(
            ToolResult(
                content="done",
                details=LlmBashExecutionResult(
                    stdout="/repo", stderr="", exit_code=0, timed_out=False
                ),
            )
        )
    )
    assert sum(isinstance(p.obj, ToolCallDebug) for p in packets) == int(debug)
    start = next(i for i, p in enumerate(packets) if isinstance(p.obj, BashToolStart))
    assert isinstance(packets[start + 1].obj, BashToolDelta)


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("run_python", {"code": []}),
        ("internal_search", {"queries": 3}),
        ("open_url", {"urls": {}}),
        ("bash", {"cmd": None}),
    ],
)
def test_invalid_tool_arguments_replay_the_error_and_later_answer(
    name: str, arguments: dict[str, JsonValue]
) -> None:
    call = ToolCall(id="call", name=name, arguments=arguments)
    response = ResponseRecord(
        run_id="r",
        status=RunStatus.COMPLETE,
        steps=[
            StepRecord(
                message=AssistantMessage(id="m", content=[call]),
                generation_status=ExecutionStatus.COMPLETE,
                tools={
                    "call": ToolExecutionRecord(
                        status=ExecutionStatus.ERROR,
                        result=ToolResultMessage(
                            tool_call_id="call",
                            tool_name=name,
                            content="Invalid arguments",
                            is_error=True,
                            details=ToolExecutionError(message="Invalid arguments"),
                        ),
                    )
                },
            ),
            StepRecord(
                message=AssistantMessage(
                    id="answer", content=[TextContent(text="Recovered answer")]
                ),
                generation_status=ExecutionStatus.COMPLETE,
            ),
        ],
        answer_step_index=1,
    )
    packets = replay_response(response, {}, {}, {})
    assert any(isinstance(p.obj, CustomToolStart) for p in packets)
    assert any(
        isinstance(p.obj, PacketException)
        and str(p.obj.exception) == "Invalid arguments"
        for p in packets
    )
    assert any(
        isinstance(p.obj, AgentResponseDelta) and p.obj.content == "Recovered answer"
        for p in packets
    )


@pytest.mark.parametrize("reasoning", ["Reasoning", []])
def test_replay_hides_configured_thinking_tool(reasoning: str | list[str]) -> None:
    response = ResponseRecord(
        run_id="r",
        status=RunStatus.COMPLETE,
        steps=[
            StepRecord(
                message=AssistantMessage(
                    id="m",
                    content=[
                        ToolCall(
                            id="think",
                            name="think",
                            arguments={"reasoning": reasoning},
                        )
                    ],
                ),
                generation_status=ExecutionStatus.COMPLETE,
            ),
        ],
    )
    packets = replay_response(
        response, {}, {"m": MessageRendering(think_tool="think")}, {}
    )
    assert not any(isinstance(p.obj, CustomToolStart) for p in packets)
    assert any(p.obj.type == "reasoning_delta" for p in packets) == bool(reasoning)


@pytest.mark.parametrize("status", [RunStatus.ERROR, RunStatus.CANCELLED])
def test_interrupted_answer_citations_belong_to_the_selected_text(
    status: RunStatus,
) -> None:
    doc = SearchDoc(
        document_id="doc",
        chunk_ind=0,
        semantic_identifier="Source",
        link="https://example.com",
        blurb="source",
        source_type=DocumentSource.WEB,
        boost=1,
        hidden=False,
        metadata={},
        match_highlights=[],
    )
    metadata = ChatMessageMetadata(sources={1: doc})
    snapshot = RunState(
        run_id="r",
        status=status,
        steps=[
            StepRecord(
                message=AssistantMessage(
                    id="checking",
                    content=[TextContent(text="Checking [1].")],
                    metadata=metadata,
                ),
                generation_status=ExecutionStatus.COMPLETE,
            ),
            StepRecord(
                message=AssistantMessage(
                    id="partial",
                    content=[TextContent(text="Partial answer")],
                    metadata=metadata,
                ),
                generation_status=ExecutionStatus.ERROR,
            ),
        ],
    )
    response = project_response(snapshot, tool_ids={})
    assert response.answer == "Partial answer"
    assert response.citation_info == []
