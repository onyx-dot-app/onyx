"""Restore feature state and tool execution through JSON."""

from io import BytesIO
from unittest.mock import patch
from uuid import uuid4

import pytest
from pydantic import JsonValue, TypeAdapter, ValidationError

from onyx.agents.agent_coordination import AgentCoordinator
from onyx.agents.models import (
    AgentState,
    AgentStep,
    ExecutionCheckpoint,
    ExecutionStatus,
    PreparedStep,
    RunProgress,
    RunState,
    RunStatus,
    StepInput,
    StepRecord,
    ToolExecutionRecord,
)
from onyx.agents.runtime import Agent
from onyx.agents.tools import (
    HumanToolAnswer,
    InputDecision,
    InputMode,
    PendingToolInput,
    ToolInvocation,
)
from onyx.chat.agent import ChatFeature
from onyx.chat.checkpoint import CHECKPOINT_PAYLOAD_TYPES
from onyx.chat.models import (
    ChatFeatureState,
    ChatSearchResult,
    CheckpointBinding,
    ResponseCheckpoint,
)
from onyx.chat.restoration import persist_checkpoint_files
from onyx.configs.constants import DocumentSource
from onyx.context.search.models import SearchCycle, SearchDoc
from onyx.deep_research.agent import DeepResearchFeature
from onyx.deep_research.research_agent import ResearchFeature
from onyx.deep_research.tool_definitions import (
    GENERATE_PLAN_TOOL_NAME,
    GENERATE_REPORT_TOOL_NAME,
)
from onyx.file_store.models import ChatFileType, ChatLoadedFile, ExtractedContextFiles
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.interfaces import LLM
from onyx.llm.model_response import Delta
from onyx.llm.models import (
    AssistantMessage,
    ReasoningEffort,
    TextContent,
    ToolCall,
    ToolResult,
    ToolResultMessage,
    UserMessage,
)
from onyx.tools.interface import Tool
from onyx.tools.models import ChatFile, ToolContext
from onyx.tools.tool_implementations.search.models import (
    SearchContext,
    SearchPlanningResult,
)
from onyx.tools.tool_implementations.search.search_tool import (
    SearchTool,
)
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool
from tests.unit.onyx.agents.checkpoint_storage import CheckpointStorage, SavedCheckpoint
from tests.unit.onyx.agents.fakes import EchoTool, FakeModelClient, ScriptedLLM
from tests.unit.onyx.agents.test_feature_agents import tool_delta


def document() -> SearchDoc:
    return SearchDoc(
        document_id="reference",
        chunk_ind=0,
        semantic_identifier="Reference",
        link="https://example.com/reference",
        blurb="Evidence",
        source_type=DocumentSource.WEB,
        boost=0,
        hidden=False,
        metadata={},
        match_highlights=[],
    )


def model() -> FakeModelClient:
    return FakeModelClient(
        lambda _request, _signal: AssistantMessage(content=[TextContent(text="done")])
    )


def chat(*tools: Tool) -> ChatFeature:
    return ChatFeature(
        messages=[],
        tools=list(tools),
        custom_agent_prompt=None,
        base_system_prompt="Help",
        context_files=ExtractedContextFiles(
            file_texts=[],
            image_files=[],
            use_as_search_filter=False,
            total_token_count=0,
            file_metadata=[],
            uncapped_token_count=None,
        ),
        persona=None,
        user_memory_context=None,
        llm=model(),
    )


class CaptureContextTool(EchoTool):
    def __init__(self) -> None:
        self.contexts: list[ToolContext] = []

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:
        invocation.cancellation.check()
        self.contexts.append(context.model_copy(deep=True))
        return ToolResult(content="done")


