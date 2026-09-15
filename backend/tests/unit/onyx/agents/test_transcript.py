"""Transcript recording follows runtime order without retaining application objects."""

from collections.abc import Generator

import pytest
from pydantic import BaseModel

from onyx.agents.runtime import Agent, AgentContext, AgentHooks, ToolCallContext
from onyx.agents.tools import AgentTool
from onyx.agents.transcript import AgentTranscript
from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.llm.interfaces import GenerationContext
from onyx.llm.models import (
    AssistantMessage,
    GenerationEvent,
    GenerationRequest,
    TextContent,
    TextDeltaEvent,
    ToolCall,
    ToolResult,
    ToolResultMessage,
    UserMessage,
)
from tests.unit.onyx.agents.fakes import FakeModelClient


class ApplicationData(BaseModel):
    private_field: str = "application-only"


def test_result_order_hook_updates_and_application_data_exclusion() -> None:
    def finalize(_context: ToolCallContext, result: ToolResult) -> ToolResult:
        result.content = "updated " + str(result.content)
        return result

    tool = AgentTool(
        name="work",
        description="",
        parameters={},
        execute=lambda invocation: ToolResult(
            content=invocation.call_id, details=ApplicationData()
        ),
    )
    agent = Agent(
        FakeModelClient(
            lambda _context, _signal: AssistantMessage(
                content=[
                    ToolCall(id="a", name="work", arguments={}),
                    ToolCall(id="b", name="work", arguments={}),
                ]
            )
        ),
        context=AgentContext(tools=[tool]),
        hooks=AgentHooks(after_tool_call=finalize),
    )
    agent.run(max_steps=1)
    transcript = agent.snapshot()
    assert transcript and transcript.status == "limit"
    assert [
        message.content
        for message in transcript.messages
        if isinstance(message, ToolResultMessage)
    ] == ["updated a", "updated b"]
    canonical = transcript.transcript()
    serialized = canonical.model_dump_json()
    assert "application-only" not in serialized
    persisted = serialized.replace('"step_index":', '"turn":')
    assert AgentTranscript.model_validate_json(persisted) == canonical


@pytest.mark.parametrize("cancelled", [False, True])
def test_partial_run_keeps_input_and_replayable_output(cancelled: bool) -> None:
    signal = CancellationSignal()

    class PartialClient(FakeModelClient):
        def stream(
            self, request: GenerationRequest, context: GenerationContext | None = None
        ) -> Generator[GenerationEvent, None, None]:
            del request, context
            yield TextDeltaEvent(
                message=AssistantMessage(content=[TextContent(text="partial")]),
                content_index=0,
                text="partial",
            )
            if cancelled:
                signal.cancel()
                signal.check()
            raise ValueError("Generation failed")

    agent = Agent(
        PartialClient(
            lambda *_: AssistantMessage(content=[TextContent(text="unused")])
        ),
        context=AgentContext(output_metadata=ApplicationData()),
    )
    with pytest.raises(AgentCancelled if cancelled else ValueError):
        agent.run(
            max_steps=1,
            cancellation=signal,
            messages=[UserMessage(content="Question", metadata=ApplicationData())],
        )
    snapshot = agent.snapshot()
    assert snapshot is not None
    assert snapshot.status == ("cancelled" if cancelled else "error")
    assert [message.text for message in snapshot.input_messages] == ["Question"]
    assert snapshot.transcript().input_messages[0].metadata is None
    assert snapshot.messages[0].metadata == ApplicationData()
    message = snapshot.transcript().messages[0]
    assert message.metadata is None
    assert isinstance(message, AssistantMessage)
    assert message.text == "partial"
    assert message.stop_reason == ("aborted" if cancelled else "error")


def test_running_snapshot_records_unfinished_calls_without_inventing_results() -> None:
    snapshots = []

    def before_tool(_context: ToolCallContext) -> ToolResult:
        snapshots.append(agent.snapshot(cancelled=True))
        return ToolResult(content="finished")

    agent = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(
                content=[ToolCall(id="a", name="work", arguments={})]
            )
        ),
        context=AgentContext(
            tools=[
                AgentTool(
                    name="work",
                    description="",
                    parameters={},
                    execute=lambda _: ToolResult(content="unused"),
                )
            ]
        ),
        hooks=AgentHooks(before_tool_call=before_tool),
    )
    agent.run(max_steps=1)
    snapshot = snapshots[0]
    assert snapshot is not None and snapshot.status == "cancelled"
    assert len(snapshot.messages) == 1
    assert isinstance(snapshot.messages[0], AssistantMessage)
    assert snapshot.messages[0].tool_calls[0].id == "a"
    assert any(operation.tool_call_id == "a" for operation in snapshot.operations)


def test_successive_run_views_separate_history_input_and_output() -> None:
    replies = iter(["First answer", "Second answer"])
    history = [UserMessage(content="Earlier question")]
    agent = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(content=[TextContent(text=next(replies))])
        ),
        context=AgentContext(messages=history),
    )
    assert agent.snapshot() is None
    first_input = UserMessage(content="First question", metadata=ApplicationData())
    first = agent.run(max_steps=1, messages=[first_input])
    first_snapshot = agent.snapshot()
    assert first_snapshot is not None and first_snapshot.run_id == first.run_id
    assert first.output.text == "First answer"
    assert [message.text for message in first_snapshot.input_messages] == [
        "First question"
    ]
    assert [message.text for message in first_snapshot.messages] == ["First answer"]
    first_input.content = "Caller mutation"
    snapshot_input = first_snapshot.input_messages[0]
    assert isinstance(snapshot_input, UserMessage)
    snapshot_input.content = "Snapshot mutation"
    first.output.content.clear()
    first_record = agent.snapshot()
    assert first_record is not None
    assert first_record.input_messages[0].text == "First question"
    assert first_record.messages[0].text == "First answer"
    assert first_record.transcript().input_messages[0].metadata is None

    second = agent.run(max_steps=1, messages=[UserMessage(content="Second question")])
    second_snapshot = agent.snapshot()
    assert second_snapshot is not None and second_snapshot.run_id == second.run_id
    assert first.run_id != second.run_id
    assert [message.text for message in second_snapshot.input_messages] == [
        "Second question"
    ]
    assert [message.text for message in second_snapshot.messages] == ["Second answer"]
    assert [message.text for message in agent.context.messages] == [
        "Earlier question",
        "First question",
        "First answer",
        "Second question",
        "Second answer",
    ]
    assert first_record.messages[0].text == "First answer"
