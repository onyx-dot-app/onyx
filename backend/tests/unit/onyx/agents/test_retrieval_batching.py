"""Grouped retrieval preserves call identities, ordering, hooks, and cancellation."""

import threading
from functools import partial

import pytest
from pydantic import JsonValue

from onyx.agents.events import AgentEvent, ToolEndEvent, ToolStartEvent, ToolUpdateEvent
from onyx.agents.models import ToolCallContext
from onyx.agents.runtime import Agent
from onyx.agents.tools import AgentTool, ToolExecutionMode, ToolInvocation, ToolProgress
from onyx.llm.cancellation import AgentCancelled
from onyx.llm.models import (
    AssistantMessage,
    TextContent,
    ToolCall,
    ToolResult,
    ToolResultMessage,
)
from onyx.tools.tool_runner import _merge_tool_arguments
from tests.unit.onyx.agents.fakes import FakeModelClient


@pytest.mark.parametrize("mode", list(ToolExecutionMode))
@pytest.mark.parametrize("failed", [False, True])
def test_compatible_calls_share_execution_and_keep_each_result(
    mode: ToolExecutionMode, failed: bool
) -> None:
    executions: list[dict[str, JsonValue]] = []
    events: list[AgentEvent] = []
    calls = [
        ToolCall(id="a", name="search", arguments={"queries": ["a"], "filter": "x"}),
        ToolCall(
            id="b", name="search", arguments={"queries": ["b", "a"], "filter": "x"}
        ),
        ToolCall(id="c", name="search", arguments={"queries": ["c"], "filter": "y"}),
    ]
    replies = iter(
        [
            AssistantMessage(content=calls),
            AssistantMessage(content=[TextContent(text="done")]),
        ]
    )

    def execute(invocation: ToolInvocation) -> ToolResult:
        executions.append(invocation.arguments)
        invocation.update(ToolProgress(content="retrieving"))
        return ToolResult(content=str(invocation.arguments), is_error=failed)

    run = Agent(
        FakeModelClient(lambda *_: next(replies)),
        tools=[
            AgentTool(
                name="search",
                description="Search",
                parameters={},
                execute=execute,
                execution_mode=mode,
                merge_arguments=partial(_merge_tool_arguments, field="queries"),
            )
        ],
    ).start(max_steps=2, on_event=events.append)
    run.result(timeout=10)
    run.wait_for_idle(timeout=10)
    assert len(executions) == 2
    assert {"queries": ["a", "b", "a"], "filter": "x"} in executions
    assert {"queries": ["c"], "filter": "y"} in executions
    results = [
        item for item in run.snapshot().messages if isinstance(item, ToolResultMessage)
    ]
    assert [item.tool_call_id for item in results] == ["a", "b", "c"]
    assert results[0].content == results[1].content
    assert all(item.is_error == failed for item in results)
    for event_type in (ToolStartEvent, ToolEndEvent):
        assert {
            event.tool_call.id for event in events if isinstance(event, event_type)
        } == {"a", "b", "c"}
    assert {
        event.tool_call.id for event in events if isinstance(event, ToolUpdateEvent)
    } == {"a", "b", "c"}
    assistant = run.snapshot().messages[0]
    assert isinstance(assistant, AssistantMessage)
    assert assistant.tool_calls == calls


def test_before_tool_hook_keeps_individual_calls() -> None:
    executions: list[str] = []
    checked: list[str] = []
    replies = iter(
        [
            AssistantMessage(
                content=[
                    ToolCall(id=key, name="search", arguments={"queries": [key]})
                    for key in ("a", "b")
                ]
            ),
            AssistantMessage(content=[TextContent(text="done")]),
        ]
    )

    def before(context: ToolCallContext) -> ToolResult | None:
        checked.append(context.call.id)
        return (
            ToolResult(content="denied", is_error=True)
            if context.call.id == "a"
            else None
        )

    def execute(invocation: ToolInvocation) -> ToolResult:
        executions.append(invocation.call_id)
        return ToolResult(content="found")

    run = Agent(
        FakeModelClient(lambda *_: next(replies)),
        before_tool_call=before,
        tools=[
            AgentTool(
                name="search",
                description="Search",
                parameters={},
                execute=execute,
                merge_arguments=partial(_merge_tool_arguments, field="queries"),
            )
        ],
    ).start(max_steps=2)
    run.result(timeout=10)
    run.wait_for_idle(timeout=10)
    assert set(checked) == {"a", "b"}
    assert executions == ["b"]