def test_chat_json_restores_tool_context_from_feature_state() -> None:
    original = chat(CaptureContextTool())
    original.citation_mapping = {9: "new"}
    original.citation_processor.citation_to_doc = {9: document()}
    original.has_called_search_tool = True
    original.chat_files = [ChatFile(filename="result.csv", content=b"1,2")]
    snapshot = RunState(
        run_id="run",
        agent_id="agent",
        status=RunStatus.SUSPENDED,
        steps=[],
        progress=RunProgress(
            step_limit=3,
            feature_state=original.capture_state().model_dump(mode="json"),
        ),
    )
    encoded = CheckpointStorage(CHECKPOINT_PAYLOAD_TYPES).save(
        snapshot,
        AgentState(),
        CheckpointBinding(tenant_id="tenant", response_id=snapshot.run_id),
    )
    del original, snapshot
    tool = CaptureContextTool()
    restored = chat(tool)
    saved = CheckpointStorage(CHECKPOINT_PAYLOAD_TYPES).load(encoded).run_state
    assert saved.progress is not None
    assert saved.progress.feature_state is not None
    restored.restore_state(saved.progress.feature_state)
    restored.bind().tools[0].execute(
        ToolInvocation(
            call_id="call",
            arguments={},
            cancellation=CancellationSignal(),
            update=lambda _update: None,
        )
    )
    assert tool.contexts[0].citation_mapping == {9: "new"}
    assert tool.contexts[0].skip_search_query_expansion
    assert tool.contexts[0].next_citation_num == 10
    assert tool.contexts[0].chat_files[0].content == b"1,2"
    assert restored.citation_mapping == {9: "new"}
    assert restored.citation_processor.get_next_citation_number() == 10
    assert restored.has_called_search_tool


def test_research_json_restores_next_citation_number() -> None:
    original = ResearchFeature([], model(), len, None, "", ReasoningEffort.LOW)
    original.citation_processor.citation_to_doc = {8: document()}
    original.citation_mapping = {8: "reference"}
    encoded = original.capture_state().model_dump_json()
    restored = ResearchFeature([], model(), len, None, "", ReasoningEffort.LOW)
    restored.restore_state(TypeAdapter(dict[str, JsonValue]).validate_json(encoded))
    assert restored.citation_processor.get_next_citation_number() == 9
    assert restored.citation_mapping == {8: "reference"}
    changed = ResearchFeature([], model(), len, None, "French", ReasoningEffort.LOW)
    with pytest.raises(ValueError, match="configuration"):
        changed.restore_state(TypeAdapter(dict[str, JsonValue]).validate_json(encoded))


def test_deep_research_restores_citations_and_control_tools() -> None:
    def feature() -> DeepResearchFeature:
        return DeepResearchFeature(
            allowed_tools=[],
            llm=model(),
            token_counter=len,
            user_identity=None,
            language_section="",
            reasoning_effort=ReasoningEffort.LOW,
            all_injected_file_metadata=None,
        )

    original = feature()
    prepared = original._prepare_step(
        StepInput(
            history=[],
            input_messages=[],
            messages=[],
            step=AgentStep(index=0, limit=5),
        )
    )
    original.citation_mapping = {4: document()}
    encoded = original.capture_state().model_dump_json()
    restored = feature()
    restored.restore_state(TypeAdapter(dict[str, JsonValue]).validate_json(encoded))
    assert prepared.tool_phase == "clarification"
    tools = [
        tool for tool in restored.bind().tools if tool.name == GENERATE_PLAN_TOOL_NAME
    ]
    assert restored.citation_mapping[4].document_id == "reference"
    assert tools[0].definition == next(
        tool.definition
        for tool in original.bind().tools
        if tool.name == GENERATE_PLAN_TOOL_NAME
    )
    result = tools[0].execute(
        ToolInvocation(
            call_id="call",
            arguments={},
            cancellation=CancellationSignal(),
            update=lambda _update: None,
        )
    )
    assert isinstance(result, ToolResult)
    assert result.text == "Proceed to planning."


