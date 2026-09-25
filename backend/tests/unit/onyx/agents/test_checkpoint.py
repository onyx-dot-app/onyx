"""Checkpoints preserve typed execution data and resume without repeating tools."""

import gc
import json
import weakref
from contextvars import ContextVar
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from onyx.agents.models import (
    AgentState,
    ExecutionCheckpoint,
    RunAction,
    RunProgress,
    RunState,
    ToolCallContext,
)
from onyx.agents.runtime import Agent
from onyx.agents.tools import (
    AgentTool,
    HumanToolAnswer,
    InputDecision,
    InputMode,
    PendingToolInput,
    ToolInvocation,
)
from onyx.agents.transcript import OperationSnapshot, RunStatus
from onyx.chat.checkpoint import CheckpointBinding
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.models import (
    AssistantMessage,
    GenerationOptions,
    GenerationRequest,
    TextContent,
    ToolCall,
    ToolResult,
    ToolResultMessage,
    UserMessage,
)
from tests.unit.onyx.agents.checkpoint_storage import CheckpointStorage
from tests.unit.onyx.agents.fakes import FakeModelClient


class CitationMetadata(BaseModel):
    citations: dict[int, str]


class SearchDetails(BaseModel):
    documents: list[str]


class FeatureState(BaseModel):
    next_citation: int


def codec() -> CheckpointStorage:
    return CheckpointStorage(
        {
            "test.citations.v1": CitationMetadata,
            "test.search.v1": SearchDetails,
            "test.state.v1": FeatureState,
        }
    )


def checkpoint() -> ExecutionCheckpoint:
    instruction = UserMessage(
        content="Search then send",
        cacheable=True,
        metadata=CitationMetadata(citations={1: "source"}),
    )
    result = ToolResultMessage(
        content="found",
        tool_call_id="search",
        tool_name="search",
        cacheable=True,
        metadata=CitationMetadata(citations={1: "source"}),
        details=SearchDetails(documents=["source"]),
    )
    snapshot = RunState(
        run_id="run",
        agent_id="agent",
        revision=4,
        status=RunStatus.SUSPENDED,
        input_messages=[instruction],
        messages=[
            AssistantMessage(
                id="generation",
                content=[
                    ToolCall(id="search", name="search", arguments={}),
                    ToolCall(id="send", name="send", arguments={"to": "recipient"}),
                ],
                metadata=CitationMetadata(citations={1: "source"}),
            ),
            result,
        ],
        operations=[
            OperationSnapshot(step_index=0, message_index=0, status=RunStatus.COMPLETE)
        ],
        progress=RunProgress(
            step_limit=3,
            action=RunAction.TOOLS,
            message_index=0,
            options=GenerationOptions(),
            previous_options=GenerationOptions(),
            feature_state=FeatureState(next_citation=2),
            finalized_tools=1,
            pending_tool_calls={
                "send": PendingToolInput(
                    request_id="approve-send", prompt="Send?", mode=InputMode.EXECUTE
                )
            },
            human_tool_answers={
                "question": HumanToolAnswer(
                    request_id="question",
                    decision=InputDecision.RESULT,
                    result=ToolResult(
                        content="answer",
                        cacheable=True,
                        details=SearchDetails(documents=["answer-source"]),
                    ),
                )
            },
        ),
    )
    return ExecutionCheckpoint(
        run_state=snapshot,
        agent_state=AgentState(messages=[instruction, result]),
    )


def test_json_round_trip_preserves_typed_payloads_at_every_execution_location() -> None:
    captured = checkpoint()
    serialized = codec().save(
        captured.run_state,
        captured.agent_state,
        CheckpointBinding(
            tenant_id="tenant", branch_id="branch", context_version="history-7"
        ),
    )
    restored = codec().load(serialized)
    assert restored == captured
    assert isinstance(restored.agent_state.messages[0].metadata, CitationMetadata)
    result = restored.agent_state.messages[1]
    assert isinstance(result, ToolResultMessage)
    assert isinstance(result.details, SearchDetails)
    assert result.cacheable
    assert restored.agent_state.messages[0] is not captured.agent_state.messages[0]


def test_unknown_payload_types_and_versions_fail_before_execution() -> None:
    captured = checkpoint()
    with pytest.raises(ValueError, match="unregistered"):
        CheckpointStorage({}).save(
            captured.run_state,
            captured.agent_state,
            CheckpointBinding(
                tenant_id="tenant", branch_id="branch", context_version="history-7"
            ),
        )
    serialized = codec().save(
        captured.run_state,
        captured.agent_state,
        CheckpointBinding(
            tenant_id="tenant", branch_id="branch", context_version="history-7"
        ),
    )
    with pytest.raises(ValueError, match="Unknown checkpoint payload"):
        CheckpointStorage({}).load(serialized)
    payload = json.loads(serialized)
    payload["checkpoint"]["version"] = 2
    with pytest.raises(ValidationError):
        codec().load(json.dumps(payload))
    with pytest.raises(ValueError, match="selected context"):
        codec().load(
            serialized,
            expected_binding=CheckpointBinding(
                tenant_id="tenant", branch_id="branch", context_version="history-7"
            ).model_copy(update={"context_version": "other"}),
        )


