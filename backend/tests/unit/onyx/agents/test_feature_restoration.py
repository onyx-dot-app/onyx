"""Restore feature state and tool execution through JSON."""

from collections.abc import Callable, Generator
from contextlib import contextmanager
from io import BytesIO
from threading import Event
from unittest.mock import MagicMock, patch

import pytest

from onyx.agents.agent_coordination import AgentCoordinator
from onyx.agents.execution_records import OperationSnapshot, RunStatus
from onyx.agents.models import (
    AgentState,
    AgentStep,
    PreparedStep,
    RunProgress,
    RunState,
    StepInput,
)
from onyx.agents.runtime import Agent
from onyx.agents.tools import (
    HumanToolAnswer,
    InputDecision,
    InputMode,
    PendingToolInput,
    ToolInvocation,
)
from onyx.chat.agent import ChatAgent
from onyx.chat.checkpoint import CheckpointBinding, _checkpoint_model_types
from onyx.chat.models import ChatFeatureState, ChatSearchResult
from onyx.coding_agent.agent import CodingAgent
from onyx.coding_agent.tool_definitions import BASH_TOOL_NAME
from onyx.configs.constants import DocumentSource
from onyx.context.search.models import SearchDoc
from onyx.deep_research.agent import DeepResearchAgent
from onyx.deep_research.research_agent import ResearchAgent
from onyx.deep_research.tool_definitions import GENERATE_REPORT_TOOL_NAME
from onyx.file_store.models import ChatFileType, ChatLoadedFile, ExtractedContextFiles
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.interfaces import LLM, LLMUserIdentity
from onyx.llm.litellm_models import Delta
from onyx.llm.models import (
    AssistantMessage,
    ReasoningEffort,
    TextContent,
    ToolCall,
    ToolResult,
    ToolResultMessage,
    UserMessage,
)
from onyx.secondary_llm_flows.source_filter import SearchCycle
from onyx.tools.interface import ToolContext
from onyx.tools.models import ChatFile
from onyx.tools.tool_implementations.bash.bash_tool import BashTool
from onyx.tools.tool_implementations.coding_agent.coding_agent_tool import (
    CodingAgentTool,
)
from onyx.tools.tool_implementations.search.models import SearchToolState
from onyx.tools.tool_implementations.search.search_tool import (
    SearchTool,
)
from onyx.tools.tool_runner import bind_tool
from tests.unit.onyx.agents.checkpoint_storage import CheckpointStorage
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


def chat(tool: EchoTool | None = None) -> ChatAgent:
    return ChatAgent(
        messages=[],
        tools=[tool] if tool else [],
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
        token_counter=len,
    )