def test_chat_suspends_and_resumes_with_fresh_feature_and_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feature = chat(CaptureContextTool())
    feature.llm = FakeModelClient(
        lambda _request, _signal: AssistantMessage(
            content=[ToolCall(id="echo-call", name="echo", arguments={})]
        )
    )
    original = feature.agent(AgentState())
    original.feature = feature.bind().model_copy(
        update={
            "before_tool_call": lambda _context: PendingToolInput(
                request_id="approve-echo", prompt="Run echo?", mode=InputMode.EXECUTE
            )
        }
    )
    run = original.start(max_steps=3, messages=[UserMessage(content="Check")])
    assert run.wait_until_settled(timeout=5).status == RunStatus.SUSPENDED
    assert run.wait_for_idle(timeout=5)
    checkpoint = run.capture()
    encoded = CheckpointStorage(CHECKPOINT_PAYLOAD_TYPES).save(
        checkpoint.run_state,
        checkpoint.agent_state,
        CheckpointBinding(tenant_id="tenant", response_id=checkpoint.run_state.run_id),
    )
    del feature, original, run, checkpoint

    tool = CaptureContextTool()
    restored = chat(tool)
    checkpoint = CheckpointStorage(CHECKPOINT_PAYLOAD_TYPES).load(encoded)
    restored = ChatFeature(
        messages=checkpoint.agent_state.messages,
        tools=[tool],
        custom_agent_prompt=None,
        base_system_prompt="Help",
        context_files=restored.context_files,
        persona=None,
        user_memory_context=None,
        llm=model(),
    )
    prepared_indices: list[int] = []
    prepare = restored._prepare_step

    def prepare_next(state: StepInput) -> PreparedStep:
        prepared_indices.append(state.step.index)
        return prepare(state)

    monkeypatch.setattr(restored, "_prepare_step", prepare_next)
    resumed = restored.agent(
        checkpoint.agent_state, agent_id=checkpoint.run_state.agent_id
    ).resume(checkpoint.run_state)
    resumed.submit(
        HumanToolAnswer(request_id="approve-echo", decision=InputDecision.APPROVE)
    )
    assert resumed.result(timeout=5).output.text == "done"
    assert resumed.wait_for_idle(timeout=5)
    assert resumed.id == checkpoint.run_state.run_id
    assert prepared_indices == [1]
    assert len(tool.contexts) == 1


@pytest.mark.parametrize("kind", ["chat", "research"])
def test_search_planning_survives_partial_step_checkpoint(kind: str) -> None:
    class PlanningSearch(CaptureContextTool):
        @property
        def name(self) -> str:
            return SearchTool.NAME

        def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:
            self.contexts.append(context)
            return ToolResult(
                content="No matching documents",
                metadata=SearchPlanningResult(
                    tool_call_id=invocation.call_id,
                    original_queries=("facts",),
                    searched_sources=("web",),
                    cached_expansion=("facts", ("facts", "evidence")),
                    scope_decision_settled=True,
                    time_filter_computed=True,
                ),
            )

    class ApprovalTool(CaptureContextTool):
        @property
        def name(self) -> str:
            return WebSearchTool.NAME

    search = PlanningSearch()
    gated = ApprovalTool()

    def build(
        llm: LLM, agent_id: str | None = None
    ) -> tuple[ChatFeature | ResearchFeature, Agent]:
        if kind == "research":
            research = ResearchFeature(
                [search, gated], llm, len, None, "", ReasoningEffort.LOW
            )
            return research, research.agent(agent_id=agent_id)
        feature = chat(search, gated)
        feature.llm = llm
        return feature, feature.agent(AgentState(), agent_id=agent_id)

    original_feature, original = build(
        FakeModelClient(
            lambda _request, _signal: AssistantMessage(
                content=[
                    ToolCall(id="search", name=SearchTool.NAME, arguments={}),
                    ToolCall(id="approval", name=WebSearchTool.NAME, arguments={}),
                ]
            )
        )
    )
    original.feature = original_feature.bind().model_copy(
        update={
            "before_tool_call": lambda context: (
                PendingToolInput(
                    request_id="approval", prompt="Run tool?", mode=InputMode.EXECUTE
                )
                if context.call.name == WebSearchTool.NAME
                else None
            )
        }
    )
    run = original.start(max_steps=2, messages=[UserMessage(content="Find facts")])
    assert run.wait_until_settled(timeout=5).status == RunStatus.SUSPENDED
    assert run.wait_for_idle(timeout=5)
    assert original_feature.search_context == SearchContext()
    checkpoint = run.capture()
    storage = CheckpointStorage(CHECKPOINT_PAYLOAD_TYPES)
    encoded = storage.save(
        checkpoint.run_state,
        checkpoint.agent_state,
        CheckpointBinding(tenant_id="tenant", response_id=run.id),
    )
    saved = SavedCheckpoint.model_validate_json(encoded)
    assert saved.checkpoint is not None
    assert saved.checkpoint.version == 1
    with pytest.raises(ValidationError, match="version"):
        ResponseCheckpoint.model_validate(
            saved.checkpoint.model_dump() | {"version": 2}
        )
    checkpoint = storage.load(encoded)
    completed_search = checkpoint.run_state.steps[0].tools["search"].result
    assert completed_search is not None
    assert isinstance(completed_search.metadata, SearchPlanningResult)
    assert completed_search.metadata.original_queries == ("facts",)

    restored, restored_agent = build(model(), checkpoint.run_state.agent_id)
    resumed = restored_agent.resume(checkpoint.run_state)
    resumed.submit(
        HumanToolAnswer(request_id="approval", decision=InputDecision.APPROVE)
    )
    assert resumed.result(timeout=5).output.text == "done"
    assert resumed.wait_for_idle(timeout=5)
    assert len(search.contexts) == 1
    assert search.contexts[0].search_context == SearchContext()
    assert gated.contexts[0].search_context == SearchContext()
    assert restored.search_context.cached_expansion == ("facts", ("facts", "evidence"))
    assert len(restored.search_context.search_cycles) == 1
    assert restored.search_context.search_cycles[0].searched_sources == ["web"]

    next_run = restored_agent.start(
        max_steps=1, messages=[UserMessage(content="New turn")]
    )
    assert next_run.result(timeout=5).output.text == "done"
    assert next_run.wait_for_idle(timeout=5)
    assert restored.search_context == SearchContext()


