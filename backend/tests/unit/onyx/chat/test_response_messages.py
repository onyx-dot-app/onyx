"""Saved messages retain identity, completion, and explicit answer selection."""

import pytest

from onyx.agents.events import AgentEndEvent, AgentEvent
from onyx.agents.execution_records import RunStatus
from onyx.agents.models import StepResult
from onyx.agents.runtime import Agent, Run
from onyx.chat.response import response_record, response_snapshot
from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.llm.models import AssistantMessage, GenerationRequest, TextContent
from tests.unit.onyx.agents.fakes import FakeModelClient, run_agent


def test_harness_selects_answer_and_message_ids_survive_restore() -> None:
    replies = iter(
        [
            AssistantMessage(content=[TextContent(text="Checking the context")]),
            AssistantMessage(content=[TextContent(text="The answer")]),
        ]
    )

    def after_step(result: StepResult) -> bool:
        return result.message.text != "The answer"

    agent = Agent(
        FakeModelClient(lambda _request, _signal: next(replies)), after_step=after_step
    )
    runs: list[Run] = []
    events: list[AgentEvent] = []
    run_agent(agent, max_steps=2, runs=runs, listener=events.append)
    snapshot = runs[0].snapshot()
    record = response_record(snapshot)
    assert record.answer_step_index == 1
    terminal = next(event for event in events if isinstance(event, AgentEndEvent))
    answer = snapshot.messages[1]
    assert isinstance(answer, AssistantMessage)
    assert terminal.answer_message_id == answer.id
    restored = response_snapshot(record)
    assert restored.messages == snapshot.messages
    assert restored.steps == snapshot.steps
    assert restored.answer_step_index == snapshot.answer_step_index
    assert snapshot.answer_step_index == 1


def test_empty_cancelled_generation_survives_storage_round_trip() -> None:
    def cancel(
        _request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        raise AgentCancelled()

    runs: list[Run] = []
    with pytest.raises(AgentCancelled):
        run_agent(Agent(FakeModelClient(cancel)), max_steps=1, runs=runs)
    snapshot = runs[0].snapshot()
    record = response_record(snapshot)
    assert record.answer_step_index is None
    assert len(record.messages) == 1
    assert record.steps[0].generation_status == RunStatus.CANCELLED
    assert response_snapshot(record).messages == snapshot.messages
