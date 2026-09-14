"""Transcript recording follows runtime order without retaining application objects."""

import pytest
from pydantic import BaseModel

from onyx.agents.events import AgentEvent
from onyx.agents.runtime import Agent, AgentContext, AgentHooks, TurnResult
from onyx.agents.tools import AgentTool
from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.llm.litellm_models import Delta
from onyx.llm.models import (
    AssistantMessage,
    ToolCall,
    ToolResult,
    ToolResultMessage,
)
from tests.unit.onyx.agents.fakes import FakeModelClient, ScriptedLLM


class ApplicationData(BaseModel):
    private_field: str = "application-only"


def test_result_order_hook_updates_and_application_data_exclusion() -> None:
    def after_turn(turn: TurnResult) -> None:
        for result in turn.tool_results:
            result.content = "updated " + str(result.content)

    tool = AgentTool(
        name="work",
        description="",
        parameters={},
        execute=lambda call_id, _args, _signal, _update: ToolResult(
            content=call_id, details=ApplicationData()
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
        hooks=AgentHooks(after_turn=after_turn),
    )
    agent.run(max_turns=1)
    transcript = agent.snapshot()
    assert transcript and transcript.status == "limit"
    assert [
        message.content
        for message in transcript.messages
        if isinstance(message, ToolResultMessage)
    ] == ["updated a", "updated b"]
    assert "application-only" not in transcript.model_dump_json()


def test_partial_cancellation_is_replayable_without_rendering() -> None:
    signal = CancellationSignal()
    agent = Agent(ScriptedLLM([Delta(content="partial")]))

    def stop(event: AgentEvent) -> None:
        if (
            event.type == "message_update"
            and event.generation_event.type == "text_delta"
        ):
            signal.cancel()

    agent.subscribe(stop)
    with pytest.raises(AgentCancelled):
        agent.run(max_turns=1, cancellation=signal)
    transcript = agent.snapshot()
    assert transcript and transcript.status == "cancelled"
    message = transcript.messages[0]
    assert isinstance(message, AssistantMessage)
    assert message.text == "partial" and message.stop_reason == "aborted"


def test_stop_snapshot_pairs_unfinished_calls() -> None:
    agent = Agent(
        FakeModelClient(
            lambda _context, _signal: AssistantMessage(
                content=[ToolCall(id="a", name="work", arguments={})]
            )
        ),
    )
    snapshots = []

    def observe(event: AgentEvent) -> None:
        if event.type == "message_end":
            snapshots.append(agent.snapshot(cancelled=True))

    agent.subscribe(observe)
    agent.run(max_turns=1)
    transcript = snapshots[0]
    assert transcript and transcript.status == "cancelled"
    assert isinstance(transcript.messages[-1], ToolResultMessage)
    assert transcript.messages[-1].tool_call_id == "a"
    assert transcript.messages[-1].is_error