@pytest.mark.parametrize("kind", ["research", "deep_research"])
def test_real_feature_resumes_pending_control_call_after_json(kind: str) -> None:

    def build(
        llm: LLM, agent_id: str | None = None, context: AgentState | None = None
    ) -> tuple[ResearchFeature | DeepResearchFeature, Agent]:
        context = context or AgentState()
        if kind == "research":
            research = ResearchFeature([], llm, len, None, "", ReasoningEffort.LOW)
            return research, research.agent(context, agent_id=agent_id)
        if kind == "deep_research":
            deep_research = DeepResearchFeature(
                allowed_tools=[],
                llm=llm,
                token_counter=len,
                user_identity=None,
                language_section="",
                reasoning_effort=ReasoningEffort.LOW,
                all_injected_file_metadata=None,
                skip_clarification=True,
            )
            return deep_research, deep_research.agent(context, agent_id=agent_id)
        raise ValueError(f"Unknown feature: {kind}")

    name = GENERATE_REPORT_TOOL_NAME
    responses = (
        [Delta(content="Research plan")] if kind == "deep_research" else []
    ) + [tool_delta(name)]
    original_feature, original = build(ScriptedLLM(responses, 128000))
    if isinstance(original_feature, ResearchFeature):
        original_feature.citation_processor.citation_to_doc = {6: document()}
        original_feature.citation_mapping = {6: "reference"}
    elif isinstance(original_feature, DeepResearchFeature):
        original_feature.citation_mapping = {6: document()}
    original.feature = original_feature.bind().model_copy(
        update={
            "before_tool_call": lambda _context: PendingToolInput(
                request_id="control",
                prompt="Continue?",
                mode=InputMode.EXECUTE,
            )
        }
    )
    run = original.start(max_steps=3, messages=[UserMessage(content="Research")])
    assert run.wait_until_settled(timeout=5).status == RunStatus.SUSPENDED
    assert run.wait_for_idle(timeout=5)
    checkpoint = run.capture()
    encoded = CheckpointStorage(CHECKPOINT_PAYLOAD_TYPES).save(
        checkpoint.run_state,
        checkpoint.agent_state,
        CheckpointBinding(tenant_id="tenant", response_id=checkpoint.run_state.run_id),
    )
    saved_id = run.id
    del original_feature, original, run, checkpoint

    final_model = ScriptedLLM([Delta(content="Answer [6]")], 128000)
    checkpoint = CheckpointStorage(CHECKPOINT_PAYLOAD_TYPES).load(encoded)
    restored, restored_agent = build(
        final_model, checkpoint.run_state.agent_id, checkpoint.agent_state
    )
    resumed = restored_agent.resume(checkpoint.run_state)
    resumed.submit(
        HumanToolAnswer(request_id="control", decision=InputDecision.APPROVE)
    )
    result = resumed.result(timeout=5)
    assert resumed.wait_for_idle(timeout=5)
    assert result.run_id == saved_id
    assert result.output.text == "Answer [6]"
    assert len(final_model.requests) == 1
    if isinstance(restored, ResearchFeature):
        assert restored.citation_processor.citation_to_doc[6].document_id == "reference"
    elif isinstance(restored, DeepResearchFeature):
        assert restored.citation_mapping[6].document_id == "reference"


