"""Research deadlines and failed children must preserve the parent's report."""

from threading import Event, Timer

import pytest

from onyx.agents.agent_coordination import AgentCoordinator
from onyx.agents.runtime import Run
from onyx.chat.models import ChatMessageMetadata
from onyx.chat.presentation import project_response
from onyx.configs.constants import DocumentSource
from onyx.context.search.models import SearchDoc, SearchDocsResponse
from onyx.deep_research.agent import DeepResearchAgent
from onyx.deep_research.models import ResearchAgentCallResult
from onyx.deep_research.research_agent import ResearchAgent
from onyx.deep_research.tool_definitions import (
    GENERATE_REPORT_TOOL_NAME,
    RESEARCH_AGENT_TOOL_NAME,
    THINK_TOOL_NAME,
)
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.models import (
    AssistantMessage,
    GenerationRequest,
    Message,
    ReasoningEffort,
    TextContent,
    ToolCall,
    ToolChoiceOptions,
    ToolResultMessage,
    UserMessage,
)
from tests.unit.onyx.agents.fakes import FakeModelClient, run_agent


def test_timed_out_child_preserves_successful_sibling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("onyx.deep_research.agent.RESEARCH_AGENT_TIMEOUT_SECONDS", 0.1)
    child_cancelled = Event()
    timers: list[Timer] = []

    class RecordedTimer(Timer):
        def start(self) -> None:
            timers.append(self)
            super().start()

    monkeypatch.setattr("onyx.agents.agent_coordination.threading.Timer", RecordedTimer)

    def reply(
        request: GenerationRequest, signal: CancellationSignal
    ) -> AssistantMessage:
        results = [m for m in request.messages if isinstance(m, ToolResultMessage)]
        if any(tool.name == RESEARCH_AGENT_TOOL_NAME for tool in request.tools):
            if results:
                assert [(m.tool_call_id, m.is_error) for m in results] == [
                    ("slow", True),
                    ("fast", False),
                ]
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
                        id=name, name=RESEARCH_AGENT_TOOL_NAME, arguments={"task": name}
                    )
                    for name in ("slow", "fast")
                ]
            )
        if any(m.text == "slow" for m in request.messages):
            with signal.on_cancel(child_cancelled.set):
                assert child_cancelled.wait(5)
            signal.check()
        if any(m.text == "fast" for m in request.messages):
            return AssistantMessage(content=[TextContent(text="Fast report")])
        return AssistantMessage(
            content=[TextContent(text="Final report" if results else "Plan")]
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
    runs: list[Run] = []
    result = run_agent(
        feature,
        messages=[UserMessage(content="Research")],
        max_steps=4,
        coordinator=AgentCoordinator(),
        runs=runs,
    )
    assert result.output.text == "Final report"
    assert child_cancelled.is_set()
    assert len(timers) == 2
    assert all(timer.finished.is_set() for timer in timers)
    assert sorted(child.status.value for child in runs[-1].snapshot().child_runs) == [
        "cancelled",
        "complete",
    ]


@pytest.mark.parametrize("parent", [False, True])
def test_elapsed_time_forces_report_before_step_limit(parent: bool) -> None:
    requests: list[GenerationRequest] = []
    feature: DeepResearchAgent | ResearchAgent

    def reply(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        requests.append(request)
        feature.started -= (31 if parent else 13) * 60
        if len(requests) == 1:
            return (
                AssistantMessage(content=[TextContent(text="Plan")])
                if parent
                else AssistantMessage(
                    content=[
                        ToolCall(
                            id="think",
                            name=THINK_TOOL_NAME,
                            arguments={"reasoning": "Plan"},
                        )
                    ]
                )
            )
        assert request.options.tool_choice == ToolChoiceOptions.NONE
        assert request.allowed_tool_names == frozenset()
        if parent:
            assert not request.tools
        else:
            assert request.tools == requests[0].tools
        return AssistantMessage(content=[TextContent(text="Report")])

    llm = FakeModelClient(reply)
    feature = (
        DeepResearchAgent(
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
        if parent
        else ResearchAgent([], llm, len, None, "", ReasoningEffort.LOW)
    )
    result = run_agent(
        feature, messages=[UserMessage(content="Research")], max_steps=10
    )
    assert result.output.text == "Report"
    assert len(requests) == 2


@pytest.mark.parametrize("source_kind", ["search", "file", "research"])
def test_deep_research_reuses_sources_from_chat_history(source_kind: str) -> None:
    source = SearchDoc(
        document_id="previous-source",
        chunk_ind=0,
        semantic_identifier="Evidence",
        link="https://example.com/evidence",
        blurb="Evidence",
        source_type=DocumentSource.WEB,
        boost=0,
        hidden=False,
        metadata={},
        match_highlights=[],
    )
    history: list[Message] = [UserMessage(content="Find evidence")]
    if source_kind == "file":
        history.append(
            AssistantMessage(
                content=[TextContent(text="Evidence [7]")],
                metadata=ChatMessageMetadata(sources={7: source}),
            )
        )
    else:
        history.extend(
            [
                AssistantMessage(
                    content=[
                        ToolCall(id="search", name="internal_search", arguments={})
                    ]
                ),
                ToolResultMessage(
                    tool_call_id="search",
                    tool_name="internal_search",
                    content="Evidence [7]",
                    details=SearchDocsResponse(
                        search_docs=[source], citation_mapping={7: source.document_id}
                    )
                    if source_kind == "search"
                    else ResearchAgentCallResult(
                        intermediate_report="Evidence [7]",
                        citation_mapping={7: source},
                    ),
                ),
                AssistantMessage(content=[TextContent(text="Evidence [7]")]),
            ]
        )

    def reply(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        if any(tool.name == RESEARCH_AGENT_TOOL_NAME for tool in request.tools):
            return AssistantMessage(
                content=[
                    ToolCall(id="report", name=GENERATE_REPORT_TOOL_NAME, arguments={})
                ]
            )
        return AssistantMessage(content=[TextContent(text="Evidence [7]")])

    feature = DeepResearchAgent(
        history,
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
    run_agent(
        feature,
        messages=[UserMessage(content="Explain the evidence")],
        max_steps=4,
        runs=runs,
    )
    assert feature.citation_mapping == {7: source}
    projection = project_response(runs[0].snapshot(), tool_ids={})
    assert projection.answer is not None
    assert "[[7]](https://example.com/evidence)" in projection.answer


def test_request_context_is_trailing_uncacheable_and_restorable() -> None:
    from onyx.agents.models import AgentStep, StepInput

    question = UserMessage(content="Research the launch")
    feature = DeepResearchAgent(
        [question],
        [],
        FakeModelClient(lambda _request, _signal: AssistantMessage(content=[])),
        len,
        None,
        "",
        ReasoningEffort.LOW,
        None,
        additional_context="Use the October launch plan",
    )
    state = feature.capture_state()
    assert state.request_context == "Use the October launch plan"
    feature.restore_state(state.model_dump(mode="json"))
    prepared = feature._prepare_step(
        StepInput(
            history=[],
            input_messages=[question],
            messages=[],
            step=AgentStep(index=0, limit=4),
        )
    )
    request = prepared.generation_request([question])
    assert request.messages[-2].text == question.text
    context = request.messages[-1]
    assert "Use the October launch plan" in context.text
    assert context.text.startswith("<system-reminder>")
    assert not context.cacheable
    assert request.messages[-2].cacheable
    assert [message.text for message in feature.state.messages] == [question.text]


def test_project_images_use_stable_preamble_and_file_references(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from onyx.agents.models import AgentStep, StepInput
    from onyx.file_store.models import (
        ChatFileType,
        ChatLoadedFile,
        ExtractedContextFiles,
    )
    from onyx.llm.models import ImageContentPart

    image = ChatLoadedFile(
        file_id="project-image",
        filename="project.png",
        content=b"\x89PNG\r\n\x1a\n",
        file_type=ChatFileType.IMAGE,
        content_text=None,
        token_count=100,
    )
    feature = DeepResearchAgent(
        [],
        [],
        FakeModelClient(lambda _request, _signal: AssistantMessage(content=[])),
        len,
        None,
        "",
        ReasoningEffort.LOW,
        None,
        context_files=ExtractedContextFiles(
            file_texts=[],
            image_files=[image],
            use_as_search_filter=False,
            total_token_count=100,
            uncapped_token_count=100,
            file_metadata=[],
        ),
    )
    monkeypatch.setattr(
        "onyx.chat.prompt_formatting.model_supports_image_input",
        lambda *_args: True,
    )
    image.filename = "edited-after-construction.png"
    saved = feature.capture_state()
    assert saved.context_files is not None
    assert saved.context_files.context.image_files == []
    assert saved.context_files.images[0].file_id == "project-image"
    assert saved.context_files.images[0].filename == "project.png"
    feature.restore_state(saved.model_dump(mode="json"))
    question = UserMessage(content="Describe the project image")
    prepared = feature._prepare_step(
        StepInput(
            history=[],
            input_messages=[question],
            messages=[],
            step=AgentStep(index=0, limit=4),
        )
    )
    first = prepared.generation_request([question])
    followup = prepared.generation_request(
        [question, UserMessage(content="What else is visible?")]
    )
    assert first.messages == followup.messages[: len(first.messages)]
    project = first.messages[1]
    assert isinstance(project, UserMessage) and isinstance(project.content, list)
    assert sum(isinstance(part, ImageContentPart) for part in project.content) == 1
    assert project.cacheable
    assert first.messages[-1].text == question.text


@pytest.mark.parametrize("reasoning", [False, True])
def test_research_cycles_keep_system_and_tool_phase_stable(
    reasoning: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    from onyx.agents.models import AgentStep, StepInput, StepResult
    from onyx.deep_research.models import ResearchMessageMetadata, ResearchPhase
    from onyx.llm.models import GenerationOptions

    monkeypatch.setattr(
        "onyx.deep_research.agent.model_is_reasoning_model",
        lambda *_args: reasoning,
    )
    feature = DeepResearchAgent(
        [],
        [],
        FakeModelClient(lambda _request, _signal: AssistantMessage(content=[])),
        len,
        None,
        "",
        ReasoningEffort.LOW,
        None,
    )
    question = UserMessage(content="Research the launch")
    plan = AssistantMessage(
        content=[TextContent(text="Compare launch evidence")],
        metadata=ResearchMessageMetadata(
            phase=ResearchPhase.PLANNING, is_reasoning_model=reasoning
        ),
    )
    research = AssistantMessage(
        content=[ToolCall(id="child", name=RESEARCH_AGENT_TOOL_NAME, arguments={})],
        metadata=ResearchMessageMetadata(
            phase=ResearchPhase.RESEARCH, is_reasoning_model=reasoning
        ),
    )
    result = ToolResultMessage(
        tool_call_id="child", tool_name=RESEARCH_AGENT_TOOL_NAME, content="Evidence"
    )
    requests: list[GenerationRequest] = []
    for completed in ([], [research, result]):
        previous = research if completed else plan
        prepared = feature._prepare_step(
            StepInput(
                history=[],
                input_messages=[question],
                messages=[plan, *completed],
                previous=StepResult(
                    step=AgentStep(index=1, limit=8),
                    message=previous,
                    tool_results=[result] if completed else [],
                    options=GenerationOptions(),
                ),
                step=AgentStep(index=2 if completed else 1, limit=8),
            )
        )
        assert prepared.tool_phase == ResearchPhase.RESEARCH.value
        requests.append(prepared.generation_request([question, plan, *completed]))
    assert requests[0].messages[0] == requests[1].messages[0]
    assert "currently used" not in requests[0].messages[0].text
    assert "currently used 0" in requests[0].messages[-1].text
    assert "currently used 1" in requests[1].messages[-1].text
    assert all(not request.messages[-1].cacheable for request in requests)
