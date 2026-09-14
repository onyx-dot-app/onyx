"""Exercise the shared loop with real Onyx rendering and workflow policies."""

import queue
import time
from typing import Any
from unittest.mock import MagicMock

import pytest

from onyx.chat.chat_state import ChatStateContainer
from onyx.chat.emitter import Emitter, ModelStreamStatus
from onyx.coding_agent.agent import CodingAgent
from onyx.coding_agent.tool_definitions import BASH_TOOL_NAME, GENERATE_ANSWER_TOOL_NAME
from onyx.context.messages import PromptMetadata
from onyx.deep_research.agent import DeepResearchAgent, run_deep_research
from onyx.deep_research.models import ResearchAgentCallResult
from onyx.deep_research.research_agent import ResearchAgent
from onyx.deep_research.tool_definitions import (
    GENERATE_REPORT_TOOL_NAME,
    RESEARCH_AGENT_TOOL_NAME,
    THINK_TOOL_NAME,
)
from onyx.llm.cancellation import AgentCancelled, CancellationSignal, cancellation_scope
from onyx.llm.litellm_models import ChatCompletionDeltaToolCall, Delta, FunctionCall
from onyx.llm.models import Message, ReasoningEffort, ToolCall, ToolResult, UserMessage
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import (
    OverallStop,
    Packet,
    TopLevelBranching,
)
from onyx.tools.interface import Tool
from onyx.tools.models import ToolCallKickoff
from onyx.tools.tool_implementations.bash.bash_tool import BashTool
from onyx.tools.tool_runner import run_tool_call
from tests.unit.onyx.agents.fakes import EchoTool, ScriptedLLM


def tool_delta(name: str, arguments: str = "{}", count: int = 1) -> Delta:
    return Delta(
        tool_calls=[
            ChatCompletionDeltaToolCall(
                index=i,
                id=f"call-{i}",
                function=FunctionCall(name=name, arguments=arguments),
            )
            for i in range(count)
        ]
    )


def kickoff(name: str, **arguments: Any) -> ToolCallKickoff:
    return ToolCallKickoff(
        tool_name=name,
        tool_args=arguments,
        tool_call_id="parent",
        placement=Placement(turn_index=1, tab_index=0),
    )


def emitter() -> Emitter:
    return Emitter(merged_queue=queue.Queue())