def test_research_restores_search_context_and_resets_it_for_new_run() -> None:
    original = ResearchFeature([], model(), len, None, "", ReasoningEffort.LOW)
    original.search_context = SearchContext(
        search_cycles=(
            SearchCycle(cycle_number=1, queries=["facts"], searched_sources=["web"]),
        ),
        cached_expansion=("facts", ("facts", "evidence")),
        scope_decision_settled=True,
        time_filter=None,
        time_filter_computed=True,
    )
    encoded = original.capture_state().model_dump_json()
    restored = ResearchFeature([], model(), len, None, "", ReasoningEffort.LOW)
    restored.restore_state(TypeAdapter(dict[str, JsonValue]).validate_json(encoded))
    assert restored._tool_context().search_context == original.search_context
    assert not restored._tool_context().skip_search_query_expansion

    run = restored.agent().start(
        max_steps=1, messages=[UserMessage(content="New question")]
    )
    assert run.result(timeout=5).output.text == "done"
    assert run.wait_for_idle(timeout=5)
    assert restored.search_context == SearchContext()
    assert original.search_context.search_cycles[0].queries == ["facts"]


def test_checkpoint_file_storage_preserves_binary_feature_data() -> None:
    payload = b"\xff\x00\x80generated"
    original = chat()
    original.chat_files = [ChatFile(filename="result.bin", content=payload)]
    checkpoint = ExecutionCheckpoint(
        agent_state=AgentState(),
        run_state=RunState(
            run_id="file-checkpoint",
            status=RunStatus.SUSPENDED,
            progress=RunProgress(
                step_limit=2,
                feature_state=original.capture_state().model_dump(mode="json"),
            ),
        ),
    )
    with patch("onyx.chat.restoration.get_default_file_store") as file_store:
        file_store.return_value.has_file.return_value = False
        persist_checkpoint_files(checkpoint, session_id=uuid4())
        written = file_store.return_value.save_file.call_args.kwargs["content"]
        assert written.getvalue() == payload

    restored = ExecutionCheckpoint.model_validate_json(checkpoint.model_dump_json())
    assert restored.run_state.progress is not None
    state = ChatFeatureState.model_validate(restored.run_state.progress.feature_state)
    saved_file = state.chat_files[0]
    assert saved_file.filename == "result.bin"
    assert saved_file.content is None
    assert saved_file.file_id is not None
    with patch("onyx.file_store.file_store.get_default_file_store") as file_store:
        file_store.return_value.read_file.return_value = BytesIO(payload)
        assert saved_file.restore().content == payload


