"""Input ownership across active tools, suspension drain, and fresh execution."""

import gc
import threading
import weakref
from collections.abc import Mapping

import pytest
from pydantic import BaseModel, Field, JsonValue

import onyx.agents.runtime as runtime
from onyx.agents.agent_coordination import AgentCoordinator
from onyx.agents.events import AgentEvent, AgentSuspendedEvent, InputRequiredEvent
from onyx.agents.models import (
    AgentState,
    ExecutionCheckpoint,
    PreparedStep,
    RunFailureKind,
    RunStatus,
    StepInput,
    StepResult,
    ToolCallContext,
)
from onyx.agents.runtime import Agent, RestorableFeature, Run, RunFailed, RunReleased
from onyx.agents.tools import (
    AgentTool,
    HumanToolAnswer,
    InputDecision,
    InputMode,
    PendingToolInput,
    ToolInvocation,
)
from onyx.chat.models import CheckpointBinding
from onyx.llm.cancellation import CancellationSignal
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
from tests.unit.onyx.agents.checkpoint_storage import CheckpointStorage
from tests.unit.onyx.agents.fakes import FakeModelClient, FakeRunOwnership, FakeRunStore


def _approve(request_id: str = "permission") -> HumanToolAnswer:
    return HumanToolAnswer(request_id=request_id, decision=InputDecision.APPROVE)


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


def test_prepared_tool_selection_survives_json_handoff_without_repreparation() -> None:
    effects: list[str] = []
    prepared_steps: list[int] = []
    reservations: set[str] = set()

    def register(run: Run) -> None:
        assert run.id not in reservations
        reservations.add(run.id)

    coordinator = AgentCoordinator(
        ownership=FakeRunOwnership(register=register, release=reservations.remove)
    )

    def execute(_invocation: ToolInvocation) -> ToolResult:
        effects.append("sent")
        return ToolResult(content="sent")

    def unexpected(_invocation: ToolInvocation) -> ToolResult:
        pytest.fail("Unselected tool must not execute")

    def make_agent(state: AgentState) -> Agent:
        selected = AgentTool(
            definition=ToolDefinition(name="effect", description="", parameters={}),
            execute=execute,
        )
        unselected = AgentTool(
            definition=ToolDefinition(name="unused", description="", parameters={}),
            execute=unexpected,
        )

        def prepare(step: StepInput) -> PreparedStep:
            prepared_steps.append(step.step.index)
            return PreparedStep(tools=[selected] if step.step.index == 0 else [])

        return Agent(
            _model([ToolCall(id="effect", name="effect", arguments={})]),
            generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
            agent_id="agent",
            state=state,
            tools=[selected, unselected],
            prepare_step=prepare,
            before_tool_call=_gate,
        )

    run = make_agent(AgentState()).start(max_steps=2, coordinator=coordinator)
    try:
        assert run.wait_until_settled(3).status == RunStatus.SUSPENDED
        assert run.wait_for_idle(3)
        checkpoint = ExecutionCheckpoint.model_validate_json(
            run.handoff().model_dump_json()
        )
        assert not reservations
        restored = make_agent(checkpoint.agent_state).resume(
            checkpoint.run_state, coordinator=coordinator
        )
        try:
            assert restored.wait_until_settled(3).status == RunStatus.SUSPENDED
            assert prepared_steps == [0]
            restored.submit(_approve())
            assert restored.result(3).output.text == "done"
            assert effects == ["sent"]
            assert prepared_steps == [0, 1]
        finally:
            restored.cancel()
            assert restored.wait_for_idle(3)
    finally:
        run.cancel()
        assert run.wait_for_idle(3)
        assert coordinator.close(3)
        assert not reservations


