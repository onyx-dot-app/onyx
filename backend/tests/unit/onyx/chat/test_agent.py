"""Exercise ChatFeature through model streaming, tools, and packet rendering."""

import json
import queue
import threading
from collections.abc import Mapping
from datetime import datetime, timezone
from functools import partial
from unittest.mock import Mock

import pytest
from pydantic import JsonValue, TypeAdapter

from onyx.agents.agent_coordination import AgentCoordinator
from onyx.agents.events import AgentEvent, MessageStartEvent, MessageUpdateEvent
from onyx.agents.models import (
    AgentCompletion,
    AgentState,
    AgentStep,
    ExecutionStatus,
    RunState,
    RunStatus,
    StepInput,
    StepRecord,
    StepResult,
    ToolExecutionRecord,
)
from onyx.agents.runtime import Agent, Run, RunFailed
from onyx.agents.tool_execution import NO_TOOL_CAN_RUN_RESULT
from onyx.agents.tools import ToolInvocation
from onyx.chat.agent import ChatFeature
from onyx.chat.emitter import Emitter
from onyx.chat.models import (
    ChatMessageMetadata,
    ContextDocuments,
    IncognitoState,
    PersonaPromptConfig,
    PromptMetadata,
    ResponseReplayData,
)
from onyx.chat.presentation import (
    ResponsePresenter,
    project_response,
    replay_response,
)
from onyx.chat.run_store import agent_result_message
from onyx.configs.constants import DocumentSource
from onyx.context.search.models import SearchDoc, SearchDocsResponse
from onyx.deep_research.models import ResearchAgentCallResult
from onyx.deep_research.tool_definitions import RESEARCH_AGENT_TOOL_NAME
from onyx.file_store.models import ContextFileMetadata, ExtractedContextFiles
from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.llm.interfaces import LLM, LLMConfig
from onyx.llm.model_capabilities import ToolFamily
from onyx.llm.model_response import (
    ChatCompletionDeltaToolCall,
    Delta,
    ResponseFunctionCall,
)
from onyx.llm.models import (
    AssistantMessage,
    GenerationOptions,
    GenerationRequest,
    Message,
    TextContent,
    TextDeltaEvent,
    ToolCall,
    ToolChoiceOptions,
    ToolResult,
    ToolResultMessage,
    UserMessage,
)
from onyx.prompts.chat_prompts import (
    FILE_REMINDER,
    IMAGE_GEN_REMINDER,
    OPEN_URL_REMINDER,
    REQUIRE_CITATION_GUIDANCE,
    ROOT_AGENT_INSTRUCTIONS,
    SUBAGENT_INSTRUCTIONS,
)
from onyx.server.query_and_chat.streaming_models import (
    AgentResponseStart,
    CitationInfo,
    CustomToolStart,
    OverallStop,
    Packet,
)
from onyx.tools.constants import PYTHON_TOOL_NAME
from onyx.tools.interface import Tool
from onyx.tools.models import CapabilityEntry, ChatFile, ToolContext
from onyx.tools.tool_implementations.api_app.openapi_parsing import MethodSpec
from onyx.tools.tool_implementations.api_app.rest_tool import RestTool
from onyx.tools.tool_implementations.mcp.mcp_tool import MCPTool
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.subagents.shapes import AGENT_SHAPES
from onyx.tools.tool_implementations.subagents.subagent_tools import SpawnAgentTool
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool
from onyx.utils.fleet_query_telemetry import QueryMode, QueryObservation
from tests.unit.fakes import NO_CREDENTIALS
from tests.unit.onyx.agents.fakes import (
    EchoTool,
    FakeModelClient,
    FakeRunOwnership,
    ScriptedLLM,
    run_agent,
)


def chat_agent(
    llm: LLM, tools: list[Tool], *, code_mode: bool = False, is_subagent: bool = False
) -> tuple[Agent, ChatFeature]:
    """Build a chat agent whose children share its configuration."""
    feature = ChatFeature(
        messages=[],
        tools=tools,
        code_mode=code_mode,
        custom_agent_prompt=None,
        base_system_prompt="",
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
        llm=llm,
        is_subagent=is_subagent,
        create_subagent=lambda: chat_agent(
            llm, tools, code_mode=code_mode, is_subagent=True
        )[0],
    )
    return feature.agent(AgentState()), feature


@pytest.mark.parametrize("multiple_operations", [False, True])
@pytest.mark.parametrize(
    "render, observer_fails", [(True, False), (False, False), (True, True)]
)
def test_chat_preserves_parallel_tool_history_preference_and_packets(
    render: bool,
    observer_fails: bool,
    monkeypatch: pytest.MonkeyPatch,
    multiple_operations: bool,
) -> None:
    class SecondOperation(EchoTool):
        @property
        def name(self) -> str:
            return "second_operation"

    class OtherTool(EchoTool):
        @property
        def id(self) -> int:
            return 2

        @property
        def name(self) -> str:
            return "other"

    runs: list[Run] = []
    if observer_fails:

        def broken_observer(_presenter: ResponsePresenter, _event: AgentEvent) -> None:
            raise RuntimeError("Packet renderer failed")

        monkeypatch.setattr(
            "onyx.chat.presentation.ResponsePresenter.consume", broken_observer
        )

    operation_name = "second_operation" if multiple_operations else "echo"
    llm = ScriptedLLM(
        [
            Delta(
                tool_calls=[
                    ChatCompletionDeltaToolCall(
                        id=f"call-{index}",
                        index=index,
                        function=ResponseFunctionCall(
                            name=operation_name, arguments='{"value":"hello"}'
                        ),
                    )
                    for index in range(2)
                ]
            ),
            Delta(content="Final answer", reasoning_content="Compare the evidence"),
        ]
    )
    output: queue.Queue[Packet] = queue.Queue()
    observation = QueryObservation(channel="api", mode=QueryMode.CHAT)
    telemetry = Mock()
    monkeypatch.setattr("onyx.utils.fleet_query_telemetry.emit_telemetry", telemetry)

    def publish(packet: Packet) -> None:
        observation.observe_packet(packet)
        output.put_nowait(packet)

    emitter = Emitter(model_idx=0, publish=publish, query_observation=observation)
    history: list[Message] = [
        UserMessage(content="Hello", metadata=PromptMetadata(token_count=1))
    ]
    feature = ChatFeature(
        messages=[],
        tools=[
            EchoTool(),
            *([SecondOperation()] if multiple_operations else []),
            OtherTool(),
        ],
        custom_agent_prompt=None,
        base_system_prompt="",
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
        llm=llm,
        preferred_tool=CapabilityEntry(tool_id=1),
    )
    agent = feature.agent(AgentState())
    project = partial(
        project_response,
        tool_ids={tool.name: tool.id for tool in feature.application_tools},
        initial_citations=feature.initial_citations,
    )
    run_agent(
        agent,
        runs=runs,
        messages=history,
        listener=ResponsePresenter(emitter).consume if render else None,
        max_steps=2,
        cancellation=CancellationSignal(),
    )
    if render and not observer_fails:
        observation.finish()
        assert telemetry.call_args.args[1]["llm_cycles"] == 2
    assert len(llm.requests) == 2
    assert llm.requests[0]["tool_choice"] == ToolChoiceOptions.AUTO
    assert [tool["function"]["name"] for tool in llm.requests[0]["tools"]] == [
        tool.name for tool in feature.application_tools
    ]
    for request in llm.requests:
        assert "The user selected these operations for this request: " in str(
            request["prompt"]
        )
    assert llm.requests[1]["tools"] == llm.requests[0]["tools"]
    assert llm.requests[1]["tool_choice"] == ToolChoiceOptions.NONE
    assert [message.role for message in agent.state.messages] == [
        "user",
        "assistant",
        "tool_result",
        "tool_result",
        "assistant",
    ]
    assert [
        message.tool_call_id
        for message in agent.state.messages[2:4]
        if message.role == "tool_result"
    ] == ["call-0", "call-1"]
    assert all(
        message.tool_name == operation_name and not message.is_error
        for message in agent.state.messages[2:4]
        if isinstance(message, ToolResultMessage)
    )
    assert agent.state.messages[-1].text == "Final answer"
    snapshot = project(runs[-1].snapshot())
    assert snapshot.answer == "Final answer"
    assert snapshot.reasoning == "Compare the evidence"
    assert snapshot.response is not None
    assert snapshot.response.messages[-1].text == "Final answer"
    assert [call.tool_call_response for call in snapshot.tool_calls] == [
        "hello",
        "hello",
    ]
    assert [
        message.text
        for message in snapshot.response.messages
        if message.role == "tool_result"
    ] == ["hello", "hello"]
    if observer_fails:
        runtime_snapshot = runs[-1].snapshot()
        assert runtime_snapshot is not None and runs[-1].delivery_failed
        return
    if not render:
        assert output.empty()
        return
    assert project(runs[-1].snapshot()).answer == "Final answer"
    packets = [output.get_nowait() for _ in range(output.qsize())]
    assert isinstance(packets[-1], Packet)
    assert isinstance(packets[-1].obj, OverallStop)