def test_chat_checkpoint_preserves_lazy_file_references() -> None:
    payload = b"\xff\x00\x80binary"
    loads: list[str] = []

    def load(name: str) -> bytes:
        loads.append(name)
        return payload

    original = chat(CaptureContextTool())
    original.context_files.image_files = [
        ChatLoadedFile.lazy_loaded(
            file_id="image",
            file_type=ChatFileType.IMAGE,
            filename="image.png",
            content_text=None,
            token_count=10,
            loader=lambda: load("image"),
        )
    ]
    original.chat_files = [
        ChatFile.lazy_from_filename(
            filename="table.xlsx",
            file_id="table",
            loader=lambda: load("table"),
        )
    ]
    assert loads == []
    snapshot = RunState(
        run_id="binary",
        agent_id="agent",
        status=RunStatus.SUSPENDED,
        steps=[
            StepRecord(
                message=AssistantMessage(
                    id="generation",
                    content=[ToolCall(id="search", name="search", arguments={})],
                ),
                generation_status=ExecutionStatus.COMPLETE,
                tools={
                    "search": ToolExecutionRecord(
                        status=ExecutionStatus.COMPLETE,
                        result=ToolResultMessage(
                            tool_call_id="search",
                            tool_name="search",
                            content="files",
                            details=ChatSearchResult(
                                search_docs=[],
                                citation_mapping={},
                                staged_files=[
                                    ChatFile(filename="result.bin", content=payload)
                                ],
                            ),
                        ),
                    )
                },
            )
        ],
        progress=RunProgress(
            step_limit=2,
            feature_state=original.capture_state().model_dump(mode="json"),
        ),
    )
    codec = CheckpointStorage(CHECKPOINT_PAYLOAD_TYPES)
    encoded = codec.save(
        snapshot,
        AgentState(),
        CheckpointBinding(
            tenant_id="tenant",
            response_id=snapshot.run_id,
        ),
    )
    del original, snapshot
    restored = codec.load(encoded).run_state
    assert restored.progress is not None
    saved = ChatFeatureState.model_validate(restored.progress.feature_state)
    assert loads == []
    with patch("onyx.file_store.file_store.get_default_file_store") as file_store:
        file_store.return_value.read_file.side_effect = lambda *_args, **_kwargs: (
            BytesIO(payload)
        )
        assert saved.chat_files[0].restore().content == payload
        assert saved.context_files.restore().image_files[0].content == payload
    result = restored.messages[1]
    assert isinstance(result, ToolResultMessage)
    assert isinstance(result.details, ChatSearchResult)
    assert result.details.staged_files[0].content == payload
    assert loads == []


def test_chat_binary_checkpoint_resumes_new_execution_in_same_coordinator() -> None:
    payload = b"\xff\x00file"
    coordinator = AgentCoordinator()
    feature = chat(CaptureContextTool())
    feature.chat_files = [
        ChatFile.lazy_from_filename(
            filename="input.bin",
            loader=lambda: payload,
        )
    ]
    feature.llm = FakeModelClient(
        lambda _request, _signal: AssistantMessage(
            content=[ToolCall(id="echo-call", name="echo", arguments={})],
        )
    )
    original = feature.agent(AgentState())
    original.feature = feature.bind().model_copy(
        update={
            "before_tool_call": lambda _context: PendingToolInput(
                request_id="echo",
                prompt="Continue?",
                mode=InputMode.EXECUTE,
            )
        }
    )
    run = original.start(
        max_steps=2, messages=[UserMessage(content="Check")], coordinator=coordinator
    )
    try:
        assert run.wait_until_settled(timeout=5).status == RunStatus.SUSPENDED
        assert run.wait_for_idle(timeout=5)
        checkpoint = run.handoff()
        codec = CheckpointStorage(CHECKPOINT_PAYLOAD_TYPES)
        binding = CheckpointBinding(
            tenant_id="tenant", response_id=checkpoint.run_state.run_id
        )
        encoded = codec.save(checkpoint.run_state, checkpoint.agent_state, binding)
        decoded = codec.load(encoded, expected_binding=binding)
        tool = CaptureContextTool()
        restored = ChatFeature(
            messages=decoded.agent_state.messages,
            tools=[tool],
            custom_agent_prompt=None,
            base_system_prompt="Help",
            context_files=feature.context_files,
            persona=None,
            user_memory_context=None,
            llm=model(),
        ).agent(decoded.agent_state, agent_id=decoded.run_state.agent_id)
        resumed = restored.resume(decoded.run_state, coordinator=coordinator)
        assert resumed is not run and resumed.id == run.id
        resumed.submit(
            HumanToolAnswer(request_id="echo", decision=InputDecision.APPROVE)
        )
        assert resumed.result(timeout=5).output.text == "done"
        assert resumed.wait_for_idle(timeout=5)
        assert tool.contexts[0].chat_files[0].content == payload
    finally:
        assert coordinator.close(timeout=5)