@pytest.mark.parametrize("render", [True, False])
def test_coding_bash_order_history_and_final_answer(
    render: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    if not render:
        monkeypatch.setattr(
            "onyx.chat.presentation.TurnPresentation.__init__",
            lambda *_args, **_kwargs: pytest.fail(
                "headless agent constructed a renderer"
            ),
        )
    llm = ScriptedLLM(
        [
            tool_delta(BASH_TOOL_NAME, '{"cmd":"pwd"}', 2),
            tool_delta(GENERATE_ANSWER_TOOL_NAME),
            Delta(content="Done"),
        ],
        128000,
    )
    bash = MagicMock(spec=BashTool)
    bash.run.side_effect = [
        ToolResult(details=None, content=value) for value in ["first", "second"]
    ]
    harness = CodingAgent(
        ToolCall(
            id="parent",
            name="coding_agent",
            arguments={"query": "Read repository", "github_repo": "org/repo"},
        ),
        emitter() if render else None,
        llm,
        len,
        None,
        bash,
    )
    result = harness.run(max_turns=3)
    assert len(llm.requests) == 3
    assert result.output.text == "Done"
    assert bash.run.call_count == 2
    responses = [
        message for message in harness.context.messages if message.role == "tool_result"
    ]
    assert [(message.tool_call_id, message.text) for message in responses] == [
        ("call-0", "first"),
        ("call-1", "second"),
        ("call-0", "Ready to produce the final answer."),
    ]
    assert llm.requests[-1]["tools"] == []


@pytest.mark.parametrize("render", [True, False])
def test_research_think_turns_are_bounded_and_report_is_generated(
    render: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    if not render:
        monkeypatch.setattr(
            "onyx.chat.presentation.TurnPresentation.__init__",
            lambda *_args, **_kwargs: pytest.fail(
                "headless agent constructed a renderer"
            ),
        )
    llm = ScriptedLLM(
        [
            tool_delta(THINK_TOOL_NAME, '{"reasoning":"inspect"}'),
            tool_delta(THINK_TOOL_NAME, '{"reasoning":"compare"}'),
            Delta(content="Report"),
        ],
        128000,
    )
    harness = ResearchAgent(
        ToolCall(id="parent", name="research_agent", arguments={"task": "Find facts"}),
        "parent",
        [],
        emitter() if render else None,
        llm,
        False,
        len,
        None,
        "",
        ReasoningEffort.LOW,
    )
    result = harness.run(max_turns=3)
    assert len(llm.requests) == 3
    assert result.output.text == "Report"
    assert len(llm.requests) == 3
    assert (
        len(
            [
                message
                for message in harness.context.messages
                if message.role == "tool_result"
            ]
        )
        == 2
    )


def test_research_executes_tools_and_records_results() -> None:
    llm = ScriptedLLM(
        [
            tool_delta("echo", '{"value":"found"}'),
            tool_delta(GENERATE_REPORT_TOOL_NAME),
            Delta(content="Report"),
        ],
        128000,
    )
    output = emitter()
    state = ChatStateContainer()
    harness = ResearchAgent(
        ToolCall(id="parent", name="research_agent", arguments={"task": "Find facts"}),
        "parent",
        [EchoTool(output)],
        output,
        llm,
        True,
        len,
        None,
        "",
        ReasoningEffort.LOW,
    )
    result = harness.run(max_turns=3)
    assert result.output.text == "Report"
    assert state.get_tool_calls() == []
    accepted = [
        message
        for message in harness.output_messages
        if message.role == "tool_result" and message.tool_name == "echo"
    ]
    assert accepted[0].text == "found"


def test_orchestrator_preserves_failed_child_tool_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm = ScriptedLLM(
        [
            tool_delta(RESEARCH_AGENT_TOOL_NAME, '{"task":"task"}', 2),
            tool_delta(GENERATE_REPORT_TOOL_NAME),
            Delta(content="Final report"),
        ],
        128000,
    )
    monkeypatch.setattr(
        "onyx.deep_research.agent.run_research_agent_call",
        lambda **kwargs: (
            ResearchAgentCallResult(
                intermediate_report="First report", citation_mapping={}
            )
            if kwargs["research_agent_call"].tool_call_id == "call-0"
            else None
        ),
    )
    monkeypatch.setattr(
        "onyx.deep_research.agent._get_research_agent_tool_id", lambda: 7
    )
    history: list[Message] = [
        UserMessage(content="Research this", metadata=PromptMetadata(token_count=2))
    ]
    state = ChatStateContainer()
    packets: queue.Queue[tuple[int, Packet | ModelStreamStatus]] = queue.Queue()
    harness = DeepResearchAgent(
        Emitter(merged_queue=packets),
        state,
        history,
        [],
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
    harness.run(max_turns=3)
    responses = [
        message for message in harness.context.messages if message.role == "tool_result"
    ]
    assert [message.tool_call_id for message in responses[:2]] == ["call-0", "call-1"]
    assert "failed" in responses[1].text
    assert state.get_answer_tokens() == "Final report"

    assert any(
        isinstance(item[1], Packet)
        and isinstance(item[1].obj, TopLevelBranching)
        and item[1].obj.num_parallel_branches == 2
        for item in list(packets.queue)
    )


def test_cancel_after_coding_tools_prevents_final_model_call() -> None:
    llm = ScriptedLLM([tool_delta(BASH_TOOL_NAME, '{"cmd":"pwd"}')], 128000)
    bash = MagicMock(spec=BashTool)
    bash.run.return_value = ToolResult(details=None, content="done")
    harness = CodingAgent(
        ToolCall(
            id="parent",
            name="coding_agent",
            arguments={"query": "Read repository", "github_repo": "org/repo"},
        ),
        emitter(),
        llm,
        len,
        None,
        bash,
    )
    signal = CancellationSignal()

    agent = harness
    agent.subscribe(lambda event: signal.cancel() if event.type == "tool_end" else None)
    with pytest.raises(AgentCancelled):
        agent.run(max_turns=3, cancellation=signal)
    assert len(llm.requests) == 1


def test_deep_research_composes_plan_child_and_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # One script is consumed by the orchestrator and its single child worker.
    llm = ScriptedLLM(
        [
            Delta(content="Plan"),
            tool_delta(RESEARCH_AGENT_TOOL_NAME, '{"task":"facts"}'),
            tool_delta(GENERATE_REPORT_TOOL_NAME),
            Delta(content="Child report"),
            tool_delta(GENERATE_REPORT_TOOL_NAME),
            Delta(content="Final report"),
        ],
        128000,
    )
    monkeypatch.setattr(
        "onyx.deep_research.agent._get_research_agent_tool_id", lambda: 7
    )
    output: queue.Queue[tuple[int, Packet | ModelStreamStatus]] = queue.Queue()
    state = ChatStateContainer()
    run_deep_research(
        emitter=Emitter(merged_queue=output),
        state_container=state,
        messages=[
            UserMessage(content="Research", metadata=PromptMetadata(token_count=1))
        ],
        tools=[],
        custom_agent_prompt=None,
        llm=llm,
        token_counter=len,
        user_language=None,
        skip_clarification=True,
    )
    assert state.get_answer_tokens() == "Final report"
    assert len(llm.requests) == 6
    snapshot = state.snapshot()
    assert snapshot.transcript is not None
    assert snapshot.transcript.messages[0].text == "Plan"
    assert snapshot.transcript.messages[-1].text == "Final report"
    assert any(
        isinstance(item[1], Packet) and isinstance(item[1].obj, OverallStop)
        for item in list(output.queue)
    )


@pytest.mark.parametrize("skip_clarification", [False, True])
def test_deep_research_prelude_cancellation_keeps_canonical_partial_output(
    skip_clarification: bool,
) -> None:
    from onyx.agents.events import MessageUpdateEvent

    state = ChatStateContainer()
    signal = CancellationSignal()
    agent = DeepResearchAgent(
        None,
        state,
        [UserMessage(content="Research")],
        [],
        ScriptedLLM([Delta(content="Partial prelude")], 128000),
        len,
        None,
        "",
        ReasoningEffort.LOW,
        None,
        time.monotonic(),
        None,
        1,
        False,
        skip_clarification=skip_clarification,
    )

    def stop(event: object) -> None:
        if (
            isinstance(event, MessageUpdateEvent)
            and event.generation_event.type == "text_delta"
        ):
            signal.cancel()

    agent.subscribe(stop)
    with pytest.raises(AgentCancelled):
        agent.run(max_turns=4, cancellation=signal)
    snapshot = state.snapshot(cancelled=True)
    assert snapshot.transcript is not None
    assert snapshot.transcript.status == "cancelled"
    assert snapshot.transcript.messages[-1].text == "Partial prelude"
    assert agent.presentation is None


def test_parent_cancellation_reaches_parallel_research_workers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import threading

    from onyx.deep_research.research_agent import run_research_agent_calls
    from onyx.llm.cancellation import cancellation_scope, current_cancellation

    signal = CancellationSignal()
    observed: queue.Queue[CancellationSignal] = queue.Queue()
    finished = threading.Event()
    errors: list[BaseException] = []

    def child(*_args: Any) -> None:
        inherited = current_cancellation()
        assert inherited is not None
        wake = threading.Event()
        with inherited.on_cancel(wake.set):
            observed.put(inherited)
            assert wake.wait(3)
            inherited.check()
        raise AssertionError("Child did not receive cancellation")

    monkeypatch.setattr(
        "onyx.deep_research.research_agent.run_research_agent_call", child
    )

    def execute() -> None:
        try:
            with cancellation_scope(signal):
                run_research_agent_calls(
                    [
                        kickoff("research_agent", task="one"),
                        kickoff("research_agent", task="two"),
                    ],
                    ["one", "two"],
                    [],
                    emitter(),
                    ScriptedLLM([]),
                    False,
                    len,
                    {},
                    "",
                )
        except AgentCancelled:
            finished.set()
        except BaseException as error:
            errors.append(error)

    worker = threading.Thread(target=execute, daemon=True)
    worker.start()
    try:
        assert observed.get(timeout=3) is signal
        assert observed.get(timeout=3) is signal
        signal.cancel()
        assert finished.wait(2), errors
    finally:
        signal.cancel()
        worker.join(timeout=3)
    assert not worker.is_alive()
    assert not errors


def test_deep_research_continues_after_planning_and_research() -> None:
    from onyx.agents.events import AgentEvent

    llm = ScriptedLLM(
        [
            Delta(content="Plan"),
            tool_delta(THINK_TOOL_NAME, '{"reasoning":"Inspect"}'),
            tool_delta(GENERATE_REPORT_TOOL_NAME),
            Delta(content="Final report"),
        ],
        128000,
    )
    agent = DeepResearchAgent(
        None,
        ChatStateContainer(),
        [UserMessage(content="Research")],
        [],
        llm,
        len,
        None,
        "",
        ReasoningEffort.LOW,
        None,
        time.monotonic(),
        None,
        1,
        False,
        skip_clarification=True,
    )
    agent.run(max_turns=1)
    assert agent.phase == "research"
    assert agent.research_turns == 0
    signal = CancellationSignal()

    def pause(event: AgentEvent) -> None:
        if event.type == "turn_end" and agent.research_turns == 1:
            signal.cancel()

    agent.subscribe(pause)
    with pytest.raises(AgentCancelled):
        agent.run(max_turns=3, cancellation=signal)
    assert agent.research_turns == 1
    outcome = agent.run(max_turns=2)
    assert outcome.output.text == "Final report"
    assert agent.research_turns == 3
    assert len(llm.requests) == 4


def test_deep_research_normalizes_canonical_child_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from onyx.agents.runtime import ToolCallContext
    from onyx.llm.models import ToolResult

    monkeypatch.setattr(
        "onyx.deep_research.agent._get_research_agent_tool_id", lambda: 7
    )
    monkeypatch.setattr(
        "onyx.deep_research.agent.run_research_agent_call",
        lambda **_kwargs: ResearchAgentCallResult(
            intermediate_report="Original report", citation_mapping={}
        ),
    )
    llm = ScriptedLLM(
        [
            tool_delta(RESEARCH_AGENT_TOOL_NAME, '{"task":"facts"}'),
            Delta(content="Final"),
        ],
        128000,
    )
    agent = DeepResearchAgent(
        None,
        ChatStateContainer(),
        [UserMessage(content="Research")],
        [],
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

    def edit_report(_context: ToolCallContext, result: ToolResult) -> ToolResult:
        return result.model_copy(update={"content": "Edited report"})

    agent.hooks = agent.hooks.model_copy(update={"after_tool_call": edit_report})
    agent.run(max_turns=2)
    reports = [
        message for message in agent.output_messages if message.role == "tool_result"
    ]
    assert reports[0].text == "Edited report"


def test_cancelled_tool_return_does_not_emit_completion() -> None:
    signal = CancellationSignal()
    tool = MagicMock(spec=Tool)
    tool.name = "cancelled_tool"

    def finish_tool(**_kwargs: Placement | None) -> ToolResult:
        signal.cancel()
        return ToolResult(content="finished")

    tool.run.side_effect = finish_tool
    with cancellation_scope(signal), pytest.raises(AgentCancelled):
        run_tool_call(
            tool_call=kickoff(tool.name),
            tool=tool,
            message_history=[],
            user_memory_context=None,
            user_info=None,
            citation_mapping={},
            next_citation_num=1,
        )
    tool.emitter.emit.assert_not_called()