def _late_call(call_id: str, lead_in: str | None = None) -> Delta:
    return Delta(
        content=lead_in,
        tool_calls=[
            ChatCompletionDeltaToolCall(
                id=call_id,
                index=0,
                function=ResponseFunctionCall(name="echo", arguments='{"value":"hi"}'),
            )
        ],
    )


def test_last_step_call_is_denied_and_the_extra_step_answers() -> None:
    runs: list[Run] = []
    output: queue.Queue[Packet] = queue.Queue()
    llm = ScriptedLLM(
        [_late_call("late-call", "Let me search for that."), Delta(content="Answer")]
    )
    agent, feature = chat_agent(llm, [EchoTool()])
    result = run_agent(
        agent,
        runs=runs,
        messages=[UserMessage(content="Hello")],
        max_steps=1,
        listener=ResponsePresenter(
            Emitter(model_idx=0, publish=output.put_nowait)
        ).consume,
    )
    denied, extra = llm.requests
    assert [tool["function"]["name"] for tool in denied["tools"]] == [
        tool.name for tool in feature.application_tools
    ]
    assert extra["tools"] == denied["tools"]
    assert denied["tool_choice"] == extra["tool_choice"] == ToolChoiceOptions.NONE
    assert NO_TOOL_CAN_RUN_RESULT in str(extra["prompt"])
    rejected = agent.state.messages[2]
    assert isinstance(rejected, ToolResultMessage)
    assert rejected.tool_call_id == "late-call" and rejected.is_error
    assert rejected.text == NO_TOOL_CAN_RUN_RESULT
    assert result.stop_reason == RunStatus.COMPLETE
    assert result.output.text == "Answer"
    snapshot = runs[-1].snapshot()
    assert snapshot is not None and snapshot.answer_step_index == 1
    projection = project_response(snapshot, tool_ids={})
    assert projection.answer == "Answer"
    assert projection.response is not None
    # The denied call shows as a closed tool card, live and on replay.
    live = [output.get_nowait() for _ in range(output.qsize())]
    replayed = replay_response(projection.response, {}, projection.presentation, {})
    cards = [
        [
            type(packet.obj).__name__
            for packet in packets
            if packet.placement
            == next(
                card.placement
                for card in packets
                if isinstance(card.obj, CustomToolStart)
            )
        ]
        for packets in (live, replayed)
    ]
    assert cards[0] == cards[1]
    assert cards[0][0] == "CustomToolStart" and cards[0][-1] == "SectionEnd"


def test_extra_step_without_an_answer_fails_the_turn() -> None:
    llm = ScriptedLLM([_late_call("late-call"), _late_call("again", " ")])
    with pytest.raises(RunFailed):
        run_agent(
            chat_agent(llm, [EchoTool()])[0],
            messages=[UserMessage(content="Hello")],
            max_steps=1,
        )
    assert len(llm.requests) == 2


