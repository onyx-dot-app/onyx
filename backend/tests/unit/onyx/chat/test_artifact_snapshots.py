"""Accepted artifacts survive cancellation of their parent or sibling operation."""

import asyncio
from queue import Queue
from threading import Event

import pytest

from onyx.agents.coordination import AgentCoordinator
from onyx.agents.events import AgentEvent
from onyx.agents.runtime import Agent, Run
from onyx.agents.tools import AgentTool, ToolInvocation
from onyx.chat.emitter import Emitter
from onyx.chat.presentation import ResponsePresenter, project_response
from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.llm.models import AssistantMessage, ToolCall, ToolResult
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.tools.models import PythonExecutionFile, PythonToolRichResponse
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
        tools=[
            AgentTool(name="write", description="", parameters={}, execute=write),
            AgentTool(name="wait", description="", parameters={}, execute=wait),
        ],
    )

    def on_event(event: AgentEvent) -> None:
        if event.type == "tool_end" and event.tool_call.id == "file":
            accepted.set()

    if child_run:

        async def research(invocation: ToolInvocation) -> ToolResult:
            submission = await invocation.agents.spawn_agent(
                worker,
                name="research",
                description="Research",
                max_steps=1,
                messages=[],
            )
            result = await invocation.agents.wait_run(submission.run_id)
            assert result is not None
            return ToolResult(content=result.output.text)

        agent = Agent(
            FakeModelClient(
                lambda _request, _signal: AssistantMessage(
                    content=[ToolCall(id="parent", name="research", arguments={})]
                )
            ),
            tools=[
                AgentTool(
                    name="research",
                    description="",
                    parameters={},
                    execute_async=research,
                )
            ],
        )
    else:
        agent = worker
    signal = CancellationSignal()

    async def exercise() -> Run:
        coordinator = AgentCoordinator() if child_run else None
        run = agent.start(max_steps=2, cancellation=signal, coordinator=coordinator)
        run.subscribe(on_event)
        if render:
            run.subscribe(
                ResponsePresenter(
                    Emitter(Queue[Packet]().put_nowait, response_id=42)
                ).consume
            )
        try:
            async with asyncio.timeout(5):
                while not accepted.is_set():
                    await asyncio.sleep(0.01)
            signal.cancel()
            with pytest.raises(AgentCancelled):
                await run.wait(timeout=2)
            assert not await run.wait_for_idle(timeout=0)
        finally:
            release.set()
            assert await run.wait_for_idle(timeout=3)
            if coordinator is not None:
                assert await coordinator.close(timeout=3)
        return run

    run = asyncio.run(exercise())
    for _ in range(2):
        snapshot = project_response(
            run.snapshot(),
            response_id=42,
            tool_ids={"write": 1, "wait": 2, "research": 7},
        )
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
            assert snapshot.transcript.child_runs
        file_record.generated_files = []
