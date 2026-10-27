"""Exercise ChatAgent through model streaming, tools, and packet rendering."""

import queue
import threading
from datetime import datetime, timezone
from functools import partial
from unittest.mock import Mock

import pytest
from pydantic import JsonValue, TypeAdapter

from onyx.agents.events import AgentEvent
from onyx.agents.models import AgentStep, StepInput
from onyx.agents.runtime import Run
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
from onyx.deep_research.models import ResearchAgentCallResult
from onyx.deep_research.tool_definitions import RESEARCH_AGENT_TOOL_NAME
from onyx.file_store.models import ContextFileMetadata, ExtractedContextFiles
from onyx.llm.cancellation import AgentCancelled, CancellationSignal
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
from onyx.server.query_and_chat.streaming_models import OverallStop, Packet
from onyx.tools.models import ChatFile
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool
from onyx.utils.fleet_query_telemetry import QueryMode, QueryObservation
from tests.unit.onyx.agents.fakes import (
    EchoTool,
    FakeModelClient,
    ScriptedLLM,
    run_agent,
)


@pytest.mark.parametrize(
    "render, observer_fails", [(True, False), (False, False), (True, True)]
)
def test_chat_preserves_parallel_tool_history_forcing_and_packets(
    render: bool,
    observer_fails: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runs: list[Run] = []
    if observer_fails:

        def broken_observer(_presenter: ResponsePresenter, _event: AgentEvent) -> None:
            raise RuntimeError("Packet renderer failed")

        monkeypatch.setattr(
            "onyx.chat.presentation.ResponsePresenter.consume", broken_observer
        )

    llm = ScriptedLLM(
        [
            Delta(
                tool_calls=[
                    ChatCompletionDeltaToolCall(
                        id=f"call-{index}",
                        index=index,
                        function=ResponseFunctionCall(
                            name="echo", arguments='{"value":"hello"}'
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
        forced_tool_id=1,
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
    assert llm.requests[0]["tool_choice"] == ToolChoiceOptions.REQUIRED
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
    agent = ChatAgent(
        [],
        [EchoTool()],
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
    "tool_name", [WebSearchTool.NAME, SearchTool.NAME, RESEARCH_AGENT_TOOL_NAME]
)
@pytest.mark.parametrize("incognito", [False, True])
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
        llm=ScriptedLLM(
            [Delta(content="Evidence [4]"), Delta(content="More evidence [4]")], 128000
        ),
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
        history = feature.state.messages


@pytest.mark.parametrize("replace_base", [False, True])
def test_chat_prepared_prompt_rebuilds_history_with_captured_instructions(
    replace_base: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("onyx.chat.prompt_utils.get_company_context", lambda: None)
    monkeypatch.setattr("onyx.chat.prompt_formatting.PROMPT_CACHE_CHAT_HISTORY", True)
    files = ExtractedContextFiles(
        file_texts=["Attached evidence"],
        image_files=[],
        use_as_search_filter=False,
        total_token_count=4,
        uncapped_token_count=4,
        file_metadata=[],
    )
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
    first = prepared.generation_request(history)
    files.file_texts[0] = "Changed attachment"
    agent.custom_agent_prompt = "Changed instructions"
    second = prepared.generation_request([history[-1]])
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
        assert [tool.name for tool in request.tools] == ["echo"]
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
    monkeypatch.setattr("onyx.chat.prompt_formatting.PROMPT_CACHE_CHAT_HISTORY", True)
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