def test_after_step_runs_on_the_denied_step(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: list[tuple[int, list[str]]] = []
    after_step = ChatFeature._after_step

    def observe(feature: ChatFeature, result: StepResult) -> bool:
        observed.append(
            (result.step.index, [message.text for message in result.tool_results])
        )
        return after_step(feature, result)

    monkeypatch.setattr(ChatFeature, "_after_step", observe)
    llm = ScriptedLLM([_late_call("late-call"), Delta(content="Answer")])
    run_agent(
        chat_agent(llm, [EchoTool()])[0],
        messages=[UserMessage(content="Hello")],
        max_steps=1,
    )
    assert observed == [(0, [NO_TOOL_CAN_RUN_RESULT]), (1, [])]


_XML_CALL = (
    '<function_calls><invoke name="echo"><parameter name="value">hi</parameter>'
    "</invoke></function_calls>"
)


@pytest.mark.parametrize(
    ("provider", "model_name", "sent_choice"),
    [
        ("openai", "qwen3.7-plus", ToolChoiceOptions.AUTO),
        ("openai", "z-ai/glm-5.3", ToolChoiceOptions.AUTO),
        ("ollama_chat", "llama3.2", ToolChoiceOptions.AUTO),
        ("bedrock", "us.amazon.nova-pro-v1:0", ToolChoiceOptions.AUTO),
        ("openai", "gpt-5", ToolChoiceOptions.NONE),
    ],
)
def test_last_step_text_tool_call_follows_the_sent_tool_choice(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    model_name: str,
    sent_choice: ToolChoiceOptions,
) -> None:
    """Under AUTO a text tool call is denied and the extra step answers; under
    NONE the provider forbade calls, so the text is the answer."""
    monkeypatch.setattr(
        ScriptedLLM,
        "config",
        property(
            lambda self: LLMConfig(
                model_provider=provider,
                model_name=model_name,
                max_input_tokens=self.max_input_tokens,
                temperature=0,
            )
        ),
    )

    def never_run(*_args: object, **_kwargs: object) -> ToolResult:
        raise AssertionError("A call on the last step ran")

    monkeypatch.setattr(EchoTool, "_run", never_run)
    llm = ScriptedLLM([Delta(content=_XML_CALL), Delta(content="Answer")])
    agent, _ = chat_agent(llm, [EchoTool()])
    result = run_agent(agent, messages=[UserMessage(content="Hello")], max_steps=1)

    assert llm.requests[0]["tool_choice"] == sent_choice
    if sent_choice == ToolChoiceOptions.NONE:
        assert len(llm.requests) == 1
        assert result.output.text == _XML_CALL
        return
    assert len(llm.requests) == 2
    denied = agent.state.messages[2]
    assert isinstance(denied, ToolResultMessage)
    assert denied.is_error and denied.text == NO_TOOL_CAN_RUN_RESULT
    assert result.stop_reason == RunStatus.COMPLETE
    assert result.output.text == "Answer"


def test_last_step_xml_without_a_tool_call_is_the_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ScriptedLLM,
        "config",
        property(
            lambda self: LLMConfig(
                model_provider="ollama_chat",
                model_name="llama3.2",
                max_input_tokens=self.max_input_tokens,
                temperature=0,
            )
        ),
    )
    text = '<function_calls><invoke name="unknown"></invoke></function_calls>'
    llm = ScriptedLLM([Delta(content=text)])
    result = run_agent(
        chat_agent(llm, [EchoTool()])[0],
        messages=[UserMessage(content="Hello")],
        max_steps=1,
    )

    assert llm.requests[0]["tool_choice"] == ToolChoiceOptions.AUTO
    assert len(llm.requests) == 1
    assert result.stop_reason == RunStatus.COMPLETE
    assert result.output.text == text


class _PythonTool(EchoTool):
    @property
    def id(self) -> int:
        return 2

    @property
    def name(self) -> str:
        return PYTHON_TOOL_NAME


