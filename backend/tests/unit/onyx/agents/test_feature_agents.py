"""Exercise feature policies through shared execution, child ownership, and rendering."""

import json
import queue
from collections.abc import Generator
from functools import partial
from threading import Event
from unittest.mock import MagicMock

import pytest

from onyx.agents.agent_coordination import AgentCoordinator
from onyx.agents.events import AgentEvent, ToolEndEvent
from onyx.agents.models import (
    AgentCompletion,
    InputMessageMetadata,
    InputSource,
    PreparedStep,
    RunFailureKind,
    RunStatus,
    StepInput,
    StepRecord,
)
from onyx.agents.runtime import Run, RunFailed
from onyx.agents.tools import AgentTool
from onyx.chat.citation_processor import CitationMapping
from onyx.chat.citation_utils import collapse_citations
from onyx.chat.emitter import Emitter
from onyx.chat.models import ChatMessageMetadata
from onyx.chat.presentation import ResponsePresenter, project_response, replay_response
from onyx.chat.run_store import agent_result_message
from onyx.configs.chat_configs import DR_REPORT_LLM_TIMEOUT_S
from onyx.configs.constants import DocumentSource
from onyx.context.search.models import SearchDoc, SearchDocsResponse
from onyx.deep_research.agent import DeepResearchAgent
from onyx.deep_research.models import (
    ResearchAgentCallResult,
    ResearchMessageMetadata,
    ResearchPhase,
)
from onyx.deep_research.research_agent import ResearchAgent
from onyx.deep_research.tool_definitions import (
    GENERATE_REPORT_TOOL_NAME,
    RESEARCH_AGENT_TOOL_NAME,
)
from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.llm.exceptions import LLMTimeoutError
from onyx.llm.interfaces import GenerationContext, LLMUserIdentity
from onyx.llm.model_response import (
    ChatCompletionDeltaToolCall,
    Delta,
    ResponseFunctionCall,
)
from onyx.llm.models import (
    AssistantMessage,
    GenerationEvent,
    GenerationRequest,
    Message,
    ReasoningEffort,
    TextContent,
    ToolCall,
    ToolChoiceOptions,
    ToolDefinition,
    ToolResultMessage,
    UserMessage,
)
from onyx.server.query_and_chat.streaming_models import (
    AgentResponseDelta,
    DeepResearchPlanDelta,
    IntermediateReportDelta,
    OverallStop,
    Packet,
)
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool
from onyx.tracing.flows import LLMFlow
from tests.unit.onyx.agents.fakes import (
    EchoTool,
    FakeModelClient,
    FakeRunOwnership,
    ScriptedLLM,
    run_agent,
)


def tool_delta(name: str, arguments: str = "{}", count: int = 1) -> Delta:
    return Delta(
        tool_calls=[
            ChatCompletionDeltaToolCall(
                index=i,
                id=f"call-{i}",
                function=ResponseFunctionCall(name=name, arguments=arguments),
            )
            for i in range(count)
        ]
    )


@pytest.mark.parametrize("render", [True, False])
def test_research_search_steps_are_bounded_and_report_is_generated(
    render: bool,
) -> None:
    runs: list[Run] = []
    llm = ScriptedLLM(
        [
            tool_delta(WebSearchTool.NAME, '{"value":"inspect"}'),
            tool_delta(WebSearchTool.NAME, '{"value":"compare"}'),
            Delta(content="Report"),
        ],
        128000,
    )
    presentation = (
        ResponsePresenter(Emitter(queue.Queue[Packet]().put_nowait)) if render else None
    )
    feature = ResearchAgent(
        [ResearchWebSearchStub()], llm, len, None, "", ReasoningEffort.LOW
    )
    result = run_agent(
        feature,
        runs=runs,
        max_steps=3,
        messages=[UserMessage(content="Find facts")],
        listener=presentation.consume if presentation else None,
    )
    assert len(llm.requests) == 3
    assert result.output.text == "Report"
    assert (
        len(
            [
                message
                for message in feature.state.messages
                if message.role == "tool_result"
            ]
        )
        == 2
    )


