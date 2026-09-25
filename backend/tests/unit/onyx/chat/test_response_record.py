"""Response capture preserves accepted output and excludes live application objects."""

from collections.abc import Generator

import pytest
from pydantic import BaseModel

from onyx.agents.models import AgentState, PreparedStep, RunState, ToolCallContext
from onyx.agents.runtime import Agent, Run, RunFailed
from onyx.agents.tools import AgentTool
from onyx.agents.transcript import RunStatus
from onyx.chat.models import ResponseRecord
from onyx.chat.response import response_record, response_snapshot
from onyx.chat.response_items import messages_from_items
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
    Usage,
    UserMessage,
)
from tests.unit.onyx.agents.fakes import FakeModelClient, run_agent


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
        tools=[tool],
        after_tool_call=finalize,
    )
    runs: list[Run] = []
    run_agent(agent, max_steps=1, runs=runs)
    transcript = runs[0].snapshot()
    assert transcript and transcript.status == "limit"
    assert [
        message.content
        for message in transcript.messages
        if isinstance(message, ToolResultMessage)
    ] == ["updated a", "updated b"]
    canonical = response_record(transcript)
    serialized = canonical.model_dump_json()
    assert "application-only" not in serialized
    assert ResponseRecord.model_validate_json(serialized) == canonical


@pytest.mark.parametrize("cancelled", [False, True])
def test_partial_run_keeps_input_and_replayable_output(cancelled: bool) -> None:
    signal = CancellationSignal()

    class PartialClient(FakeModelClient):
        def stream(
            self, request: GenerationRequest, context: GenerationContext | None = None
        ) -> Generator[GenerationEvent, None, None]:
            del request, context
            yield TextDeltaEvent(
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
        prepare_step=lambda _input: PreparedStep(output_metadata=ApplicationData()),
    )
    runs: list[Run] = []
    with pytest.raises(AgentCancelled if cancelled else RunFailed):
        run_agent(
            agent,
            runs=runs,
            max_steps=1,
            cancellation=signal,
            messages=[UserMessage(content="Question", metadata=ApplicationData())],
        )
    snapshot = runs[0].snapshot()
    assert snapshot is not None
    assert snapshot.status == ("cancelled" if cancelled else "error")
    assert [message.text for message in snapshot.input_messages] == ["Question"]
    assert response_record(snapshot).input_messages[0].metadata is None
    assert snapshot.messages[0].metadata == ApplicationData()
    message = messages_from_items(response_record(snapshot).items)[0]
    assert message.metadata is None
    assert isinstance(message, AssistantMessage)
    assert message.text == "partial"
    assert message.stop_reason == ("aborted" if cancelled else "error")


def test_running_snapshot_records_unfinished_calls_without_inventing_results() -> None:
    snapshots: list[RunState] = []
    runs: list[Run] = []

    def before_tool(_context: ToolCallContext) -> ToolResult:
        snapshots.append(runs[0].snapshot())
        return ToolResult(content="finished")

    agent = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(
                content=[ToolCall(id="a", name="work", arguments={})]
            )
        ),
        tools=[
            AgentTool(
                name="work",
                description="",
                parameters={},
                execute=lambda _: ToolResult(content="unused"),
            )
        ],
        before_tool_call=before_tool,
    )
    run_agent(agent, max_steps=1, runs=runs)
    snapshot = snapshots[0]
    assert snapshot is not None and snapshot.status == "running"
    assert len(snapshot.messages) == 1
    assert isinstance(snapshot.messages[0], AssistantMessage)
    assert snapshot.messages[0].tool_calls[0].id == "a"
    assert any(operation.tool_call_id == "a" for operation in snapshot.operations)


def test_run_record_is_isolated_from_caller_and_snapshot_mutations() -> None:
    agent = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(content=[TextContent(text="First answer")])
        ),
        state=AgentState(messages=[UserMessage(content="Earlier question")]),
    )
    runs: list[Run] = []
    first_input = UserMessage(content="First question", metadata=ApplicationData())
    first = run_agent(agent, runs=runs, max_steps=1, messages=[first_input])
    first_snapshot = runs[0].snapshot()
    assert first_snapshot is not None and first_snapshot.run_id == first.run_id
    assert [message.text for message in first_snapshot.input_messages] == [
        "First question"
    ]
    assert [message.text for message in first_snapshot.messages] == ["First answer"]
    first_input.content = "Caller mutation"
    snapshot_input = first_snapshot.input_messages[0]
    assert isinstance(snapshot_input, UserMessage)
    snapshot_input.content = "Snapshot mutation"
    first.output.content.clear()
    first_record = runs[0].snapshot()
    assert first_record is not None
    assert first_record.input_messages[0].text == "First question"
    assert first_record.messages[0].text == "First answer"
    assert response_record(first_record).input_messages[0].metadata is None


def test_captured_and_restored_usage_is_isolated_from_mutation() -> None:
    snapshot = RunState(
        run_id="run",
        status=RunStatus.COMPLETE,
        messages=[
            AssistantMessage(
                content=[TextContent(text="Answer")],
                usage=Usage(
                    completion_tokens=3,
                    prompt_tokens=7,
                    total_tokens=10,
                    cache_creation_input_tokens=0,
                    cache_read_input_tokens=0,
                ),
            )
        ],
    )
    record = response_record(snapshot)
    restored = response_snapshot(record)
    source_message = snapshot.messages[0]
    restored_message = restored.messages[0]
    assert (
        isinstance(source_message, AssistantMessage)
        and source_message.usage is not None
    )
    assert (
        isinstance(restored_message, AssistantMessage)
        and restored_message.usage is not None
    )
    source_message.usage.total_tokens = 999
    restored_message.usage.total_tokens = 888
    saved_message = messages_from_items(record.items)[0]
    assert (
        isinstance(saved_message, AssistantMessage) and saved_message.usage is not None
    )
    assert saved_message.usage.total_tokens == 10
