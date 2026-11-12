"""Queued instructions start from the latest saved run of their recipient."""

from unittest.mock import patch

from onyx.agents.agent_coordination import AgentCoordinator
from onyx.agents.models import (
    AgentInfo,
    AgentState,
    RunState,
    RunStatus,
)
from onyx.agents.runtime import Agent
from onyx.llm.interfaces import GenerationContext
from onyx.llm.models import AssistantMessage, TextContent, UserMessage
from onyx.tracing.flows import LLMFlow
from tests.unit.onyx.agents.fakes import FakeAgentDirectory, FakeModelClient


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
        latest = next(info for info in owner.discover_agents() if info.id == "child")
        assert latest.latest_run_id == "remote-followup"
        assert latest.status == RunStatus.RUNNING
        assert owner.discover_agents()[0].latest_run_id == "remote-followup"
        owner.cancel_child(latest.latest_run_id, "root")
        assert cancellations == ["remote-followup"]
        current = current.model_copy(update={"status": RunStatus.COMPLETE})
        run = owner.start_message_run(
            "child",
            spawner_id="root",
            messages=[UserMessage(id="next", content="next task")],
            max_steps=1,
            deadline_at=None,
            parent_run_id="parent",
            parent_message_id="parent:0",
            parent_tool_call_id="send",
        )
        assert run is not None and run.previous_run_id == "remote-followup"
        assert run.result(3).output.text == "done"
        assert run.wait_for_idle(3)
        assert len(restored) == 2
        assert restored[-1].state.messages[0].text == "remote-followup"
    finally:
        assert owner.close(3)


def test_restoring_an_agent_at_the_load_bound_evicts_an_idle_agent() -> None:
    """Queued work for another agent starts once loaded agents are idle."""
    infos = {
        agent_id: AgentInfo(
            id=agent_id,
            path=f"/root/{agent_id}",
            parent_id="root",
            description="",
            restoration_config=None,
            latest_run_id=None,
            status=RunStatus.COMPLETE,
        )
        for agent_id in ["first", "second"]
    }

    def restore(agent_id: str, _parent_id: str) -> Agent:
        return Agent(
            FakeModelClient(
                lambda *_: AssistantMessage(content=[TextContent(text="done")])
            ),
            agent_id=agent_id,
            generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        )

    owner = AgentCoordinator(
        directory=FakeAgentDirectory(
            list_agents=lambda: list(infos.values()),
            lookup_agent=lambda agent_id, _parent_id: infos.get(agent_id),
            restore_agent=restore,
        )
    )
    try:
        with patch("onyx.agents.agent_coordination.MAX_LOADED_AGENTS", 1):
            first = owner.resolve_child("first", "root")
            run = first.start(
                max_steps=1, coordinator=owner, parent_run_id="parent", background=False
            )
            assert run.wait_for_idle(3)
            second = owner.resolve_child("second", "root")
        assert second.id == "second"
    finally:
        assert owner.close(3)


def test_loaded_agent_eviction_keeps_the_most_recently_used_agent() -> None:
    """A use moves an agent to the back, so the least recently used one is evicted."""
    infos = {
        agent_id: AgentInfo(
            id=agent_id,
            path=f"/root/{agent_id}",
            parent_id="root",
            description="",
            restoration_config=None,
            latest_run_id=None,
            status=RunStatus.COMPLETE,
        )
        for agent_id in ["first", "second", "third"]
    }

    def restore(agent_id: str, _parent_id: str) -> Agent:
        return Agent(
            FakeModelClient(
                lambda *_: AssistantMessage(content=[TextContent(text="done")])
            ),
            agent_id=agent_id,
            generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        )

    owner = AgentCoordinator(
        directory=FakeAgentDirectory(
            list_agents=lambda: list(infos.values()),
            lookup_agent=lambda agent_id, _parent_id: infos.get(agent_id),
            restore_agent=restore,
        )
    )
    try:
        with patch("onyx.agents.agent_coordination.MAX_LOADED_AGENTS", 2):
            first = owner.resolve_child("first", "root")
            second = owner.resolve_child("second", "root")
            assert owner.resolve_child("first", "root") is first
            owner.resolve_child("third", "root")
            assert owner.resolve_child("first", "root") is first
            assert owner.resolve_child("second", "root") is not second
    finally:
        assert owner.close(3)