class CaptureContextTool(EchoTool):
    def __init__(self) -> None:
        self.contexts: list[ToolContext] = []

    def run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:
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
        messages=[],
        progress=RunProgress(
            step_limit=3,
            feature_state=original.capture_state(),
        ),
    )
    encoded = CheckpointStorage(_checkpoint_model_types()).save(
        snapshot,
        AgentState(),
        CheckpointBinding(tenant_id="tenant", branch_id="branch", context_version="1"),
    )
    del original, snapshot
    tool = CaptureContextTool()
    restored = chat(tool)
    saved = CheckpointStorage(_checkpoint_model_types()).load(encoded).run_state
    assert saved.progress is not None
    assert isinstance(saved.progress.feature_state, ChatFeatureState)
    restored.restore_state(saved.progress.feature_state)
    restored.agent.tools[0].execute(
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
    original = ResearchAgent([], model(), len, None, "", ReasoningEffort.LOW)
    original.citation_processor.citation_to_doc = {8: document()}
    original.citation_mapping = {8: "reference"}
    encoded = original.capture_state().model_dump_json()
    restored = ResearchAgent([], model(), len, None, "", ReasoningEffort.LOW)
    schema = _checkpoint_model_types()["research.state.v1"]
    restored.restore_state(schema.model_validate_json(encoded))
    assert restored.citation_processor.get_next_citation_number() == 9
    assert restored.citation_mapping == {8: "reference"}
    changed = ResearchAgent([], model(), len, None, "French", ReasoningEffort.LOW)
    with pytest.raises(ValueError, match="configuration"):
        changed.restore_state(schema.model_validate_json(encoded))


def test_deep_research_restores_citations_and_control_tools() -> None:
    def feature() -> DeepResearchAgent:
        return DeepResearchAgent(
            messages=[],
            allowed_tools=[],
            llm=model(),
            token_counter=len,
            user_identity=None,
            language_section="",
            reasoning_effort=ReasoningEffort.LOW,
            all_injected_file_metadata=None,
        )

    original = feature()
    prepared = original.prepare_step(
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
    restored.restore_state(
        _checkpoint_model_types()["deep_research.state.v1"].model_validate_json(encoded)
    )
    names = {tool.name for tool in prepared.tools}
    tools = [tool for tool in restored.agent.tools if tool.name in names]
    assert restored.citation_mapping[4].document_id == "reference"
    assert tools[0].definition == prepared.tools[0].definition
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


def test_chat_suspends_and_resumes_with_fresh_feature_and_model() -> None:

    original = chat(CaptureContextTool())
    original.agent.llm = FakeModelClient(
        lambda _request, _signal: AssistantMessage(
            content=[ToolCall(id="echo-call", name="echo", arguments={})]
        )
    )
    original.agent.before_tool_call = lambda _context: PendingToolInput(
        request_id="approve-echo", prompt="Run echo?", mode=InputMode.EXECUTE
    )
    run = original.agent.start(max_steps=3, messages=[UserMessage(content="Check")])
    assert run.wait_until_settled(timeout=5).status == RunStatus.SUSPENDED
    assert run.wait_for_idle(timeout=5)
    checkpoint = run.capture()
    encoded = CheckpointStorage(_checkpoint_model_types()).save(
        checkpoint.run_state,
        checkpoint.agent_state,
        CheckpointBinding(tenant_id="tenant", branch_id="branch", context_version="1"),
    )
    del original, run, checkpoint

    tool = CaptureContextTool()
    restored = chat(tool)
    checkpoint = CheckpointStorage(_checkpoint_model_types()).load(encoded)
    restored = ChatAgent(
        messages=checkpoint.agent_state.messages,
        tools=[tool],
        custom_agent_prompt=None,
        base_system_prompt="Help",
        context_files=restored.context_files,
        persona=None,
        user_memory_context=None,
        llm=model(),
        token_counter=len,
        agent_id=checkpoint.run_state.agent_id,
        checkpoint=checkpoint.agent_state.checkpoint,
    )
    prepared_indices: list[int] = []
    prepare = restored.prepare_step

    def prepare_next(state: StepInput) -> PreparedStep:
        prepared_indices.append(state.step.index)
        return prepare(state)

    restored.agent.prepare_step = prepare_next
    resumed = restored.agent.resume(checkpoint.run_state)
    resumed.submit(
        HumanToolAnswer(request_id="approve-echo", decision=InputDecision.APPROVE)
    )
    assert resumed.result(timeout=5).output.text == "done"
    assert resumed.wait_for_idle(timeout=5)
    assert resumed.id == checkpoint.run_state.run_id
    assert prepared_indices == [1]
    assert len(tool.contexts) == 1


@pytest.mark.parametrize("kind", ["research", "deep_research"])
def test_real_feature_resumes_pending_control_call_after_json(kind: str) -> None:

    def build(
        llm: LLM, agent_id: str | None = None, context: AgentState | None = None
    ) -> ResearchAgent | DeepResearchAgent:
        context = context or AgentState()
        if kind == "research":
            return ResearchAgent(
                [],
                llm,
                len,
                None,
                "",
                ReasoningEffort.LOW,
                messages=context.messages,
                checkpoint=context.checkpoint,
                agent_id=agent_id,
            )
        if kind == "deep_research":
            return DeepResearchAgent(
                messages=context.messages,
                allowed_tools=[],
                llm=llm,
                token_counter=len,
                user_identity=None,
                language_section="",
                reasoning_effort=ReasoningEffort.LOW,
                all_injected_file_metadata=None,
                skip_clarification=True,
                checkpoint=context.checkpoint,
                agent_id=agent_id,
            )
        raise ValueError(f"Unknown feature: {kind}")

    name = GENERATE_REPORT_TOOL_NAME
    responses = (
        [Delta(content="Research plan")] if kind == "deep_research" else []
    ) + [tool_delta(name)]
    original = build(ScriptedLLM(responses, 128000))
    if isinstance(original, ResearchAgent):
        original.citation_processor.citation_to_doc = {6: document()}
        original.citation_mapping = {6: "reference"}
    elif isinstance(original, DeepResearchAgent):
        original.citation_mapping = {6: document()}
    original.agent.before_tool_call = lambda _context: PendingToolInput(
        request_id="control",
        prompt="Continue?",
        mode=InputMode.EXECUTE,
    )
    run = original.agent.start(max_steps=3, messages=[UserMessage(content="Research")])
    assert run.wait_until_settled(timeout=5).status == RunStatus.SUSPENDED
    assert run.wait_for_idle(timeout=5)
    checkpoint = run.capture()
    encoded = CheckpointStorage(_checkpoint_model_types()).save(
        checkpoint.run_state,
        checkpoint.agent_state,
        CheckpointBinding(tenant_id="tenant", branch_id="branch", context_version="1"),
    )
    saved_id = run.id
    del original, run, checkpoint

    final_model = ScriptedLLM([Delta(content="Answer [6]")], 128000)
    restored = build(final_model)
    checkpoint = CheckpointStorage(_checkpoint_model_types()).load(encoded)
    restored = build(final_model, checkpoint.run_state.agent_id, checkpoint.agent_state)
    resumed = restored.agent.resume(checkpoint.run_state)
    resumed.submit(
        HumanToolAnswer(request_id="control", decision=InputDecision.APPROVE)
    )
    result = resumed.result(timeout=5)
    assert resumed.wait_for_idle(timeout=5)
    assert result.run_id == saved_id
    assert result.output.text == "Answer [6]"
    assert len(final_model.requests) == 1
    if isinstance(restored, ResearchAgent):
        assert restored.citation_processor.citation_to_doc[6].document_id == "reference"
    elif isinstance(restored, DeepResearchAgent):
        assert restored.citation_mapping[6].document_id == "reference"


def test_research_restores_search_scope_cache_without_recomputing() -> None:

    def search() -> SearchTool:
        return SearchTool(
            tool_id=1,
            user=MagicMock(),
            persona_search_info=MagicMock(),
            llm=model(),
            document_index=MagicMock(),
            user_selected_filters=None,
            project_id_filter=None,
        )

    original = ResearchAgent([search()], model(), len, None, "", ReasoningEffort.LOW)
    saved_tool = original.tools[0]
    assert isinstance(saved_tool, SearchTool)
    saved_tool.restore_state(
        SearchToolState(
            search_cycles=[
                SearchCycle(cycle_number=1, queries=["facts"], searched_sources=["web"])
            ],
            cached_expansion=("facts", ["facts", "evidence"]),
            scope_decision_settled=True,
            time_filter=None,
            time_filter_computed=True,
        )
    )
    encoded = original.capture_state().model_dump_json()
    del original, saved_tool
    restored = ResearchAgent([search()], model(), len, None, "", ReasoningEffort.LOW)
    restored.restore_state(
        _checkpoint_model_types()["research.state.v1"].model_validate_json(encoded)
    )
    tool = restored.tools[0]
    assert isinstance(tool, SearchTool)
    state = tool.capture_state()
    assert state.cached_expansion == ("facts", ["facts", "evidence"])
    assert state.scope_decision_settled and state.time_filter_computed
    assert state.search_cycles[0].cycle_number == 1


def test_coding_delegation_releases_parent_worker_without_deleting_waiting_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    deleted = Event()
    children: list[CodingAgent] = []

    @contextmanager
    def sandbox(repo: str, github_token: str | None) -> Generator[str, None, None]:
        assert repo == "org/repo" and github_token is None
        yield "waiting-workspace"
        deleted.set()

    def child_feature(
        *,
        repo: str,
        llm: LLM,
        token_counter: Callable[[str], int],
        user_identity: LLMUserIdentity | None,
        bash_tool: BashTool,
    ) -> CodingAgent:
        child = CodingAgent(
            repo=repo,
            llm=llm,
            token_counter=token_counter,
            user_identity=user_identity,
            bash_tool=bash_tool,
        )
        child.agent.before_tool_call = lambda _context: PendingToolInput(
            request_id="allow-bash",
            prompt="Run command?",
            mode=InputMode.EXECUTE,
        )
        children.append(child)
        return child

    module = "onyx.tools.tool_implementations.coding_agent.coding_agent_tool"
    monkeypatch.setattr(f"{module}._setup_session", sandbox)
    monkeypatch.setattr(f"{module}.CodingAgent", child_feature)
    monkeypatch.setattr(f"{module}.get_llm_token_counter", lambda _llm: len)
    monkeypatch.setattr(
        BashTool,
        "run",
        lambda _self, _invocation, _context: ToolResult(content="files"),
    )
    child_model = ScriptedLLM(
        [
            tool_delta(BASH_TOOL_NAME, '{"cmd":"ls"}'),
            Delta(content="Investigation done"),
            Delta(content="Child answer"),
        ],
        128000,
    )
    tool = CodingAgentTool(1, child_model)
    parent_model = ScriptedLLM(
        [
            tool_delta(tool.name, '{"query":"Read code","github_repo":"org/repo"}'),
            Delta(content="Parent answer"),
        ],
        128000,
    )
    coordinator = AgentCoordinator()
    parent = Agent(parent_model, tools=[bind_tool(tool, lambda: ToolContext())])
    run = parent.start(max_steps=2, coordinator=coordinator)
    try:
        assert run.wait_until_settled(timeout=5).status == RunStatus.SUSPENDED
        assert run.wait_for_idle(timeout=5)
        child = coordinator.active_run(children[0].agent.id)
        assert child is not None
        assert child.wait_until_settled(timeout=5).status == RunStatus.SUSPENDED
        assert child.wait_for_idle(timeout=5)
        assert not deleted.is_set()
        child.submit(
            HumanToolAnswer(request_id="allow-bash", decision=InputDecision.APPROVE)
        )
        assert run.result(timeout=5).output.text == "Parent answer"
        assert run.wait_for_idle(timeout=5)
        assert deleted.wait(5)
        assert not children[0].is_sandbox_available
    finally:
        assert coordinator.close(timeout=5)


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
        operations=[
            OperationSnapshot(step_index=0, message_index=0, status=RunStatus.COMPLETE)
        ],
        messages=[
            AssistantMessage(
                id="generation",
                content=[ToolCall(id="search", name="search", arguments={})],
            ),
            ToolResultMessage(
                tool_call_id="search",
                tool_name="search",
                content="files",
                details=ChatSearchResult(
                    search_docs=[],
                    citation_mapping={},
                    staged_files=[ChatFile(filename="result.bin", content=payload)],
                ),
            ),
        ],
        progress=RunProgress(step_limit=2, feature_state=original.capture_state()),
    )
    codec = CheckpointStorage(_checkpoint_model_types())
    encoded = codec.save(
        snapshot,
        AgentState(),
        CheckpointBinding(
            tenant_id="tenant",
            branch_id="branch",
            context_version="1",
        ),
    )
    del original, snapshot
    restored = codec.load(encoded).run_state
    assert restored.progress is not None
    saved = restored.progress.feature_state
    assert isinstance(saved, ChatFeatureState)
    assert loads == []
    with patch("onyx.tools.file_snapshot.get_default_file_store") as file_store:
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
    original = chat(CaptureContextTool())
    original.chat_files = [
        ChatFile.lazy_from_filename(
            filename="input.bin",
            loader=lambda: payload,
        )
    ]
    original.agent.llm = FakeModelClient(
        lambda _request, _signal: AssistantMessage(
            content=[ToolCall(id="echo-call", name="echo", arguments={})],
        )
    )
    original.agent.before_tool_call = lambda _context: PendingToolInput(
        request_id="echo",
        prompt="Continue?",
        mode=InputMode.EXECUTE,
    )
    run = original.agent.start(
        max_steps=2, messages=[UserMessage(content="Check")], coordinator=coordinator
    )
    try:
        assert run.wait_until_settled(timeout=5).status == RunStatus.SUSPENDED
        assert run.wait_for_idle(timeout=5)
        checkpoint = run.handoff()
        codec = CheckpointStorage(_checkpoint_model_types())
        binding = CheckpointBinding(
            tenant_id="tenant", branch_id="branch", context_version="1"
        )
        encoded = codec.save(checkpoint.run_state, checkpoint.agent_state, binding)
        decoded = codec.load(encoded, expected_binding=binding)
        tool = CaptureContextTool()
        restored = ChatAgent(
            messages=decoded.agent_state.messages,
            tools=[tool],
            custom_agent_prompt=None,
            base_system_prompt="Help",
            context_files=original.context_files,
            persona=None,
            user_memory_context=None,
            llm=model(),
            token_counter=len,
            agent_id=decoded.run_state.agent_id,
        )
        resumed = restored.agent.resume(decoded.run_state, coordinator=coordinator)
        assert resumed is not run and resumed.id == run.id
        resumed.submit(
            HumanToolAnswer(request_id="echo", decision=InputDecision.APPROVE)
        )
        assert resumed.result(timeout=5).output.text == "done"
        assert resumed.wait_for_idle(timeout=5)
        assert tool.contexts[0].chat_files[0].content == payload
    finally:
        assert coordinator.close(timeout=5)