@pytest.mark.parametrize("python_enabled", [False, True])
@pytest.mark.parametrize("already_available", [False, True])
def test_search_stages_files_only_when_python_needs_them(
    python_enabled: bool,
    already_available: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = SearchDoc(
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
        file_id="source-file",
    )
    search = SearchDocsResponse(
        search_docs=[document],
        citation_mapping={1: "reference"},
        openable_file_names={"source-file": "reference.txt"},
    )
    staged = ChatFile(
        filename="reference.txt", content=b"Evidence", file_id="source-file"
    )
    loaded: dict[str, str] = {}

    def stage(file_names: Mapping[str, str]) -> list[ChatFile]:
        loaded.update(file_names)
        return [staged] if file_names else []

    monkeypatch.setattr(
        "onyx.chat.agent.build_python_chat_files_from_search_docs", stage
    )
    contexts: list[ToolContext] = []

    def run(
        _tool: EchoTool, _invocation: ToolInvocation, context: ToolContext
    ) -> ToolResult:
        contexts.append(context)
        return ToolResult(details=search, content="Evidence [1]")

    monkeypatch.setattr("tests.unit.onyx.agents.fakes.EchoTool.run", run)
    llm = ScriptedLLM(
        [
            *(
                Delta(
                    tool_calls=[
                        ChatCompletionDeltaToolCall(
                            id=f"search-{index}",
                            index=0,
                            function=ResponseFunctionCall(
                                name="echo", arguments='{"value":"query"}'
                            ),
                        )
                    ]
                )
                for index in range(2)
            ),
            Delta(content="Evidence [1]"),
        ]
    )
    feature = ChatFeature(
        messages=[],
        tools=[EchoTool(), _PythonTool()] if python_enabled else [EchoTool()],
        custom_agent_prompt=None,
        base_system_prompt="",
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
        llm=llm,
        chat_files=[staged] if already_available else [],
    )
    agent = feature.agent(AgentState())
    run_agent(agent, messages=[UserMessage(content="Find evidence twice")], max_steps=3)
    # The search tool names staged files only when the chat stages them.
    assert [context.python_stages_search_files for context in contexts] == [
        python_enabled
    ] * 2
    assert loaded == (
        {"source-file": "reference.txt"}
        if python_enabled and not already_available
        else {}
    )
    assert feature.chat_files == (
        [staged] if python_enabled or already_available else []
    )
    results = [
        item for item in agent.state.messages if isinstance(item, ToolResultMessage)
    ]
    assert len(results) == 2
    for result in results:
        assert isinstance(result.details, SearchDocsResponse)
        assert result.details.search_docs == [document]
        assert result.details.citation_mapping == {1: "reference"}


def test_chat_preserves_search_filters_in_accepted_result_and_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    search = SearchDocsResponse(
        queries=["expanded query", "another query"],
        sources=["confluence"],
        time_filter_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
        time_filter_end=datetime(2026, 2, 1, tzinfo=timezone.utc),
        search_docs=[],
        citation_mapping={},
    )
    monkeypatch.setattr(
        "tests.unit.onyx.agents.fakes.EchoTool.run",
        lambda *_args, **_kwargs: ToolResult(details=search, content="No documents"),
    )
    llm = ScriptedLLM(
        [
            Delta(
                tool_calls=[
                    ChatCompletionDeltaToolCall(
                        id="search",
                        index=0,
                        function=ResponseFunctionCall(
                            name="echo", arguments='{"value":"query"}'
                        ),
                    )
                ]
            ),
            Delta(content="No matching documents."),
        ]
    )
    agent = ChatFeature(
        messages=[],
        tools=[EchoTool()],
        custom_agent_prompt=None,
        base_system_prompt="",
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
        llm=llm,
    ).agent(AgentState())
    runs: list[Run] = []
    run_agent(
        agent,
        runs=runs,
        messages=[UserMessage(content="Find documents")],
        max_steps=2,
    )
    accepted = next(
        message
        for message in agent.state.messages
        if isinstance(message, ToolResultMessage)
    )
    assert isinstance(accepted.details, SearchDocsResponse)
    assert accepted.details.model_dump(exclude={"staged_files"}) == search.model_dump()
    projected = project_response(runs[-1].snapshot(), tool_ids={"echo": 1})
    assert projected.response is not None
    saved_result = projected.response.steps[0].tools["search"].result
    assert saved_result is not None
    assert type(saved_result.details) is SearchDocsResponse
    assert saved_result.details == search


def test_cancelled_source_file_staging_drains_before_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = threading.Event()
    release = threading.Event()

    stage_calls = 0

    def stage(_file_names: Mapping[str, str]) -> list[ChatFile]:
        nonlocal stage_calls
        stage_calls += 1
        entered.set()
        assert release.wait(2)
        return []

    monkeypatch.setattr(
        "onyx.chat.agent.build_python_chat_files_from_search_docs", stage
    )
    monkeypatch.setattr(
        "tests.unit.onyx.agents.fakes.EchoTool.run",
        lambda *_args, **_kwargs: ToolResult(
            details=SearchDocsResponse(search_docs=[], citation_mapping={}),
            content="Found documents",
        ),
    )
    llm = ScriptedLLM(
        [
            Delta(
                tool_calls=[
                    ChatCompletionDeltaToolCall(
                        id="search",
                        index=0,
                        function=ResponseFunctionCall(
                            name="echo", arguments='{"value":"query"}'
                        ),
                    )
                ]
            )
        ]
    )
    # Files of found documents are staged only for the Python tool.
    feature = ChatFeature(
        [],
        [EchoTool(), _PythonTool()],
        None,
        "",
        ExtractedContextFiles(
            file_texts=[],
            image_files=[],
            use_as_search_filter=False,
            total_token_count=0,
            file_metadata=[],
            uncapped_token_count=None,
        ),
        None,
        None,
        llm,
    )
    agent = feature.agent(AgentState())
    project = partial(
        project_response,
        tool_ids={tool.name: tool.id for tool in feature.application_tools},
        initial_citations=feature.initial_citations,
    )
    signal = CancellationSignal()

    def exercise() -> None:
        run = agent.start(
            messages=[UserMessage(content="Find documents")],
            max_steps=2,
            cancellation=signal,
        )
        try:
            assert entered.wait(2)
            signal.cancel()
            with pytest.raises(TimeoutError):
                run.result(timeout=0.05)
            assert not run.wait_for_idle(timeout=0)
            assert not run._reusable.done()
        finally:
            release.set()
        with pytest.raises(AgentCancelled):
            run.result(timeout=2)
        assert run.wait_for_idle(timeout=2)
        snapshot = project(run.snapshot())
        assert snapshot.response is not None
        assert snapshot.response.status == "cancelled"

    exercise()
    assert stage_calls == 1


@pytest.mark.parametrize(
    "tool_name, incognito",
    [
        (WebSearchTool.NAME, False),
        (WebSearchTool.NAME, True),
        (SearchTool.NAME, False),
        (SearchTool.NAME, True),
        (RESEARCH_AGENT_TOOL_NAME, False),
        (RESEARCH_AGENT_TOOL_NAME, True),
    ],
)
def test_chat_reuses_completed_source_artifacts_without_duplicate_documents(
    tool_name: str,
    incognito: bool,
) -> None:
    runs: list[Run] = []
    document = SearchDoc(
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
    history: list[Message] = [
        UserMessage(content="Find evidence"),
        AssistantMessage(content=[ToolCall(id="search", name=tool_name, arguments={})]),
        ToolResultMessage(
            tool_call_id="search",
            tool_name=tool_name,
            content="Evidence [4]",
            details=ResearchAgentCallResult(
                intermediate_report="Evidence [4]", citation_mapping={4: document}
            )
            if tool_name == RESEARCH_AGENT_TOOL_NAME
            else SearchDocsResponse(
                search_docs=[document], citation_mapping={4: "reference"}
            ),
        ),
    ]
    if incognito:
        history = IncognitoState.model_validate_json(
            IncognitoState(messages=history).model_dump_json()
        ).messages
    llm = ScriptedLLM(
        [Delta(content="Evidence [4]"), Delta(content="More evidence [4]")], 128000
    )
    feature = ChatFeature(
        messages=history,
        tools=[],
        custom_agent_prompt=None,
        base_system_prompt="",
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
        llm=llm,
    )
    agent = feature.agent(AgentState(messages=history))
    for _ in range(2):
        output: queue.Queue[Packet] = queue.Queue()
        run_agent(
            agent,
            runs=runs,
            messages=[UserMessage(content="Explain the evidence")],
            max_steps=1,
            listener=ResponsePresenter(
                Emitter(model_idx=0, publish=output.put_nowait)
            ).consume,
        )
        reminder = llm.requests[-1]["prompt"][-1].content
        assert isinstance(reminder, str)
        assert REQUIRE_CITATION_GUIDANCE.strip() in reminder
        assert FILE_REMINDER.strip() not in reminder
        assert IMAGE_GEN_REMINDER.strip() not in reminder
        assert OPEN_URL_REMINDER.strip() not in reminder
        assert feature.citation_mapping == {4: "reference"}
        assert feature.citation_processor.citation_to_doc == {4: document}
        assert list(feature.gathered_documents.values()) == [document]
        assert not feature._tool_context().skip_search_query_expansion
        assert feature._tool_context().next_citation_num == 5
        projection = project_response(runs[-1].snapshot(), tool_ids={})
        assert projection.answer is not None
        assert "[[4]](https://example.com/reference)" in projection.answer
        assert any(
            packet.obj.type == "citation_info" and packet.obj.document_id == "reference"
            for packet in output.queue
        )


@pytest.mark.parametrize("source_record", ["tool", "metadata"])
def test_context_file_citations_keep_history_numbers_across_turns(
    source_record: str,
) -> None:
    source = SearchDoc(
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
    history: list[Message] = [UserMessage(content="Find evidence")]
    if source_record == "tool":
        history.extend(
            [
                AssistantMessage(
                    content=[ToolCall(id="search", name=SearchTool.NAME, arguments={})]
                ),
                ToolResultMessage(
                    tool_call_id="search",
                    tool_name=SearchTool.NAME,
                    content="Evidence [1]",
                    details=SearchDocsResponse(
                        search_docs=[source], citation_mapping={1: source.document_id}
                    ),
                ),
            ]
        )
    else:
        history.append(
            AssistantMessage(
                content=[TextContent(text="Evidence [1]")],
                metadata=ChatMessageMetadata(sources={1: source}),
            )
        )
    files = [
        ContextFileMetadata(file_id="file-a", filename="A.txt", file_content="File A"),
        ContextFileMetadata(file_id="file-b", filename="B.txt", file_content="File B"),
    ]
    requests: list[GenerationRequest] = []

    def reply(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        requests.append(request)
        return AssistantMessage(
            content=[TextContent(text="Evidence [1], file [2], other file [3]")]
        )

    for ordered_files in (files, list(reversed(files))):
        feature = ChatFeature(
            messages=history,
            tools=[],
            custom_agent_prompt=None,
            base_system_prompt="Use the evidence.",
            context_files=ExtractedContextFiles(
                file_texts=[file.file_content for file in ordered_files],
                image_files=[],
                use_as_search_filter=False,
                total_token_count=10,
                file_metadata=ordered_files,
                uncapped_token_count=None,
            ),
            persona=None,
            user_memory_context=None,
            llm=FakeModelClient(reply),
        )
        # Resume decodes feature state separately from the retained conversation.
        feature.restore_state(
            TypeAdapter(dict[str, JsonValue]).validate_json(
                feature.capture_state().model_dump_json()
            )
        )
        agent = feature.agent(AgentState(messages=history))
        runs: list[Run] = []
        run_agent(
            agent,
            max_steps=1,
            messages=[UserMessage(content="Compare the sources")],
            runs=runs,
        )
        assert feature._tool_context().citation_mapping == {
            1: "reference",
            2: "file-a",
            3: "file-b",
        }
        assert feature._tool_context().next_citation_num == 4
        context = next(
            message
            for message in requests[-1].messages
            if isinstance(message, UserMessage)
            and isinstance(message.content, str)
            and message.content.startswith(
                "Here are some documents provided for context"
            )
        )
        assert isinstance(context, UserMessage) and isinstance(context.content, str)
        documents = ContextDocuments.model_validate_json(
            context.content.split("\n", 1)[1]
        ).documents
        assert {doc.title: doc.document for doc in documents} == {
            "A.txt": 2,
            "B.txt": 3,
        }
        projection = project_response(runs[0].snapshot(), tool_ids={})
        assert projection.answer is not None
        assert "[[1]](https://example.com/reference)" in projection.answer
        assert {
            number: doc.document_id
            for number, doc in projection.citation_to_doc.items()
        } == {1: "reference", 2: "file-a", 3: "file-b"}
        history = IncognitoState.model_validate_json(
            IncognitoState(messages=agent.state.messages).model_dump_json()
        ).messages


@pytest.mark.parametrize("replace_base", [False, True])
def test_chat_prepared_prompt_rebuilds_history_with_captured_instructions(
    replace_base: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("onyx.chat.prompt_utils.get_company_context", lambda: None)
    files = ExtractedContextFiles(
        file_texts=["Attached evidence"],
        image_files=[],
        use_as_search_filter=False,
        total_token_count=4,
        uncapped_token_count=4,
        file_metadata=[],
    )
    feature = ChatFeature(
        messages=[],
        tools=[EchoTool()],
        custom_agent_prompt="Custom instructions",
        base_system_prompt="Base instructions",
        context_files=files,
        persona=PersonaPromptConfig(
            system_prompt="Replacement instructions",
            task_prompt="Task reminder",
            datetime_aware=False,
            replace_base_system_prompt=replace_base,
        ),
        user_memory_context=None,
        llm=ScriptedLLM([]),
        reminders_enabled=False,
    )
    agent = feature.agent(AgentState())
    prepared = feature._prepare_step(
        StepInput(
            history=[],
            input_messages=[UserMessage(content="Current question")],
            messages=[],
            step=AgentStep(index=0, limit=2),
        )
    )
    history: list[Message] = [
        UserMessage(content="Earlier question"),
        UserMessage(content="Current question"),
    ]
    original = [message.model_dump() for message in history]
    first = prepared.generation_request(
        history, tools=[tool.definition for tool in agent.tools]
    )
    files.file_texts[0] = "Changed attachment"
    feature.custom_agent_prompt = "Changed instructions"
    second = prepared.generation_request(
        [history[-1]], tools=[tool.definition for tool in agent.tools]
    )
    for request in [first, second]:
        assert request.messages[0].text.startswith(
            "Replacement instructions" if replace_base else "Base instructions"
        )
        assert request.messages[0].cacheable
        assert any(
            '"contents": "Attached evidence"' in message.text
            for message in request.messages
        )
        assert not any("Changed" in message.text for message in request.messages)
        assert any(
            message.text == "Custom instructions" for message in request.messages
        )
        assert request.messages[-2].text == "Current question"
        assert (
            request.messages[-1].text
            == "<system-reminder>\nTask reminder\n</system-reminder>"
        )
        assert {tool.name for tool in request.tools} == {"echo"}
    assert any(message.text == "Earlier question" for message in first.messages)
    assert not any(message.text == "Earlier question" for message in second.messages)
    assert [message.model_dump() for message in history] == original


@pytest.mark.parametrize("inject_memories", [False, True])
def test_user_information_is_split_out_of_the_shared_system_prompt(
    monkeypatch: pytest.MonkeyPatch, inject_memories: bool
) -> None:
    from onyx.context.models import UserInfo, UserMemoryContext
    from onyx.llm.models import SystemMessage

    monkeypatch.setattr(
        "onyx.chat.prompt_utils.get_company_context", lambda: "Acme Inc"
    )
    requests = []
    for name in ("Alice", "Bob"):
        feature = ChatFeature(
            messages=[],
            tools=[],
            custom_agent_prompt=None,
            base_system_prompt="Base instructions",
            persona=None,
            context_files=ExtractedContextFiles(
                file_texts=[],
                image_files=[],
                use_as_search_filter=False,
                total_token_count=0,
                uncapped_token_count=0,
                file_metadata=[],
            ),
            user_memory_context=UserMemoryContext(
                user_info=UserInfo(name=name, email=f"{name}@example.com"),
                user_preferences=f"{name} prefers bullet points.",
                memories=[f"{name} works on billing."],
            ),
            llm=ScriptedLLM([]),
            inject_memories_in_prompt=inject_memories,
            reminders_enabled=False,
        )
        current = UserMessage(content="Question")
        prepared = feature._prepare_step(
            StepInput(
                history=[],
                input_messages=[current],
                messages=[],
                step=AgentStep(index=0, limit=2),
            )
        )
        requests.append(prepared.generation_request([current]))
    assert requests[0].messages[0].text == requests[1].messages[0].text
    for request, name, other in zip(
        requests, ("Alice", "Bob"), ("Bob", "Alice"), strict=True
    ):
        shared, user_info, question = request.messages
        assert isinstance(shared, SystemMessage)
        assert shared.cacheable
        assert "Acme Inc" in shared.text
        assert name not in shared.text
        assert isinstance(user_info, SystemMessage)
        assert user_info.cacheable
        assert name in user_info.text
        assert other not in user_info.text
        assert "prefers bullet points" in user_info.text
        assert ("works on billing" in user_info.text) == inject_memories
        assert question.text == "Question"


@pytest.mark.parametrize("use_other_tool", [False, True])
def test_preference_is_advisory_restorable_and_scoped_to_one_turn(
    use_other_tool: bool,
) -> None:
    class OtherTool(EchoTool):
        @property
        def id(self) -> int:
            return 2

        @property
        def name(self) -> str:
            return "other"

    requests: list[GenerationRequest] = []

    def reply(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        requests.append(request)
        if use_other_tool and len(requests) == 1:
            return AssistantMessage(
                content=[
                    ToolCall(
                        id="other-call", name="other", arguments={"value": "evidence"}
                    )
                ]
            )
        return AssistantMessage(
            content=[TextContent(text="Answered without the preferred tool.")]
        )

    make_feature = partial(
        ChatFeature,
        tools=[EchoTool(), OtherTool()],
        custom_agent_prompt="Stable instructions",
        base_system_prompt="",
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
        llm=FakeModelClient(reply),
        reminders_enabled=False,
    )
    original = make_feature(messages=[], preferred_tool=CapabilityEntry(tool_id=1))
    saved = TypeAdapter(dict[str, JsonValue]).validate_json(
        original.capture_state().model_dump_json()
    )
    restored_feature = make_feature(
        messages=[], preferred_tool=CapabilityEntry(tool_id=1)
    )
    restored_feature.restore_state(saved)
    restored = restored_feature.agent(AgentState())
    outcome = run_agent(
        restored, messages=[UserMessage(content="Question")], max_steps=2
    )
    assert outcome.output.text == "Answered without the preferred tool."
    assert len(requests) == (2 if use_other_tool else 1)
    for request in requests:
        assert [tool.name for tool in request.tools] == ["echo", "other"]
        reminder = request.messages[-1]
        assert (
            "The user selected these operations for this request: echo."
            in reminder.text
        )
        assert not reminder.cacheable
        assert request.messages[0].text.startswith("Stable instructions")
        assert request.messages[0] == requests[0].messages[0]
        assert request.messages[0].cacheable
    assert requests[0].options.tool_choice == ToolChoiceOptions.AUTO
    assert requests[0].allowed_tool_names is None
    if use_other_tool:
        assert requests[-1].options.tool_choice == ToolChoiceOptions.NONE
        assert "Prefer them when" not in requests[-1].messages[-1].text
        result = next(
            message
            for message in restored.state.messages
            if isinstance(message, ToolResultMessage)
        )
        assert result.tool_name == "other" and not result.is_error
    assert not any(
        "The user selected" in message.text for message in restored.state.messages
    )
    history = restored.state.messages
    followup = make_feature(messages=history).agent(AgentState(messages=history))
    run_agent(followup, messages=[UserMessage(content="Next question")], max_steps=2)
    assert not any(
        "The user selected" in message.text for message in requests[-1].messages
    )


@pytest.mark.parametrize("code_mode", [False, True])
def test_chat_child_has_its_own_context_and_the_parent_tools(code_mode: bool) -> None:
    """Store-backed delegation is covered by ext-dep `test_run_store.py`."""
    requests: list[GenerationRequest] = []

    def reply(request: GenerationRequest, _: CancellationSignal) -> AssistantMessage:
        requests.append(request)
        return AssistantMessage(content=[TextContent(text="Answer")])

    agent, feature = chat_agent(
        FakeModelClient(reply), [EchoTool()], code_mode=code_mode
    )
    spawn = next(
        tool for tool in feature.application_tools if isinstance(tool, SpawnAgentTool)
    )
    child = spawn.create_agent()
    child_feature = child.feature
    assert isinstance(child_feature, ChatFeature)
    assert child_feature.search_context is not feature.search_context
    assert child_feature.code_mode == code_mode
    if code_mode:
        assert (
            child_feature.code_cells is not None
            and child_feature.code_cells is not feature.code_cells
        )
    for runner in (agent, child):
        run_agent(runner, messages=[UserMessage(content="Task")], max_steps=1)
    expected = {
        *({"execute_code", "wait"} if code_mode else {"echo"}),
        "spawn_agent",
        "list_agents",
        "interrupt_agent",
        "send_message",
    }
    # Only the root waits for its agents by ending its turn.
    assert [{tool.name for tool in request.tools} for request in requests] == [
        {*expected, "wait_agent"},
        expected,
    ]
    root_instructions = ROOT_AGENT_INSTRUCTIONS.format(
        wait_line=AGENT_SHAPES[ToolFamily.OPENAI].wait_line
    )
    roles = [
        [
            m.text
            for m in request.messages
            if m.text in (root_instructions, SUBAGENT_INSTRUCTIONS) and m.cacheable
        ]
        for request in requests
    ]
    assert roles == [[root_instructions], [SUBAGENT_INSTRUCTIONS]]


@pytest.mark.parametrize("family", list(ToolFamily))
def test_the_root_instructions_name_how_its_shape_waits(family: ToolFamily) -> None:
    """One root block for both families; only the wait line is the shape's:
    the wait tool, or ending the response."""
    _, feature = chat_agent(
        FakeModelClient(
            lambda _request, _signal: AssistantMessage(
                content=[TextContent(text="Answer")]
            ),
            family,
        ),
        [EchoTool()],
    )
    assert feature.agent_instructions == ROOT_AGENT_INSTRUCTIONS.format(
        wait_line=AGENT_SHAPES[family].wait_line
    )
    assert feature.agent_instructions is not None
    assert "agent notification" in feature.agent_instructions
    assert ("`wait_agent`" in feature.agent_instructions) == (
        family is ToolFamily.OPENAI
    )
    assert ("End your response to wait" in feature.agent_instructions) == (
        family is ToolFamily.CLAUDE
    )


@pytest.mark.parametrize("custom", [False, True])
def test_builtin_subagent_controls_do_not_shadow_configured_tools(custom: bool) -> None:
    configured = (
        RestTool(
            integration_id=42,
            method_spec=MethodSpec(
                name="list_agents",
                raw_name="list_agents",
                summary="List remote agents",
                path="/agents",
                method="get",
                spec={},
            ),
            base_url="https://example.com",
            headers={},
            approval=None,
            action_key="list_agents",
            credentials=NO_CREDENTIALS,
        )
        if custom
        else MCPTool(
            integration_id=42,
            integration_name="remote",
            integration_description=None,
            server_url="https://example.com",
            transport=None,
            acting_user_id=None,
            credentials=NO_CREDENTIALS,
            tool_name="list_agents",
            tool_description="List remote agents",
            tool_definition={"type": "object", "properties": {}},
        )
    )
    expected_name = (
        "custom__42__list_agents" if custom else "mcp__42__remote__list_agents"
    )

    def reply(request: GenerationRequest, _: CancellationSignal) -> AssistantMessage:
        names = [tool.name for tool in request.tools or []]
        assert names.count("list_agents") == 1
        assert names.count(expected_name) == 1
        assert len(names) == len(set(names))
        return AssistantMessage(content=[TextContent(text="Ready")])

    agent, feature = chat_agent(FakeModelClient(reply), [configured])
    assert (
        run_agent(
            agent, messages=[UserMessage(content="List agents")], max_steps=2
        ).output.text
        == "Ready"
    )
    spawn = next(
        tool for tool in feature.application_tools if isinstance(tool, SpawnAgentTool)
    )
    child = spawn.create_agent()
    assert (
        run_agent(
            child, messages=[UserMessage(content="List agents")], max_steps=2
        ).output.text
        == "Ready"
    )
    assert configured.name == expected_name


def test_child_notification_remaps_citations() -> None:
    existing, child_document, other_child_document = [
        SearchDoc(
            document_id=document_id,
            chunk_ind=0,
            semantic_identifier=document_id,
            link=f"https://example.com/{document_id}",
            blurb="Evidence",
            source_type=DocumentSource.WEB,
            boost=0,
            hidden=False,
            metadata={},
            match_highlights=[],
        )
        for document_id in ("existing", "child", "other-child")
    ]
    completions = [
        AgentCompletion(
            agent_path="/root/research",
            run_id=run_id,
            status=RunStatus.COMPLETE,
            output=AssistantMessage(
                content=[TextContent(text="Child evidence [1]")],
                metadata=ChatMessageMetadata(sources={1: document}),
            ),
        )
        for run_id, document in (
            ("123", child_document),
            ("456", other_child_document),
        )
    ]

    def reply(request: GenerationRequest, _: CancellationSignal) -> AssistantMessage:
        notifications = [
            message
            for message in request.messages
            if message.text.startswith("<agent_notification>")
        ]
        assert len(notifications) == 2
        for notification, citation in zip(notifications, (2, 3), strict=True):
            assert json.loads(notification.text.splitlines()[2]) == {
                "agent": "/root/research",
                "status": "complete",
                "answer": f"Child evidence [{citation}]",
                "still_running": ["/root/review"],
            }
            assert notification.metadata is None
        return AssistantMessage(content=[TextContent(text="Answer [2, 3]")])

    history: list[Message] = [
        AssistantMessage(
            content=[TextContent(text="Earlier answer [1]")],
            metadata=ChatMessageMetadata(sources={1: existing}),
        )
    ]
    feature = ChatFeature(
        messages=history,
        tools=[],
        custom_agent_prompt=None,
        base_system_prompt="",
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
        llm=FakeModelClient(reply),
    )
    agent = feature.agent(AgentState(messages=history))
    coordinator = AgentCoordinator(
        ownership=FakeRunOwnership(
            receive_inputs=lambda _run: [
                agent_result_message(item, ["/root/review"]) for item in completions
            ],
        ),
    )
    try:
        result = run_agent(
            agent,
            messages=[UserMessage(content="Check the research")],
            max_steps=1,
            coordinator=coordinator,
        )
        assert isinstance(result.output.metadata, ChatMessageMetadata)
        assert result.output.metadata.sources == {
            1: existing,
            2: child_document,
            3: other_child_document,
        }
        assert feature.citation_mapping == {1: "existing", 2: "child", 3: "other-child"}
    finally:
        assert coordinator.close(10)


def _document(document_id: str, blurb: str) -> SearchDoc:
    return SearchDoc(
        document_id=document_id,
        chunk_ind=0,
        semantic_identifier=document_id.title(),
        link=f"https://example.com/{document_id}",
        blurb=blurb,
        source_type=DocumentSource.WEB,
        boost=0,
        hidden=False,
        metadata={},
        match_highlights=[],
    )


class _DocumentsTool(EchoTool):
    """Returns the documents that its call's value names."""

    def __init__(self, results: Mapping[str, list[SearchDoc]]) -> None:
        self.results = results

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        documents = self.results[str(invocation.arguments["value"])]
        numbers = {"a": 1, "b": 2, "c": 3}
        return ToolResult(
            content="Found documents",
            details=SearchDocsResponse(
                search_docs=documents,
                citation_mapping={
                    numbers[doc.document_id]: doc.document_id for doc in documents
                },
            ),
        )


def test_each_step_carries_only_new_documents_and_shows_them_all() -> None:
    a, b, c = _document("a", "A"), _document("b", "B"), _document("c", "C")
    newer_b = _document("b", "Newer B")
    results = {
        "first": [a, b],
        "second": [newer_b, c],
        # Equal copies of documents that earlier steps carry.
        "third": [a.model_copy(), c.model_copy()],
    }
    llm = ScriptedLLM(
        [
            *(
                Delta(
                    tool_calls=[
                        ChatCompletionDeltaToolCall(
                            id=value,
                            index=0,
                            function=ResponseFunctionCall(
                                name="echo", arguments=json.dumps({"value": value})
                            ),
                        )
                    ]
                )
                for value in results
            ),
            Delta(content="Answer [1] and [3]."),
        ],
        128000,
    )
    agent, feature = chat_agent(llm, [_DocumentsTool(results)])
    runs: list[Run] = []
    output: queue.Queue[Packet] = queue.Queue()
    run_agent(
        agent,
        runs=runs,
        messages=[UserMessage(content="Find documents")],
        max_steps=5,
        listener=ResponsePresenter(
            Emitter(model_idx=0, publish=output.put_nowait)
        ).consume,
    )
    snapshot = runs[0].snapshot()
    step_documents = [
        [(doc.document_id, doc.blurb) for doc in step.message.metadata.documents]
        for step in snapshot.steps
        if isinstance(step.message.metadata, ChatMessageMetadata)
    ]
    assert step_documents == [
        [],
        [("a", "A"), ("b", "B")],
        [("b", "Newer B"), ("c", "C")],
        [],
    ]
    # In the order first gathered, each in its latest copy, once.
    expected = [("a", "A"), ("b", "Newer B"), ("c", "C")]

    def final_documents(packets: list[Packet]) -> list[tuple[str, str]]:
        starts = [
            packet.obj
            for packet in packets
            if isinstance(packet.obj, AgentResponseStart)
        ]
        assert len(starts) == 1 and starts[0].final_documents is not None
        return [(doc.document_id, doc.blurb) for doc in starts[0].final_documents]

    live = list(output.queue)
    projection = project_response(
        snapshot, tool_ids={tool.name: tool.id for tool in feature.application_tools}
    )
    assert final_documents(live) == expected
    assert projection.top_documents is not None
    assert [
        (doc.document_id, doc.blurb) for doc in projection.top_documents
    ] == expected
    assert projection.response is not None
    replayed = replay_response(
        projection.response,
        {},
        projection.presentation,
        projection.all_search_docs,
    )
    assert final_documents(replayed) == expected
    assert projection.answer is not None
    assert "[[1]](https://example.com/a)" in projection.answer
    assert "[[3]](https://example.com/c)" in projection.answer
    cited = [
        packet.obj.document_id
        for packet in live
        if isinstance(packet.obj, CitationInfo)
    ]
    assert cited == ["a", "c"]

    # A stream that continues the saved response adds to its documents.
    continued: list[Packet] = []
    presenter = ResponsePresenter(Emitter(model_idx=0, publish=continued.append))
    presenter.replay(
        projection.response,
        ResponseReplayData(
            tools={}, documents=projection.all_search_docs, approvals={}
        ),
        projection.presentation,
    )
    del continued[:]
    later = _document("d", "D")
    presenter.consume(
        MessageStartEvent(
            agent_id=snapshot.agent_id,
            run_id=snapshot.run_id,
            message_id=f"{snapshot.run_id}:4",
            step_index=4,
            metadata=ChatMessageMetadata(documents=[later]),
        )
    )
    presenter.consume(
        MessageUpdateEvent(
            agent_id=snapshot.agent_id,
            run_id=snapshot.run_id,
            message_id=f"{snapshot.run_id}:4",
            step_index=4,
            generation_event=TextDeltaEvent(content_index=0, text="More."),
        )
    )
    assert final_documents(continued) == [*expected, ("d", "D")]


def _answer_documents(packets: list[Packet]) -> list[str]:
    starts = [
        packet.obj for packet in packets if isinstance(packet.obj, AgentResponseStart)
    ]
    assert len(starts) == 1 and starts[0].final_documents is not None
    return [doc.document_id for doc in starts[0].final_documents]


def _cited(packets: list[Packet]) -> dict[int, str]:
    return {
        packet.obj.citation_number: packet.obj.document_id
        for packet in packets
        if isinstance(packet.obj, CitationInfo)
    }


def test_steps_that_hold_whole_lists_show_each_document_once() -> None:
    """Steps saved with the run's whole source and document lists, with a
    repeated document, show and cite the same documents as new-only steps."""
    a, b, c = _document("a", "A"), _document("b", "B"), _document("c", "C")
    steps = [
        StepRecord(
            message=AssistantMessage(
                id="run:0",
                content=[ToolCall(id="search", name="echo", arguments={})],
                metadata=ChatMessageMetadata(sources={1: a}, documents=[a, b, a]),
            ),
            generation_status=ExecutionStatus.COMPLETE,
        ),
        StepRecord(
            message=AssistantMessage(
                id="run:1",
                content=[TextContent(text="See [1] and [3].")],
                metadata=ChatMessageMetadata(
                    sources={1: a, 3: c}, documents=[a, b, a, c]
                ),
            ),
            generation_status=ExecutionStatus.COMPLETE,
        ),
    ]
    projection = project_response(
        RunState(
            run_id="run",
            agent_id="agent",
            status=RunStatus.COMPLETE,
            answer_step_index=1,
            steps=steps,
        ),
        tool_ids={},
    )
    assert projection.top_documents is not None
    assert [doc.document_id for doc in projection.top_documents] == ["a", "b", "c"]
    assert projection.answer == (
        "See [[1]](https://example.com/a) and [[3]](https://example.com/c)."
    )
    assert projection.response is not None
    replayed = replay_response(
        projection.response,
        {},
        projection.presentation,
        {doc.document_id: doc for doc in (a, b, c)},
    )
    assert _answer_documents(replayed) == ["a", "b", "c"]
    assert _cited(replayed) == {1: "a", 3: "c"}


def test_a_citation_keeps_its_own_copy_when_a_newer_copy_is_gathered() -> None:
    """Two citation numbers can hold different copies of one document. A step
    adds no source that an earlier step already carries in the same copy,
    even when the gathered documents hold the newer copy."""
    older, newer = _document("a", "Old A"), _document("a", "New A")
    earlier = AssistantMessage(
        id="run:0",
        content=[ToolCall(id="search", name="echo", arguments={"value": "x"})],
        metadata=ChatMessageMetadata(sources={1: older, 2: newer}, documents=[newer]),
    )
    result = ToolResultMessage(
        id="run:0:result:search", tool_call_id="search", tool_name="echo", content="x"
    )
    _, feature = chat_agent(ScriptedLLM([]), [EchoTool()])
    feature.gathered_documents = {"a": newer}
    feature.citation_processor.update_citation_mapping({1: older, 2: newer})
    prepared = feature._prepare_step(
        StepInput(
            history=(),
            input_messages=(UserMessage(content="Find documents"),),
            messages=(earlier, result),
            step=AgentStep(index=1, limit=3),
            previous=StepResult(
                step=AgentStep(index=0, limit=3),
                message=earlier,
                tool_results=(result,),
                options=GenerationOptions(),
            ),
        )
    )
    metadata = prepared.output_metadata
    assert isinstance(metadata, ChatMessageMetadata)
    assert metadata.sources == {}
    assert metadata.documents == []


def test_resumed_run_adds_only_new_documents_after_whole_list_steps() -> None:
    """A run that resumes after steps saved with whole lists adds only what
    those steps lack, and still shows every document once."""
    a, b, c = _document("a", "A"), _document("b", "B"), _document("c", "C")
    earlier = AssistantMessage(
        id="run:0",
        content=[ToolCall(id="search", name="echo", arguments={"value": "x"})],
        metadata=ChatMessageMetadata(sources={1: a, 2: b}, documents=[a, b, a]),
    )
    result = ToolResultMessage(
        id="run:0:result:search", tool_call_id="search", tool_name="echo", content="x"
    )
    _, feature = chat_agent(ScriptedLLM([]), [EchoTool()])
    feature.gathered_documents = {"a": a, "b": b, "c": c}
    feature.citation_processor.update_citation_mapping({1: a, 2: b, 3: c})
    prepared = feature._prepare_step(
        StepInput(
            history=(),
            input_messages=(UserMessage(content="Find documents"),),
            messages=(earlier, result),
            step=AgentStep(index=1, limit=3),
            previous=StepResult(
                step=AgentStep(index=0, limit=3),
                message=earlier,
                tool_results=(result,),
                options=GenerationOptions(),
            ),
        )
    )
    metadata = prepared.output_metadata
    assert isinstance(metadata, ChatMessageMetadata)
    assert {number: doc.document_id for number, doc in metadata.sources.items()} == {
        3: "c"
    }
    assert [doc.document_id for doc in metadata.documents] == ["c"]
    later = AssistantMessage(
        id="run:1", content=[TextContent(text="See [2] and [3].")], metadata=metadata
    )
    projection = project_response(
        RunState(
            run_id="run",
            agent_id="agent",
            status=RunStatus.COMPLETE,
            answer_step_index=1,
            steps=[
                StepRecord(
                    message=earlier,
                    generation_status=ExecutionStatus.COMPLETE,
                    tools={
                        "search": ToolExecutionRecord(
                            status=ExecutionStatus.COMPLETE, result=result
                        )
                    },
                ),
                StepRecord(message=later, generation_status=ExecutionStatus.COMPLETE),
            ],
        ),
        tool_ids={},
    )
    assert projection.top_documents is not None
    assert [doc.document_id for doc in projection.top_documents] == ["a", "b", "c"]
    assert projection.answer == (
        "See [[2]](https://example.com/b) and [[3]](https://example.com/c)."
    )