def test_cancellation_reaches_shared_retrieval() -> None:
    started = threading.Event()
    cancelled = threading.Event()
    executions: list[str] = []

    def execute(invocation: ToolInvocation) -> ToolResult:
        executions.append(invocation.call_id)
        with invocation.cancellation.on_cancel(cancelled.set):
            started.set()
            if not cancelled.wait(10):
                raise TimeoutError("Cancellation was not delivered")
        invocation.cancellation.check()
        return ToolResult(content="unreachable")

    run = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(
                content=[
                    ToolCall(id=key, name="search", arguments={"queries": [key]})
                    for key in ("a", "b")
                ]
            )
        ),
        tools=[
            AgentTool(
                name="search",
                description="Search",
                parameters={},
                execute=execute,
                merge_arguments=partial(_merge_tool_arguments, field="queries"),
            )
        ],
    ).start(max_steps=2)
    try:
        assert started.wait(10)
    finally:
        run.cancel()
    with pytest.raises(AgentCancelled):
        run.result(timeout=10)
    run.wait_for_idle(timeout=10)
    assert cancelled.is_set()
    assert executions == ["a"]
    assert not any(
        isinstance(item, ToolResultMessage) for item in run.snapshot().messages
    )


def test_suspended_batch_restores_results_without_retrieval_reexecution() -> None:
    entered = threading.Event()
    release = threading.Event()
    executions: list[str] = []

    def execute(invocation: ToolInvocation) -> ToolResult:
        executions.append(invocation.call_id)
        entered.set()
        if not release.wait(10):
            raise TimeoutError("Retrieval was not released")
        return ToolResult(content="shared evidence")

    tool = AgentTool(
        name="search",
        description="Search",
        parameters={},
        execute=execute,
        merge_arguments=partial(_merge_tool_arguments, field="queries"),
    )
    run = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(
                content=[
                    ToolCall(id=key, name="search", arguments={"queries": [key]})
                    for key in ("a", "b")
                ]
            )
        ),
        tools=[tool],
    ).start(max_steps=2)
    try:
        assert entered.wait(10)
        run.suspend()
    finally:
        release.set()
    assert run.wait_for_idle(timeout=10)
    checkpoint = run.handoff()
    results = [
        item
        for item in checkpoint.run_state.messages
        if isinstance(item, ToolResultMessage)
    ]
    assert [item.tool_call_id for item in results] == ["a", "b"]
    restored = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(content=[TextContent(text="done")])
        ),
        tools=[tool],
        state=checkpoint.agent_state,
        agent_id=checkpoint.run_state.agent_id,
    ).resume(checkpoint.run_state)
    restored.result(timeout=10)
    assert restored.wait_for_idle(timeout=10)
    assert executions == ["a"]


def test_sequential_batching_does_not_cross_another_tool() -> None:
    executions: list[str] = []
    replies = iter(
        [
            AssistantMessage(
                content=[
                    ToolCall(id="a", name="search", arguments={"queries": ["a"]}),
                    ToolCall(id="middle", name="other", arguments={}),
                    ToolCall(id="b", name="search", arguments={"queries": ["b"]}),
                ]
            ),
            AssistantMessage(content=[TextContent(text="done")]),
        ]
    )

    def execute(invocation: ToolInvocation) -> ToolResult:
        executions.append(invocation.call_id)
        return ToolResult(content="done")

    run = Agent(
        FakeModelClient(lambda *_: next(replies)),
        tools=[
            AgentTool(
                name="search",
                description="Search",
                parameters={},
                execute=execute,
                execution_mode=ToolExecutionMode.SEQUENTIAL,
                merge_arguments=partial(_merge_tool_arguments, field="queries"),
            ),
            AgentTool(
                name="other", description="Other", parameters={}, execute=execute
            ),
        ],
    ).start(max_steps=2)
    run.result(timeout=10)
    assert run.wait_for_idle(timeout=10)
    assert executions == ["a", "middle", "b"]
