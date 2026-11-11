"""Exercise ChatAgent through model streaming, tools, and packet rendering."""

import json
import queue
import threading
from datetime import datetime, timezone
from functools import partial
from typing import Literal
from unittest.mock import Mock

import pytest
from pydantic import JsonValue, TypeAdapter

from onyx.agents.agent_coordination import AgentCoordinator
from onyx.agents.events import AgentEvent
from onyx.agents.models import (
    AgentCompletion,
    AgentStep,
    InputMessageMetadata,
    InputSource,
    RunState,
    RunStatus,
    StepInput,
)
from onyx.agents.runtime import Run
from onyx.agents.tools import ToolInvocation
from onyx.chat.agent import ChatAgent
from onyx.chat.emitter import Emitter
from onyx.chat.models import (
    ChatMessageMetadata,
    ContextDocuments,
    IncognitoState,
    PersonaPromptConfig,
    PromptMetadata,
)
from onyx.chat.presentation import ResponsePresenter, project_response
from onyx.configs.constants import DocumentSource
from onyx.context.search.models import SearchDoc, SearchDocsResponse
from onyx.db.enums import IncognitoRecordMode, MCPOAuthProviderMode
from onyx.db.models import MCPServer
from onyx.deep_research.models import ResearchAgentCallResult
from onyx.deep_research.tool_definitions import RESEARCH_AGENT_TOOL_NAME
from onyx.file_store.models import ContextFileMetadata, ExtractedContextFiles
from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.llm.interfaces import LLMConfig
from onyx.llm.model_response import (
    ChatCompletionDeltaToolCall,
    Delta,
    ResponseFunctionCall,
)
from onyx.llm.models import (
    AssistantMessage,
    GenerationRequest,
    Message,
    TextContent,
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
    SUBAGENT_INSTRUCTIONS,
)
from onyx.server.query_and_chat.streaming_models import OverallStop, Packet
from onyx.tools.constants import PYTHON_TOOL_NAME
from onyx.tools.models import ChatFile, ToolContext
from onyx.tools.tool_implementations.custom.custom_tool import CustomTool
from onyx.tools.tool_implementations.custom.openapi_parsing import MethodSpec
from onyx.tools.tool_implementations.mcp.mcp_tool import MCPTool
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.subagents.subagent_tools import SpawnAgentTool
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool
from onyx.utils.fleet_query_telemetry import QueryMode, QueryObservation
from shared_configs.contextvars import CURRENT_INCOGNITO_RECORD_MODE_CONTEXTVAR
from tests.unit.onyx.agents.fakes import (
    EchoTool,
    FakeAgentDirectory,
    FakeModelClient,
    FakeRunStore,
    ScriptedLLM,
    run_agent,
)


