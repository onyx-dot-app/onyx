"""Exercise ChatAgent through model streaming, tools, and packet rendering."""

import queue
import threading
from datetime import datetime, timezone
from functools import partial

import pytest

from onyx.agents.events import AgentEvent
from onyx.agents.items import messages_from_items
from onyx.agents.runtime import Run
from onyx.chat.agent import ChatAgent
from onyx.chat.emitter import Emitter
from onyx.chat.presentation import ResponsePresenter, project_response
from onyx.configs.constants import DocumentSource
from onyx.context.messages import PromptMetadata
from onyx.context.search.models import SearchDoc, SearchDocsResponse
from onyx.file_store.models import ExtractedContextFiles
from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.llm.litellm_models import ChatCompletionDeltaToolCall, Delta, FunctionCall
from onyx.llm.models import (
    AssistantMessage,
    Message,
    ToolCall,
    ToolChoiceOptions,
    ToolResult,
    ToolResultMessage,
    UserMessage,
)
from onyx.server.query_and_chat.streaming_models import OverallStop, Packet
from onyx.tools.models import ChatFile
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool
from tests.unit.onyx.agents.fakes import EchoTool, ScriptedLLM, run_agent


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
                        function=FunctionCall(
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
    emitter = Emitter(model_idx=0, publish=output.put_nowait, response_id=42)
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
        response_id=42,
        tool_ids={tool.name: tool.id for tool in agent.tools},
        initial_citations=agent.artifacts.initial_citations,
    )
    run_agent(
        agent.agent,
        runs=runs,
        messages=history,
        listener=ResponsePresenter(emitter).consume if render else None,
        max_steps=2,
        cancellation=CancellationSignal(),
    )
    assert len(llm.requests) == 2
    assert llm.requests[0]["tool_choice"] == ToolChoiceOptions.REQUIRED
    assert llm.requests[1]["tools"] == []
    assert llm.requests[1]["tool_choice"] == ToolChoiceOptions.NONE
    assert [message.role for message in agent.agent.context.messages] == [
        "user",
        "assistant",
        "tool_result",
        "tool_result",
        "assistant",
    ]
    assert [
        message.tool_call_id
        for message in agent.agent.context.messages[2:4]
        if message.role == "tool_result"
    ] == ["call-0", "call-1"]
    assert agent.agent.context.messages[-1].text == "Final answer"
    snapshot = project(runs[-1].snapshot())
    assert snapshot.answer == "Final answer"
    assert snapshot.reasoning == "Compare the evidence"
    assert snapshot.response is not None
    assert messages_from_items(snapshot.response.items)[-1].text == "Final answer"
    assert [call.tool_call_response for call in snapshot.tool_calls] == [
        "hello",
        "hello",
    ]
    assert [
        message.text
        for message in messages_from_items(snapshot.response.items)
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
                        function=FunctionCall(
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
        agent.agent,
        runs=runs,
        messages=[UserMessage(content="Find documents")],
        max_steps=2,
    )
    accepted = next(
        message
        for message in agent.agent.context.messages
        if isinstance(message, ToolResultMessage)
    )
    assert isinstance(accepted.details, SearchDocsResponse)
    assert accepted.details.model_dump(exclude={"staged_files"}) == search.model_dump()
    projected = project_response(
        runs[-1].snapshot(), response_id=42, tool_ids={"echo": 1}
    )
    assert projected.tool_calls[0].result_metadata == search


def test_source_file_staging_does_not_block_cancelled_snapshot(
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
                        function=FunctionCall(
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
        response_id=42,
        tool_ids={tool.name: tool.id for tool in agent.tools},
        initial_citations=agent.artifacts.initial_citations,
    )
    signal = CancellationSignal()

    def exercise() -> None:
        run = agent.agent.start(
            messages=[UserMessage(content="Find documents")],
            max_steps=2,
            cancellation=signal,
        )
        try:
            assert entered.wait(2)
            signal.cancel()
            with pytest.raises(AgentCancelled):
                run.result(timeout=0.5)
            snapshot = project(run.snapshot())
            assert snapshot.response is not None
            assert snapshot.response.status == "cancelled"
            assert not run.wait_for_idle(timeout=0)
        finally:
            release.set()
            assert run.wait_for_idle(timeout=2)

    exercise()
    assert stage_calls == 1


def test_chat_reuses_completed_search_artifacts_without_duplicate_documents() -> None:
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
    feature = ChatAgent(
        messages=[
            UserMessage(content="Find evidence"),
            AssistantMessage(
                content=[ToolCall(id="search", name=WebSearchTool.NAME, arguments={})]
            ),
            ToolResultMessage(
                tool_call_id="search",
                tool_name=WebSearchTool.NAME,
                content="Evidence [4]",
                details=SearchDocsResponse(
                    search_docs=[document], citation_mapping={4: "reference"}
                ),
            ),
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
        llm=ScriptedLLM(
            [Delta(content="Evidence [4]"), Delta(content="More evidence [4]")], 128000
        ),
        token_counter=len,
    )
    for _ in range(2):
        run_agent(
            feature.agent,
            runs=runs,
            messages=[UserMessage(content="Explain the evidence")],
            max_steps=1,
        )
        assert feature.artifacts.citation_mapping == {4: "reference"}
        assert feature.artifacts.citation_processor.citation_to_doc == {4: document}
        assert feature.artifacts.gathered_documents == [document]
