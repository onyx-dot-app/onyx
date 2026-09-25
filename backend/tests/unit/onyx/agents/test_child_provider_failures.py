"""Provider failure in one research child must not cancel independent evidence gathering."""

import json
from collections.abc import Iterator
from threading import Event, Lock

from litellm.exceptions import APIConnectionError

from onyx.agents.agent_coordination import AgentCoordinator
from onyx.agents.events import AgentEndEvent, AgentEvent
from onyx.agents.execution_records import RunFailureKind, RunStatus
from onyx.deep_research.agent import DeepResearchAgent
from onyx.deep_research.tool_definitions import (
    GENERATE_REPORT_TOOL_NAME,
    RESEARCH_AGENT_TOOL_NAME,
)
from onyx.llm.litellm_models import ChatCompletionDeltaToolCall, Delta, FunctionCall
from onyx.llm.models import ReasoningEffort, ToolResultMessage, UserMessage
from tests.unit.onyx.agents.fakes import ScriptedLLM


class _ResearchResponses(Iterator[Delta]):
    def __init__(self, steps: list[Delta | Exception]) -> None:
        self._steps = iter(enumerate(steps))
        self._lock = Lock()
        self.sibling_started = Event()
        self.failure_observed = Event()

    def __next__(self) -> Delta:
        with self._lock:
            index, response = next(self._steps)
        if index == 2:
            assert self.sibling_started.wait(5)
        elif index == 3:
            self.sibling_started.set()
            # The successful child resumes only after its sibling has failed.
            assert self.failure_observed.wait(5)
        if isinstance(response, Exception):
            raise response
        return response


def test_research_continues_after_child_provider_failure() -> None:
    report_call = Delta(
        tool_calls=[
            ChatCompletionDeltaToolCall(
                index=0,
                id="report",
                function=FunctionCall(name=GENERATE_REPORT_TOOL_NAME, arguments="{}"),
            )
        ]
    )
    responses = _ResearchResponses(
        [
            Delta(content="Plan"),
            Delta(
                tool_calls=[
                    ChatCompletionDeltaToolCall(
                        index=index,
                        id=f"research-{index}",
                        function=FunctionCall(
                            name=RESEARCH_AGENT_TOOL_NAME,
                            arguments=json.dumps({"task": f"Topic {index}"}),
                        ),
                    )
                    for index in range(2)
                ]
            ),
            APIConnectionError(
                "Provider unavailable", model="test", llm_provider="openai"
            ),
            report_call,
            Delta(content="Evidence from the successful child"),
            report_call,
            Delta(content="Final report with remaining evidence"),
        ]
    )
    llm = ScriptedLLM([], 128000)
    llm.steps = responses
    feature = DeepResearchAgent(
        messages=[],
        allowed_tools=[],
        llm=llm,
        token_counter=len,
        user_identity=None,
        language_section="",
        reasoning_effort=ReasoningEffort.LOW,
        all_injected_file_metadata=None,
        skip_clarification=True,
    )

    def observe(event: AgentEvent) -> None:
        if (
            isinstance(event, AgentEndEvent)
            and event.parent_run_id is not None
            and event.outcome == RunStatus.ERROR
        ):
            responses.failure_observed.set()

    run = feature.agent.start(
        max_steps=4,
        messages=[UserMessage(content="Research both topics")],
        coordinator=AgentCoordinator(),
        on_event=observe,
    )
    try:
        result = run.result(10)
    finally:
        run.cancel()
        assert run.wait_for_idle(10)

    assert result.output.text == "Final report with remaining evidence"
    children = run.snapshot().child_runs
    assert len(children) == 2
    assert {child.status for child in children} == {RunStatus.ERROR, RunStatus.COMPLETE}
    failed = next(child for child in children if child.status == RunStatus.ERROR)
    assert failed.failure is not None
    assert failed.failure.kind == RunFailureKind.LLM
    assert failed.failure.llm_error is not None
    assert failed.failure.llm_error.error_code == "CONNECTION_ERROR"
    results = [
        message
        for message in feature.agent.state.messages
        if isinstance(message, ToolResultMessage)
        and message.tool_name == RESEARCH_AGENT_TOOL_NAME
    ]
    assert len(results) == 2
    assert sum(message.is_error for message in results) == 1
    assert [message.text for message in results if not message.is_error] == [
        "Evidence from the successful child"
    ]
