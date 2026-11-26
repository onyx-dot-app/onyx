"""The packet view cannot drive model requests or tool execution."""

import threading
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
    RunFailure,
    RunFailureKind,
    RunOutcome,
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
    RunDocuments,
)
from onyx.chat.presentation import ResponsePresenter, project_response, replay_response
from onyx.chat.renderer import (
    CUSTOM_TOOL_ERROR_RESPONSE_TYPE,
    MessageRenderer,
    ResponseLayout,
    ToolRenderer,
)
from onyx.chat.response import response_record
from onyx.configs.constants import DocumentSource
from onyx.context.search.models import SearchDoc
from onyx.db.models import StoredToolResult
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
    CitationInfo,
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
)
from onyx.tools.models import (
    CustomToolCallSummary,
    CustomToolErrorInfo,
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
        RunDocuments(),
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
    live = MessageRenderer(settings, RunDocuments(), ResponseLayout())
    output = live.consume(TextDeltaEvent(content_index=0, text="See [1"))
    output += live.complete(message)
    output += live.finish()
    saved = MessageRenderer(settings, RunDocuments(), ResponseLayout())
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
        MessageRendering(citation_mode=CitationMode.HYPERLINK),
        RunDocuments(),
        ResponseLayout(),
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
    renderer = MessageRenderer(MessageRendering(), RunDocuments(), ResponseLayout())
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
    live = MessageRenderer(
        settings, RunDocuments().add_steps([(settings, documents)]), ResponseLayout()
    )
    output = live.consume(TextDeltaEvent(content_index=0, text=text))
    output.extend(live.complete(message))
    saved = MessageRenderer(
        settings, RunDocuments().add_steps([(settings, documents)]), ResponseLayout()
    ).complete(message)
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
        MessageRendering(citation_mode=CitationMode.HYPERLINK),
        RunDocuments(),
        ResponseLayout(),
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
    settings = MessageRendering(
        citation_mode=CitationMode.HYPERLINK, citation_documents={1: "doc"}
    )
    renderer = MessageRenderer(
        settings, RunDocuments().add_steps([(settings, {"doc": doc})]), ResponseLayout()
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


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("run_python", {"code": []}),
        ("internal_search", {"queries": 3}),
        ("open_url", {"urls": {}}),
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
@pytest.mark.parametrize("is_error", [False, True])
def test_generic_card_marks_a_failed_call_without_details(
    live: bool, is_error: bool
) -> None:
    """A call that raised ToolCallException has no error details. Its card
    still says that it failed, without the text the model got and without an
    error packet."""
    call = ToolCall(id="call", name="skills_read", arguments={"name": "missing"})
    result = ToolResultMessage(
        tool_call_id=call.id,
        tool_name=call.name,
        content="No skill is named 'missing'.",
        is_error=is_error,
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
    failures = [
        packet.obj
        for packet in output
        if isinstance(packet.obj, CustomToolDelta)
        and packet.obj.response_type == CUSTOM_TOOL_ERROR_RESPONSE_TYPE
    ]
    assert len(failures) == int(is_error)
    assert all(failure.data is None for failure in failures)
    assert not any(isinstance(packet.obj, PacketException) for packet in output)
    assert all(
        "No skill is named" not in packet.model_dump_json()
        for packet in output
        if is_error
    )
    assert any(isinstance(packet.obj, SectionEnd) for packet in output)


@pytest.mark.parametrize("live", [False, True])
def test_app_tool_auth_error_names_its_integration(live: bool) -> None:
    """An app tool has no tool row, so the chat opens the sign-in from the
    delta's integration ID."""
    call = ToolCall(id="call", name="app_7_list_issues", arguments={})
    result = ToolResultMessage(
        tool_call_id=call.id,
        tool_name=call.name,
        content="HTTP 401",
        is_error=True,
        details=CustomToolCallSummary(
            tool_name=call.name,
            integration_id=7,
            response_type="text",
            tool_result="",
            error=CustomToolErrorInfo(
                status_code=401, message="auth failed", is_auth_error=True
            ),
        ),
    )
    if live:
        renderer = ToolRenderer(call, Placement(turn_index=0))
        output = renderer.start() + renderer.complete(result)
    else:
        record = ResponseRecord(
            run_id="r",
            status=RunStatus.COMPLETE,
            steps=[
                StepRecord(
                    message=AssistantMessage(id="m", content=[call]),
                    generation_status=ExecutionStatus.COMPLETE,
                    tools={
                        call.id: ToolExecutionRecord(
                            status=ExecutionStatus.COMPLETE,
                            result=StoredToolResult.model_validate_json(
                                result.model_dump_json()
                            ),
                        )
                    },
                )
            ],
        )
        output = replay_response(record, {}, {}, {})
    deltas = [
        (packet.obj.tool_id, packet.obj.integration_id, packet.obj.error)
        for packet in output
        if isinstance(packet.obj, CustomToolDelta)
    ]
    assert len(deltas) == 1
    tool_id, integration_id, error = deltas[0]
    assert (tool_id, integration_id) == (None, 7)
    assert error is not None and error.is_auth_error


@pytest.mark.parametrize("live", [False, True])
def test_completion_batches_content(live: bool) -> None:
    tool = ToolCall(id="lookup", name="lookup", arguments={})
    message = AssistantMessage(
        content=[
            *[ThinkingContent(text="r") for _ in range(256)],
            *[TextContent(text="a") for _ in range(128)],
            tool,
            *[TextContent(text="b") for _ in range(128)],
        ]
    )
    renderer = MessageRenderer(MessageRendering(), RunDocuments(), ResponseLayout())
    output: list[Packet] = []
    if live:
        output.extend(
            renderer.consume(ThinkingDeltaEvent(content_index=0, text="r" * 64))
        )
    output.extend(renderer.complete(message))
    assert renderer.complete(message) == []
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


def test_completed_agent_tool_output_matches_replay() -> None:
    name = RESEARCH_AGENT_TOOL_NAME
    details = ResearchAgentCallResult(
        intermediate_report="Final report", citation_mapping={}
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
        assert [
            packet.obj.content
            for packet in packets
            if isinstance(packet.obj, IntermediateReportDelta)
        ] == ["Final report"]


def test_parallel_search_packets_complete_without_waiting_for_an_earlier_call() -> None:
    release_internal = threading.Event()
    internal_started = threading.Event()
    web_completed = threading.Event()
    packets: list[Packet] = []
    replies = iter(
        [
            AssistantMessage(
                content=[
                    ToolCall(
                        id="internal",
                        name="internal_search",
                        arguments={"queries": ["policy"]},
                    ),
                    ToolCall(
                        id="web", name="web_search", arguments={"queries": ["policy"]}
                    ),
                ]
            ),
            AssistantMessage(content=[TextContent(text="Answer")]),
        ]
    )

    def internal(_invocation: ToolInvocation) -> ToolResult:
        internal_started.set()
        assert release_internal.wait(10)
        return ToolResult(content="Internal result")

    def publish(packet: Packet) -> None:
        packets.append(packet)
        if isinstance(packet.obj, SectionEnd) and packet.placement.tab_index == 1:
            web_completed.set()

    presenter = ResponsePresenter(Emitter(publish))
    run = Agent(
        FakeModelClient(lambda *_: next(replies)),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        tools=[
            AgentTool(
                definition=ToolDefinition(
                    name="internal_search", description="", parameters={}
                ),
                execute=internal,
            ),
            AgentTool(
                definition=ToolDefinition(
                    name="web_search", description="", parameters={}
                ),
                execute=lambda _: ToolResult(content="Web result"),
            ),
        ],
    ).start(max_steps=2, on_event=presenter.consume)
    try:
        assert internal_started.wait(10)
        assert web_completed.wait(10)
        starts = [
            packet for packet in packets if isinstance(packet.obj, SearchToolStart)
        ]
        assert {packet.placement.tab_index for packet in starts} == {0, 1}
        assert len({packet.placement.turn_index for packet in starts}) == 1
        assert not any(
            isinstance(packet.obj, SectionEnd) and packet.placement.tab_index == 0
            for packet in packets
        )
        release_internal.set()
        assert run.result(10).output.text == "Answer"
    finally:
        release_internal.set()
        run.cancel()
        assert run.wait_for_idle(10)


@pytest.mark.parametrize(
    "outcome, failure, reason",
    [
        (RunStatus.COMPLETE, None, "finished"),
        (RunStatus.LIMIT, None, "finished"),
        (RunStatus.ERROR, None, "finished"),
        (RunStatus.CANCELLED, None, "user_cancelled"),
        (
            RunStatus.CANCELLED,
            RunFailure(kind=RunFailureKind.DEADLINE, message="deadline"),
            "timed_out",
        ),
    ],
)
def test_stop_reason_is_the_same_live_and_on_replay(
    outcome: RunOutcome, failure: RunFailure | None, reason: str
) -> None:
    output: list[Packet] = []
    ResponsePresenter(_emitter(output)).consume(
        AgentEndEvent(run_id="r", outcome=outcome, failure=failure)
    )
    replay = replay_response(
        ResponseRecord(run_id="r", status=outcome, failure=failure), {}, {}, {}
    )
    for packets in (output, replay):
        stops = [p.obj for p in packets if isinstance(p.obj, OverallStop)]
        assert [stop.stop_reason for stop in stops] == [reason]