def _make_executable_agent(counts: dict[str, int], context: AgentState) -> Agent:
    def generate(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        counts["generation"] += 1
        if any(isinstance(message, ToolResultMessage) for message in request.messages):
            assert (
                sum(message.text == "Search then send" for message in request.messages)
                == 1
            )
            return AssistantMessage(content=[TextContent(text="done")])
        return AssistantMessage(
            content=[
                ToolCall(id="search", name="search", arguments={}),
                ToolCall(id="send", name="send", arguments={}),
            ]
        )

    def search(_invocation: ToolInvocation) -> ToolResult:
        counts["search"] += 1
        return ToolResult(content="found", details=SearchDetails(documents=["source"]))

    def send(_invocation: ToolInvocation) -> ToolResult:
        counts["send"] += 1
        return ToolResult(content="sent")

    def gate(context: ToolCallContext) -> PendingToolInput | None:
        if context.call.name == "send":
            counts["gate"] += 1
            return PendingToolInput(
                request_id="approve-send", prompt="Send?", mode=InputMode.EXECUTE
            )
        return None

    def finalize(context: ToolCallContext, result: ToolResult) -> ToolResult:
        counts["finalize-" + context.call.name] += 1
        return result

    return Agent(
        FakeModelClient(generate),
        agent_id="agent",
        state=context,
        tools=[
            AgentTool(name="search", description="", parameters={}, execute=search),
            AgentTool(name="send", description="", parameters={}, execute=send),
        ],
        before_tool_call=gate,
        after_tool_call=finalize,
    )


def test_answer_resumes_in_the_execution_owners_context() -> None:
    tenant = ContextVar("test_tenant", default="unset")
    model_contexts: list[str] = []
    callback_contexts: list[str] = []

    def generate(
        _request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        model_contexts.append(tenant.get())
        return AssistantMessage(
            content=[ToolCall(id="question", name="ask", arguments={})]
            if len(model_contexts) == 1
            else [TextContent(text="done")]
        )

    def finalize(_context: ToolCallContext, result: ToolResult) -> ToolResult:
        callback_contexts.append(tenant.get())
        return result

    token = tenant.set("owner")
    agent = Agent(
        FakeModelClient(generate),
        tools=[
            AgentTool(
                name="ask",
                description="",
                parameters={},
                execute=lambda _: PendingToolInput(
                    request_id="answer", mode=InputMode.RESULT, prompt="Question"
                ),
            )
        ],
        after_tool_call=finalize,
    )
    run = agent.start(max_steps=2)
    try:
        assert run.wait_until_settled(3).status == RunStatus.SUSPENDED
        tenant.set("answer-sender")
        run.submit(
            HumanToolAnswer(
                request_id="answer",
                decision=InputDecision.RESULT,
                result=ToolResult(content="yes"),
            )
        )
        assert run.result(3).output.text == "done"
        assert model_contexts == ["owner", "owner"]
        assert callback_contexts == ["owner"]
    finally:
        run.cancel()
        assert run.wait_for_idle(3)
        tenant.reset(token)


def test_fresh_objects_resume_json_checkpoint_without_repeating_tools(
    tmp_path: Path,
) -> None:
    counts = dict.fromkeys(
        ["generation", "search", "send", "gate", "finalize-search", "finalize-send"], 0
    )
    agent = _make_executable_agent(counts, AgentState())
    run = agent.start(max_steps=3, messages=[UserMessage(content="Search then send")])
    assert run.wait_until_settled(timeout=3).status == RunStatus.SUSPENDED
    assert run.wait_for_idle(3)
    captured = run.capture()
    assert captured.agent_state.messages == []
    assert len(captured.run_state.input_messages) == 1
    run_id = run.id
    path = tmp_path / "run.json"
    path.write_text(
        codec().save(
            captured.run_state,
            captured.agent_state,
            CheckpointBinding(
                tenant_id="tenant", branch_id="branch", context_version="history"
            ),
        )
    )
    old_agent = weakref.ref(agent)
    old_run = weakref.ref(run)
    del captured, agent, run
    gc.collect()
    assert old_agent() is None
    assert old_run() is None

    restored = codec().load(path.read_text())
    agent = _make_executable_agent(counts, restored.agent_state)
    resumed = agent.resume(restored.run_state)
    resumed.submit(
        HumanToolAnswer(request_id="approve-send", decision=InputDecision.APPROVE)
    )
    assert resumed.result(timeout=3).output.text == "done"
    assert resumed.wait_for_idle(3)
    assert resumed.id == run_id
    assert counts == {
        "generation": 2,
        "search": 1,
        "send": 1,
        "gate": 1,
        "finalize-search": 1,
        "finalize-send": 1,
    }
