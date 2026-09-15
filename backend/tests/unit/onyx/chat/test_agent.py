"""Exercise ChatAgent through model streaming, tools, and packet rendering."""

import queue
import threading

import pytest

from onyx.agents.events import AgentEvent
from onyx.chat.agent import ChatAgent
from onyx.chat.emitter import Emitter, ModelStreamStatus
from onyx.chat.presentation import ResponseBinding, ResponsePresenter, attach_response
from onyx.context.messages import PromptMetadata
from onyx.context.search.models import SearchDoc, SearchDocsResponse
from onyx.file_store.models import ExtractedContextFiles
from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.llm.litellm_models import ChatCompletionDeltaToolCall, Delta, FunctionCall
from onyx.llm.models import Message, ToolChoiceOptions, ToolResult, UserMessage
from onyx.server.query_and_chat.streaming_models import OverallStop, Packet
from onyx.tools.models import ChatFile
from onyx.utils.threadpool_concurrency import ContextThreadPoolExecutor
from tests.unit.onyx.agents.fakes import EchoTool, ScriptedLLM


@pytest.mark.parametrize(
    "render, observer_fails", [(True, False), (False, False), (True, True)]
)
def test_chat_preserves_parallel_tool_history_forcing_and_packets(
    render: bool,
    observer_fails: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    output: queue.Queue[tuple[int, Packet | ModelStreamStatus]] = queue.Queue()
    emitter = Emitter(model_idx=0, merged_queue=output, response_id=42)
    state = ResponseBinding()
    history: list[Message] = [
        UserMessage(content="Hello", metadata=PromptMetadata(token_count=1))
    ]
    agent = ChatAgent(
        messages=history,
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
    attach_response(
        agent.agent,
        state,
        emitter if render else None,
        response_id=42,
        tool_ids={tool.name: tool.id for tool in agent.tools},
        initial_citations=agent.artifacts.initial_citations,
    )
    agent.agent.run(max_steps=2, cancellation=CancellationSignal())
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
    snapshot = state.snapshot()
    assert snapshot.answer == "Final answer"
    assert snapshot.reasoning == "Compare the evidence"
    assert snapshot.transcript is not None
    assert snapshot.transcript.messages[-1].text == "Final answer"
    assert [call.tool_call_response for call in snapshot.tool_calls] == [
        "hello",
        "hello",
    ]
    if observer_fails:
        runtime_snapshot = agent.agent.snapshot()
        assert runtime_snapshot is not None and runtime_snapshot.delivery_failed
        return
    if not render:
        assert output.empty()
        return
    assert state.snapshot().answer == "Final answer"
    packets = [output.get_nowait()[1] for _ in range(output.qsize())]
    assert isinstance(packets[-1], Packet)
    assert isinstance(packets[-1].obj, OverallStop)


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
    state = ResponseBinding()
    agent = ChatAgent(
        [UserMessage(content="Find documents")],
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
    attach_response(
        agent.agent,
        state,
        None,
        response_id=42,
        tool_ids={tool.name: tool.id for tool in agent.tools},
        initial_citations=agent.artifacts.initial_citations,
    )
    signal = CancellationSignal()
    with ContextThreadPoolExecutor(max_workers=2) as workers:
        future = workers.submit(
            lambda: agent.agent.run(max_steps=2, cancellation=signal)
        )
        try:
            assert entered.wait(2)
            signal.cancel()
            saved = workers.submit(lambda: state.snapshot(cancelled=True))
            snapshot = saved.result(timeout=0.5)
            assert snapshot.transcript is not None
            assert snapshot.transcript.status == "cancelled"
        finally:
            release.set()
        with pytest.raises(AgentCancelled):
            future.result(timeout=2)
    assert stage_calls == 1