def test_handoff_release_failure_settles_waiters_after_saving() -> None:
    saved: list[ExecutionCheckpoint] = []
    released: list[str] = []
    finished = threading.Event()
    failure = RuntimeError("Ownership release failed")

    def release(run_id: str) -> None:
        released.append(run_id)
        raise failure

    coordinator = AgentCoordinator(ownership=FakeRunOwnership(release=release))
    agent = Agent(
        _model([ToolCall(id="effect", name="effect", arguments={})]),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        tools=[
            AgentTool(
                definition=ToolDefinition(name="effect", description="", parameters={}),
                execute=lambda _: ToolResult(content="sent"),
            )
        ],
        before_tool_call=_gate,
    )
    run = agent.start(max_steps=2, coordinator=coordinator)
    try:
        assert run.wait_until_settled(3).status == RunStatus.SUSPENDED
        assert run.wait_for_idle(3)
        run.add_done_callback(finished.set)
        with pytest.raises(RuntimeError) as raised:
            run.handoff(save=saved.append)
        assert raised.value is failure
        assert released == [run.id]
        assert len(saved) == 1 and saved[0].run_state.status == RunStatus.SUSPENDED
        assert finished.is_set() and run.is_done
        assert coordinator.active_run(agent.id) is None
        with pytest.raises(RuntimeError) as result_error:
            run.result(0)
        assert result_error.value is failure
        assert run._reusable.done()
        with pytest.raises(RuntimeError) as reuse_error:
            run.wait_until_reusable(CancellationSignal())
        assert reuse_error.value is failure
    finally:
        assert coordinator.close(3)


