"""Input ownership across active tools, suspension drain, and fresh execution."""

import gc
import threading
import weakref

import pytest
from pydantic import BaseModel

import onyx.agents.runtime as runtime
from onyx.agents.agent_coordination import AgentCoordinator
from onyx.agents.events import AgentEvent, AgentSuspendedEvent, InputRequiredEvent
from onyx.agents.execution_records import RunFailureKind, RunStatus
from onyx.agents.models import (
    AgentState,
    ExecutionCheckpoint,
    StepResult,
    ToolCallContext,
)
from onyx.agents.runtime import Agent, FeatureRestoration, Run, RunFailed, RunReleased
from onyx.agents.tools import (
    AgentTool,
    HumanToolAnswer,
    InputDecision,
    InputMode,
    PendingToolInput,
    ToolInvocation,
)
from onyx.chat.checkpoint import CheckpointBinding
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
from tests.unit.onyx.agents.checkpoint_storage import CheckpointStorage
from tests.unit.onyx.agents.fakes import FakeModelClient, FakeRunStore


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
            agent_id="question-agent",
            state=context,
            tools=[
                AgentTool(
                    name="question", description="", parameters={}, execute=question
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
        CheckpointBinding(
            tenant_id="tenant", branch_id="branch", context_version="history"
        ),
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
            agent_id="agent",
            state=context,
            tools=[
                AgentTool(name="effect", description="", parameters={}, execute=effect),
                AgentTool(
                    name="question", description="", parameters={}, execute=question
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
        CheckpointBinding(
            tenant_id="tenant", branch_id="branch", context_version="history"
        ),
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
        captured = run.handoff()
        serialized = CheckpointStorage({}).save(
            captured.run_state,
            captured.agent_state,
            CheckpointBinding(
                tenant_id="tenant", branch_id="branch", context_version="version"
            ),
        )
        restored = CheckpointStorage({}).load(serialized)
        replacement = Agent(
            FakeModelClient(
                lambda *_: pytest.fail("Completed generation must not repeat")
            ),
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
        tools=[AgentTool(name="effect", description="", parameters={}, execute=effect)],
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
        tools=[AgentTool(name="effect", description="", parameters={}, execute=effect)],
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
        state=AgentState(messages=[UserMessage(content="Earlier context")]),
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
