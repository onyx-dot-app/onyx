"""Accepted tool artifacts remain available when Stop prevents turn completion."""

import queue
import threading
from contextlib import nullcontext

import pytest

from onyx.agents.events import AgentEvent
from onyx.chat.agent import ChatAgent
from onyx.chat.chat_state import ChatStateContainer
from onyx.chat.emitter import Emitter
from onyx.file_store.models import ExtractedContextFiles
from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.llm.litellm_models import ChatCompletionDeltaToolCall, Delta, FunctionCall
from onyx.llm.models import ToolResult, ToolResultMessage, UserMessage
from onyx.tools.models import (
    PythonExecutionFile,
    PythonToolRichResponse,
    ToolCallKickoff,
)
from tests.unit.onyx.agents.fakes import EchoTool, ScriptedLLM


@pytest.mark.parametrize("render", [False, True])
@pytest.mark.parametrize("blocked_sibling", [False, True])
def test_stop_preserves_accepted_file_artifact(
    monkeypatch: pytest.MonkeyPatch, render: bool, blocked_sibling: bool
) -> None:
    monkeypatch.setattr(
        "onyx.chat.agent.get_session_with_current_tenant", lambda: nullcontext(None)
    )
    monkeypatch.setattr("onyx.chat.agent.get_default_base_system_prompt", lambda _: "")
    generated = PythonExecutionFile(
        filename="result.csv", file_link="/files/result.csv"
    )
    calls = 0
    sibling_started = threading.Event()
    release_sibling = threading.Event()

    def execute(**_kwargs: object) -> ToolResult:
        nonlocal calls
        call = _kwargs["tool_call"]
        assert isinstance(call, ToolCallKickoff)
        if call.tool_call_id == "pending":
            sibling_started.set()
            assert release_sibling.wait(5)
            raise AgentCancelled()
        if blocked_sibling:
            assert sibling_started.wait(5)
        calls += 1
        return ToolResult(
            content="Created result.csv",
            details=PythonToolRichResponse(generated_files=[generated]),
        )

    monkeypatch.setattr("onyx.chat.agent.run_tool_call", execute)
    llm = ScriptedLLM(
        [
            Delta(
                tool_calls=[
                    ChatCompletionDeltaToolCall(
                        id="file",
                        index=0,
                        function=FunctionCall(
                            name="echo", arguments='{"value":"create file"}'
                        ),
                    ),
                    *(
                        [
                            ChatCompletionDeltaToolCall(
                                id="pending",
                                index=1,
                                function=FunctionCall(
                                    name="echo", arguments='{"value":"wait"}'
                                ),
                            )
                        ]
                        if blocked_sibling
                        else []
                    ),
                ]
            ),
        ]
    )
    emitter = Emitter(queue.Queue())
    state = ChatStateContainer()
    agent = ChatAgent(
        emitter if render else None,
        state,
        [UserMessage(content="Create a file")],
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

    def stop_after_result(event: AgentEvent) -> None:
        if event.type == "tool_end":
            signal.cancel()

    agent.subscribe(stop_after_result)
    try:
        with pytest.raises(AgentCancelled):
            agent.run(max_turns=2, cancellation=signal)
    finally:
        release_sibling.set()

    for _ in range(2):
        snapshot = state.snapshot(cancelled=True)
        assert snapshot.transcript is not None
        result = next(
            message
            for message in snapshot.transcript.messages
            if isinstance(message, ToolResultMessage) and message.tool_call_id == "file"
        )
        assert result.text == "Created result.csv"
        assert result.details is None
        assert len(snapshot.tool_calls) == 1 + int(blocked_sibling)
        assert snapshot.tool_calls[0].generated_files == [generated]
        assert snapshot.tool_calls[0].tool_call_response == result.text
        # Mutating a projection cannot affect accepted results or later snapshots.
        snapshot.tool_calls[0].generated_files = []
    assert calls == 1


def test_stop_preserves_accepted_research_child_artifacts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import time

    from onyx.deep_research.agent import DeepResearchAgent
    from onyx.deep_research.models import ResearchAgentCallResult
    from onyx.deep_research.tool_definitions import RESEARCH_AGENT_TOOL_NAME
    from onyx.llm.models import AssistantMessage, ReasoningEffort, ToolCall
    from onyx.server.query_and_chat.placement import Placement

    generated = PythonExecutionFile(filename="facts.csv", file_link="/files/facts.csv")
    child = ResearchAgentCallResult(
        intermediate_report="Child report",
        citation_mapping={},
        output_messages=[
            AssistantMessage(
                content=[ToolCall(id="child-file", name="echo", arguments={})]
            ),
            ToolResultMessage(
                tool_call_id="child-file",
                tool_name="echo",
                content="Created facts.csv",
                details=PythonToolRichResponse(generated_files=[generated]),
            ),
        ],
        call_placements={"child-file": Placement(turn_index=0, sub_turn_index=2)},
    )
    monkeypatch.setattr(
        "onyx.deep_research.agent.run_research_agent_call", lambda **_kwargs: child
    )
    monkeypatch.setattr(
        "onyx.deep_research.agent._get_research_agent_tool_id", lambda: 7
    )
    llm = ScriptedLLM(
        [
            Delta(
                tool_calls=[
                    ChatCompletionDeltaToolCall(
                        id="parent",
                        index=0,
                        function=FunctionCall(
                            name=RESEARCH_AGENT_TOOL_NAME, arguments='{"task":"facts"}'
                        ),
                    )
                ]
            ),
        ],
        128000,
    )
    emitter = Emitter(queue.Queue())
    state = ChatStateContainer()
    agent = DeepResearchAgent(
        emitter,
        state,
        [UserMessage(content="Research")],
        [EchoTool(emitter)],
        llm,
        len,
        None,
        "",
        ReasoningEffort.LOW,
        None,
        time.monotonic(),
        "Plan",
        1,
        False,
    )
    signal = CancellationSignal()
    agent.subscribe(lambda event: signal.cancel() if event.type == "tool_end" else None)
    with pytest.raises(AgentCancelled):
        agent.run(max_turns=3, cancellation=signal)
    snapshot = state.snapshot(cancelled=True)
    assert len(snapshot.tool_calls) == 2
    child_record, parent_record = snapshot.tool_calls
    assert child_record.parent_tool_call_id == "parent"
    assert child_record.turn_index == 2
    assert child_record.tab_index == parent_record.tab_index
    assert child_record.generated_files == [generated]
    assert parent_record.tool_call_response == "Child report"
