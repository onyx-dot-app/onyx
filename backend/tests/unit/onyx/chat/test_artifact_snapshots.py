"""Accepted artifacts survive cancellation of their parent or sibling operation."""

from queue import Queue
from threading import Event

import pytest

from onyx.agents.events import AgentEvent
from onyx.agents.runtime import Agent, AgentContext
from onyx.agents.tools import AgentTool, ToolInvocation
from onyx.chat.emitter import Emitter
from onyx.chat.presentation import ResponseBinding, attach_response
from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.llm.models import AssistantMessage, ToolCall, ToolResult
from onyx.tools.models import PythonExecutionFile, PythonToolRichResponse
from onyx.utils.threadpool_concurrency import ContextThreadPoolExecutor
from tests.unit.onyx.agents.fakes import FakeModelClient


@pytest.mark.parametrize("child_run", [False, True])
@pytest.mark.parametrize("render", [False, True])
def test_stop_preserves_accepted_file_and_unfinished_parent(
    child_run: bool, render: bool
) -> None:
    accepted = Event()
    release = Event()
    generated = PythonExecutionFile(
        filename="result.csv", file_link="/files/result.csv"
    )

    def write(_invocation: ToolInvocation) -> ToolResult:
        return ToolResult(
            content="Created result.csv",
            details=PythonToolRichResponse(generated_files=[generated]),
        )

    def wait(invocation: ToolInvocation) -> ToolResult:
        assert release.wait(5)
        invocation.cancellation.check()
        return ToolResult(content="Finished waiting")

    worker = Agent(
        FakeModelClient(
            lambda _request, _signal: AssistantMessage(
                content=[
                    ToolCall(id="file", name="write", arguments={}),
                    ToolCall(id="pending", name="wait", arguments={}),
                ]
            )
        ),
        context=AgentContext(
            tools=[
                AgentTool(name="write", description="", parameters={}, execute=write),
                AgentTool(name="wait", description="", parameters={}, execute=wait),
            ]
        ),
    )

    def on_event(event: AgentEvent) -> None:
        if event.type == "tool_end" and event.tool_call.id == "file":
            accepted.set()

    worker.subscribe(on_event)
    if child_run:

        async def research(invocation: ToolInvocation) -> ToolResult:
            result = await invocation.run_child(worker, max_steps=1)
            return ToolResult(content=result.output.text)

        agent = Agent(
            FakeModelClient(
                lambda _request, _signal: AssistantMessage(
                    content=[ToolCall(id="parent", name="research", arguments={})]
                )
            ),
            context=AgentContext(
                tools=[
                    AgentTool(
                        name="research",
                        description="",
                        parameters={},
                        execute_async=research,
                    )
                ]
            ),
        )
    else:
        agent = worker
    state = ResponseBinding()
    attach_response(
        agent,
        state,
        Emitter(Queue(), response_id=42) if render else None,
        response_id=42,
        tool_ids={"write": 1, "wait": 2, "research": 7},
    )
    signal = CancellationSignal()
    with ContextThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(lambda: agent.run(max_steps=2, cancellation=signal))
        try:
            assert accepted.wait(5)
            signal.cancel()
            with pytest.raises(AgentCancelled):
                future.result(timeout=5)
        finally:
            release.set()
    for _ in range(2):
        snapshot = state.snapshot(cancelled=True)
        assert snapshot.transcript is not None
        file_record = next(
            record for record in snapshot.tool_calls if record.tool_call_id == "file"
        )
        assert file_record.generated_files == [generated]
        assert file_record.tool_call_response == "Created result.csv"
        if child_run:
            parent = next(
                record
                for record in snapshot.tool_calls
                if record.tool_call_id == "parent"
            )
            assert file_record.parent_execution_key == parent.execution_key
            assert parent.tool_call_response == ""
            assert snapshot.transcript.children
        file_record.generated_files = []