@pytest.mark.parametrize("multiple_operations", [False, True])
@pytest.mark.parametrize(
    "render, observer_fails", [(True, False), (False, False), (True, True)]
)
@pytest.mark.parametrize(
    ("model_name", "deployment_name", "last_has_tools"),
    [
        ("test-model", None, True),
        ("claude-haiku-4-5", None, True),
        ("qwen3.7-plus", None, False),
        ("z-ai/glm-5.3", None, False),
        ("alias", "glm-5.3", False),
    ],
)
def test_chat_preserves_parallel_tool_history_preference_and_packets(
    render: bool,
    observer_fails: bool,
    monkeypatch: pytest.MonkeyPatch,
    model_name: str,
    deployment_name: str | None,
    last_has_tools: bool,
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
    monkeypatch.setattr(
        ScriptedLLM,
        "config",
        property(
            lambda self: LLMConfig(
                model_provider="openai",
                model_name=model_name,
                deployment_name=deployment_name,
                max_input_tokens=self.max_input_tokens,
                temperature=0,
            )
        ),
    )
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
    agent = ChatAgent(
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
        token_counter=len,
        preferred_tool_id=1,
    )
    project = partial(
        project_response,
        tool_ids={tool.name: tool.id for tool in agent.application_tools},
        initial_citations=agent.initial_citations,
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
        tool.name for tool in agent.application_tools
    ]
    for request in llm.requests:
        assert "The user selected these operations for this request: " in str(
            request["prompt"]
        )
    if last_has_tools:
        assert [tool["function"]["name"] for tool in llm.requests[1]["tools"]] == [
            tool.name for tool in agent.application_tools
        ]
    else:
        assert llm.requests[1]["tools"] is None
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
        search_docs=[document], citation_mapping={1: "reference"}
    )
    staged = ChatFile(
        filename="reference.txt", content=b"Evidence", file_id="source-file"
    )
    loaded: list[SearchDoc] = []

    def stage(docs: list[SearchDoc]) -> list[ChatFile]:
        loaded.extend(docs)
        return [staged] if docs else []

    monkeypatch.setattr(
        "onyx.chat.agent.build_python_chat_files_from_search_docs", stage
    )
    monkeypatch.setattr(
        "tests.unit.onyx.agents.fakes.EchoTool.run",
        lambda *_args, **_kwargs: ToolResult(details=search, content="Evidence [1]"),
    )
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
    agent = ChatAgent(
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
        token_counter=len,
        chat_files=[staged] if already_available else [],
    )
    run_agent(agent, messages=[UserMessage(content="Find evidence twice")], max_steps=3)
    assert loaded == ([document] if python_enabled and not already_available else [])
    assert agent.chat_files == ([staged] if python_enabled or already_available else [])
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
    agent = ChatAgent(
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
        token_counter=len,
    )
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

    def stage(_docs: list[SearchDoc]) -> list[ChatFile]:
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
    agent = ChatAgent(
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
        len,
    )
    project = partial(
        project_response,
        tool_ids={tool.name: tool.id for tool in agent.application_tools},
        initial_citations=agent.initial_citations,
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
    feature = ChatAgent(
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
        token_counter=len,
    )
    for _ in range(2):
        output: queue.Queue[Packet] = queue.Queue()
        run_agent(
            feature,
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
        assert feature.gathered_documents == [document]
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
        feature = ChatAgent(
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
            token_counter=len,
        )
        # Resume decodes feature state separately from the retained conversation.
        feature.restore_state(
            TypeAdapter(dict[str, JsonValue]).validate_json(
                feature.capture_state().model_dump_json()
            )
        )
        runs: list[Run] = []
        run_agent(
            feature,
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
            IncognitoState(messages=feature.state.messages).model_dump_json()
        ).messages


@pytest.mark.parametrize("replace_base", [False, True])
@pytest.mark.parametrize("incognito_mode", [None, *IncognitoRecordMode])
def test_chat_prepared_prompt_rebuilds_history_with_captured_instructions(
    replace_base: bool,
    incognito_mode: IncognitoRecordMode | None,
    monkeypatch: pytest.MonkeyPatch,
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
    token = CURRENT_INCOGNITO_RECORD_MODE_CONTEXTVAR.set(
        incognito_mode.value if incognito_mode else None
    )
    try:
        agent = ChatAgent(
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
            token_counter=len,
            reminders_enabled=False,
        )
    finally:
        CURRENT_INCOGNITO_RECORD_MODE_CONTEXTVAR.reset(token)
    prepared = agent._prepare_step(
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
    agent.custom_agent_prompt = "Changed instructions"
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
        assert {tool.name for tool in request.tools} == (
            {"echo"}
            if incognito_mode is not None
            else {
                "echo",
                "spawn_agent",
                "list_agents",
                "interrupt_agent",
                "send_message",
                "queue_message",
            }
        )
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
        agent = ChatAgent(
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
            token_counter=len,
            inject_memories_in_prompt=inject_memories,
            reminders_enabled=False,
        )
        current = UserMessage(content="Question")
        prepared = agent._prepare_step(
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

    make_agent = partial(
        ChatAgent,
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
        token_counter=len,
        reminders_enabled=False,
    )
    original = make_agent(messages=[], preferred_tool_id=1)
    saved = TypeAdapter(dict[str, JsonValue]).validate_json(
        original.capture_state().model_dump_json()
    )
    restored = make_agent(messages=[], preferred_tool_id=1)
    restored.restore_state(saved)
    outcome = run_agent(
        restored, messages=[UserMessage(content="Question")], max_steps=2
    )
    assert outcome.output.text == "Answered without the preferred tool."
    assert len(requests) == (2 if use_other_tool else 1)
    for request in requests:
        assert [tool.name for tool in request.tools] == [
            "echo",
            "other",
            "spawn_agent",
            "list_agents",
            "interrupt_agent",
            "send_message",
            "queue_message",
        ]
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
    followup = make_agent(messages=restored.state.messages)
    run_agent(followup, messages=[UserMessage(content="Next question")], max_steps=2)
    assert not any(
        "The user selected" in message.text for message in requests[-1].messages
    )


@pytest.mark.parametrize("parent_action", ["finish", "work"])
@pytest.mark.parametrize("code_mode", [False, True])
def test_chat_delegates_to_an_independent_agent(
    parent_action: Literal["finish", "work"], code_mode: bool
) -> None:
    entered, release = threading.Event(), threading.Event()
    child_requests: list[GenerationRequest] = []
    saved: list[RunState] = []
    child_run_ids: list[str] = []

    class SlowTool(EchoTool):
        def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
            if invocation.arguments["value"] == "parent":
                release.set()
                coordinator.completion(child_run_ids[0]).result(10)
            else:
                entered.set()
                assert release.wait(10)
            invocation.cancellation.check()
            return ToolResult(content="work complete")

    def reply(
        request: GenerationRequest, cancellation: CancellationSignal
    ) -> AssistantMessage:
        cancellation.check()
        is_child = any(
            message.text in {"Independent task", "Leaf task"}
            for message in request.messages
        )
        role_messages = [
            message
            for message in request.messages
            if message.text == SUBAGENT_INSTRUCTIONS
        ]
        assert len(role_messages) == int(is_child)
        if role_messages:
            assert role_messages[0].cacheable
        names = {tool.name for tool in request.tools}
        results = [
            message
            for message in request.messages
            if isinstance(message, ToolResultMessage)
        ]
        assert names == {
            *({"execute_code", "wait_code"} if code_mode else {"echo"}),
            "spawn_agent",
            "list_agents",
            "interrupt_agent",
            "send_message",
            "queue_message",
        }
        if any(message.text == "Leaf task" for message in request.messages):
            if not results:
                return AssistantMessage(
                    content=[
                        ToolCall(
                            id="work",
                            name="execute_code" if code_mode else "echo",
                            arguments={
                                "code": "print(await echo(value='child'))",
                                "yield_time_ms": 10000,
                            }
                            if code_mode
                            else {"value": "child"},
                        )
                    ]
                )
            assert not results[0].is_error
            assert "work complete" in results[0].content
            return AssistantMessage(content=[TextContent(text="Leaf answer")])
        if any(message.text == "Independent task" for message in request.messages):
            child_requests.append(request)
            if not results:
                return AssistantMessage(
                    content=[
                        ToolCall(
                            id="spawn-leaf",
                            name="spawn_agent",
                            arguments={"name": "leaf", "instruction": "Leaf task"},
                        )
                    ]
                )
            if not any(
                isinstance(message, UserMessage)
                and '"answer": "Leaf answer"' in message.text
                for message in request.messages
            ):
                return AssistantMessage(
                    content=[TextContent(text="Leaf work is pending")]
                )
            assert any(
                isinstance(message, UserMessage)
                and '"answer": "Leaf answer"' in message.text
                for message in request.messages
            )
            return AssistantMessage(content=[TextContent(text="Child answer")])
        if not results:
            return AssistantMessage(
                content=[
                    ToolCall(
                        id="spawn",
                        name="spawn_agent",
                        arguments={
                            "name": "investigate",
                            "instruction": "Independent task",
                        },
                    )
                ]
            )
        if len(results) == 1:
            (started,) = [
                child
                for child in coordinator.discover_children(agent.id)
                if child.parent_id == agent.id
            ]
            assert started.latest_run_id is not None
            child_run_ids.append(started.latest_run_id)
            assert entered.wait(10)
            if parent_action == "work":
                return AssistantMessage(
                    content=[
                        ToolCall(
                            id="parent-work",
                            name="execute_code" if code_mode else "echo",
                            arguments={
                                "code": "print(await echo(value='parent'))",
                                "yield_time_ms": 10000,
                            }
                            if code_mode
                            else {"value": "parent"},
                        )
                    ]
                )
        else:
            assert not results[-1].is_error
            assert any(
                isinstance(message, UserMessage)
                and '"answer": "Child answer"' in message.text
                for message in request.messages
            )
        return AssistantMessage(content=[TextContent(text="Parent answer")])

    agent = ChatAgent(
        messages=[],
        tools=[SlowTool()],
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
        llm=FakeModelClient(reply),
        token_counter=lambda text: len(text) // 4,
    )
    spawn = next(
        tool for tool in agent.application_tools if isinstance(tool, SpawnAgentTool)
    )
    child = spawn.create_agent()
    assert isinstance(child, ChatAgent)
    assert child.search_context is not agent.search_context
    assert child.code_mode == agent.code_mode == code_mode
    if code_mode:
        assert child.code_cells is not None and child.code_cells is not agent.code_cells
    assert {tool.name for tool in child.tools} == {tool.name for tool in agent.tools}
    coordinator = AgentCoordinator(
        store=FakeRunStore(save=lambda run: saved.append(run.snapshot()))
    )
    try:
        result = run_agent(
            agent,
            messages=[UserMessage(content="Delegate this")],
            max_steps=4,
            coordinator=coordinator,
        )
        assert result.output.text == "Parent answer"
        child_run = coordinator.child_run(child_run_ids[0], agent.id)
        assert child_run is not None
        progress = child_run.snapshot().progress
        assert progress is not None
        assert progress.step_limit == child.max_steps
        if parent_action == "finish":
            assert child_run.status in (RunStatus.RUNNING, RunStatus.SUSPENDED)
            assert not child_run.cancellation_signal.cancelled
        release.set()
        assert child_run.result(10).output.text == "Child answer"
        assert child_run.wait_for_idle(10)
        assert (
            coordinator.completion(child_run.id).result(10).status == RunStatus.COMPLETE
        )
        assert any(
            state.run_id == child_run.id and state.status == RunStatus.COMPLETE
            for state in saved
        )
        assert len(child_requests) == 3
        assert any(
            message.text == "Independent task" for message in child_requests[0].messages
        )
        assert all(
            message.text != "Delegate this" for message in child_requests[0].messages
        )
    finally:
        release.set()
        assert coordinator.close(10)


@pytest.mark.parametrize("leaf_outcome", ["complete", "error", "cancelled"])
@pytest.mark.parametrize("child_steps", [2, 4])
def test_nested_agent_collects_child_result_before_completing(
    leaf_outcome: Literal["complete", "error", "cancelled"],
    child_steps: int,
) -> None:
    leaf_entered = threading.Event()
    release_leaf = threading.Event()
    middle_answered = threading.Event()
    final_inputs: list[str] = []

    def reply(
        request: GenerationRequest, cancellation: CancellationSignal
    ) -> AssistantMessage:
        instructions = {message.text for message in request.messages}
        results = [
            message
            for message in request.messages
            if isinstance(message, ToolResultMessage)
        ]
        if "Leaf task" in instructions:
            leaf_entered.set()
            assert release_leaf.wait(10)
            cancellation.check()
            if leaf_outcome == "error":
                raise ValueError("Research source unavailable")
            return AssistantMessage(content=[TextContent(text="Verified evidence")])
        if "Middle task" in instructions:
            received = [
                message.text
                for message in request.messages
                if isinstance(message, UserMessage)
                and "Background agent result" in message.text
            ]
            if received:
                final_inputs.extend(received)
                return AssistantMessage(
                    content=[TextContent(text="Final child answer")]
                )
            if results:
                middle_answered.set()
                return AssistantMessage(content=[TextContent(text="Research underway")])
            target = "Leaf"
        else:
            if results:
                return AssistantMessage(
                    content=[TextContent(text="I started the research")]
                )
            target = "Middle"
        return AssistantMessage(
            content=[
                ToolCall(
                    id=f"spawn-{target.lower()}",
                    name="spawn_agent",
                    arguments={"name": target.lower(), "instruction": f"{target} task"},
                )
            ]
        )

    agent = ChatAgent(
        messages=[],
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
        token_counter=lambda text: len(text) // 4,
    )
    for tool in agent.application_tools:
        if isinstance(tool, SpawnAgentTool):
            tool.max_steps = child_steps
    coordinator = AgentCoordinator()
    try:
        root = agent.start(
            messages=[UserMessage(content="Root task")],
            max_steps=4,
            coordinator=coordinator,
        )
        assert root.result(10).output.text == "I started the research"
        if child_steps > 2:
            assert middle_answered.wait(10)
        assert leaf_entered.wait(10)
        middle_info = next(
            info
            for info in coordinator.discover_children(agent.id)
            if info.parent_id == agent.id
        )
        assert middle_info.latest_run_id is not None
        middle = coordinator.child_run(middle_info.latest_run_id, agent.id)
        assert middle is not None
        assert middle.wait_until_settled(10).status == RunStatus.SUSPENDED
        assert coordinator.completed_agents(agent.id, ()) == []
        if leaf_outcome == "cancelled":
            leaf_info = next(
                info
                for info in coordinator.discover_children(middle_info.id)
                if info.parent_id == middle_info.id
            )
            leaf = coordinator.active_run(leaf_info.id)
            assert leaf is not None
            leaf.cancel()
        release_leaf.set()
        assert middle.result(10).output.text == "Final child answer"
        assert middle.wait_for_idle(10)
        completed = coordinator.completed_agents(agent.id, ())
        assert len(completed) == 1
        assert completed[0].output is not None
        assert completed[0].output.text == "Final child answer"
        assert len(final_inputs) == 1
        assert f'"status": "{leaf_outcome}"' in final_inputs[0]
    finally:
        release_leaf.set()
        assert coordinator.close(10)


@pytest.mark.parametrize("custom", [False, True])
def test_builtin_subagent_controls_do_not_shadow_configured_tools(custom: bool) -> None:
    configured = (
        CustomTool(
            id=42,
            method_spec=MethodSpec(
                name="list_agents",
                raw_name="list_agents",
                summary="List remote agents",
                path="/agents",
                method="get",
                spec={},
            ),
            base_url="https://example.com",
        )
        if custom
        else MCPTool(
            tool_id=42,
            mcp_server=MCPServer(
                id=42,
                name="remote",
                server_url="https://example.com",
                oauth_provider_mode=MCPOAuthProviderMode.AUTO_DISCOVERY,
                oauth_cimd_enabled=True,
            ),
            tool_name="list_agents",
            tool_description="List remote agents",
            tool_definition={"type": "object", "properties": {}},
        )
    )
    expected_name = "custom_42_list_agents" if custom else "mcp_remote_list_agents"

    def reply(request: GenerationRequest, _: CancellationSignal) -> AssistantMessage:
        names = [tool.name for tool in request.tools or []]
        assert names.count("list_agents") == 1
        assert names.count(expected_name) == 1
        assert len(names) == len(set(names))
        return AssistantMessage(content=[TextContent(text="Ready")])

    agent = ChatAgent(
        messages=[],
        tools=[configured],
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
        token_counter=len,
    )
    assert (
        run_agent(
            agent, messages=[UserMessage(content="List agents")], max_steps=2
        ).output.text
        == "Ready"
    )
    spawn = next(
        tool for tool in agent.application_tools if isinstance(tool, SpawnAgentTool)
    )
    child = spawn.create_agent()
    assert (
        run_agent(
            child, messages=[UserMessage(content="List agents")], max_steps=2
        ).output.text
        == "Ready"
    )
    assert configured.name == expected_name


@pytest.mark.parametrize("message_tool", ["send_message", "queue_message"])
def test_chat_message_tools_continue_a_completed_child(message_tool: str) -> None:
    child_requests: list[GenerationRequest] = []
    child_ids: list[str] = []
    child_runs: list[str] = []
    coordinator = AgentCoordinator()

    def reply(request: GenerationRequest, _: CancellationSignal) -> AssistantMessage:
        is_parent = any(message.text == "Delegate this" for message in request.messages)
        if not is_parent:
            child_requests.append(request)
            if len(child_requests) == 1:
                assert any(
                    message.text == "Initial task" for message in request.messages
                )
                answer = "Initial child answer"
            else:
                assert any(
                    isinstance(message, AssistantMessage)
                    and message.text == "Initial child answer"
                    for message in request.messages
                )
                assert any(
                    "Follow-up task" in message.text for message in request.messages
                )
                answer = "Follow-up child answer"
            return AssistantMessage(content=[TextContent(text=answer)])
        results = [
            message
            for message in request.messages
            if isinstance(message, ToolResultMessage)
        ]
        if not results:
            return AssistantMessage(
                content=[
                    ToolCall(
                        id="spawn",
                        name="spawn_agent",
                        arguments={"name": "worker", "instruction": "Initial task"},
                    )
                ]
            )
        if not child_ids:
            (started,) = coordinator.discover_children(agent.id)
            assert started.latest_run_id is not None
            child_ids.append(started.id)
            child_runs.append(started.latest_run_id)
            assert (
                coordinator.completion(started.latest_run_id).result(10).status
                == RunStatus.COMPLETE
            )
        if any(message.text == "Continue the child" for message in request.messages):
            if results[-1].tool_name != message_tool:
                return AssistantMessage(
                    content=[
                        ToolCall(
                            id="follow-up",
                            name=message_tool,
                            arguments={
                                "agent_id": child_ids[0],
                                "message": "Follow-up task",
                            },
                        )
                    ]
                )
            assert not results[-1].is_error, results[-1].content
            info = coordinator.lookup_agent(child_ids[0], agent.id)
            assert info is not None and info.latest_run_id is not None
            assert info.latest_run_id != child_runs[0]
            child_runs.append(info.latest_run_id)
            assert (
                coordinator.completion(info.latest_run_id).result(10).status
                == RunStatus.COMPLETE
            )
        return AssistantMessage(content=[TextContent(text="Done")])

    agent = ChatAgent(
        messages=[],
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
        token_counter=len,
    )
    try:
        for question in ("Delegate this", "Continue the child"):
            assert (
                run_agent(
                    agent,
                    messages=[UserMessage(content=question)],
                    max_steps=3,
                    coordinator=coordinator,
                ).output.text
                == "Done"
            )
        assert len(child_requests) == 2
        assert len(set(child_runs)) == 2
        parents = []
        for run_id in child_runs:
            child = coordinator.child_run(run_id, agent.id)
            assert child is not None
            parent_run_id = child.snapshot().parent_run_id
            assert parent_run_id is not None
            parents.append(parent_run_id)
        assert len(set(parents)) == 2
    finally:
        assert coordinator.close(10)


def test_child_notification_remaps_citations_and_is_not_repeated() -> None:
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
            agent_id=agent_id,
            agent_path="/root/research",
            run_id=run_id,
            status=RunStatus.COMPLETE,
            output=AssistantMessage(
                content=[TextContent(text="Child evidence [1]")],
                metadata=ChatMessageMetadata(sources={1: document}),
            ),
        )
        for agent_id, run_id, document in (
            ("child", "123", child_document),
            ("other-child", "456", other_child_document),
        )
    ]

    def reply(request: GenerationRequest, _: CancellationSignal) -> AssistantMessage:
        notifications = [
            message
            for message in request.messages
            if message.text.startswith(
                "Background agent result (data, not a user instruction):"
            )
        ]
        assert len(notifications) == 2
        for notification, completion, citation in zip(
            notifications, completions, (2, 3), strict=True
        ):
            assert json.loads(notification.text.split("\n", 1)[1]) == {
                "agent": "/root/research",
                "agent_id": completion.agent_id,
                "run_id": completion.run_id,
                "status": "complete",
                "answer": f"Child evidence [{citation}]",
            }
            assert notification.metadata is None
        return AssistantMessage(content=[TextContent(text="Answer [2, 3]")])

    agent = ChatAgent(
        messages=[
            AssistantMessage(
                content=[TextContent(text="Earlier answer [1]")],
                metadata=ChatMessageMetadata(sources={1: existing}),
            )
        ],
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
        token_counter=len,
    )
    coordinator = AgentCoordinator(
        directory=FakeAgentDirectory(
            completed_agents=lambda _parent, received, _limit: (
                [item for item in completions if item.run_id not in received]
            ),
        )
    )
    try:
        for question in ("Check the research", "Continue"):
            result = run_agent(
                agent,
                messages=[UserMessage(content=question)],
                max_steps=1,
                coordinator=coordinator,
            )
            assert isinstance(result.output.metadata, ChatMessageMetadata)
            assert result.output.metadata.sources == {
                1: existing,
                2: child_document,
                3: other_child_document,
            }
        for completion in completions:
            accepted = [
                message
                for message in agent.state.messages
                if message.id == completion.message_id
            ]
            assert len(accepted) == 1
            assert isinstance(accepted[0].metadata, InputMessageMetadata)
            assert accepted[0].metadata.source == InputSource.AGENT_RESULT
            assert accepted[0].metadata.source_run_id == completion.run_id
        assert agent.citation_mapping == {1: "existing", 2: "child", 3: "other-child"}
    finally:
        assert coordinator.close(10)
