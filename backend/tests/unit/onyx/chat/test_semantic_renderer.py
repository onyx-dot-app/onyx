"""The packet view cannot drive model requests or tool execution."""

from collections.abc import Mapping

import pytest
from pydantic import BaseModel, JsonValue

from onyx.agents.events import (
    AgentEndEvent,
    MessageEndEvent,
    MessageStartEvent,
    MessageUpdateEvent,
    ToolEndEvent,
    ToolStartEvent,
)
from onyx.agents.models import (
    ExecutionStatus,
    RunState,
    RunStatus,
    StepRecord,
    ToolExecutionRecord,
)
from onyx.agents.runtime import Agent, Run
from onyx.agents.tools import AgentTool, ToolInvocation
from onyx.chat.emitter import Emitter
from onyx.chat.models import (
    ChatMessageMetadata,
    CitationMode,
    MessageRendering,
    PresentationMode,
    ResponseRecord,
)
from onyx.chat.presentation import ResponsePresenter, project_response, replay_response
from onyx.chat.renderer import MessageRenderer, ResponseLayout, ToolRenderer
from onyx.chat.response import response_record, tool_arguments_for_display
from onyx.coding_agent.models import CodingAgentCallResult
from onyx.coding_agent.tool_definitions import CODING_AGENT_TOOL_NAME
from onyx.configs.constants import DocumentSource
from onyx.context.search.models import SearchDoc
from onyx.deep_research.models import ResearchAgentCallResult
from onyx.deep_research.tool_definitions import RESEARCH_AGENT_TOOL_NAME
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
    ThinkingContent,
    ThinkingDeltaEvent,
    ToolCall,
    ToolCallDeltaEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
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
    CodingAgentFinal,
    CodingAgentThinkingDelta,
    CustomToolDelta,
    CustomToolStart,
    IntermediateReportCitedDocs,
    IntermediateReportDelta,
    OverallStop,
    Packet,
    PacketException,
    PythonToolStart,
    ReasoningDelta,
    SearchToolStart,
    SectionEnd,
    ToolCallArgumentDelta,
    ToolCallDebug,
)
from onyx.tools.models import (
    CustomToolCallSummary,
    CustomToolErrorInfo,
    LlmBashExecutionResult,
    ToolExecutionError,
)
from onyx.tools.tool_implementations.python.python_tool import PythonTool
from onyx.tracing.flows import LLMFlow
from tests.unit.onyx.agents.fakes import FakeModelClient, run_agent


