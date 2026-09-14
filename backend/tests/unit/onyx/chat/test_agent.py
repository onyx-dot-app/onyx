"""Exercise ChatAgent through model streaming, tools, and packet rendering."""

import queue
from contextlib import nullcontext

import pytest

from onyx.chat.agent import ChatAgent
from onyx.chat.chat_state import ChatStateContainer
from onyx.chat.emitter import Emitter, ModelStreamStatus
from onyx.context.messages import PromptMetadata
from onyx.context.search.models import SearchDoc
from onyx.file_store.models import ExtractedContextFiles
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.litellm_models import ChatCompletionDeltaToolCall, Delta, FunctionCall
from onyx.llm.models import Message, ToolChoiceOptions, UserMessage
from onyx.server.query_and_chat.streaming_models import OverallStop, Packet
from onyx.tools.models import ChatFile
from tests.unit.onyx.agents.fakes import EchoTool, ScriptedLLM


@pytest.fixture(autouse=True)
def prompt_store(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "onyx.chat.agent.get_session_with_current_tenant", lambda: nullcontext(None)
    )
    monkeypatch.setattr("onyx.chat.agent.get_default_base_system_prompt", lambda _: "")


@pytest.mark.parametrize(
    "render, observer_fails", [(True, False), (False, False), (True, True)]
)
def test_chat_preserves_parallel_tool_history_forcing_and_packets(
    render: bool,
    observer_fails: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if observer_fails:

        def broken_observer(*_args: object) -> None:
            raise RuntimeError("Packet renderer failed")

        monkeypatch.setattr(
            "onyx.chat.presentation.TurnPresentation.consume", broken_observer
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
            Delta(content="Final answer"),
        ]
    )
    output: queue.Queue[tuple[int, Packet | ModelStreamStatus]] = queue.Queue()
    emitter = Emitter(model_idx=0, merged_queue=output)
    state = ChatStateContainer()
    history: list[Message] = [
        UserMessage(content="Hello", metadata=PromptMetadata(token_count=1))
    ]
    agent = ChatAgent(
        emitter=emitter if render else None,
        state_container=state,
        messages=history,
        tools=[EchoTool(emitter)],
        custom_agent_prompt=None,
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
    agent.run(max_turns=2, cancellation=CancellationSignal())
    assert len(llm.requests) == 2
    assert llm.requests[0]["tool_choice"] == ToolChoiceOptions.REQUIRED
    assert llm.requests[1]["tools"] == []
    assert llm.requests[1]["tool_choice"] == ToolChoiceOptions.NONE
    assert [message.role for message in agent.context.messages] == [
        "user",
        "assistant",
        "tool_result",
        "tool_result",
        "assistant",
    ]
    assert [
        message.tool_call_id
        for message in agent.context.messages[2:4]
        if message.role == "tool_result"
    ] == ["call-0", "call-1"]
    assert agent.context.messages[-1].text == "Final answer"
    snapshot = state.snapshot()
    assert snapshot.transcript is not None
    assert snapshot.transcript.messages[-1].text == "Final answer"
    assert [call.tool_call_response for call in snapshot.tool_calls] == [
        "hello",
        "hello",
    ]
    if observer_fails:
        assert agent.presentation is not None and agent.presentation.calls == {}
        assert all(
            call.turn_index == 0 and call.tab_index == 0 for call in snapshot.tool_calls
        )
        return
    if not render:
        assert agent.presentation is None
        return
    assert state.get_answer_tokens() == "Final answer"
    packets = [output.get_nowait()[1] for _ in range(output.qsize())]
    assert isinstance(packets[-1], Packet)
    assert isinstance(packets[-1].obj, OverallStop)


def test_source_file_staging_does_not_block_cancelled_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from onyx.context.search.models import SearchDocsResponse
    from onyx.llm.cancellation import AgentCancelled
    from onyx.llm.models import ToolResult

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
        "onyx.chat.agent.run_tool_call",
        lambda **_kwargs: ToolResult(
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
    emitter = Emitter(queue.Queue())
    state = ChatStateContainer()
    agent = ChatAgent(
        None,
        state,
        [UserMessage(content="Find documents")],
        [EchoTool(emitter)],
        None,
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
    signal = CancellationSignal()
    with ThreadPoolExecutor(max_workers=1) as workers:
        future = workers.submit(agent.run, max_turns=2, cancellation=signal)
        acquired = False
        try:
            assert entered.wait(2)
            acquired = agent.state_lock.acquire(timeout=0.2)
            assert acquired, "file staging held the snapshot lock"
            signal.cancel()
            snapshot = state.snapshot(cancelled=True)
            assert snapshot.transcript is not None
            assert snapshot.transcript.status == "cancelled"
        finally:
            if acquired:
                agent.state_lock.release()
            release.set()
        with pytest.raises(AgentCancelled):
            future.result(timeout=2)
    assert stage_calls == 1
