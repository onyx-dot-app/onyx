"""Input ownership across active tools, suspension drain, and fresh execution."""

import threading

import pytest
from pydantic import BaseModel

import onyx.agents.runtime as runtime
from onyx.agents.checkpoint import CheckpointBinding, SnapshotCodec
from onyx.agents.coordination import AgentCoordinator
from onyx.agents.events import AgentEvent, AgentSuspendedEvent, InputRequiredEvent
from onyx.agents.models import AgentContext, StepResult, ToolCallContext
from onyx.agents.restoration import FeatureRestoration
from onyx.agents.runtime import Agent, Run, RunFailed
from onyx.agents.tools import (
    AgentTool,
    InputDecision,
    InputMode,
    PendingToolInput,
    ToolAnswer,
    ToolInvocation,
)
from onyx.agents.transcript import RunFailureKind, RunStatus
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.models import (
    AssistantMessage,
    GenerationRequest,
    TextContent,
    ToolCall,
    ToolResult,
    ToolResultMessage,
    UserMessage,
)
from tests.unit.onyx.agents.fakes import FakeModelClient


def _approve(request_id: str = "permission") -> ToolAnswer:
    return ToolAnswer(request_id=request_id, decision=InputDecision.APPROVE)


def _gate(context: ToolCallContext) -> PendingToolInput | None:
    if context.call.name == "effect":
        return PendingToolInput(
            request_id="permission", prompt="Proceed?", mode=InputMode.EXECUTE
        )
    return None