def _emitter(packets: list[Packet]) -> Emitter:
    return Emitter(packets.append)


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
            presentation = ResponsePresenter(Emitter(lambda _packet: None))
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
        (["[1]"], ""),
        (["<unknown>literal XML</unknown>"], "<unknown>literal XML</unknown>"),
        (["unfinished ["], "unfinished ["),
    ],
)
@pytest.mark.parametrize("streamed", [False, True])
def test_citation_display_keeps_raw_transcript(
    fragments: list[str], expected: str, streamed: bool
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
            if streamed and not isinstance(
                event, (GenerationStartEvent, GenerationDoneEvent, GenerationErrorEvent)
            ):
                packets.extend(renderer.consume(event))
    for event in accumulator.end():
        if streamed and not isinstance(
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


@pytest.mark.parametrize("boundary", ["thinking", "tool"])
@pytest.mark.parametrize("streamed_blocks", [0, 1, 2, 3])
def test_interleaved_answer_sections_preserve_content_order(
    boundary: str, streamed_blocks: int
) -> None:
    call = ToolCall(id="search", name="internal_search", arguments={})
    message = AssistantMessage(
        content=[
            TextContent(text="Before ["),
            ThinkingContent(text="Check") if boundary == "thinking" else call,
            TextContent(text="After"),
        ]
    )
    renderer = MessageRenderer(
        MessageRendering(citation_mode=CitationMode.HYPERLINK), {}, ResponseLayout()
    )
    events = [
        TextDeltaEvent(content_index=0, text="Before ["),
        ThinkingDeltaEvent(content_index=1, text="Check")
        if boundary == "thinking"
        else ToolCallStartEvent(
            content_index=1, tool_call_id=call.id, tool_name=call.name
        ),
        TextDeltaEvent(content_index=2, text="After"),
    ]
    output = [
        packet
        for event in events[:streamed_blocks]
        for packet in renderer.consume(event)
    ]
    output.extend(renderer.complete(message))
    sections: dict[int, str] = {}
    for packet in output:
        if isinstance(packet.obj, AgentResponseDelta):
            section = packet.placement.turn_index
            sections[section] = sections.get(section, "") + packet.obj.content
    assert sections == {0: "Before [", 2: "After"}
    assert renderer.answer == "Before [After"
    assert renderer.answer_started
    assert [
        packet.placement.turn_index
        for packet in output
        if isinstance(packet.obj, SectionEnd)
    ] == ([0, 1, 2] if boundary == "thinking" else [0, 2])


@pytest.mark.parametrize("boundary", ["text", "thinking"])
@pytest.mark.parametrize("streamed_blocks", [0, 1, 3, 5])
def test_tool_tabs_do_not_cross_interleaved_content(
    boundary: str, streamed_blocks: int
) -> None:
    calls = [
        ToolCall(id=str(index), name="internal_search", arguments={})
        for index in range(4)
    ]
    content = (
        TextContent(text="Between searches")
        if boundary == "text"
        else ThinkingContent(text="Between searches")
    )
    message = AssistantMessage(content=[*calls[:2], content, *calls[2:]])
    events = [
        ToolCallStartEvent(
            content_index=0, tool_call_id="0", tool_name="internal_search"
        ),
        ToolCallStartEvent(
            content_index=1, tool_call_id="1", tool_name="internal_search"
        ),
        TextDeltaEvent(content_index=2, text="Between searches")
        if boundary == "text"
        else ThinkingDeltaEvent(content_index=2, text="Between searches"),
        ToolCallStartEvent(
            content_index=3, tool_call_id="2", tool_name="internal_search"
        ),
        ToolCallStartEvent(
            content_index=4, tool_call_id="3", tool_name="internal_search"
        ),
    ]
    renderer = MessageRenderer(MessageRendering(), {}, ResponseLayout())
    output = [
        packet
        for event in events[:streamed_blocks]
        for packet in renderer.consume(event)
    ]
    output.extend(renderer.complete(message))
    for call in calls:
        output.extend(ToolRenderer(call, renderer.tool_placement(call.id)).start())
    assert [
        (packet.placement.turn_index, packet.placement.tab_index)
        for packet in output
        if isinstance(packet.obj, SearchToolStart)
    ] == [(0, 0), (0, 1), (2, 0), (2, 1)]
    assert [
        packet.placement.turn_index
        for packet in output
        if isinstance(packet.obj, (AgentResponseDelta, ReasoningDelta))
    ] == [1]


@pytest.mark.parametrize("text, cited", [("Report [2]", ["2"]), ("Report", [])])
def test_report_sources_include_only_observed_citations(
    text: str, cited: list[str]
) -> None:
    documents = {
        key: SearchDoc(
            document_id=key,
            chunk_ind=0,
            semantic_identifier=key,
            link=f"https://example.com/{key}",
            blurb="source",
            source_type=DocumentSource.WEB,
            boost=1,
            hidden=False,
            metadata={},
            match_highlights=[],
        )
        for key in ("1", "2")
    }
    settings = MessageRendering(
        mode=PresentationMode.REPORT,
        citation_mode=CitationMode.KEEP_MARKERS,
        citation_documents={1: "1", 2: "2"},
        document_ids=["1", "2"],
    )
    message = AssistantMessage(content=[TextContent(text=text)])
    live = MessageRenderer(settings, documents, ResponseLayout())
    output = live.consume(TextDeltaEvent(content_index=0, text=text))
    output.extend(live.complete(message))
    saved = MessageRenderer(settings, documents, ResponseLayout()).complete(message)
    for packets in (output, saved):
        assert [
            doc.document_id
            for packet in packets
            if isinstance(packet.obj, IntermediateReportCitedDocs)
            for doc in packet.obj.cited_docs or []
        ] == cited


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


@pytest.mark.parametrize("live", [False, True])
@pytest.mark.parametrize("tool_thinking", [False, True])
@pytest.mark.parametrize(
    "mode", [PresentationMode.CODING_THINKING, PresentationMode.CODING_ANSWER]
)
def test_coding_thinking_uses_coding_packets(
    live: bool, tool_thinking: bool, mode: PresentationMode
) -> None:
    settings = MessageRendering(mode=mode, think_tool="think")
    message = AssistantMessage(
        id="m",
        content=[
            ToolCall(id="t", name="think", arguments={"reasoning": "Inspect the code"})
            if tool_thinking
            else ThinkingContent(text="Inspect the code")
        ],
    )
    parent = Placement(turn_index=3, tab_index=1)
    if live:
        renderer = MessageRenderer(settings, {}, ResponseLayout(), parent)
        if tool_thinking:
            call = message.tool_calls[0]
            output = renderer.consume(
                ToolCallStartEvent(
                    content_index=0, tool_call_id=call.id, tool_name=call.name
                )
            )
            output.extend(
                renderer.consume(ToolCallEndEvent(content_index=0, tool_call=call))
            )
        else:
            output = renderer.consume(
                ThinkingDeltaEvent(content_index=0, text="Inspect the code")
            )
        output.extend(renderer.complete(message))
    else:
        output = replay_response(
            ResponseRecord(
                run_id="child",
                parent_run_id="root",
                status=RunStatus.COMPLETE,
                steps=[
                    StepRecord(
                        message=message, generation_status=ExecutionStatus.COMPLETE
                    )
                ],
            ),
            {},
            {"m": settings},
            {},
            parent=parent,
        )
    assert [
        packet.obj.content
        for packet in output
        if isinstance(packet.obj, CodingAgentThinkingDelta)
    ] == ["Inspect the code"]
    assert not any(packet.obj.type.startswith("reasoning_") for packet in output)
    assert all(
        (packet.placement.turn_index, packet.placement.tab_index) == (3, 1)
        for packet in output
    )


@pytest.mark.parametrize("live", [False, True])
def test_parallel_coding_commands_keep_separate_output_sections(live: bool) -> None:
    calls = [
        ToolCall(id=str(index), name="bash", arguments={"cmd": f"command-{index}"})
        for index in range(2)
    ]
    message = AssistantMessage(
        id="coding", content=[ThinkingContent(text="Inspect both files"), *calls]
    )
    settings = MessageRendering(mode=PresentationMode.CODING_THINKING)
    parent = Placement(turn_index=3, tab_index=1)
    results = {
        call.id: ToolResultMessage(
            tool_call_id=call.id,
            tool_name=call.name,
            content=f"output-{call.id}",
            details=LlmBashExecutionResult(
                stdout=f"output-{call.id}",
                stderr="",
                exit_code=int(call.id),
                timed_out=False,
            ),
        )
        for call in calls
    }
    if live:
        renderer = MessageRenderer(settings, {}, ResponseLayout(), parent)
        output = renderer.consume(
            ThinkingDeltaEvent(content_index=0, text="Inspect both files")
        )
        for index, call in enumerate(calls, 1):
            output.extend(
                renderer.consume(
                    ToolCallStartEvent(
                        content_index=index, tool_call_id=call.id, tool_name=call.name
                    )
                )
            )
        output.extend(renderer.complete(message))
        tools = [ToolRenderer(call, renderer.tool_placement(call.id)) for call in calls]
        for tool in tools:
            output.extend(tool.start())
        for tool, call in zip(reversed(tools), reversed(calls), strict=True):
            output.extend(tool.complete(results[call.id]))
    else:
        output = replay_response(
            ResponseRecord(
                run_id="child",
                parent_run_id="root",
                status=RunStatus.COMPLETE,
                steps=[
                    StepRecord(
                        message=message,
                        generation_status=ExecutionStatus.COMPLETE,
                        tools={
                            call.id: ToolExecutionRecord(
                                status=ExecutionStatus.COMPLETE, result=results[call.id]
                            )
                            for call in calls
                        },
                    )
                ],
            ),
            {},
            {"coding": settings},
            {},
            parent=parent,
        )
    starts = {
        packet.obj.cmd: packet.placement
        for packet in output
        if isinstance(packet.obj, BashToolStart)
    }
    assert starts["command-0"] != starts["command-1"]
    for index in range(2):
        delta = next(
            packet
            for packet in output
            if isinstance(packet.obj, BashToolDelta)
            and packet.obj.stdout == f"output-{index}"
        )
        assert delta.placement == starts[f"command-{index}"]
        assert isinstance(delta.obj, BashToolDelta)
        assert delta.obj.exit_code == index
    thinking = next(
        packet for packet in output if isinstance(packet.obj, CodingAgentThinkingDelta)
    )
    assert all(thinking.placement != placement for placement in starts.values())


@pytest.mark.parametrize("tool_first", [False, True])
def test_replay_preserves_live_text_and_tool_section_order(tool_first: bool) -> None:
    call = ToolCall(id="search", name="internal_search", arguments={"queries": ["q"]})
    text = TextContent(text="Let me check.")
    message = AssistantMessage(
        id="m", content=[call, text] if tool_first else [text, call]
    )
    output: list[Packet] = []
    presenter = ResponsePresenter(_emitter(output))
    presenter.consume(MessageStartEvent(run_id="r", message_id="m", step_index=0))
    for index, block in enumerate(message.content):
        event = (
            ToolCallStartEvent(
                content_index=index, tool_call_id=call.id, tool_name=call.name
            )
            if isinstance(block, ToolCall)
            else TextDeltaEvent(content_index=index, text=text.text)
        )
        presenter.consume(
            MessageUpdateEvent(
                run_id="r", message_id="m", step_index=0, generation_event=event
            )
        )
    presenter.consume(
        MessageEndEvent(
            run_id="r",
            message_id="m",
            step_index=0,
            message=message,
            status=ExecutionStatus.COMPLETE,
        )
    )
    presenter.consume(
        ToolStartEvent(run_id="r", message_id="m", step_index=0, tool_call=call)
    )
    replay = replay_response(
        ResponseRecord(
            run_id="r",
            status=RunStatus.COMPLETE,
            steps=[
                StepRecord(message=message, generation_status=ExecutionStatus.COMPLETE)
            ],
        ),
        {},
        {},
        {},
    )
    for packet_type in (AgentResponseStart, SearchToolStart):
        live_placements = [
            (
                packet.placement.turn_index,
                packet.placement.tab_index,
                packet.placement.sub_turn_index,
            )
            for packet in output
            if isinstance(packet.obj, packet_type)
        ]
        saved_placements = [
            (
                packet.placement.turn_index,
                packet.placement.tab_index,
                packet.placement.sub_turn_index,
            )
            for packet in replay
            if isinstance(packet.obj, packet_type)
        ]
        assert live_placements == saved_placements
        assert len(live_placements) == 1
    tool_section = next(
        packet.placement.turn_index
        for packet in replay
        if isinstance(packet.obj, SearchToolStart)
    )
    text_section = next(
        packet.placement.turn_index
        for packet in replay
        if isinstance(packet.obj, AgentResponseStart)
    )
    assert (tool_section < text_section) == tool_first


@pytest.mark.parametrize("live", [False, True])
@pytest.mark.parametrize("public_error", [False, True])
def test_tool_errors_only_display_explicit_public_details(
    live: bool, public_error: bool
) -> None:
    call = ToolCall(id="call", name="custom", arguments={})
    result = ToolResultMessage(
        tool_call_id=call.id,
        tool_name=call.name,
        content="Private provider exception",
        is_error=True,
        details=CustomToolCallSummary(
            tool_name=call.name,
            response_type="text",
            tool_result="",
            error=CustomToolErrorInfo(
                status_code=None, message="Please reconnect this tool"
            ),
        )
        if public_error
        else None,
    )
    if live:
        renderer = ToolRenderer(call, Placement(turn_index=0))
        output = renderer.start() + renderer.complete(result)
    else:
        output = replay_response(
            ResponseRecord(
                run_id="r",
                status=RunStatus.COMPLETE,
                steps=[
                    StepRecord(
                        message=AssistantMessage(id="m", content=[call]),
                        generation_status=ExecutionStatus.COMPLETE,
                        tools={
                            call.id: ToolExecutionRecord(
                                status=ExecutionStatus.COMPLETE, result=result
                            )
                        },
                    )
                ],
            ),
            {},
            {},
            {},
        )
    assert all(
        "Private provider exception" not in packet.model_dump_json()
        for packet in output
    )
    public_errors = [
        packet.obj.error
        for packet in output
        if isinstance(packet.obj, CustomToolDelta) and packet.obj.error
    ]
    assert [error.message for error in public_errors] == (
        ["Please reconnect this tool"] if public_error else []
    )
    assert result.text == "Private provider exception"


@pytest.mark.parametrize("live", [False, True])
def test_completion_batches_content_and_decodes_thinking_once(
    live: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    decoded_calls: list[str] = []

    def decode(call: ToolCall) -> dict[str, JsonValue]:
        decoded_calls.append(call.id)
        return tool_arguments_for_display(call)

    monkeypatch.setattr("onyx.chat.response.tool_arguments_for_display", decode)
    think = ToolCall(
        id="think",
        name="think",
        arguments={},
        raw_arguments='{"reasoning":"' + "r" * 128,
        arguments_complete=False,
    )
    tool = ToolCall(id="lookup", name="lookup", arguments={})
    message = AssistantMessage(
        content=[
            *[ThinkingContent(text="r") for _ in range(128)],
            think,
            *[TextContent(text="a") for _ in range(128)],
            tool,
            *[TextContent(text="b") for _ in range(128)],
        ]
    )
    renderer = MessageRenderer(
        MessageRendering(think_tool="think"), {}, ResponseLayout()
    )
    output: list[Packet] = []
    if live:
        output.extend(
            renderer.consume(ThinkingDeltaEvent(content_index=0, text="r" * 64))
        )
    output.extend(renderer.complete(message))
    assert renderer.complete(message) == []
    assert decoded_calls == ["think"]
    assert renderer.reasoning == "r" * 256
    assert renderer.answer == "a" * 128 + "b" * 128
    assert [
        packet.obj.reasoning
        for packet in output
        if isinstance(packet.obj, ReasoningDelta)
    ] == (["r" * 64, "r" * 192] if live else ["r" * 256])
    assert [
        packet.obj.content
        for packet in output
        if isinstance(packet.obj, AgentResponseDelta)
    ] == ["a" * 128, "b" * 128]
    answer_start = next(
        packet for packet in output if isinstance(packet.obj, AgentResponseStart)
    )
    assert (
        renderer.tool_placement(tool.id).turn_index > answer_start.placement.turn_index
    )
    assert think.arguments == {}
    assert len(message.content) == 386


@pytest.mark.parametrize("public_error", [False, True])
def test_live_tool_failure_keeps_private_text_out_of_packets(
    public_error: bool,
) -> None:
    packets: list[Packet] = []
    presenter = ResponsePresenter(_emitter(packets))
    private_error = "Internal service credential could not be loaded"
    tool = AgentTool(
        definition=ToolDefinition(name="custom_action", description="", parameters={}),
        execute=lambda _: ToolResult(
            content=private_error,
            is_error=True,
            details=ToolExecutionError(message="Action unavailable")
            if public_error
            else None,
        ),
    )
    agent = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(
                content=[ToolCall(id="call", name=tool.name, arguments={})]
            )
        ),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        tools=[tool],
    )
    run_agent(agent, max_steps=1, listener=presenter.consume)
    assert all(private_error not in packet.model_dump_json() for packet in packets)
    assert sum(isinstance(packet.obj, PacketException) for packet in packets) == int(
        public_error
    )
    result = agent.state.messages[-1]
    assert isinstance(result, ToolResultMessage)
    assert result.is_error and result.text == private_error


@pytest.mark.parametrize(
    ("status", "tool_started", "tool_finished"),
    [
        (ExecutionStatus.CANCELLED, False, False),
        (ExecutionStatus.ERROR, False, False),
        (ExecutionStatus.COMPLETE, False, False),
        (ExecutionStatus.COMPLETE, True, False),
        (ExecutionStatus.COMPLETE, True, True),
    ],
)
def test_interrupted_python_arguments_close_the_live_code_card(
    status: ExecutionStatus,
    tool_started: bool,
    tool_finished: bool,
) -> None:
    output: list[Packet] = []
    presenter = ResponsePresenter(_emitter(output))
    call = ToolCall(
        id="python",
        name=PythonTool.NAME,
        arguments={"code": "print(1)"} if status == ExecutionStatus.COMPLETE else {},
        raw_arguments=(
            '{"code":"print(1)"}'
            if status == ExecutionStatus.COMPLETE
            else '{"code":"print(1)'
        ),
        arguments_complete=status == ExecutionStatus.COMPLETE,
    )
    message = AssistantMessage(id="m", content=[call])
    presenter.consume(MessageStartEvent(run_id="r", message_id="m", step_index=0))
    for update in (
        ToolCallStartEvent(content_index=0, tool_call_id=call.id, tool_name=call.name),
        ToolCallDeltaEvent(content_index=0, arguments_delta=call.raw_arguments or ""),
    ):
        presenter.consume(
            MessageUpdateEvent(
                run_id="r", message_id="m", step_index=0, generation_event=update
            )
        )
    assert any(isinstance(packet.obj, ToolCallArgumentDelta) for packet in output)
    if status == ExecutionStatus.COMPLETE:
        presenter.consume(
            MessageUpdateEvent(
                run_id="r",
                message_id="m",
                step_index=0,
                generation_event=ToolCallEndEvent(content_index=0, tool_call=call),
            )
        )
    presenter.consume(
        MessageEndEvent(
            run_id="r", message_id="m", step_index=0, message=message, status=status
        )
    )
    if tool_started:
        presenter.consume(
            ToolStartEvent(run_id="r", message_id="m", step_index=0, tool_call=call)
        )
    if tool_finished:
        presenter.consume(
            ToolEndEvent(
                run_id="r",
                message_id="m",
                step_index=0,
                tool_call=call,
                result=ToolResult(content=""),
            )
        )
    presenter.consume(AgentEndEvent(run_id="r", outcome=RunStatus.CANCELLED))
    replay = replay_response(
        ResponseRecord(
            run_id="r",
            status=RunStatus.CANCELLED
            if status == ExecutionStatus.CANCELLED
            else RunStatus.ERROR,
            steps=[StepRecord(message=message, generation_status=status)],
        ),
        {},
        {},
        {},
    )
    for packets in (output, replay):
        starts = [
            packet for packet in packets if isinstance(packet.obj, PythonToolStart)
        ]
        assert len(starts) == 1
        assert starts[0].obj == PythonToolStart(code="print(1)")
        assert (
            sum(
                isinstance(packet.obj, SectionEnd)
                and packet.placement == starts[0].placement
                for packet in packets
            )
            == 1
        )


def test_child_completion_closes_only_its_tool_cards() -> None:
    output: list[Packet] = []
    presenter = ResponsePresenter(_emitter(output))
    call = ToolCall(id="python", name=PythonTool.NAME, arguments={"code": "print(1)"})
    for run_id in ("parent", "child"):
        presenter.consume(
            MessageStartEvent(run_id=run_id, message_id="m", step_index=0)
        )
        presenter.consume(
            MessageEndEvent(
                run_id=run_id,
                message_id="m",
                step_index=0,
                message=AssistantMessage(id="m", content=[call]),
                status=ExecutionStatus.COMPLETE,
            )
        )
        presenter.consume(
            ToolStartEvent(run_id=run_id, message_id="m", step_index=0, tool_call=call)
        )
    starts = [packet for packet in output if isinstance(packet.obj, PythonToolStart)]
    assert len(starts) == 2
    presenter.consume(
        AgentEndEvent(
            run_id="child", parent_run_id="parent", outcome=RunStatus.CANCELLED
        )
    )
    ends = [packet for packet in output if isinstance(packet.obj, SectionEnd)]
    assert [packet.placement for packet in ends] == [starts[1].placement]
    presenter.consume(AgentEndEvent(run_id="parent", outcome=RunStatus.CANCELLED))
    ends = [packet for packet in output if isinstance(packet.obj, SectionEnd)]
    assert [packet.placement for packet in ends] == [
        starts[1].placement,
        starts[0].placement,
    ]


@pytest.mark.parametrize("coding", [False, True])
def test_completed_agent_tool_output_matches_replay(coding: bool) -> None:
    name = CODING_AGENT_TOOL_NAME if coding else RESEARCH_AGENT_TOOL_NAME
    details = (
        CodingAgentCallResult(answer="Final report")
        if coding
        else ResearchAgentCallResult(
            intermediate_report="Final report", citation_mapping={}
        )
    )
    output: list[Packet] = []
    presenter = ResponsePresenter(_emitter(output))
    runs: list[Run] = []
    run_agent(
        Agent(
            FakeModelClient(
                lambda *_: AssistantMessage(
                    content=[ToolCall(id="child", name=name, arguments={})]
                )
            ),
            generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
            tools=[
                AgentTool(
                    definition=ToolDefinition(name=name, description="", parameters={}),
                    execute=lambda _: ToolResult(
                        content="Final report", details=details
                    ),
                )
            ],
        ),
        max_steps=1,
        runs=runs,
        listener=presenter.consume,
    )
    replay = replay_response(response_record(runs[0].snapshot()), {}, {}, {})
    for packets in (output, replay):
        assert not any(
            isinstance(packet.obj, CodingAgentThinkingDelta) for packet in packets
        )
        if coding:
            assert [
                packet.obj.answer
                for packet in packets
                if isinstance(packet.obj, CodingAgentFinal)
            ] == ["Final report"]
        else:
            assert [
                packet.obj.content
                for packet in packets
                if isinstance(packet.obj, IntermediateReportDelta)
            ] == ["Final report"]