class ResearchWebSearchStub(EchoTool):
    @property
    def name(self) -> str:
        return WebSearchTool.NAME


def test_research_executes_only_allowed_tools_and_records_results() -> None:
    runs: list[Run] = []
    llm = ScriptedLLM(
        [
            tool_delta(WebSearchTool.NAME, '{"value":"found"}'),
            tool_delta(GENERATE_REPORT_TOOL_NAME),
            Delta(content="Report"),
        ],
        128000,
    )
    search = MagicMock(spec=SearchTool)
    search.name = SearchTool.NAME
    search.tool_definition.return_value = ToolDefinition(
        name=SearchTool.NAME,
        description="Search documents",
        parameters={"type": "object"},
    )
    search.bind.return_value = AgentTool(
        definition=search.tool_definition.return_value,
        execute=MagicMock(
            side_effect=AssertionError("Internal search was not requested")
        ),
    )
    feature = ResearchAgent(
        [ResearchWebSearchStub(), EchoTool(), search],
        llm,
        len,
        None,
        "",
        ReasoningEffort.LOW,
    )
    result = run_agent(
        feature,
        runs=runs,
        max_steps=3,
        messages=[UserMessage(content="Find facts")],
    )
    assert [tool.name for tool in feature.application_tools] == [
        WebSearchTool.NAME,
        SearchTool.NAME,
    ]
    assert feature.application_tools[1] is search
    assert result.output.text == "Report"
    snapshot = runs[-1].snapshot()
    assert snapshot is not None
    accepted = [
        message
        for message in snapshot.messages
        if message.role == "tool_result" and message.tool_name == WebSearchTool.NAME
    ]
    assert accepted[0].text == "found"


def test_deep_research_composes_plan_child_and_report() -> None:
    runs: list[Run] = []
    contexts: list[GenerationContext] = []

    class TracedLLM(ScriptedLLM):
        def stream(
            self, request: GenerationRequest, context: GenerationContext | None = None
        ) -> Generator[GenerationEvent, None, None]:
            assert context is not None
            contexts.append(context.model_copy())
            yield from super().stream(request, context)

    llm = TracedLLM(
        [
            Delta(content="Plan"),
            tool_delta(RESEARCH_AGENT_TOOL_NAME, '{"task":"facts"}'),
            tool_delta(GENERATE_REPORT_TOOL_NAME),
            Delta(content="Child report"),
            tool_delta(GENERATE_REPORT_TOOL_NAME),
            Delta(content="Final report"),
        ],
        128000,
    )
    output: queue.Queue[Packet] = queue.Queue()
    identity = LLMUserIdentity(user_id="researcher", session_id="session")
    feature = DeepResearchAgent(
        messages=[],
        allowed_tools=[],
        llm=llm,
        token_counter=len,
        user_identity=identity,
        language_section="",
        reasoning_effort=ReasoningEffort.LOW,
        all_injected_file_metadata=None,
        skip_clarification=True,
    )
    feature.generation_context.stall_timeout_s = 11
    coordinator = AgentCoordinator()
    project = partial(
        project_response,
        tool_ids={RESEARCH_AGENT_TOOL_NAME: 7},
    )
    run_agent(
        feature,
        runs=runs,
        coordinator=coordinator,
        messages=[UserMessage(content="Research")],
        listener=ResponsePresenter(Emitter(output.put_nowait)).consume,
        max_steps=8,
    )
    assert (
        project(runs[-1].snapshot(), registrations=coordinator.registrations()).answer
        == "Final report"
    )
    assert len(llm.requests) == 6
    assert [context.flow for context in contexts] == [
        LLMFlow.DEEP_RESEARCH,
        LLMFlow.DEEP_RESEARCH,
        LLMFlow.RESEARCH_AGENT,
        LLMFlow.RESEARCH_AGENT,
        LLMFlow.DEEP_RESEARCH,
        LLMFlow.DEEP_RESEARCH,
    ]
    assert all(context.user_identity == identity for context in contexts)
    assert [context.stall_timeout_s for context in contexts] == [
        11,
        11,
        None,
        DR_REPORT_LLM_TIMEOUT_S,
        11,
        DR_REPORT_LLM_TIMEOUT_S,
    ]
    snapshot = project(runs[-1].snapshot(), registrations=coordinator.registrations())
    assert snapshot.response is not None
    assert snapshot.response.messages[0].text == "Plan"
    assert snapshot.response.messages[-1].text == "Final report"
    assert len(snapshot.response.child_runs) == 1
    assert snapshot.response.child_runs[0].messages[-1].text == "Child report"
    packets = list(output.queue)
    report_packets = [
        packet for packet in packets if isinstance(packet.obj, IntermediateReportDelta)
    ]
    assert report_packets
    assert all(packet.placement.sub_turn_index is None for packet in report_packets)
    saved_reports = [
        packet
        for packet in replay_response(
            snapshot.response, {}, snapshot.presentation, snapshot.all_search_docs
        )
        if isinstance(packet.obj, IntermediateReportDelta)
    ]
    assert (
        "".join(
            packet.obj.content
            for packet in saved_reports
            if isinstance(packet.obj, IntermediateReportDelta)
        )
        == "Child report"
    )
    assert all(packet.placement.sub_turn_index is None for packet in saved_reports)
    assert (
        "".join(
            packet.obj.content
            for packet in packets
            if isinstance(packet.obj, DeepResearchPlanDelta)
        )
        == "Plan"
    )
    assert (
        "".join(
            packet.obj.content
            for packet in packets
            if isinstance(packet.obj, IntermediateReportDelta)
        )
        == "Child report"
    )
    assert (
        "".join(
            packet.obj.content
            for packet in packets
            if isinstance(packet.obj, AgentResponseDelta)
            and packet.placement.sub_turn_index is None
        )
        == "Final report"
    )
    assert any(isinstance(item.obj, OverallStop) for item in list(output.queue))