def _model(calls: list[ToolCall]) -> FakeModelClient:
    def generate(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        if any(isinstance(message, ToolResultMessage) for message in request.messages):
            return AssistantMessage(content=[TextContent(text="done")])
        return AssistantMessage(content=list(calls))

    return FakeModelClient(generate)


def test_answer_starts_approved_action_while_parallel_sibling_is_running() -> None:
    sibling_started = threading.Event()
    release_sibling = threading.Event()
    effect_started = threading.Event()
    requested = threading.Event()

    def sibling(_invocation: ToolInvocation) -> ToolResult:
        sibling_started.set()
        assert release_sibling.wait(3)
        return ToolResult(content="search result")

    def effect(_invocation: ToolInvocation) -> ToolResult:
        effect_started.set()
        return ToolResult(content="sent")

    def observe(event: AgentEvent) -> None:
        if isinstance(event, InputRequiredEvent):
            requested.set()

    agent = Agent(
        _model(
            [
                ToolCall(id="search", name="search", arguments={}),
                ToolCall(id="effect", name="effect", arguments={}),
            ]
        ),
        tools=[
            AgentTool(name="search", description="", parameters={}, execute=sibling),
            AgentTool(name="effect", description="", parameters={}, execute=effect),
        ],
        before_tool_call=_gate,
    )
    run = agent.start(max_steps=2, on_event=observe)
    try:
        assert sibling_started.wait(3)
        assert requested.wait(3)
        pending = run.pending_inputs
        assert len(pending) == 1
        pending[0].prompt = "Changed by caller"
        assert run.pending_inputs[0].prompt != "Changed by caller"
        run.submit(_approve())
        assert effect_started.wait(3)
        assert not release_sibling.is_set()
        release_sibling.set()
        assert run.result(timeout=3).output.text == "done"
        assert run.pending_inputs == []
    finally:
        release_sibling.set()
        run.cancel()
        assert run.wait_for_idle(3)


def test_answer_during_suspension_delivery_drain_restarts_exactly_once() -> None:
    draining = threading.Event()
    release_delivery = threading.Event()
    effect_calls: list[str] = []

    def effect(_invocation: ToolInvocation) -> ToolResult:
        effect_calls.append("sent")
        return ToolResult(content="sent")

    def observe(event: AgentEvent) -> None:
        if isinstance(event, AgentSuspendedEvent):
            draining.set()
            assert release_delivery.wait(3)

    agent = Agent(
        _model([ToolCall(id="effect", name="effect", arguments={})]),
        tools=[AgentTool(name="effect", description="", parameters={}, execute=effect)],
        before_tool_call=_gate,
    )
    run = agent.start(max_steps=2, on_event=observe)
    try:
        assert draining.wait(3)
        run.submit(_approve())
        run.submit(_approve())
        assert effect_calls == []
        release_delivery.set()
        assert run.result(timeout=3).output.text == "done"
        assert effect_calls == ["sent"]
    finally:
        release_delivery.set()
        run.cancel()
        assert run.wait_for_idle(3)


def test_identical_answer_retry_restarts_after_thread_start_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    effects: list[str] = []

    def effect(_invocation: ToolInvocation) -> ToolResult:
        effects.append("sent")
        return ToolResult(content="sent")

    agent = Agent(
        _model([ToolCall(id="effect", name="effect", arguments={})]),
        tools=[AgentTool(name="effect", description="", parameters={}, execute=effect)],
        before_tool_call=_gate,
    )
    run = agent.start(max_steps=2)
    assert run.wait_until_settled(3).status == RunStatus.SUSPENDED
    assert run.wait_for_idle(3)

    def fail_start(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("Thread capacity temporarily unavailable")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(runtime, "start_thread_with_context", fail_start)
            with pytest.raises(RuntimeError, match="temporarily unavailable"):
                run.submit(_approve())
        snapshot = run.snapshot()
        assert snapshot.progress is not None
        assert snapshot.progress.answers["permission"] == _approve()
        assert snapshot.status == RunStatus.SUSPENDED
        assert effects == []
        run.submit(_approve())
        assert run.result(timeout=3).output.text == "done"
        assert effects == ["sent"]
    finally:
        run.cancel()
        assert run.wait_for_idle(3)


def test_cold_question_resume_uses_answer_without_repeating_tool() -> None:
    question_calls: list[str] = []

    def make_agent(context: AgentContext) -> Agent:
        def question(_invocation: ToolInvocation) -> PendingToolInput:
            question_calls.append("asked")
            return PendingToolInput(
                request_id="question", prompt="Which?", mode=InputMode.RESULT
            )

        return Agent(
            _model([ToolCall(id="question", name="question", arguments={})]),
            agent_id="question-agent",
            context=context,
            tools=[
                AgentTool(
                    name="question", description="", parameters={}, execute=question
                )
            ],
        )

    agent = make_agent(AgentContext())
    run = agent.start(max_steps=2)
    assert run.wait_until_settled(3).status == RunStatus.SUSPENDED
    assert run.wait_for_idle(3)
    captured = agent.capture()
    serialized = SnapshotCodec({}).encode(
        captured.snapshot,
        captured.context,
        CheckpointBinding(
            tenant_id="tenant", branch_id="branch", context_version="history"
        ),
    )
    del captured, run, agent
    restored = SnapshotCodec({}).decode(serialized)
    agent = make_agent(restored.context)
    resumed = agent.resume(restored.snapshot)
    assert resumed.wait_until_settled(3).status == RunStatus.SUSPENDED
    try:
        resumed.submit(
            ToolAnswer(
                request_id="question",
                decision=InputDecision.RESULT,
                result=ToolResult(content="selected"),
            )
        )
        assert resumed.result(timeout=3).output.text == "done"
        assert question_calls == ["asked"]
    finally:
        resumed.cancel()
        assert resumed.wait_for_idle(3)


def test_cold_resume_retains_consumed_answer_identity_and_rejects_conflict() -> None:
    effects: list[str] = []

    def make_agent(context: AgentContext) -> Agent:
        def generate(
            request: GenerationRequest, _signal: CancellationSignal
        ) -> AssistantMessage:
            results = [
                message
                for message in request.messages
                if isinstance(message, ToolResultMessage)
            ]
            if not results:
                return AssistantMessage(
                    content=[ToolCall(id="effect", name="effect", arguments={})]
                )
            if len(results) == 1:
                return AssistantMessage(
                    content=[ToolCall(id="question", name="question", arguments={})]
                )
            return AssistantMessage(content=[TextContent(text="done")])

        def effect(_invocation: ToolInvocation) -> ToolResult:
            effects.append("sent")
            return ToolResult(content="sent")

        def question(_invocation: ToolInvocation) -> PendingToolInput:
            return PendingToolInput(
                request_id="question", prompt="Which?", mode=InputMode.RESULT
            )

        return Agent(
            FakeModelClient(generate),
            agent_id="agent",
            context=context,
            tools=[
                AgentTool(name="effect", description="", parameters={}, execute=effect),
                AgentTool(
                    name="question", description="", parameters={}, execute=question
                ),
            ],
            before_tool_call=_gate,
        )

    agent = make_agent(AgentContext())
    run = agent.start(max_steps=3)
    assert run.wait_until_settled(3).status == RunStatus.SUSPENDED
    run.submit(_approve())
    assert run.wait_until_settled(3).status == RunStatus.SUSPENDED
    assert run.wait_for_idle(3)
    captured = agent.capture()
    serialized = SnapshotCodec({}).encode(
        captured.snapshot,
        captured.context,
        CheckpointBinding(
            tenant_id="tenant", branch_id="branch", context_version="history"
        ),
    )
    del captured, run, agent
    restored = SnapshotCodec({}).decode(serialized)
    agent = make_agent(restored.context)
    resumed = agent.resume(restored.snapshot)
    assert resumed.wait_until_settled(3).status == RunStatus.SUSPENDED
    try:
        resumed.submit(_approve())
        with pytest.raises(ValueError, match="Conflicting"):
            resumed.submit(
                ToolAnswer(request_id="permission", decision=InputDecision.DENY)
            )
        resumed.submit(
            ToolAnswer(
                request_id="question",
                decision=InputDecision.RESULT,
                result=ToolResult(content="selected"),
            )
        )
        assert resumed.result(timeout=3).output.text == "done"
        assert effects == ["sent"]
    finally:
        resumed.cancel()
        assert resumed.wait_for_idle(3)


def test_last_step_rejects_steering_after_model_input_is_closed() -> None:
    generating = threading.Event()
    release_generation = threading.Event()

    def generate(
        _request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        generating.set()
        assert release_generation.wait(3)
        return AssistantMessage(content=[TextContent(text="done")])

    agent = Agent(FakeModelClient(generate))
    run = agent.start(max_steps=1)
    try:
        assert generating.wait(3)
        with pytest.raises(ValueError, match="steps remain"):
            run.steer(UserMessage(content="This cannot reach another model call"))
        release_generation.set()
        assert run.result(timeout=3).output.text == "done"
        progress = run.snapshot().progress
        assert progress is not None
        assert progress.steering == []
    finally:
        release_generation.set()
        run.cancel()
        assert run.wait_for_idle(3)


class _FailingRestoration(FeatureRestoration):
    def capture_state(self) -> BaseModel:
        raise RuntimeError("Feature state could not be captured")

    def restore_state(self, state: BaseModel) -> None:
        raise AssertionError(f"Unexpected restore: {state}")


def test_feature_capture_failure_finishes_run_and_releases_work() -> None:
    def question(_invocation: ToolInvocation) -> PendingToolInput:
        return PendingToolInput(
            request_id="question", prompt="Which?", mode=InputMode.RESULT
        )

    agent = Agent(
        _model([ToolCall(id="question", name="question", arguments={})]),
        tools=[
            AgentTool(name="question", description="", parameters={}, execute=question)
        ],
        restoration=_FailingRestoration(),
    )
    run = agent.start(max_steps=2)
    snapshot = run.wait_until_settled(3)
    assert snapshot.status == RunStatus.ERROR
    assert snapshot.failure is not None
    assert snapshot.failure.kind == RunFailureKind.EXECUTION
    with pytest.raises(RunFailed):
        run.result(timeout=3)
    assert run.wait_for_idle(3)


def test_resume_after_completed_step_does_not_repeat_completion_callback() -> None:
    entered = threading.Event()
    release = threading.Event()
    completed_steps: list[int] = []

    def complete(result: StepResult) -> bool:
        completed_steps.append(result.step.index)
        entered.set()
        assert release.wait(2)
        return False

    agent = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(content=[TextContent(text="finished")])
        ),
        after_step=complete,
    )
    run = agent.start(max_steps=1)
    try:
        assert entered.wait(2)
        run.suspend()
        release.set()
        assert run.wait_until_settled(2).status == RunStatus.SUSPENDED
        captured = agent.handoff()
        serialized = SnapshotCodec({}).encode(
            captured.snapshot,
            captured.context,
            CheckpointBinding(
                tenant_id="tenant", branch_id="branch", context_version="version"
            ),
        )
        restored = SnapshotCodec({}).decode(serialized)
        replacement = Agent(
            FakeModelClient(
                lambda *_: pytest.fail("Completed generation must not repeat")
            ),
            context=restored.context,
            agent_id=restored.snapshot.agent_id,
            after_step=lambda _: pytest.fail("Completed callback must not repeat"),
        )
        resumed = replacement.resume(restored.snapshot)
        assert resumed.result(2).output.text == "finished"
        assert resumed.wait_for_idle(2)
        assert completed_steps == [0]
    finally:
        release.set()
        run.cancel()
        assert run.wait_for_idle(2)


def test_execute_releases_caller_on_suspension_and_finalizes_on_resumed_worker() -> (
    None
):
    caller = threading.current_thread()
    finalized = threading.Event()
    terminal_threads: list[threading.Thread] = []
    agent = Agent(
        _model([ToolCall(id="effect", name="effect", arguments={})]),
        tools=[
            AgentTool(
                name="effect",
                description="",
                parameters={},
                execute=lambda _: ToolResult(content="sent"),
            )
        ],
        before_tool_call=_gate,
    )

    def terminal(_run: Run) -> None:
        terminal_threads.append(threading.current_thread())
        finalized.set()

    run = agent.execute(max_steps=2, on_terminal=terminal)
    assert run.status == RunStatus.SUSPENDED
    assert run.wait_for_idle(3)
    assert not finalized.is_set()
    run.submit(_approve())
    assert run.result(3).output.text == "done"
    assert finalized.wait(3)
    assert len(terminal_threads) == 1
    assert terminal_threads[0] is not caller
    assert run.wait_for_idle(3)


def test_transferred_cancel_does_not_run_slow_finalizer_on_control_thread() -> None:
    caller = threading.current_thread()
    entered, release = threading.Event(), threading.Event()
    terminal_threads: list[threading.Thread] = []
    coordinator = AgentCoordinator()
    agent = Agent(
        _model([ToolCall(id="effect", name="effect", arguments={})]),
        tools=[
            AgentTool(
                name="effect",
                description="",
                parameters={},
                execute=lambda _: ToolResult(content="sent"),
            )
        ],
        before_tool_call=_gate,
    )

    def terminal(_run: Run) -> None:
        terminal_threads.append(threading.current_thread())
        entered.set()
        assert release.wait(3)

    run = agent.execute(max_steps=2, coordinator=coordinator, on_terminal=terminal)
    assert run.wait_for_idle(3)
    agent.handoff()
    try:
        run.cancel()
        assert entered.wait(3)
        assert len(terminal_threads) == 1
        assert terminal_threads[0] is not caller
        assert run.status == RunStatus.CANCELLED
    finally:
        release.set()
        assert coordinator.close(3)