@pytest.mark.parametrize("registered", [False, True])
def test_preparation_rejects_unregistered_implementation_before_generation(
    registered: bool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def unexpected(
        _request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        pytest.fail("Invalid tool configuration must not reach the model")

    tool = AgentTool(
        definition=ToolDefinition(name="effect", description="", parameters={}),
        execute=lambda _: ToolResult(content="sent"),
    )
    run = Agent(
        FakeModelClient(unexpected),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        tools=[tool] if registered else [],
        prepare_step=lambda _: PreparedStep(tools=[tool.snapshot()]),
    ).start(background=False, max_steps=1)
    try:
        with pytest.raises(RunFailed):
            run.result(3)
        assert run.snapshot().steps == []
        assert "must be registered in Agent.tools" in caplog.text
    finally:
        run.cancel()
        assert run.wait_for_idle(3)


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
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        tools=[
            AgentTool(
                definition=ToolDefinition(name="search", description="", parameters={}),
                execute=sibling,
            ),
            AgentTool(
                definition=ToolDefinition(name="effect", description="", parameters={}),
                execute=effect,
            ),
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
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        tools=[
            AgentTool(
                definition=ToolDefinition(name="effect", description="", parameters={}),
                execute=effect,
            )
        ],
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
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        tools=[
            AgentTool(
                definition=ToolDefinition(name="effect", description="", parameters={}),
                execute=effect,
            )
        ],
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
        assert snapshot.progress.human_tool_answers["permission"] == _approve()
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

    def make_agent(context: AgentState) -> Agent:
        def question(_invocation: ToolInvocation) -> PendingToolInput:
            question_calls.append("asked")
            return PendingToolInput(
                request_id="question", prompt="Which?", mode=InputMode.RESULT
            )

        return Agent(
            _model([ToolCall(id="question", name="question", arguments={})]),
            generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
            agent_id="question-agent",
            state=context,
            tools=[
                AgentTool(
                    definition=ToolDefinition(
                        name="question", description="", parameters={}
                    ),
                    execute=question,
                )
            ],
        )

    agent = make_agent(AgentState())
    run = agent.start(max_steps=2)
    assert run.wait_until_settled(3).status == RunStatus.SUSPENDED
    assert run.wait_for_idle(3)
    captured = run.capture()
    serialized = CheckpointStorage({}).save(
        captured.run_state,
        captured.agent_state,
        CheckpointBinding(tenant_id="tenant", response_id=captured.run_state.run_id),
    )
    del captured, run, agent
    restored = CheckpointStorage({}).load(serialized)
    agent = make_agent(restored.agent_state)
    resumed = agent.resume(restored.run_state)
    assert resumed.wait_until_settled(3).status == RunStatus.SUSPENDED
    try:
        resumed.submit(
            HumanToolAnswer(
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

    def make_agent(context: AgentState) -> Agent:
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
            generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
            agent_id="agent",
            state=context,
            tools=[
                AgentTool(
                    definition=ToolDefinition(
                        name="effect", description="", parameters={}
                    ),
                    execute=effect,
                ),
                AgentTool(
                    definition=ToolDefinition(
                        name="question", description="", parameters={}
                    ),
                    execute=question,
                ),
            ],
            before_tool_call=_gate,
        )

    agent = make_agent(AgentState())
    run = agent.start(max_steps=3)
    assert run.wait_until_settled(3).status == RunStatus.SUSPENDED
    run.submit(_approve())
    assert run.wait_until_settled(3).status == RunStatus.SUSPENDED
    assert run.wait_for_idle(3)
    captured = run.capture()
    serialized = CheckpointStorage({}).save(
        captured.run_state,
        captured.agent_state,
        CheckpointBinding(tenant_id="tenant", response_id=captured.run_state.run_id),
    )
    del captured, run, agent
    restored = CheckpointStorage({}).load(serialized)
    agent = make_agent(restored.agent_state)
    resumed = agent.resume(restored.run_state)
    assert resumed.wait_until_settled(3).status == RunStatus.SUSPENDED
    try:
        resumed.submit(_approve())
        with pytest.raises(ValueError, match="Conflicting"):
            resumed.submit(
                HumanToolAnswer(request_id="permission", decision=InputDecision.DENY)
            )
        resumed.submit(
            HumanToolAnswer(
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


class _FailingRestoration(RestorableFeature):
    def capture_state(self) -> BaseModel:
        raise RuntimeError("Feature state could not be captured")

    def restore_state(self, state: Mapping[str, JsonValue]) -> None:
        raise AssertionError(f"Unexpected restore: {state}")


class _FeatureState(BaseModel):
    next_citation: int = 0
    sources: dict[str, list[str]] = Field(default_factory=dict)


class _StatefulFeature(RestorableFeature):
    def __init__(self) -> None:
        self.state = _FeatureState()

    def capture_state(self) -> _FeatureState:
        return self.state

    def restore_state(self, state: Mapping[str, JsonValue]) -> None:
        self.state = _FeatureState.model_validate(state)

    def execute(self, _invocation: ToolInvocation) -> ToolResult:
        return ToolResult(
            content=f"{self.state.next_citation}: {self.state.sources['search'][0]}"
        )


def test_json_checkpoint_restores_feature_fields_before_resuming_tools() -> None:
    def make_agent(feature: _StatefulFeature, state: AgentState) -> Agent:
        def generate(
            request: GenerationRequest, _signal: CancellationSignal
        ) -> AssistantMessage:
            last = request.messages[-1]
            if isinstance(last, ToolResultMessage):
                return AssistantMessage(content=[TextContent(text=last.content)])
            return AssistantMessage(
                content=[ToolCall(id="effect", name="effect", arguments={})]
            )

        return Agent(
            FakeModelClient(generate),
            generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
            agent_id="stateful-agent",
            state=state,
            tools=[
                AgentTool(
                    definition=ToolDefinition(
                        name="effect", description="", parameters={}
                    ),
                    execute=feature.execute,
                )
            ],
            before_tool_call=_gate,
            restoration=feature,
        )

    original = _StatefulFeature()
    original.state = _FeatureState(next_citation=7, sources={"search": ["retained"]})
    agent = make_agent(original, AgentState())
    run = agent.start(messages=[UserMessage(content="Find evidence")], max_steps=2)
    try:
        assert run.wait_until_settled(3).status == RunStatus.SUSPENDED
        assert run.wait_for_idle(3)
        original.state.next_citation = 99
        original.state.sources["search"].append("changed")
        encoded = run.handoff().model_dump_json()
    finally:
        run.cancel()
        assert run.wait_for_idle(3)
    del original, agent, run

    checkpoint = ExecutionCheckpoint.model_validate_json(encoded)
    feature = _StatefulFeature()
    agent = make_agent(feature, checkpoint.agent_state)
    resumed = agent.resume(checkpoint.run_state)
    try:
        assert resumed.wait_until_settled(3).status == RunStatus.SUSPENDED
        resumed.submit(_approve())
        assert resumed.result(timeout=3).output.text == "7: retained"
        assert feature.state == _FeatureState(
            next_citation=7, sources={"search": ["retained"]}
        )
        feature.state.next_citation = 99
        feature.state.sources["search"].append("changed")
        progress = resumed.snapshot().progress
        assert progress is not None
        assert progress.feature_state == {
            "next_citation": 7,
            "sources": {"search": ["retained"]},
        }
    finally:
        resumed.cancel()
        assert resumed.wait_for_idle(3)


def test_feature_capture_failure_finishes_run_and_releases_work() -> None:
    def question(_invocation: ToolInvocation) -> PendingToolInput:
        return PendingToolInput(
            request_id="question", prompt="Which?", mode=InputMode.RESULT
        )

    agent = Agent(
        _model([ToolCall(id="question", name="question", arguments={})]),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        tools=[
            AgentTool(
                definition=ToolDefinition(
                    name="question", description="", parameters={}
                ),
                execute=question,
            )
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
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        after_step=complete,
    )
    run = agent.start(max_steps=1)
    try:
        assert entered.wait(2)
        run.suspend()
        release.set()
        assert run.wait_until_settled(2).status == RunStatus.SUSPENDED
        captured = run.handoff()
        serialized = CheckpointStorage({}).save(
            captured.run_state,
            captured.agent_state,
            CheckpointBinding(
                tenant_id="tenant", response_id=captured.run_state.run_id
            ),
        )
        restored = CheckpointStorage({}).load(serialized)
        replacement = Agent(
            FakeModelClient(
                lambda *_: pytest.fail("Completed generation must not repeat")
            ),
            generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
            state=restored.agent_state,
            agent_id=restored.run_state.agent_id,
            after_step=lambda _: pytest.fail("Completed callback must not repeat"),
        )
        resumed = replacement.resume(restored.run_state)
        assert resumed.result(2).output.text == "finished"
        assert resumed.wait_for_idle(2)
        assert completed_steps == [0]
    finally:
        release.set()
        run.cancel()
        assert run.wait_for_idle(2)


def test_current_thread_start_returns_on_suspension_and_resumes_on_worker() -> None:
    caller = threading.current_thread()
    finalized = threading.Event()
    terminal_threads: list[threading.Thread] = []
    agent = Agent(
        _model([ToolCall(id="effect", name="effect", arguments={})]),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        tools=[
            AgentTool(
                definition=ToolDefinition(name="effect", description="", parameters={}),
                execute=lambda _: ToolResult(content="sent"),
            )
        ],
        before_tool_call=_gate,
    )

    def terminal(_run: Run) -> None:
        terminal_threads.append(threading.current_thread())
        finalized.set()

    run = agent.start(
        background=False,
        max_steps=2,
        coordinator=AgentCoordinator(store=FakeRunStore(save=terminal)),
    )
    assert run.status == RunStatus.SUSPENDED
    assert run.wait_for_idle(3)
    assert not finalized.is_set()
    run.submit(_approve())
    assert run.result(3).output.text == "done"
    assert finalized.wait(3)
    assert len(terminal_threads) == 1
    assert terminal_threads[0] is not caller
    assert run.wait_for_idle(3)


def test_released_run_does_not_save_terminal_output() -> None:
    coordinator = AgentCoordinator()
    agent = Agent(
        _model([ToolCall(id="effect", name="effect", arguments={})]),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        tools=[
            AgentTool(
                definition=ToolDefinition(name="effect", description="", parameters={}),
                execute=lambda _: ToolResult(content="sent"),
            )
        ],
        before_tool_call=_gate,
    )
    terminals: list[Run] = []
    coordinator = AgentCoordinator(store=FakeRunStore(save=terminals.append))
    run = agent.start(
        background=False,
        max_steps=2,
        coordinator=coordinator,
    )
    assert run.wait_for_idle(3)
    saved = run.handoff()
    run.cancel()
    assert terminals == []
    assert run.snapshot() == saved.run_state
    assert coordinator.close(3)


@pytest.mark.parametrize("save_fails", [False, True])
def test_checkpoint_save_precedes_local_release(save_fails: bool) -> None:
    effects: list[str] = []

    def effect(_invocation: ToolInvocation) -> ToolResult:
        effects.append("sent")
        return ToolResult(content="sent")

    coordinator = AgentCoordinator()
    agent = Agent(
        _model([ToolCall(id="effect", name="effect", arguments={})]),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        tools=[
            AgentTool(
                definition=ToolDefinition(name="effect", description="", parameters={}),
                execute=effect,
            )
        ],
        before_tool_call=_gate,
    )
    run = agent.start(background=False, max_steps=2, coordinator=coordinator)
    assert run.wait_for_idle(3)
    captured = run.capture()
    saved: list[ExecutionCheckpoint] = []

    def save(checkpoint: ExecutionCheckpoint) -> None:
        assert coordinator.run(run.id) is run
        assert checkpoint == captured
        if save_fails:
            raise OSError("Storage unavailable")
        saved.append(checkpoint)

    try:
        if save_fails:
            with pytest.raises(OSError, match="Storage unavailable"):
                run.handoff(expected_revision=captured.run_state.revision, save=save)
            assert coordinator.run(run.id) is run
            run.submit(_approve())
            assert run.result(3).output.text == "done"
            assert effects == ["sent"]
            assert saved == []
        else:
            run.handoff(expected_revision=captured.run_state.revision, save=save)
            assert saved == [captured]
            with pytest.raises(ValueError, match="not owned"):
                coordinator.run(run.id)
            with pytest.raises(RunReleased):
                run.submit(_approve())
            assert effects == []
    finally:
        assert coordinator.close(3)


def test_explicit_suspension_blocks_dependency_wakeup_until_resume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    effects: list[str] = []

    def effect(_invocation: ToolInvocation) -> ToolResult:
        effects.append("sent")
        return ToolResult(content="sent")

    agent = Agent(
        _model([ToolCall(id="effect", name="effect", arguments={})]),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        tools=[
            AgentTool(
                definition=ToolDefinition(name="effect", description="", parameters={}),
                execute=effect,
            )
        ],
        before_tool_call=_gate,
    )
    run = agent.start(max_steps=2)
    try:
        assert run.wait_until_settled(3).status == RunStatus.SUSPENDED
        assert run.wait_for_idle(3)
        run.suspend()

        def unexpected_launch(*, background: bool) -> None:
            pytest.fail(
                f"Dependency notification launched suspended execution ({background=})"
            )

        with monkeypatch.context() as patch:
            patch.setattr(run, "_start_execution", unexpected_launch)
            # Child completion uses this notification, independently of user input.
            run._wake_execution()
        assert run.status == RunStatus.SUSPENDED
        assert effects == []
        run.submit(_approve())
        assert run.result(timeout=3).output.text == "done"
        assert effects == ["sent"]
    finally:
        run.cancel()
        assert run.wait_for_idle(3)


def test_run_can_capture_and_release_without_its_creating_agent() -> None:
    agent = Agent(
        _model([ToolCall(id="effect", name="effect", arguments={})]),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        state=AgentState(messages=[UserMessage(content="Earlier context")]),
        tools=[
            AgentTool(
                definition=ToolDefinition(name="effect", description="", parameters={}),
                execute=lambda _: ToolResult(content="sent"),
            )
        ],
        before_tool_call=_gate,
    )
    reference = weakref.ref(agent)
    run = agent.start(messages=[UserMessage(content="Send it")], max_steps=2)
    try:
        assert run.wait_until_settled(3).status == RunStatus.SUSPENDED
        assert run.wait_for_idle(3)
        del agent
        gc.collect()
        assert reference() is None
        captured = run.capture()
        assert [message.text for message in captured.agent_state.messages] == [
            "Earlier context"
        ]
        assert [message.text for message in captured.run_state.input_messages] == [
            "Send it"
        ]
        released = run.handoff(expected_revision=captured.run_state.revision)
        assert released == captured
        with pytest.raises(RunReleased):
            run.result(0)
    finally:
        run.cancel()
        assert run.wait_for_idle(3)