@pytest.mark.parametrize("skip_clarification", [False, True])
def test_deep_research_prelude_cancellation_keeps_partial_output(
    skip_clarification: bool,
) -> None:
    runs: list[Run] = []
    signal = CancellationSignal()

    class InterruptedLLM(ScriptedLLM):
        def stream(
            self, request: GenerationRequest, context: GenerationContext | None = None
        ) -> Generator[GenerationEvent, None, None]:
            for event in super().stream(request, context):
                yield event
                if event.type == "text_delta":
                    signal.cancel()
                    signal.check()

    feature = DeepResearchAgent(
        [],
        [],
        InterruptedLLM([Delta(content="Partial prelude")], 128000),
        len,
        None,
        "",
        ReasoningEffort.LOW,
        None,
        skip_clarification=skip_clarification,
    )

    coordinator = AgentCoordinator()
    project = partial(
        project_response,
        tool_ids={RESEARCH_AGENT_TOOL_NAME: 7},
    )
    with pytest.raises(AgentCancelled):
        run_agent(
            feature,
            runs=runs,
            coordinator=coordinator,
            messages=[UserMessage(content="Research")],
            max_steps=4,
            cancellation=signal,
        )
    snapshot = project(runs[-1].snapshot(), registrations=coordinator.registrations())
    assert snapshot.response is not None
    assert snapshot.response.status == "cancelled"
    assert snapshot.response.messages[-1].text == "Partial prelude"


def test_deep_research_advances_phases_without_user_queue_messages() -> None:
    runs: list[Run] = []
    llm = ScriptedLLM(
        [
            Delta(content="Plan"),
            Delta(content="Enough evidence"),
            Delta(content="Final report"),
        ],
        128000,
    )
    feature = DeepResearchAgent(
        [],
        [],
        llm,
        len,
        None,
        "",
        ReasoningEffort.LOW,
        None,
        skip_clarification=True,
    )
    result = run_agent(
        feature,
        runs=runs,
        coordinator=AgentCoordinator(),
        messages=[UserMessage(content="Research")],
        max_steps=3,
    )
    assert result.output.text == "Final report"
    metadata = runs[-1].snapshot().messages[-1].metadata
    assert isinstance(metadata, ResearchMessageMetadata)
    assert metadata.phase == ResearchPhase.REPORT
    assert len(llm.requests) == 3
    assert [
        message.text
        for message in feature.state.messages
        if isinstance(message, UserMessage)
    ] == ["Research"]


