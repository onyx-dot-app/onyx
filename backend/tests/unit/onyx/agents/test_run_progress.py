"""Saved progress identifies completed callbacks by call ID, not arrival order."""

import pytest
from pydantic import ValidationError

from onyx.agents.models import (
    ExecutionStatus,
    RunAction,
    RunProgress,
    RunState,
    RunStatus,
    StepRecord,
    ToolExecutionRecord,
)
from onyx.agents.runtime import Agent
from onyx.llm.interfaces import GenerationContext
from onyx.llm.models import AssistantMessage, ToolCall, ToolResultMessage
from onyx.tracing.flows import LLMFlow
from tests.unit.onyx.agents.fakes import FakeModelClient


def test_finalized_tool_ids_serialize_in_stable_order() -> None:
    progress = RunProgress(step_limit=1, finalized_tool_call_ids={"z", "a"})
    assert progress.model_dump(mode="json")["finalized_tool_call_ids"] == ["a", "z"]
    assert RunProgress.model_validate_json(progress.model_dump_json()) == progress
    with pytest.raises(ValidationError, match="finalized_tools"):
        RunProgress.model_validate({"step_limit": 1, "finalized_tools": 1})


@pytest.mark.parametrize(
    "invalid", ["unknown_call", "missing_result", "missing_step", "mismatched_result"]
)
def test_resume_rejects_invalid_finalized_tool_ids(invalid: str) -> None:
    state = RunState(
        run_id="run",
        agent_id="agent",
        status=RunStatus.SUSPENDED,
        steps=[
            StepRecord(
                message=AssistantMessage(
                    id="generation",
                    content=[ToolCall(id="search", name="search", arguments={})],
                ),
                generation_status=ExecutionStatus.COMPLETE,
                tools={
                    "search": ToolExecutionRecord(
                        status=ExecutionStatus.COMPLETE,
                        result=ToolResultMessage(
                            content="found", tool_call_id="search", tool_name="search"
                        ),
                    )
                },
            )
        ],
        progress=RunProgress(
            step_limit=2, action=RunAction.TOOLS, finalized_tool_call_ids={"search"}
        ),
    )
    assert state.progress is not None
    if invalid == "unknown_call":
        state.progress.finalized_tool_call_ids.add("unknown")
    elif invalid == "missing_result":
        state.steps[0].tools["search"].result = None
    elif invalid == "missing_step":
        state.progress.step_index = len(state.steps)
    else:
        result = state.steps[0].tools["search"].result
        assert result is not None
        result.tool_call_id = "different"
    agent = Agent(
        FakeModelClient(lambda *_: AssistantMessage()),
        agent_id="agent",
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
    )
    with pytest.raises(ValueError, match="Finalized tool"):
        agent.resume(state)
