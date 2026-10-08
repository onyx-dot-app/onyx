"""Grouped retrieval preserves call identities, ordering, hooks, and cancellation."""

import threading
from copy import deepcopy
from functools import partial
from unittest.mock import MagicMock, patch

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
    ToolDefinition,
    ToolResult,
    ToolResultMessage,
)
from onyx.tools.interface import Tool, ToolContext, merge_tool_arguments
from onyx.tools.tool_implementations.open_url.open_url_tool import OpenURLTool
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool
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
                definition=ToolDefinition(
                    name="search", description="Search", parameters={}
                ),
                execute=execute,
                execution_mode=mode,
                merge_arguments=partial(merge_tool_arguments, field="queries"),
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
                definition=ToolDefinition(
                    name="search", description="Search", parameters={}
                ),
                execute=execute,
                merge_arguments=partial(merge_tool_arguments, field="queries"),
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
                definition=ToolDefinition(
                    name="search", description="Search", parameters={}
                ),
                execute=execute,
                merge_arguments=partial(merge_tool_arguments, field="queries"),
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
        definition=ToolDefinition(name="search", description="Search", parameters={}),
        execute=execute,
        merge_arguments=partial(merge_tool_arguments, field="queries"),
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
                definition=ToolDefinition(
                    name="search", description="Search", parameters={}
                ),
                execute=execute,
                execution_mode=ToolExecutionMode.SEQUENTIAL,
                merge_arguments=partial(merge_tool_arguments, field="queries"),
            ),
            AgentTool(
                definition=ToolDefinition(
                    name="other", description="Other", parameters={}
                ),
                execute=execute,
            ),
        ],
    ).start(max_steps=2)
    run.result(timeout=10)
    assert run.wait_for_idle(timeout=10)
    assert executions == ["a", "middle", "b"]


@pytest.mark.parametrize(
    "kind, field",
    [("internal_search", "queries"), ("web_search", "queries"), ("open_url", "urls")],
)
def test_real_retrieval_bindings_merge_their_public_argument(
    kind: str, field: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool: Tool
    if kind == "internal_search":
        tool = SearchTool(
            tool_id=1,
            user=MagicMock(),
            persona_search_info=MagicMock(document_set_names=[]),
            llm=MagicMock(),
            document_index=MagicMock(),
            user_selected_filters=None,
            project_id_filter=None,
        )
    elif kind == "open_url":
        tool = OpenURLTool(
            tool_id=1,
            user=MagicMock(),
            document_index=MagicMock(),
            web_fetch_disabled=True,
        )
    else:
        module = "onyx.tools.tool_implementations.web_search.web_search_tool"
        provider = MagicMock(provider_type="brave", config={})
        with (
            patch(f"{module}.get_session_with_current_tenant"),
            patch(f"{module}.fetch_active_web_search_provider", return_value=provider),
            patch(f"{module}.build_search_provider_from_config"),
        ):
            tool = WebSearchTool(tool_id=1)
    executions: list[dict[str, JsonValue]] = []

    def execute(invocation: ToolInvocation, _context: ToolContext) -> ToolResult:
        executions.append(invocation.arguments)
        return ToolResult(content="found")

    monkeypatch.setattr(tool, "_run", execute)
    calls = [
        ToolCall(id=value, name=kind, arguments={field: [value]})
        for value in ("first", "second")
    ]
    replies = iter(
        [
            AssistantMessage(content=calls),
            AssistantMessage(content=[TextContent(text="done")]),
        ]
    )
    run = Agent(
        FakeModelClient(lambda *_: next(replies)),
        tools=[tool.bind(lambda: ToolContext())],
    ).start(max_steps=2)
    assert run.result(timeout=5).output.text == "done"
    assert run.wait_for_idle(5)
    assert executions == [{field: ["first", "second"]}]
    assert [
        message.tool_call_id
        for message in run.snapshot().messages
        if isinstance(message, ToolResultMessage)
    ] == ["first", "second"]


@pytest.mark.parametrize(
    "first",
    [
        {},
        {"queries": []},
        {"queries": "single"},
        {"queries": [1]},
        {"queries": ["a"], "filter": "private"},
    ],
)
def test_rejected_merges_keep_original_calls_and_arguments(
    first: dict[str, JsonValue],
) -> None:
    executions: list[tuple[str, dict[str, JsonValue]]] = []
    second: dict[str, JsonValue] = {"queries": ["b"]}
    expected = deepcopy([("first", first), ("second", second)])
    calls = [
        ToolCall(id="first", name="search", arguments=first),
        ToolCall(id="second", name="search", arguments=second),
    ]
    replies = iter(
        [
            AssistantMessage(content=calls),
            AssistantMessage(content=[TextContent(text="done")]),
        ]
    )

    def execute(invocation: ToolInvocation) -> ToolResult:
        executions.append((invocation.call_id, invocation.arguments))
        return ToolResult(content=invocation.call_id)

    tool = AgentTool(
        definition=ToolDefinition(name="search", description="", parameters={}),
        execute=execute,
        execution_mode=ToolExecutionMode.SEQUENTIAL,
        merge_arguments=partial(merge_tool_arguments, field="queries"),
    )
    run = Agent(FakeModelClient(lambda *_: next(replies)), tools=[tool]).start(
        max_steps=2
    )
    run.result(timeout=5)
    assert run.wait_for_idle(5)
    assert executions == expected
    assert [
        (message.tool_call_id, message.text)
        for message in run.snapshot().messages
        if isinstance(message, ToolResultMessage)
    ] == [("first", "first"), ("second", "second")]