@pytest.mark.parametrize("deep_research", [False, True])
def test_research_receives_background_evidence_with_distinct_citations(
    deep_research: bool,
) -> None:
    existing, incoming = [
        SearchDoc(
            document_id=name,
            chunk_ind=0,
            semantic_identifier=name,
            blurb="Evidence",
            source_type=DocumentSource.WEB,
            boost=0,
            hidden=False,
            metadata={},
            match_highlights=[],
        )
        for name in ("earlier", "child")
    ]
    completion = AgentCompletion(
        agent_path="/root/child",
        run_id="child-run",
        status=RunStatus.COMPLETE,
        output=AssistantMessage(
            content=[TextContent(text="Child evidence [1]")],
            metadata=ChatMessageMetadata(sources={1: incoming}),
        ),
    )
    requests: list[GenerationRequest] = []

    def reply(request: GenerationRequest, _: CancellationSignal) -> AssistantMessage:
        requests.append(request)
        notifications = [
            message
            for message in request.messages
            if message.text.startswith("Background agent result")
        ]
        assert len(notifications) == 1
        assert (
            json.loads(notifications[0].text.split("\n", 1)[1])["answer"]
            == "Child evidence [2]"
        )
        return AssistantMessage(content=[TextContent(text="Report cites evidence [2]")])

    llm = FakeModelClient(reply)
    history: list[Message] = [
        AssistantMessage(
            content=[TextContent(text="Earlier evidence [1]")],
            metadata=ChatMessageMetadata(sources={1: existing}),
        )
    ]
    feature = (
        DeepResearchAgent(
            messages=history,
            allowed_tools=[],
            llm=llm,
            token_counter=len,
            user_identity=None,
            language_section="",
            reasoning_effort=ReasoningEffort.LOW,
            all_injected_file_metadata=None,
            skip_clarification=True,
        )
        if deep_research
        else ResearchAgent(
            messages=history,
            sources={1: existing},
            tools=[],
            llm=llm,
            token_counter=len,
            user_identity=None,
            language_section="",
            reasoning_effort=ReasoningEffort.LOW,
        )
    )
    read_ids: set[str] = set()

    def accept(_run: Run, step: StepRecord) -> bool:
        read_ids.update(message.id or "" for message in step.input_messages)
        return True

    coordinator = AgentCoordinator(
        ownership=FakeRunOwnership(
            receive_inputs=lambda _run: (
                []
                if completion.message_id in read_ids
                else [agent_result_message(completion)]
            ),
            accept_inputs=accept,
        ),
    )
    try:
        result = run_agent(
            feature,
            messages=[UserMessage(content="Use the background evidence")],
            max_steps=3 if deep_research else 2,
            coordinator=coordinator,
        )
        assert result.output.text == "Report cites evidence [2]"
        assert isinstance(result.output.metadata, ResearchMessageMetadata)
        assert result.output.metadata.sources == {1: existing, 2: incoming}
        accepted = [
            message
            for message in feature.state.messages
            if message.id == completion.message_id
        ]
        assert len(accepted) == 1
        assert isinstance(accepted[0].metadata, InputMessageMetadata)
        assert accepted[0].metadata.source == InputSource.AGENT_RESULT
        assert accepted[0].metadata.source_run_id == completion.run_id
        assert len(requests) == (3 if deep_research else 2)
        assert (
            completion.output is not None
            and completion.output.text == "Child evidence [1]"
        )
    finally:
        assert coordinator.close(10)


