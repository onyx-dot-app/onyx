"""Snapshots preserve complete state changes while tools and callbacks run."""

import threading
from contextlib import AbstractContextManager
from types import TracebackType
from unittest.mock import patch

import pytest

from onyx.agents.execution_records import RunStatus
from onyx.agents.models import PreparedStep, RunState, StepInput, ToolCallContext
from onyx.agents.runtime import Agent, Run
from onyx.agents.tools import AgentTool, ToolInvocation
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.models import (
    AssistantMessage,
    GenerationRequest,
    TextContent,
    ToolCall,
    ToolResult,
    ToolResultMessage,
)
from tests.unit.onyx.agents.fakes import FakeModelClient


def test_snapshot_can_omit_children_before_copying() -> None:
    run = Run.from_snapshot(
        RunState(
            run_id="parent",
            agent_id="agent",
            status=RunStatus.COMPLETE,
            messages=[
                AssistantMessage(
                    content=[ToolCall(id="call", name="lookup", arguments={"q": "old"})]
                )
            ],
            child_runs=[
                RunState(run_id="child", status=RunStatus.COMPLETE, messages=[])
            ],
        )
    )
    with patch.object(
        RunState, "__deepcopy__", autospec=True, side_effect=RunState.__deepcopy__
    ) as copy:
        snapshot = run.snapshot(include_children=False)
    assert [call.args[0].run_id for call in copy.call_args_list] == ["parent"]
    assert snapshot.child_runs == []
    message = snapshot.messages[0]
    assert isinstance(message, AssistantMessage)
    message.tool_calls[0].arguments["q"] = "new"
    full = run.snapshot()
    assert [child.run_id for child in full.child_runs] == ["child"]
    original = full.messages[0]
    assert isinstance(original, AssistantMessage)
    assert original.tool_calls[0].arguments == {"q": "old"}


class SnapshotLock(AbstractContextManager[None]):
    """Capture the state exposed at each release of the run lock."""

    def __init__(self, record: RunState) -> None:
        self._lock = threading.RLock()
        self.record = record
        self.snapshots: list[RunState] = []

    def __enter__(self) -> None:
        self._lock.acquire()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            self.snapshots.append(self.record.model_copy(deep=True))
        finally:
            self._lock.release()


def test_message_and_operation_updates_are_visible_together(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preparing = threading.Event()
    release = threading.Event()

    def execute(_invocation: ToolInvocation) -> ToolResult:
        return ToolResult(content="raw")

    tool = AgentTool(name="lookup", description="", parameters={}, execute=execute)

    def prepare(_input: StepInput) -> PreparedStep:
        preparing.set()
        assert release.wait(3)
        return PreparedStep(tools=[tool])

    def generate(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        if any(isinstance(message, ToolResultMessage) for message in request.messages):
            return AssistantMessage(content=[TextContent(text="done")])
        return AssistantMessage(
            content=[ToolCall(id="call", name="lookup", arguments={})]
        )

    def enrich(_context: ToolCallContext, result: ToolResult) -> ToolResult:
        result.content = "rejected"
        result.is_error = True
        return result

    run = Agent(
        FakeModelClient(generate), prepare_step=prepare, after_tool_call=enrich
    ).start(max_steps=2)
    try:
        assert preparing.wait(3)
        lock = SnapshotLock(run._state)
        monkeypatch.setattr(run, "_lock", lock)
        release.set()
        run.result(timeout=3)
    finally:
        release.set()
        run.cancel()
        assert run.wait_for_idle(3)

    assert any(
        message.text == "rejected"
        for snapshot in lock.snapshots
        for message in snapshot.messages
    )
    for snapshot in lock.snapshots:
        for index, message in enumerate(snapshot.messages):
            if isinstance(message, AssistantMessage):
                assert any(
                    operation.message_index == index and operation.tool_call_id is None
                    for operation in snapshot.operations
                )
            elif isinstance(message, ToolResultMessage):
                operation = next(
                    operation
                    for operation in snapshot.operations
                    if operation.tool_call_id == message.tool_call_id
                )
                assert operation.status == (
                    RunStatus.ERROR if message.is_error else RunStatus.COMPLETE
                )
        for operation in snapshot.operations:
            source = snapshot.messages[operation.message_index]
            assert isinstance(source, AssistantMessage)
            if operation.tool_call_id is not None:
                assert operation.tool_call_id in {call.id for call in source.tool_calls}


def test_tool_result_is_retained_while_finalization_blocks_the_next_step() -> None:
    finalizing = threading.Event()
    release = threading.Event()
    next_generation = threading.Event()

    def generate(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        if any(isinstance(message, ToolResultMessage) for message in request.messages):
            next_generation.set()
            assert request.messages[-1].text == "final"
            return AssistantMessage(content=[TextContent(text="done")])
        return AssistantMessage(
            content=[ToolCall(id="call", name="lookup", arguments={})]
        )

    def enrich(_context: ToolCallContext, result: ToolResult) -> ToolResult:
        finalizing.set()
        assert release.wait(3)
        result.content = "final"
        return result

    agent = Agent(
        FakeModelClient(generate),
        tools=[
            AgentTool(
                name="lookup",
                description="",
                parameters={},
                execute=lambda _invocation: ToolResult(content="raw"),
            )
        ],
        after_tool_call=enrich,
    )
    run = agent.start(max_steps=2)
    try:
        assert finalizing.wait(3)
        snapshot = run.snapshot()
        assert snapshot.messages[-1].text == "raw"
        assert snapshot.operations[-1].status == RunStatus.COMPLETE
        assert not next_generation.is_set()
        assert not run.wait_for_idle(0)
        release.set()
        assert run.result(timeout=3).output.text == "done"
    finally:
        release.set()
        run.cancel()
        assert run.wait_for_idle(3)
    assert next_generation.is_set()
    assert run.snapshot().messages[1].text == "final"
