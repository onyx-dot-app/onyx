"""Accepted response items retain identity, completion, and explicit answer selection."""

import pytest

from onyx.agents.events import AgentEndEvent, AgentEvent, MessageUpdateEvent
from onyx.agents.items import (
    ResponseGeneration,
    ResponseText,
    TextPurpose,
    answer_message_index,
    build_response_items,
    messages_from_items,
)
from onyx.agents.models import StepResult
from onyx.agents.runtime import Agent, Run
from onyx.agents.transcript import RunStatus
from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.llm.models import AssistantMessage, GenerationRequest, TextContent
from tests.unit.onyx.agents.fakes import FakeModelClient, run_agent


def test_harness_selects_answer_and_item_ids_survive_restore() -> None:
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
    text_items = [
        item.content
        for item in snapshot.items
        if isinstance(item.content, ResponseText)
    ]
    assert [item.purpose for item in text_items] == [
        TextPurpose.COMMENTARY,
        TextPurpose.ANSWER,
    ]
    live_items = [
        item
        for event in events
        if isinstance(event, MessageUpdateEvent)
        for item in event.items
    ]
    assert {item.id for item in live_items} == {item.id for item in snapshot.items}
    assert all(
        item.content.purpose == TextPurpose.COMMENTARY
        for item in live_items
        if isinstance(item.content, ResponseText)
    )
    terminal = next(event for event in events if isinstance(event, AgentEndEvent))
    answer = snapshot.messages[1]
    assert isinstance(answer, AssistantMessage)
    assert terminal.answer_message_id == answer.id
    restored = messages_from_items(snapshot.items)
    assert (
        build_response_items(
            "different-execution-id",
            restored,
            snapshot.operations,
            answer_message_index=answer_message_index(snapshot.items),
        )
        == snapshot.items
    )
    assert snapshot.answer_message_index == 1


def test_empty_cancelled_generation_survives_item_round_trip() -> None:
    def cancel(
        _request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        raise AgentCancelled()

    runs: list[Run] = []
    with pytest.raises(AgentCancelled):
        run_agent(Agent(FakeModelClient(cancel)), max_steps=1, runs=runs)
    snapshot = runs[0].snapshot()
    assert snapshot.answer_message_index is None
    assert len(snapshot.items) == 1
    boundary = snapshot.items[0].content
    assert isinstance(boundary, ResponseGeneration)
    assert boundary.outcome.status == RunStatus.CANCELLED
    assert messages_from_items(snapshot.items) == snapshot.messages
