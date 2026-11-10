"""Incoming instructions respect execution boundaries, budgets, and queue ownership."""

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Literal

import pytest

from onyx.agents.agent_coordination import AgentCoordinator
from onyx.agents.events import AgentEvent, MessageStartEvent
from onyx.agents.models import (
    AgentInfo,
    AgentMessageRequest,
    AgentState,
    InputMessageMetadata,
    InputSource,
    MessageDelivery,
    PreparedStep,
    RunState,
    RunStatus,
    StepInput,
)
from onyx.agents.runtime import Agent, Run
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.interfaces import GenerationContext
from onyx.llm.models import (
    AssistantMessage,
    GenerationRequest,
    TextContent,
    UserMessage,
)
from onyx.tracing.flows import LLMFlow
from tests.unit.onyx.agents.fakes import (
    FakeAgentDirectory,
    FakeModelClient,
)


def test_send_binding_preserves_the_run_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered, release_generation = threading.Event(), threading.Event()
    staged, release_binding = threading.Event(), threading.Event()
    restarted = threading.Event()
    requests: list[list[str]] = []

    def generate(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        requests.append([message.text for message in request.messages])
        if len(requests) == 1:
            entered.set()
            assert release_generation.wait(3)
        elif len(requests) == 2:
            restarted.set()
        return AssistantMessage(content=[TextContent(text="answer")])

    owner = AgentCoordinator()
    parent = Agent(
        FakeModelClient(lambda *_: AssistantMessage()),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
    )
    parent_run = parent.start(max_steps=1, coordinator=owner, background=False)
    child = Agent(
        FakeModelClient(generate),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
    )
    owner.register_child(
        child,
        parent_id=parent.id,
        name="child",
        description="",
        restoration_config=None,
    )
    initial = child.start(max_steps=1, coordinator=owner, parent_run_id=parent_run.id)

    def submit(message_id: str) -> None:
        owner.submit_message(
            AgentMessageRequest(
                agent_id=child.id,
                parent_id=parent.id,
                message=UserMessage(id=message_id, content=message_id),
                delivery=MessageDelivery.SEND,
                max_steps=1,
                parent_run_id=parent_run.id,
                parent_message_id="parent:0",
                parent_tool_call_id=message_id,
            )
        )

    send = Run.send_message

    def stage(run: Run, message: UserMessage) -> bool:
        accepted = send(run, message)
        if message.id == "steer":
            staged.set()
            assert release_binding.wait(3)
        return accepted

    monkeypatch.setattr(Run, "send_message", stage)
    with ThreadPoolExecutor(max_workers=2) as executor:
        try:
            assert entered.wait(3)
            submission = executor.submit(submit, "steer")
            assert staged.wait(3)
            release_generation.set()
            assert not restarted.wait(0.1)
            release_binding.set()
            submission.result(3)
            assert initial.wait_for_idle(3)
            assert initial.status == RunStatus.LIMIT
            assert len(requests) == 1

        finally:
            release_generation.set()
            release_binding.set()
            assert owner.close(3)


def test_followup_refreshes_history_advanced_by_another_owner() -> None:
    current = AgentInfo(
        id="child",
        path="/root/child",
        parent_id="root",
        description="",
        restoration_config=None,
        latest_run_id="first",
        status=RunStatus.COMPLETE,
    )
    restored: list[Agent] = []
    cancellations: list[str] = []

    def restore(_agent_id: str, _parent_id: str) -> Agent:
        rebuilt = Agent(
            FakeModelClient(
                lambda *_: AssistantMessage(content=[TextContent(text="done")])
            ),
            agent_id=current.id,
            previous_run_id=current.latest_run_id,
            state=AgentState(
                messages=[UserMessage(content=current.latest_run_id or "")]
            ),
            generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        )
        restored.append(rebuilt)
        return rebuilt

    owner = AgentCoordinator(
        directory=FakeAgentDirectory(
            list_agents=lambda: [current],
            lookup_agent=lambda *_: current,
            restore_agent=restore,
            read_run=lambda run_id, _parent_id: RunState(
                run_id=run_id,
                agent_id=current.id,
                status=current.status or RunStatus.COMPLETE,
            ),
            read_run_status=lambda *_: current.status or RunStatus.COMPLETE,
            cancel_run=lambda run_id, _parent_id: cancellations.append(run_id),
        )
    )
    try:
        initial = owner.resolve_child("child", "root")
        assert owner.resolve_child("child", "root") is initial
        local = initial.start(
            max_steps=1, coordinator=owner, parent_run_id="parent", background=False
        )
        assert local.wait_for_idle(3)
        current = current.model_copy(
            update={"latest_run_id": "remote-followup", "status": RunStatus.RUNNING}
        )
        latest = owner.lookup_agent("child", "root")
        assert latest is not None and latest.latest_run_id == "remote-followup"
        assert latest.status == RunStatus.RUNNING
        assert owner.discover_children("root")[0].latest_run_id == "remote-followup"
        owner.cancel_child(latest.latest_run_id, "root")
        assert cancellations == ["remote-followup"]
        current = current.model_copy(update={"status": RunStatus.COMPLETE})
        run = owner.start_message_run(
            AgentMessageRequest(
                agent_id="child",
                parent_id="root",
                message=UserMessage(id="next", content="next task"),
                delivery=MessageDelivery.SEND,
                max_steps=1,
                parent_run_id="parent",
                parent_message_id="parent:0",
                parent_tool_call_id="send",
            )
        )
        assert run is not None and run.previous_run_id == "remote-followup"
        assert run.result(3).output.text == "done"
        assert run.wait_for_idle(3)
        assert len(restored) == 2
        assert restored[-1].state.messages[0].text == "remote-followup"
    finally:
        assert owner.close(3)


def test_ancestor_can_message_a_descendant_and_receive_its_completion() -> None:
    def agent(text: str) -> Agent:
        return Agent(
            FakeModelClient(
                lambda *_: AssistantMessage(content=[TextContent(text=text)])
            ),
            generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        )

    owner = AgentCoordinator()
    root, middle, descendant = agent("root"), agent("middle"), agent("descendant")
    root_run = root.start(max_steps=1, coordinator=owner, background=False)
    owner.register_child(
        middle,
        parent_id=root.id,
        name="middle",
        description="",
        restoration_config=None,
    )
    middle_run = middle.start(
        max_steps=1, coordinator=owner, parent_run_id=root_run.id, background=False
    )
    owner.register_child(
        descendant,
        parent_id=middle.id,
        name="descendant",
        description="",
        restoration_config=None,
    )
    initial = descendant.start(
        max_steps=1, coordinator=owner, parent_run_id=middle_run.id, background=False
    )
    try:
        assert initial.wait_for_idle(3)
        receipt = owner.submit_message(
            AgentMessageRequest(
                agent_id=descendant.id,
                parent_id=root.id,
                message=UserMessage(id="ancestor-input", content="follow-up from root"),
                delivery=MessageDelivery.SEND,
                max_steps=1,
                parent_run_id=root_run.id,
                parent_message_id="root:0",
                parent_tool_call_id="send",
            )
        )
        assert receipt.run_id is not None and receipt.run_id != initial.id
        assert owner.completion(receipt.run_id).result(3).status == RunStatus.COMPLETE
        assert owner.run(receipt.run_id).wait_for_idle(3)
        completions = owner.completed_agents(root.id, set())
        assert [completion.run_id for completion in completions] == [receipt.run_id]
        assert not owner.completed_agents(middle.id, set())
        assert owner.run(receipt.run_id).parent_run_id == root_run.id
    finally:
        assert owner.close(3)


@pytest.mark.parametrize("max_steps", [1, 2])
def test_send_during_final_generation_preserves_the_run_budget(max_steps: int) -> None:
    entered, release = threading.Event(), threading.Event()
    requests: list[list[str]] = []
    events: list[AgentEvent] = []

    def generate(
        request: GenerationRequest, signal: CancellationSignal
    ) -> AssistantMessage:
        requests.append([message.text for message in request.messages])
        if len(requests) == 1:
            entered.set()
            assert release.wait(3)
            signal.check()
        return AssistantMessage(content=[TextContent(text="answer")])

    agent = Agent(
        FakeModelClient(generate),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
    )
    run = agent.start(
        max_steps=max_steps,
        messages=[UserMessage(content="original task")],
        on_event=events.append,
    )
    try:
        assert entered.wait(3)
        assert run.send_message(
            UserMessage(id="steer", content="include the new evidence")
        )
        release.set()
        result = run.result(3)
        assert run.wait_for_idle(3)
        assert len(requests) == max_steps
        snapshot = run.snapshot()
        started = [event for event in events if isinstance(event, MessageStartEvent)]
        assert not started[0].input_messages
        assert [
            message.id for event in started for message in event.input_messages
        ] == (["steer"] if max_steps == 2 else [])
        if max_steps == 1:
            assert result.stop_reason == RunStatus.LIMIT
            assert snapshot.progress is not None
            assert [message.id for message in snapshot.progress.pending_messages] == [
                "steer"
            ]
        else:
            assert result.stop_reason == RunStatus.COMPLETE
            assert requests[1].count("include the new evidence") == 1
            accepted = snapshot.steps[1].input_messages[0]
            assert isinstance(accepted.metadata, InputMessageMetadata)
            assert accepted.metadata.source == InputSource.HUMAN
            assert not run.cancel_message("steer")
        assert not run.send_message(UserMessage(content="too late"))
    finally:
        release.set()
        run.cancel()
        assert run.wait_for_idle(3)


def test_removal_during_preparation_wins_before_model_acceptance() -> None:
    entered, release = threading.Event(), threading.Event()
    requests: list[list[str]] = []
    runs: list[Run] = []
    events: list[AgentEvent] = []

    def prepare(state: StepInput) -> PreparedStep:
        if state.received_inputs:
            assert runs[0].cancel_message("remove-me")
        return PreparedStep()

    def generate(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        requests.append([message.text for message in request.messages])
        if len(requests) == 1:
            entered.set()
            assert release.wait(3)
        return AssistantMessage(content=[TextContent(text="answer")])

    agent = Agent(
        FakeModelClient(generate),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        prepare_step=prepare,
    )
    run = agent.start(max_steps=2, on_event=events.append)
    runs.append(run)
    try:
        assert entered.wait(3)
        assert run.send_message(
            UserMessage(id="remove-me", content="removed instruction")
        )
        release.set()
        assert run.result(3).stop_reason == RunStatus.COMPLETE
        assert run.wait_for_idle(3)
        assert all("removed instruction" not in request for request in requests)
        assert len(run.snapshot().steps) == 2
        assert not run.snapshot().steps[1].input_messages
        assert not any(
            event.input_messages
            for event in events
            if isinstance(event, MessageStartEvent)
        )
    finally:
        release.set()
        run.cancel()
        assert run.wait_for_idle(3)


@pytest.mark.parametrize(
    "pause", [None, RunStatus.CANCELLED, RunStatus.ERROR, RunStatus.LIMIT]
)
def test_queued_runs_follow_normal_completion_and_pause_after_failure(
    pause: RunStatus | None,
) -> None:
    entered, release, third = threading.Event(), threading.Event(), threading.Event()
    requests: list[list[str]] = []

    def generate(
        request: GenerationRequest, signal: CancellationSignal
    ) -> AssistantMessage:
        requests.append([message.text for message in request.messages])
        if len(requests) == 1:
            entered.set()
            while not release.wait(0.01):
                signal.check()
            if pause == RunStatus.ERROR:
                raise RuntimeError("The first task failed")
        if len(requests) == 3:
            third.set()
        return AssistantMessage(content=[TextContent(text=f"answer {len(requests)}")])

    owner = AgentCoordinator()
    parent = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(content=[TextContent(text="done")])
        ),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
    )
    parent_run = parent.start(max_steps=1, background=False, coordinator=owner)
    assert parent_run.wait_for_idle(3)
    child = Agent(
        FakeModelClient(generate),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
    )
    owner.register_child(
        child,
        parent_id=parent.id,
        name="child",
        description="",
        restoration_config=None,
    )
    initial = child.start(
        max_steps=1,
        messages=[UserMessage(content="first task")],
        coordinator=owner,
        parent_run_id=parent_run.id,
    )

    def submit(
        message_id: str,
        text: str,
        delivery: Literal[MessageDelivery.SEND, MessageDelivery.QUEUE],
    ) -> None:
        owner.submit_message(
            AgentMessageRequest(
                agent_id=child.id,
                parent_id=parent.id,
                message=UserMessage(id=message_id, content=text),
                delivery=delivery,
                max_steps=1,
                parent_run_id=parent_run.id,
                parent_message_id="parent:0",
                parent_tool_call_id=message_id,
            )
        )

    try:
        assert entered.wait(3)
        submit(
            "second",
            "second task",
            MessageDelivery.SEND if pause == RunStatus.LIMIT else MessageDelivery.QUEUE,
        )
        if pause is None:
            submit("third", "third task", MessageDelivery.QUEUE)
        if pause is not None:
            if pause == RunStatus.CANCELLED:
                initial.cancel()
            else:
                release.set()
            assert initial.wait_for_idle(3)
            assert initial.status == pause
            info = owner.lookup_agent(child.id, parent.id)
            assert info is not None and info.queue_paused
            assert len(requests) == 1
            submit("resume", "explicit new task", MessageDelivery.SEND)
        release.set()
        assert third.wait(3)
        latest = owner.lookup_agent(child.id, parent.id)
        assert latest is not None and latest.latest_run_id is not None
        final = owner.run(latest.latest_run_id)
        assert final.wait_for_idle(3)
        assert len(requests) == 3
        assert requests[-1][-1] == (
            "second task" if pause is not None else "third task"
        )
        assert "first task" in requests[-1]
        if pause == RunStatus.LIMIT:
            saved_initial = initial.snapshot()
            assert saved_initial.progress is not None
            assert not saved_initial.progress.pending_messages
        finished = owner.lookup_agent(child.id, parent.id)
        assert finished is not None and not finished.pending_messages
    finally:
        release.set()
        assert owner.close(3)