@pytest.mark.parametrize(
    "error", [LLMTimeoutError("Provider timeout"), ValueError("Child failed")]
)
def test_child_failure_is_a_failed_tool_result(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    runs: list[Run] = []
    original_prepare = ResearchAgent._prepare_step

    def fail_child(self: ResearchAgent, state: StepInput) -> PreparedStep:
        if state.input_messages[0].text == "unavailable":
            raise error
        return original_prepare(self, state)

    monkeypatch.setattr(ResearchAgent, "_prepare_step", fail_child)
    llm = ScriptedLLM(
        [
            Delta(content="Plan"),
            tool_delta(RESEARCH_AGENT_TOOL_NAME, '{"task":"unavailable"}'),
            tool_delta(GENERATE_REPORT_TOOL_NAME),
            Delta(content="Report with remaining evidence"),
        ],
        128000,
    )
    feature = DeepResearchAgent(
        [],
        [],
        llm,
        len,
        None,
        "",
        ReasoningEffort.LOW,
        None,
        skip_clarification=True,
    )
    result = run_agent(
        feature,
        runs=runs,
        coordinator=AgentCoordinator(),
        messages=[UserMessage(content="Research")],
        max_steps=4,
    )
    assert result.output.text == "Report with remaining evidence"
    tool_results = [
        message for message in feature.state.messages if message.role == "tool_result"
    ]
    assert tool_results[0].is_error
    snapshot = runs[-1].snapshot()
    assert snapshot is not None
    assert snapshot.child_runs[0].status == "error"


def test_research_preserves_citation_identity_across_completion_and_call_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runs: list[Run] = []
    second_finished = Event()
    completion_order: list[str] = []
    documents = {
        topic: SearchDoc(
            document_id=topic,
            chunk_ind=0,
            semantic_identifier=topic,
            blurb=topic,
            source_type=DocumentSource.WEB,
            boost=0,
            hidden=False,
            metadata={},
            match_highlights=[],
        )
        for topic in ("first", "second")
    }
    original_prepare = ResearchAgent._prepare_step

    def child_prepare(child: ResearchAgent, state: StepInput) -> PreparedStep:
        prepared = original_prepare(child, state)
        metadata = prepared.output_metadata
        assert isinstance(metadata, ResearchMessageMetadata)
        metadata.sources = {9: documents[state.input_messages[0].text]}
        return prepared

    monkeypatch.setattr(ResearchAgent, "_prepare_step", child_prepare)

    def allocate_citations(
        answer_text: str,
        existing_citation_mapping: CitationMapping,
        new_citation_mapping: CitationMapping,
    ) -> tuple[str, CitationMapping]:
        completion_order.append(answer_text.split()[0])
        result = collapse_citations(
            answer_text, existing_citation_mapping, new_citation_mapping
        )
        if answer_text.startswith("second "):
            second_finished.set()
        return result

    monkeypatch.setattr(
        "onyx.deep_research.agent.collapse_citations", allocate_citations
    )

    def reply(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        topic = next(
            (
                message.text
                for message in request.messages
                if isinstance(message, UserMessage) and message.text in documents
            ),
            None,
        )
        if topic is not None:
            if topic == "first":
                assert second_finished.wait(5)
            return AssistantMessage(content=[TextContent(text=f"{topic} [9]")])
        if any(tool.name == RESEARCH_AGENT_TOOL_NAME for tool in request.tools):
            if any(
                isinstance(message, ToolResultMessage)
                and message.tool_name == RESEARCH_AGENT_TOOL_NAME
                for message in request.messages
            ):
                return AssistantMessage(
                    content=[
                        ToolCall(
                            id="report", name=GENERATE_REPORT_TOOL_NAME, arguments={}
                        )
                    ]
                )
            return AssistantMessage(
                content=[
                    ToolCall(
                        id=topic,
                        name=RESEARCH_AGENT_TOOL_NAME,
                        arguments={"task": topic},
                    )
                    for topic in documents
                ]
            )
        return AssistantMessage(
            content=[
                TextContent(
                    text="Final [1] [2]"
                    if any(
                        isinstance(message, AssistantMessage)
                        for message in request.messages
                    )
                    else "Plan"
                )
            ]
        )

    feature = DeepResearchAgent(
        [],
        [],
        FakeModelClient(reply),
        len,
        None,
        "",
        ReasoningEffort.LOW,
        None,
        skip_clarification=True,
    )
    coordinator = AgentCoordinator()
    project = partial(
        project_response,
        tool_ids={RESEARCH_AGENT_TOOL_NAME: 7},
    )
    final_events: list[ToolEndEvent] = []

    def record(event: AgentEvent) -> None:
        if (
            isinstance(event, ToolEndEvent)
            and event.tool_call.name == RESEARCH_AGENT_TOOL_NAME
        ):
            final_events.append(event)

    run_agent(
        feature,
        runs=runs,
        coordinator=coordinator,
        messages=[UserMessage(content="Parent")],
        listener=record,
        max_steps=4,
    )
    accepted = [
        message
        for message in feature.state.messages
        if isinstance(message, ToolResultMessage)
        and message.tool_name == RESEARCH_AGENT_TOOL_NAME
    ]
    assert completion_order == ["second", "first"]
    assert [message.text for message in accepted] == ["first [2]", "second [1]"]
    assert sorted(
        (event.tool_call.id, event.result.text) for event in final_events
    ) == [("first", "first [2]"), ("second", "second [1]")]
    for index, message in zip([2, 1], accepted, strict=True):
        assert isinstance(message.details, ResearchAgentCallResult)
        assert message.details.intermediate_report == message.text
        assert list(message.details.citation_mapping) == [index]
    assert {
        number: doc.document_id
        for number, doc in project(
            runs[-1].snapshot(), registrations=coordinator.registrations()
        ).citation_to_doc.items()
    } == {1: "second", 2: "first"}


def test_repeated_runs_use_new_input_and_restore_tool_execution() -> None:
    runs: list[Run] = []
    requests: list[GenerationRequest] = []
    final_tool = GENERATE_REPORT_TOOL_NAME

    def generate(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        requests.append(request.model_copy(deep=True))
        if request.options.tool_choice == ToolChoiceOptions.NONE:
            return AssistantMessage(content=[TextContent(text="Report")])
        return AssistantMessage(
            content=[ToolCall(id="finish", name=final_tool, arguments={})]
        )

    llm = FakeModelClient(generate)
    feature = ResearchAgent([], llm, len, None, "", ReasoningEffort.LOW)
    first = run_agent(
        feature,
        runs=runs,
        max_steps=2,
        messages=[UserMessage(content="First question")],
    )
    second = run_agent(
        feature,
        runs=runs,
        max_steps=2,
        messages=[UserMessage(content="Second question")],
    )
    assert first.run_id != second.run_id
    assert first.steps == second.steps == 2
    assert requests[2].options.tool_choice == ToolChoiceOptions.REQUIRED
    assert "Second question" in requests[3].messages[-1].text
    assert "First question" not in requests[3].messages[-1].text
    assert second.output.text == "Report"


@pytest.mark.parametrize("from_tool_result", [False, True])
def test_restored_research_preserves_history_and_source_numbers(
    from_tool_result: bool,
) -> None:
    runs: list[Run] = []
    document = SearchDoc(
        document_id="reference",
        chunk_ind=0,
        semantic_identifier="Reference",
        link="https://example.com/reference",
        blurb="Supporting evidence",
        source_type=DocumentSource.WEB,
        boost=0,
        hidden=False,
        metadata={},
        match_highlights=[],
    )
    messages: list[Message] = [UserMessage(content="Find evidence")]
    if from_tool_result:
        messages.extend(
            [
                AssistantMessage(
                    content=[
                        ToolCall(id="search", name=WebSearchTool.NAME, arguments={})
                    ]
                ),
                ToolResultMessage(
                    tool_call_id="search",
                    tool_name=WebSearchTool.NAME,
                    content="Evidence [4]",
                    details=SearchDocsResponse(
                        search_docs=[document], citation_mapping={4: "reference"}
                    ),
                ),
            ]
        )
    else:
        messages.append(AssistantMessage(content=[TextContent(text="Evidence [4]")]))
    llm = ScriptedLLM([Delta(content="The evidence supports this [4].")], 128000)
    feature = ResearchAgent(
        tools=[],
        llm=llm,
        token_counter=len,
        user_identity=None,
        language_section="",
        reasoning_effort=ReasoningEffort.LOW,
        messages=messages,
        sources=None if from_tool_result else {4: document},
    )
    result = run_agent(
        feature,
        runs=runs,
        max_steps=1,
        messages=[UserMessage(content="Continue")],
    )
    assert isinstance(result.output.metadata, ResearchMessageMetadata)
    assert result.output.metadata.sources == {4: document}
    assert feature.citation_processor.get_next_citation_number() == 5
    assert feature.state.messages[0].text == "Find evidence"
    assert feature.citation_mapping == {4: "reference"}


@pytest.mark.parametrize("feature_name", ["research", "deep_research"])
def test_empty_final_response_fails_at_step_limit(feature_name: str) -> None:
    requests: list[GenerationRequest] = []

    def reply(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        requests.append(request)
        text = "Plan" if feature_name == "deep_research" and len(requests) == 1 else ""
        return AssistantMessage(content=[TextContent(text=text)])

    llm = FakeModelClient(reply)
    if feature_name == "research":
        feature = ResearchAgent([], llm, len, None, "", ReasoningEffort.LOW)
    else:
        feature = DeepResearchAgent(
            [],
            [],
            llm,
            len,
            None,
            "",
            ReasoningEffort.LOW,
            None,
            skip_clarification=True,
        )
    runs: list[Run] = []
    budget = 2 if feature_name == "deep_research" else 1
    with pytest.raises(RunFailed) as failure:
        run_agent(
            feature,
            messages=[UserMessage(content="Task")],
            max_steps=budget,
            runs=runs,
        )
    assert failure.value.failure.kind == RunFailureKind.EXECUTION
    assert len(requests) == budget
    assert runs[-1].snapshot().status == "error"


@pytest.mark.parametrize("missing_metadata", [False, True])
def test_research_result_failure_returns_tool_error_and_preserves_child(
    monkeypatch: pytest.MonkeyPatch,
    missing_metadata: bool,
) -> None:
    def fail_conversion(
        answer_text: str,
        existing_citation_mapping: dict[int, SearchDoc],
        new_citation_mapping: dict[int, SearchDoc],
    ) -> tuple[str, dict[int, SearchDoc]]:
        del answer_text, existing_citation_mapping, new_citation_mapping
        raise ValueError("Invalid citation mapping")

    if missing_metadata:
        original_prepare = ResearchAgent._prepare_step

        def prepare_without_metadata(
            agent: ResearchAgent, state: StepInput
        ) -> PreparedStep:
            prepared = original_prepare(agent, state)
            return prepared.model_copy(update={"output_metadata": None})

        monkeypatch.setattr(ResearchAgent, "_prepare_step", prepare_without_metadata)
    else:
        monkeypatch.setattr(
            "onyx.deep_research.agent.collapse_citations", fail_conversion
        )

    def reply(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        if any(tool.name == RESEARCH_AGENT_TOOL_NAME for tool in request.tools):
            return AssistantMessage(
                content=[
                    ToolCall(
                        id="research",
                        name=RESEARCH_AGENT_TOOL_NAME,
                        arguments={"task": "Child task"},
                    )
                ]
            )
        return AssistantMessage(content=[TextContent(text="Completed report")])

    feature = DeepResearchAgent(
        [],
        [],
        FakeModelClient(reply),
        len,
        None,
        "",
        ReasoningEffort.LOW,
        None,
        skip_clarification=True,
    )
    runs: list[Run] = []
    result = run_agent(
        feature,
        messages=[UserMessage(content="Parent task")],
        max_steps=3,
        runs=runs,
        coordinator=AgentCoordinator(),
    )
    assert result.output.text == "Completed report"
    snapshot = runs[-1].snapshot()
    assert snapshot.status == "complete"
    assert len(snapshot.child_runs) == 1
    assert snapshot.child_runs[0].status == "complete"
    assert snapshot.child_runs[0].messages[-1].text == "Completed report"
    errors = [
        message
        for message in snapshot.messages
        if isinstance(message, ToolResultMessage)
    ]
    assert len(errors) == 1
    assert errors[0].is_error
    expected_error = (
        "Research child requires a report with source metadata"
        if missing_metadata
        else "Invalid citation mapping"
    )
    assert expected_error in errors[0].content
