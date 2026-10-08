"""Research deadlines and failed children must preserve the parent's report."""

from threading import Event, Timer

import pytest

from onyx.agents.agent_coordination import AgentCoordinator
from onyx.agents.runtime import Run
from onyx.deep_research.agent import DeepResearchAgent
from onyx.deep_research.research_agent import ResearchAgent
from onyx.deep_research.tool_definitions import (
    GENERATE_REPORT_TOOL_NAME,
    RESEARCH_AGENT_TOOL_NAME,
    THINK_TOOL_NAME,
)
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.models import (
    AssistantMessage,
    GenerationRequest,
    ReasoningEffort,
    TextContent,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from tests.unit.onyx.agents.fakes import FakeModelClient, run_agent


def test_timed_out_child_preserves_successful_sibling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("onyx.deep_research.agent.RESEARCH_AGENT_TIMEOUT_SECONDS", 0.1)
    child_cancelled = Event()
    timers: list[Timer] = []

    class RecordedTimer(Timer):
        def start(self) -> None:
            timers.append(self)
            super().start()

    monkeypatch.setattr("onyx.agents.agent_coordination.threading.Timer", RecordedTimer)

    def reply(
        request: GenerationRequest, signal: CancellationSignal
    ) -> AssistantMessage:
        results = [m for m in request.messages if isinstance(m, ToolResultMessage)]
        if any(tool.name == RESEARCH_AGENT_TOOL_NAME for tool in request.tools):
            if results:
                assert [(m.tool_call_id, m.is_error) for m in results] == [
                    ("slow", True),
                    ("fast", False),
                ]
                return AssistantMessage(
                    content=[
                        ToolCall(
                            id="report", name=GENERATE_REPORT_TOOL_NAME, arguments={}
                        )
                    ]
                )
            return AssistantMessage(
                content=[
                    ToolCall(
                        id=name, name=RESEARCH_AGENT_TOOL_NAME, arguments={"task": name}
                    )
                    for name in ("slow", "fast")
                ]
            )
        if any(m.text == "slow" for m in request.messages):
            with signal.on_cancel(child_cancelled.set):
                assert child_cancelled.wait(5)
            signal.check()
        if any(m.text == "fast" for m in request.messages):
            return AssistantMessage(content=[TextContent(text="Fast report")])
        return AssistantMessage(
            content=[TextContent(text="Final report" if results else "Plan")]
        )

    feature = DeepResearchAgent(
        [],
        [],
        FakeModelClient(reply),
        len,
        None,
        "",
        ReasoningEffort.LOW,
        None,
        skip_clarification=True,
    )
    runs: list[Run] = []
    result = run_agent(
        feature,
        messages=[UserMessage(content="Research")],
        max_steps=4,
        coordinator=AgentCoordinator(),
        runs=runs,
    )
    assert result.output.text == "Final report"
    assert child_cancelled.is_set()
    assert len(timers) == 2
    assert all(timer.finished.is_set() for timer in timers)
    assert sorted(child.status.value for child in runs[-1].snapshot().child_runs) == [
        "cancelled",
        "complete",
    ]


@pytest.mark.parametrize("parent", [False, True])
def test_elapsed_time_forces_report_before_step_limit(parent: bool) -> None:
    requests: list[GenerationRequest] = []
    feature: DeepResearchAgent | ResearchAgent

    def reply(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        requests.append(request)
        feature.started -= (31 if parent else 13) * 60
        if len(requests) == 1:
            return (
                AssistantMessage(content=[TextContent(text="Plan")])
                if parent
                else AssistantMessage(
                    content=[
                        ToolCall(
                            id="think",
                            name=THINK_TOOL_NAME,
                            arguments={"reasoning": "Plan"},
                        )
                    ]
                )
            )
        assert not request.tools
        return AssistantMessage(content=[TextContent(text="Report")])

    llm = FakeModelClient(reply)
    feature = (
        DeepResearchAgent(
            [],
            [],
            llm,
            len,
            None,
            "",
            ReasoningEffort.LOW,
            None,
            skip_clarification=True,
        )
        if parent
        else ResearchAgent([], llm, len, None, "", ReasoningEffort.LOW)
    )
    result = run_agent(
        feature, messages=[UserMessage(content="Research")], max_steps=10
    )
    assert result.output.text == "Report"
    assert len(requests) == 2
