"""Saved progress identifies completed callbacks by call ID, not arrival order."""

import pytest
from pydantic import ValidationError

from onyx.agents.agent_coordination import AgentCoordinator
from onyx.agents.models import (
    AgentState,
    ExecutionStatus,
    InputMessageMetadata,
    InputSource,
    PreparedStep,
    RunAction,
    RunFailureKind,
    RunProgress,
    RunState,
    RunStatus,
    StepInput,
    StepRecord,
    ToolExecutionRecord,
)
from onyx.agents.runtime import Agent, Run, RunFailed
from onyx.agents.tools import AgentTool, ToolInvocation
from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.llm.interfaces import GenerationContext
from onyx.llm.models import (
    AssistantMessage,
    GenerationRequest,
    TextContent,
    ToolCall,
    ToolDefinition,
    ToolResult,
    ToolResultMessage,
    UserMessage,
)
from onyx.tracing.flows import LLMFlow
from tests.unit.onyx.agents.fakes import FakeModelClient, FakeRunOwnership


def test_finalized_tool_ids_serialize_in_stable_order() -> None:
    progress = RunProgress(
        tool_configuration_digest="test-tool-configuration",
        step_limit=1,
        finalized_tool_call_ids={"z", "a"},
    )
    assert progress.model_dump(mode="json")["finalized_tool_call_ids"] == ["a", "z"]
    assert RunProgress.model_validate_json(progress.model_dump_json()) == progress
    with pytest.raises(ValidationError, match="finalized_tools"):
        RunProgress.model_validate(
            {
                "step_limit": 1,
                "tool_configuration_digest": "test-tool-configuration",
                "finalized_tools": 1,
            }
        )


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
            tool_configuration_digest="test-tool-configuration",
            step_limit=2,
            action=RunAction.TOOLS,
            finalized_tool_call_ids={"search"},
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


@pytest.mark.parametrize("cancel_generation", [False, True])
def test_step_inputs_reach_the_model_and_survive_partial_generation(
    cancel_generation: bool,
) -> None:
    incoming = UserMessage(
        id="child-delivery",
        content="Child found the answer",
        metadata=InputMessageMetadata(
            source=InputSource.AGENT_RESULT,
            source_run_id="child",
            content_metadata=AssistantMessage(),
        ),
    )
    requests: list[list[str]] = []
    tool_history: list[list[str]] = []

    def prepare(step: StepInput) -> PreparedStep:
        return PreparedStep(input_messages=[incoming] if step.step.index == 1 else [])

    def reply(
        request: GenerationRequest, signal: CancellationSignal
    ) -> AssistantMessage:
        requests.append([message.text for message in request.messages])
        if len(requests) == 1:
            return AssistantMessage(
                content=[ToolCall(id="lookup", name="lookup", arguments={})]
            )
        if len(requests) == 2:
            assert requests[-1][-2] == "Other work finished"
            assert "Child found the answer" in requests[-1][-1]
            # Preparing a later input cannot mutate the accepted conversation.
            incoming.content = "Changed outside the run"
            if cancel_generation:
                signal.cancel()
                signal.check()
            return AssistantMessage(
                content=[ToolCall(id="followup", name="lookup", arguments={})]
            )
        return AssistantMessage(content=[TextContent(text="Answer")])

    def lookup(invocation: ToolInvocation) -> ToolResult:
        tool_history.append([message.text for message in invocation.messages])
        return ToolResult(content="Other work finished")

    agent = Agent(
        FakeModelClient(reply),
        state=AgentState(
            messages=[
                UserMessage(
                    id="earlier-delivery",
                    content="Earlier result",
                    metadata=InputMessageMetadata(
                        source=InputSource.AGENT_RESULT, source_run_id="earlier"
                    ),
                )
            ]
        ),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        tools=[
            AgentTool(
                definition=ToolDefinition(name="lookup", description="", parameters={}),
                execute=lookup,
            )
        ],
        prepare_step=prepare,
    )
    run = agent.start(
        messages=[UserMessage(content="Do the work")], max_steps=3, background=False
    )
    assert run.wait_for_idle(5)
    if cancel_generation:
        with pytest.raises(AgentCancelled):
            run.result()
    else:
        assert run.result().output.text == "Answer"
        assert any("Child found the answer" in text for text in tool_history[1])
    snapshot = run.snapshot()
    accepted = snapshot.steps[1].input_messages[0]
    assert "Child found the answer" in accepted.text
    # Accepted history keeps provenance; content metadata served preparation only.
    assert accepted.metadata == InputMessageMetadata(
        source=InputSource.AGENT_RESULT, source_run_id="child"
    )
    restored = Run.from_snapshot(snapshot)
    assert (
        sum(
            "Child found the answer" in message.text
            for message in restored.snapshot().messages
        )
        == 1
    )


def test_untagged_step_input_is_rejected_before_the_model_call() -> None:
    """Compaction keeps the latest untagged user message as the task question."""
    requests: list[GenerationRequest] = []

    def reply(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        requests.append(request)
        return AssistantMessage(content=[TextContent(text="Answer")])

    agent = Agent(
        FakeModelClient(reply),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        prepare_step=lambda _: PreparedStep(
            input_messages=[UserMessage(content="Untagged instruction")]
        ),
    )
    run = agent.start(
        messages=[UserMessage(content="Do the work")], max_steps=2, background=False
    )
    assert run.wait_for_idle(5)
    with pytest.raises(RunFailed) as failed:
        run.result()
    assert failed.value.failure.kind == RunFailureKind.EXECUTION
    assert requests == []


def test_final_answer_on_the_last_step_ignores_unread_input() -> None:
    """Unread input continues a run only while steps remain."""
    agent = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(content=[TextContent(text="Done")])
        ),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
    )
    coordinator = AgentCoordinator(ownership=FakeRunOwnership(has_unread_inputs=True))
    run = agent.start(
        messages=[UserMessage(content="Question")], max_steps=1, coordinator=coordinator
    )

    assert run.result(timeout=10).output.text == "Done"
    snapshot = run.snapshot()
    assert snapshot.status == RunStatus.COMPLETE
    assert snapshot.answer_step_index == 0


def test_a_terminating_step_leaves_unread_input_for_the_next_run() -> None:
    requests: list[GenerationRequest] = []
    finish = AgentTool(
        definition=ToolDefinition(name="finish", description="", parameters={}),
        execute=lambda _: ToolResult(content="Waiting", terminate=True),
    )

    def generate(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        requests.append(request)
        return AssistantMessage(
            content=[ToolCall(id="finish", name="finish", arguments={})]
        )

    agent = Agent(
        FakeModelClient(generate),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        tools=[finish],
    )
    coordinator = AgentCoordinator(ownership=FakeRunOwnership(has_unread_inputs=True))
    run = agent.start(
        messages=[UserMessage(content="Question")], max_steps=3, coordinator=coordinator
    )

    run.result(timeout=10)
    assert run.snapshot().status == RunStatus.COMPLETE
    assert len(requests) == 1
