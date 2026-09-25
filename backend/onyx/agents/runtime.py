"""Stateful agents with one execution path and independent run records."""

import threading
from collections.abc import Callable, Sequence
from concurrent.futures import Future
from contextlib import ExitStack, closing
from contextvars import copy_context
from typing import TYPE_CHECKING, Literal, Protocol, TypedDict
from uuid import uuid4

from pydantic import BaseModel

from onyx.agents.compaction import (
    ContextLimitError,
    checkpoint_matches,
    compact_history,
    context_budget,
    request_tokens,
    working_messages,
)
from onyx.agents.concurrency import (
    OPERATION_TIMEOUT_SECONDS,
    EventDelivery,
    EventDispatcher,
    ExecutionWork,
)
from onyx.agents.events import (
    AgentEndEvent,
    AgentEvent,
    AgentStartEvent,
    AgentSuspendedEvent,
    MessageEndEvent,
    MessageStartEvent,
    MessageUpdateEvent,
)
from onyx.agents.execution_records import (
    OperationSnapshot,
    RunFailure,
    RunFailureKind,
    RunStatus,
)
from onyx.agents.models import (
    AgentState,
    AgentStep,
    ExecutionCheckpoint,
    ExecutionRequest,
    PreparedStep,
    RunAction,
    RunProgress,
    RunResult,
    RunState,
    StepInput,
    StepResult,
    ToolCallContext,
)
from onyx.agents.tool_execution import ToolBatch
from onyx.agents.tools import (
    AgentTool,
    HumanToolAnswer,
    InputDecision,
    InputMode,
    PendingToolInput,
)
from onyx.llm.cancellation import (
    AgentCancelled,
    CancellationSignal,
    cancellation_scope,
    current_cancellation,
)
from onyx.llm.exceptions import (
    ClassifiedLLMError,
    LLMContextLimitError,
    LLMErrorInfo,
    LLMRateLimitError,
    LLMTimeoutError,
    litellm_exception_to_safe_error,
)
from onyx.llm.interfaces import LLM, GenerationContext
from onyx.llm.models import (
    AssistantMessage,
    GenerationDoneEvent,
    GenerationOptions,
    GenerationRequest,
    GenerationStartEvent,
    Message,
    ToolResult,
    ToolResultMessage,
    apply_generation_event,
)
from onyx.llm.token_budget import resolve_token_budget
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import start_thread_with_context

if TYPE_CHECKING:
    from onyx.agents.agent_coordination import AgentCoordinator, RunCoordination

logger = setup_logger()


class _Ancestry(TypedDict):
    agent_id: str
    run_id: str
    parent_run_id: str | None
    parent_tool_call_id: str | None
    parent_message_id: str | None


class RunNotTransferable(RuntimeError):
    """Execution changed before its owner could release a suspended run."""


class RunReleased(RuntimeError):
    """Local execution ended at a saved checkpoint; use its run ID to resume."""


class RunFailed(RuntimeError):
    def __init__(self, failure: RunFailure) -> None:
        super().__init__(failure.message)
        self.failure = failure.model_copy(deep=True)


def _failure(error: Exception, llm: LLM) -> RunFailure:
    if isinstance(error, RunFailed):
        return error.failure.model_copy(deep=True)
    if isinstance(error, ClassifiedLLMError):
        info = LLMErrorInfo(
            message=llm.redact_error(error.client_error_msg),
            error_code=error.error_code,
            is_retryable=error.is_retryable,
        )
        return RunFailure(kind=RunFailureKind.LLM, message=info.message, llm_error=info)
    info = litellm_exception_to_safe_error(error, llm, fallback_to_error_msg=False)
    if isinstance(error, LLMTimeoutError):
        kind = RunFailureKind.LLM_TIMEOUT
    elif isinstance(error, LLMRateLimitError):
        kind = RunFailureKind.LLM_RATE_LIMIT
    elif isinstance(error, LLMContextLimitError):
        kind = RunFailureKind.LLM
    else:
        kind = RunFailureKind.EXECUTION
    return RunFailure(kind=kind, message=info.message, llm_error=info)


def result_from_snapshot(record: RunState) -> RunResult:
    if record.status == RunStatus.CANCELLED:
        raise AgentCancelled()
    if record.status == RunStatus.ERROR:
        if record.failure is None:
            raise ValueError("Failed run is missing failure classification")
        raise RunFailed(record.failure)
    if record.status not in (RunStatus.COMPLETE, RunStatus.LIMIT):
        raise ValueError("Run is not terminal")
    output = next(
        (
            message
            for message in reversed(record.messages)
            if isinstance(message, AssistantMessage)
        ),
        None,
    )
    if output is None or not record.operations:
        raise ValueError("Completed run is missing output or steps")
    return RunResult(
        run_id=record.run_id,
        steps=max(operation.step_index for operation in record.operations) + 1,
        stop_reason=record.status,
        output=output.model_copy(deep=True),
    )


def _capture_unsettled_child(state: RunState) -> RunState:
    """Retain accepted output after settlement fails without changing live execution."""
    snapshot = state.model_copy(deep=True)
    pending = [snapshot]
    while pending:
        record = pending.pop()
        pending.extend(record.child_runs)
        if record.status.is_terminal:
            continue
        record.status = RunStatus.ERROR
        record.failure = RunFailure(
            kind=RunFailureKind.EXECUTION,
            message="Child execution did not settle before its parent ended.",
        )
        for operation in record.operations:
            if operation.status == RunStatus.RUNNING:
                operation.status = RunStatus.ERROR
    return snapshot


class FeatureRestoration(Protocol):
    """Capture and restore feature-owned state at safe execution boundaries."""

    def capture_state(self) -> BaseModel: ...

    def restore_state(self, state: BaseModel) -> None: ...


class Agent:
    """A conversation with resolved model, tools, and optional step decisions."""

    def __init__(
        self,
        llm: LLM,
        *,
        state: AgentState | None = None,
        system_prompt: str = "",
        tools: Sequence[AgentTool] = (),
        options: GenerationOptions | None = None,
        generation_context: GenerationContext | None = None,
        prepare_step: Callable[[StepInput], PreparedStep] | None = None,
        after_step: Callable[[StepResult], bool] | None = None,
        before_tool_call: Callable[
            [ToolCallContext], ToolResult | PendingToolInput | None
        ]
        | None = None,
        after_tool_call: Callable[[ToolCallContext, ToolResult], ToolResult]
        | None = None,
        agent_id: str | None = None,
        previous_run_id: str | None = None,
        restoration: "FeatureRestoration | None" = None,
    ) -> None:
        self._id = agent_id or str(uuid4())
        self.llm = llm
        self.tools = list(tools)
        self.system_prompt = system_prompt
        self.options = options or GenerationOptions()
        self.generation_context = generation_context or GenerationContext()
        self.prepare_step = prepare_step
        self.after_step = after_step
        self.before_tool_call = before_tool_call
        self.after_tool_call = after_tool_call
        self.restoration = restoration
        self._state = (state or AgentState()).snapshot()
        self._previous_run_id = previous_run_id
        self._lock = threading.RLock()
        self._latest_run: Run | None = None

    @property
    def id(self) -> str:
        return self._id

    @property
    def state(self) -> AgentState:
        with self._lock:
            latest_run = self._latest_run
            if latest_run is None:
                return self._state.snapshot()
            with latest_run._lock:
                record = latest_run._state
                return AgentState(
                    messages=[
                        message.model_copy(deep=True)
                        for message in [
                            *latest_run._history.messages,
                            *record.input_messages,
                            *record.messages,
                        ]
                    ],
                    checkpoint=record.checkpoint.model_copy(deep=True)
                    if record.checkpoint
                    else None,
                )

    def start(
        self,
        *,
        max_steps: int,
        background: bool = True,
        messages: Sequence[Message] = (),
        cancellation: CancellationSignal | None = None,
        coordinator: "AgentCoordinator | None" = None,
        parent_run_id: str | None = None,
        parent_tool_call_id: str | None = None,
        parent_message_id: str | None = None,
        _event_parent: EventDelivery | None = None,
        on_event: Callable[[AgentEvent], None] | None = None,
        event_dispatcher: EventDispatcher | None = None,
        _snapshot: RunState | None = None,
    ) -> "Run":
        """Start a worker, or execute here until suspension or completion with background=False."""
        AgentStep(index=0, limit=max_steps)
        with self._lock:
            previous = self._latest_run
            if previous is not None:
                with previous._lock:
                    if previous._released:
                        raise RunReleased(
                            "Agent execution was released; restore it from saved state"
                        )
                    if (
                        not previous._state.status.is_terminal
                        or not previous._idle.done()
                    ):
                        raise RuntimeError("Agent is already running or draining")
                    previous._idle.result(timeout=0)
            history = self.state
            cancellation_signal = (
                cancellation
                or current_cancellation()
                or self.generation_context.cancellation
                or CancellationSignal()
            )
            run = Run(
                _snapshot.model_copy(deep=True)
                if _snapshot is not None
                else RunState(
                    progress=RunProgress(step_limit=max_steps),
                    run_id=str(uuid4()),
                    agent_id=self.id,
                    previous_run_id=previous.id if previous else self._previous_run_id,
                    parent_run_id=parent_run_id,
                    parent_tool_call_id=parent_tool_call_id,
                    parent_message_id=parent_message_id,
                    status=RunStatus.RUNNING,
                    input_messages=[
                        message.model_copy(deep=True) for message in messages
                    ],
                    messages=[],
                    checkpoint=history.checkpoint,
                ),
                cancellation_signal,
                event_dispatcher,
                history=history,
                event_parent=_event_parent,
            )
            self._latest_run = run
        if on_event is not None:
            run.subscribe(on_event)
        try:
            run._start(
                self,
                coordinator=coordinator,
                background=background,
            )
        except BaseException:
            with self._lock:
                self._latest_run = previous
            raise
        return run

    def resume(
        self,
        snapshot: RunState,
        *,
        coordinator: "AgentCoordinator | None" = None,
        on_event: Callable[[AgentEvent], None] | None = None,
    ) -> "Run":
        """Restore a suspended run after its previous owner has released execution."""
        if snapshot.status != RunStatus.SUSPENDED or snapshot.progress is None:
            raise ValueError("Only a suspended execution snapshot can resume")
        if snapshot.agent_id != self.id:
            raise ValueError("Snapshot belongs to another agent")
        return self.start(
            max_steps=snapshot.progress.step_limit,
            coordinator=coordinator,
            on_event=on_event,
            _snapshot=snapshot,
        )


class Run:
    """Own one run’s lifecycle, controls, and accepted output."""

    def __init__(
        self,
        state: RunState,
        cancellation_signal: CancellationSignal,
        event_dispatcher: EventDispatcher | None = None,
        *,
        history: AgentState | None = None,
        event_parent: EventDelivery | None = None,
    ) -> None:
        if state.agent_id is None:
            raise ValueError("Executable run requires an agent identity")
        self.id = state.run_id
        self.agent_id = state.agent_id
        self._lock = threading.RLock()
        self._state = state
        self._history = history.snapshot() if history is not None else AgentState()
        self._cancellation_signal = cancellation_signal
        self._completed: Future[None] = Future()
        self._idle: Future[None] = Future()
        self._delivery: EventDelivery | None = EventDelivery(
            event_dispatcher, parent=event_parent
        )
        self._delivery_failed = False
        self._execution_condition = threading.Condition(self._lock)
        self._settled: Future[None] = Future()
        # Reserve execution through cleanup, even after output becomes terminal.
        self._execution_active = True
        self._execution_request = ExecutionRequest.NONE
        self._watched_children: set[str] = set()
        self._llm: LLM | None = None
        self._defaults = PreparedStep()
        self._generation_context = GenerationContext()
        self._prepare_step: Callable[[StepInput], PreparedStep] | None = None
        self._after_step: Callable[[StepResult], bool] | None = None
        self._before_tool_call: (
            Callable[[ToolCallContext], ToolResult | PendingToolInput | None] | None
        ) = None
        self._after_tool_call: (
            Callable[[ToolCallContext, ToolResult], ToolResult] | None
        ) = None
        self._restoration: FeatureRestoration | None = None
        self._prepared_step: PreparedStep | None = None
        self._work = ExecutionWork()
        self._coordination: RunCoordination | None = None
        self._thread_context = copy_context()
        self._cancellation_link = ExitStack()
        self._released = False

    @classmethod
    def from_snapshot(cls, snapshot: RunState) -> "Run":
        """Reattach a terminal child result without starting execution."""
        if snapshot.status in (RunStatus.RUNNING, RunStatus.SUSPENDED):
            raise ValueError("Only terminal snapshots can become completed handles")
        run = cls(snapshot.model_copy(deep=True), CancellationSignal())
        run._delivery = None
        run._execution_active = False
        run._completed.set_result(None)
        run._idle.set_result(None)
        run._settled.set_result(None)
        return run

    @property
    def status(self) -> RunStatus:
        with self._lock:
            return self._state.status

    @property
    def pending_inputs(self) -> list[PendingToolInput]:
        """Copy unanswered tool requests without copying execution history."""
        with self._lock:
            progress = self._state.progress
            return (
                [
                    pending.model_copy(deep=True)
                    for pending in progress.pending_tool_calls.values()
                    if isinstance(pending, PendingToolInput)
                ]
                if progress is not None
                else []
            )

    @property
    def delivery_failed(self) -> bool:
        delivery = self._delivery
        return delivery.failed.is_set() if delivery else self._delivery_failed

    def snapshot(self) -> RunState:
        with self._lock:
            return self._state.model_copy(deep=True)

    def cancel(self) -> None:
        with self._lock:
            if self._released or self._completed.done():
                return
        self._cancellation_signal.cancel()
        self._wake_execution()

    def suspend(self) -> None:
        """Request suspension at the next safe execution boundary."""
        with self._execution_condition:
            if self._released:
                raise RunReleased("Run was released; deliver input through its run ID")
            if self._completed.done():
                raise ValueError("Cannot suspend a terminal run")
            self._execution_request = ExecutionRequest.SUSPEND
            self._execution_condition.notify_all()

    def resume(self) -> None:
        """Continue a resident suspended run without changing its identity."""
        with self._lock:
            if self._released:
                raise RunReleased("Resume the saved run state in a new Agent")
            if self._completed.done():
                raise ValueError("Cannot resume a terminal run")
            if self._llm is None:
                raise RuntimeError("Run has no execution owner")
            self._wake_execution(resume=True)

    def submit(self, answer: HumanToolAnswer) -> None:
        with self._execution_condition:
            if self._released:
                raise RunReleased("Run was released; deliver input through its run ID")
            progress = self._state.progress
            if progress is None:
                raise ValueError("Run has no input state")
            existing = progress.human_tool_answers.get(answer.request_id)
            if existing is not None:
                if existing != answer:
                    raise ValueError("Conflicting answer for request")
                if self._state.status.is_terminal:
                    return
            else:
                if self._state.status.is_terminal:
                    raise ValueError("Run is not accepting input")
                request = next(
                    (
                        pending
                        for pending in progress.pending_tool_calls.values()
                        if isinstance(pending, PendingToolInput)
                        and pending.request_id == answer.request_id
                    ),
                    None,
                )
                if request is None:
                    raise ValueError("Unknown input request")
                if (request.mode == InputMode.RESULT) != (
                    answer.decision == InputDecision.RESULT
                ):
                    raise ValueError("Answer does not match the request mode")
                progress.human_tool_answers[answer.request_id] = answer.model_copy(
                    deep=True
                )
                self._state.revision += 1
            self._wake_execution(resume=True)

    def result(self, timeout: float = OPERATION_TIMEOUT_SECONDS) -> RunResult:
        """Wait for terminal output; cleanup can still be in progress."""
        self._completed.result(timeout=timeout)
        return result_from_snapshot(self.snapshot())

    def wait_until_settled(
        self, timeout: float = OPERATION_TIMEOUT_SECONDS
    ) -> RunState:
        """Wait until execution suspends or finishes; this does not wait for user input."""
        with self._lock:
            settled = self._settled
        settled.result(timeout=timeout)
        return self.snapshot()

    def wait_for_idle(self, timeout: float = OPERATION_TIMEOUT_SECONDS) -> bool:
        delivery = self._delivery
        if delivery is not None and delivery.is_dispatch_thread:
            raise RuntimeError("An observer cannot wait for its own run to become idle")
        if timeout < 0:
            raise ValueError("Idle timeout must be nonnegative")
        try:
            self._idle.result(timeout=timeout)
        except TimeoutError:
            if not self._idle.done():
                return False
            self._idle.result(timeout=0)
        return True

    def subscribe(self, listener: Callable[[AgentEvent], None]) -> Callable[[], None]:
        delivery = self._delivery
        if delivery is None:
            return lambda: None
        return delivery.subscribe(listener)

    def add_idle_callback(self, callback: Callable[[], None]) -> None:
        """Call once owned work finishes; callbacks must not block."""
        self._idle.add_done_callback(lambda _future: callback())

    @property
    def _accepting(self) -> bool:
        return not self._released and not self._state.status.is_terminal

    @property
    def _ancestry(self) -> _Ancestry:
        run_state = self._state
        return _Ancestry(
            agent_id=self.agent_id,
            run_id=self.id,
            parent_run_id=run_state.parent_run_id,
            parent_tool_call_id=run_state.parent_tool_call_id,
            parent_message_id=run_state.parent_message_id,
        )

    @property
    def _progress(self) -> RunProgress:
        progress = self._state.progress
        if progress is None:
            raise RuntimeError("Execution requires recorded progress")
        return progress

    def _start(
        self,
        agent: "Agent",
        *,
        coordinator: "AgentCoordinator | None",
        background: bool,
    ) -> None:
        state = self._state
        with self._lock:
            self._state.status = RunStatus.RUNNING
        try:
            if state.progress is not None:
                feature_state = state.progress.feature_state
                if feature_state is not None:
                    if agent.restoration is None:
                        raise ValueError(
                            "Feature restoration is required for this state"
                        )
                    agent.restoration.restore_state(feature_state)
            self._llm = agent.llm
            self._defaults = PreparedStep(
                system_prompt=agent.system_prompt,
                tools=list(agent.tools),
                options=agent.options.model_copy(deep=True),
            )
            self._generation_context = agent.generation_context.model_copy(
                update={
                    "user_identity": agent.generation_context.user_identity.model_copy()
                    if agent.generation_context.user_identity
                    else None,
                }
            )
            self._prepare_step = agent.prepare_step
            self._after_step = agent.after_step
            self._before_tool_call = agent.before_tool_call
            self._after_tool_call = agent.after_tool_call
            self._restoration = agent.restoration
            self._work = ExecutionWork()
            self._thread_context = copy_context()
            self._cancellation_link = ExitStack()
            if coordinator is not None:
                self._coordination = coordinator.bind(self)
                coordinator.bind_agent(agent)
                if state.progress is not None:
                    self._coordination.attach_children(state.progress.child_run_ids)
                    self._coordination.observe_children(
                        state.progress.observed_child_run_ids
                    )
                coordinator.begin(self)
            self._cancellation_link.enter_context(
                self._cancellation_signal.on_cancel(self._wake_execution)
            )
            self._start_execution(background=background)
        except BaseException:
            self._cancellation_link.close()
            if self._coordination is not None:
                try:
                    self._coordination.coordinator.abort_start(self)
                except Exception:
                    logger.exception("Agent start registration rollback failed")
            if self._coordination is not None:
                self._coordination.release()
            if self._delivery is not None:
                self._delivery.close()
            raise

    def _start_execution(self, *, background: bool) -> None:
        with self._lock:
            resuming = not self._execution_active
            if resuming:
                self._idle = Future()
                self._settled = Future()
                self._work = ExecutionWork()
            self._execution_active = True
            self._state.status = RunStatus.RUNNING
            if self._delivery is not None:
                self._delivery.resume()
            if background:
                try:
                    start_thread_with_context(
                        lambda: self._execute(),
                        name="agent-run",
                        daemon=True,
                        context=self._thread_context.copy(),
                    )
                except BaseException:
                    if not resuming:
                        raise
                    self._execution_active = False
                    self._state.status = RunStatus.SUSPENDED
                    if self._delivery is not None:
                        self._delivery.pause()
                    self._idle.set_result(None)
                    self._settled.set_result(None)
                    raise
                return
        self._execute()

    def _wake_execution(self, *, resume: bool = False) -> None:
        with self._execution_condition:
            if not self._accepting or self._llm is None:
                return
            if resume or self._execution_request != ExecutionRequest.SUSPEND:
                self._execution_request = ExecutionRequest.WAKE
            self._execution_condition.notify_all()
            if not self._execution_active and (
                self._execution_request == ExecutionRequest.WAKE
                or self._cancellation_signal.cancelled
            ):
                self._start_execution(background=True)

    def _begin_work_cycle(self) -> bool:
        """Acknowledge pending wakeups and return whether new work may start."""
        with self._lock:
            self._cancellation_signal.check()
            if self._execution_request == ExecutionRequest.SUSPEND:
                return False
            self._execution_request = ExecutionRequest.NONE
            return True

    def _wait_for_tool_activity(self, completed: Callable[[], bool]) -> None:
        with self._execution_condition:
            ready = self._execution_condition.wait_for(
                lambda: (
                    self._cancellation_signal.cancelled
                    or self._execution_request == ExecutionRequest.WAKE
                    or completed()
                ),
                OPERATION_TIMEOUT_SECONDS,
            )
        if not ready:
            raise TimeoutError("Agent tool exceeded its execution bound")

    def _execute(self) -> None:
        llm = self._llm
        if llm is None:
            raise RuntimeError("Run has no execution owner")
        outcome = RunStatus.ERROR
        suspended = False
        try:
            with (
                cancellation_scope(self._cancellation_signal),
                self._cancellation_signal.on_operation(self._work.track_operation),
            ):
                self._cancellation_signal.check()
                if not self._state.messages:
                    self._publish_event(AgentStartEvent(**self._ancestry))
                boundary = _advance_steps(self, llm)
                if boundary == RunStatus.SUSPENDED or self._await_children():
                    self._suspend()
                    suspended = True
                    return
                outcome = boundary
        except AgentCancelled:
            outcome = RunStatus.CANCELLED
            self._cancellation_signal.cancel()
        except Exception as error:
            logger.exception("Agent run failed")
            with self._lock:
                self._state.failure = _failure(error, llm)
            self._cancellation_signal.cancel()
        finally:
            if not suspended:
                self._finish(outcome, llm)

    def _await_children(self) -> bool:
        """Suspend until foreground children finish, without occupying a worker."""
        if self._coordination is None:
            return False
        pending = self._coordination.pending_children()
        if pending:
            self._watch_children(pending)
            return True
        children = self._coordination.finish(cancel=False)
        with self._lock:
            self._state.child_runs = children
        return False

    def _watch_children(self, run_ids: list[str]) -> None:
        if self._coordination is None:
            raise RuntimeError("Child dependencies require a coordinator")
        coordinator = self._coordination.coordinator
        for run_id in run_ids:
            with self._lock:
                if run_id in self._watched_children:
                    continue
                self._watched_children.add(run_id)
            coordinator.completion(run_id).add_done_callback(
                lambda _future: self._wake_execution()
            )
            coordinator.observe_completion(run_id)

    def _suspend(self) -> None:
        if self._restoration is not None:
            feature_state = self._work.blocking(
                self._restoration.capture_state, self._cancellation_signal
            )
            with self._lock:
                self._progress.feature_state = feature_state.model_copy(deep=True)
        if self._coordination is not None:
            with self._lock:
                self._progress.child_run_ids = list(self._coordination.children)
                self._progress.observed_child_run_ids = (
                    self._coordination.observed_children()
                )
        idle = self._idle
        settled = self._settled

        def released() -> None:
            with self._lock:
                self._state.status = RunStatus.SUSPENDED
                self._state.revision += 1
                self._execution_active = False
                restart = (
                    self._execution_request == ExecutionRequest.WAKE
                    or self._cancellation_signal.cancelled
                )
            idle.set_result(None)
            settled.set_result(None)
            if restart:
                self._wake_execution()

        def drained() -> None:
            with self._lock:
                self._state.status = RunStatus.SUSPENDED
            self._publish_event(AgentSuspendedEvent(**self._ancestry))
            delivery = self._delivery
            if delivery is not None:
                delivery.pause()
                delivery.tracker.on_idle(released)
            else:
                released()

        self._work.tracker.on_idle(drained)

    def _finish(
        self,
        outcome: Literal[
            RunStatus.COMPLETE, RunStatus.LIMIT, RunStatus.CANCELLED, RunStatus.ERROR
        ],
        llm: LLM,
    ) -> None:
        self._cancellation_link.close()
        if self._coordination and outcome in (
            RunStatus.ERROR,
            RunStatus.CANCELLED,
        ):
            try:
                children = self._coordination.finish(cancel=True)
            except Exception as error:
                logger.exception("Child executions did not reach terminal output")
                outcome = RunStatus.ERROR
                children = [
                    _capture_unsettled_child(
                        self._coordination.coordinator.run_state(
                            child.run_id, self.agent_id
                        )
                    )
                    for child in self._coordination.children.values()
                ]
                with self._lock:
                    self._state.failure = _failure(error, llm)
            with self._lock:
                self._state.child_runs = children
        with self._lock:
            for operation in self._state.operations:
                if (
                    operation.tool_call_id is not None
                    or operation.status != RunStatus.RUNNING
                ):
                    continue
                partial = self._state.messages[operation.message_index]
                if isinstance(partial, AssistantMessage):
                    partial.stop_reason = (
                        "aborted" if outcome == RunStatus.CANCELLED else "error"
                    )
            self._record_terminal_outcome(outcome)
        self._completed.set_result(None)
        if not self._settled.done():
            self._settled.set_result(None)
        if self._delivery is not None:
            self._delivery.close()
        try:
            if self._coordination is not None:
                self._coordination.coordinator.complete(self)
        except Exception:
            logger.exception("Agent output persistence failed")
        finally:
            self._drain_workers()

    def _record_terminal_outcome(
        self,
        outcome: Literal[
            RunStatus.COMPLETE, RunStatus.LIMIT, RunStatus.CANCELLED, RunStatus.ERROR
        ],
    ) -> None:
        with self._lock:
            self._state.status = outcome
            answer_message_id = None
            if self._state.answer_message_index is not None:
                answer = self._state.messages[self._state.answer_message_index]
                if not isinstance(answer, AssistantMessage):
                    raise RuntimeError("Selected answer is not an assistant message")
                answer_message_id = answer.id
            terminal = AgentEndEvent(
                **self._ancestry,
                outcome=outcome,
                answer_message_id=answer_message_id,
            )
            for operation in self._state.operations:
                if operation.status == RunStatus.RUNNING:
                    operation.status = outcome
            if self._delivery:
                self._delivery.publish(terminal)
            self._state.revision += 1

    def _clear_execution_config(self) -> None:
        self._llm = None
        self._prepared_step = None
        self._defaults = PreparedStep()
        self._generation_context = GenerationContext()
        self._prepare_step = None
        self._after_step = None
        self._before_tool_call = None
        self._after_tool_call = None
        self._restoration = None

    def _drain_workers(self) -> None:
        delivery = self._delivery
        if delivery is not None:
            self._work.tracker.follow(delivery.tracker)

        def release() -> None:
            try:
                if delivery is not None:
                    self._delivery_failed = delivery.failed.is_set()
                    self._delivery = None
                if self._coordination is not None:
                    self._coordination._links.close()
                    self._coordination.coordinator.finish(self)
            except Exception as error:
                logger.exception("Agent ownership release failed")
                self._idle.set_exception(error)
            finally:
                self._clear_execution_config()
                self._coordination = None
                self._execution_active = False
                if not self._idle.done():
                    self._idle.set_result(None)

        self._work.tracker.on_idle(release)

    def capture(self) -> ExecutionCheckpoint:
        """Capture this run and its preceding conversation under one lock."""
        with self._lock:
            self._state.revision += 1
            return ExecutionCheckpoint(
                agent_state=self._history.snapshot(),
                run_state=self._state.model_copy(deep=True),
            )

    def handoff(
        self,
        *,
        expected_revision: int | None = None,
        save: Callable[[ExecutionCheckpoint], None] | None = None,
    ) -> ExecutionCheckpoint:
        """Save suspended state before releasing local execution ownership."""
        with self._lock:
            if (
                self._released
                or self._state.status != RunStatus.SUSPENDED
                or self._cancellation_signal.cancelled
                or self._execution_active
                or not self._idle.done()
            ):
                raise RunNotTransferable(
                    "Run must be suspended and idle before release"
                )
            if (
                expected_revision is not None
                and self._state.revision != expected_revision
            ):
                raise RunNotTransferable("Run changed while preparing its checkpoint")
            if self._coordination is not None:
                self._coordination.validate_handoff()
            checkpoint = ExecutionCheckpoint(
                agent_state=self._history.snapshot(),
                run_state=self._state.model_copy(deep=True),
            )
            if save is not None:
                save(checkpoint)
            self._released = True
            self._clear_execution_config()
            coordination = self._coordination
            self._coordination = None
            delivery = self._delivery
            self._delivery = None
        self._cancellation_link.close()
        if delivery is not None:
            delivery.close()
        if coordination is not None:
            coordination.coordinator.release_execution(self)
        self._completed.set_exception(RunReleased("Local execution has been released"))
        return checkpoint

    def _publish_event(self, event: AgentEvent) -> None:
        with self._lock:
            if not self._accepting:
                return
            if self._delivery:
                self._delivery.publish(event)


def _advance_steps(
    run: Run, llm: LLM
) -> Literal[RunStatus.COMPLETE, RunStatus.LIMIT, RunStatus.SUSPENDED]:
    cancellation_signal = run._cancellation_signal
    max_steps = run._progress.step_limit
    while run._progress.step_index < max_steps:
        cancellation_signal.check()
        progress = run._progress
        if progress.action == RunAction.FINISH:
            if not run._begin_work_cycle():
                return RunStatus.SUSPENDED
            if progress.outcome not in (
                RunStatus.COMPLETE,
                RunStatus.LIMIT,
            ):
                raise RuntimeError("Execution is missing its terminal decision")
            return progress.outcome
        if progress.action == RunAction.PREPARE:
            if not run._begin_work_cycle():
                return RunStatus.SUSPENDED
            previous = (
                _step_result(
                    run,
                    progress.previous_message_index,
                    progress.previous_options,
                    progress.step_index - 1,
                )
                if progress.previous_message_index is not None
                else None
            )
            decision = StepInput(
                history=[m.model_copy(deep=True) for m in run._history.messages],
                input_messages=[
                    m.model_copy(deep=True) for m in run._state.input_messages
                ],
                messages=[m.model_copy(deep=True) for m in run._state.messages],
                step=AgentStep(index=progress.step_index, limit=max_steps),
                previous=previous,
            )
            prepare = run._prepare_step
            prepared = (
                run._work.blocking(
                    lambda prepare=prepare, decision=decision: prepare(decision),
                    cancellation_signal,
                )
                if prepare
                else run._defaults
            )
            _generate_step(run, llm, prepared, decision.step)
        if progress.action == RunAction.TOOLS:
            if not _execute_tools(run):
                return RunStatus.SUSPENDED
        if progress.action == RunAction.AFTER_STEP:
            completed = _step_result(
                run,
                progress.message_index,
                progress.options,
                progress.step_index,
            )
            _complete_step(run, completed)
    raise RuntimeError("Run exhausted its steps without a terminal decision")


def _generate_step(run: Run, llm: LLM, prepared: PreparedStep, step: AgentStep) -> None:
    cancellation_signal = run._cancellation_signal
    if len({tool.name for tool in prepared.tools}) != len(prepared.tools):
        raise ValueError("Tool names must be unique")
    prepared = prepared.model_copy(
        update={
            "tools": [tool.snapshot() for tool in prepared.tools],
            "options": prepared.options.model_copy(deep=True),
            "output_metadata": prepared.output_metadata.model_copy(deep=True)
            if prepared.output_metadata
            else None,
        }
    )
    run._prepared_step = prepared
    generation_context = run._generation_context.model_copy(
        update={
            "cancellation": cancellation_signal,
            "stall_timeout_s": prepared.stall_timeout_s
            or run._generation_context.stall_timeout_s,
        }
    )
    source = [*run._history.messages, *run._state.input_messages, *run._state.messages]
    request = _fit_context(run, llm, source, prepared, generation_context)
    started = MessageStartEvent(
        **run._ancestry,
        step_index=step.index,
        metadata=prepared.output_metadata,
    )
    with run._lock:
        cancellation_signal.check()
        start = len(run._state.messages)
        run._state.messages.append(
            AssistantMessage(
                id=f"{run._state.run_id}:{step.index}",
                metadata=prepared.output_metadata.model_copy(deep=True)
                if prepared.output_metadata
                else None,
            )
        )
        generation = OperationSnapshot(
            step_index=step.index,
            message_index=start,
            status=RunStatus.RUNNING,
        )
        run._state.operations.append(generation)
        if run._delivery:
            run._delivery.publish(started)

    def generate() -> AssistantMessage:
        final: AssistantMessage | None = None
        try:
            with closing(llm.stream(request, generation_context)) as events:
                for event in events:
                    cancellation_signal.check()
                    with run._lock:
                        if not run._accepting:
                            raise AgentCancelled()
                        if event.request_params:
                            run._state.request_params = event.request_params.model_copy(
                                deep=True
                            )
                        message = run._state.messages[start]
                        if not isinstance(message, AssistantMessage):
                            raise RuntimeError(
                                "Generation must update an assistant message"
                            )
                        apply_generation_event(message, event)
                        if run._delivery and not isinstance(
                            event, (GenerationStartEvent, GenerationDoneEvent)
                        ):
                            run._delivery.publish(
                                MessageUpdateEvent(
                                    **run._ancestry,
                                    step_index=step.index,
                                    generation_event=event,
                                )
                            )
                        if isinstance(event, GenerationDoneEvent):
                            final = message.model_copy(deep=True)
        except Exception:
            cancellation_signal.check()
            raise
        cancellation_signal.check()
        if final is None:
            raise RuntimeError("Model stream ended without completed output")
        return final

    try:
        message = generate()
    except LLMContextLimitError:
        partial = run._state.messages[start]
        if partial.text or (
            isinstance(partial, AssistantMessage) and partial.tool_calls
        ):
            raise
        request = _fit_context(
            run, llm, source, prepared, generation_context, force=True
        )
        message = generate()
    with run._lock:
        cancellation_signal.check()
        message.id = f"{run._state.run_id}:{step.index}"
        run._state.messages[start] = message.model_copy(deep=True)
        generation.status = RunStatus.COMPLETE
        ended = MessageEndEvent(**run._ancestry, step_index=step.index, message=message)
        if run._delivery:
            run._delivery.publish(ended)
    with run._lock:
        run._progress.message_index = start
        run._progress.options = request.options.model_copy(deep=True)
        run._progress.tools = [tool.model_copy(deep=True) for tool in request.tools]
        run._progress.action = RunAction.TOOLS
        run._state.revision += 1


def _fit_context(
    run: Run,
    llm: LLM,
    source: list[Message],
    prepared: PreparedStep,
    generation_context: GenerationContext,
    *,
    force: bool = False,
) -> GenerationRequest:
    cancellation_signal = run._cancellation_signal
    previous = run._state.checkpoint
    if previous and not checkpoint_matches(source, previous):
        logger.info("Ignoring checkpoint from another history branch")
        previous = None
        with run._lock:
            run._state.checkpoint = None
    request = run._work.blocking(
        lambda: prepared.generation_request(working_messages(source, previous)),
        cancellation_signal,
    )
    budget = context_budget(llm)
    size = request_tokens(request)
    if not force and size <= budget.trigger:
        return _limit_output(llm, request)
    try:
        checkpoint = run._work.blocking(
            lambda: compact_history(llm, source, previous, generation_context),
            cancellation_signal,
        )
    except ContextLimitError:
        if not force and size <= budget.input_limit:
            logger.warning(
                "Proactive compaction failed while request still fits",
                exc_info=True,
            )
            return _limit_output(llm, request)
        raise
    request = run._work.blocking(
        lambda: prepared.generation_request(working_messages(source, checkpoint)),
        cancellation_signal,
    )
    if request_tokens(request) > budget.input_limit:
        raise ContextLimitError(
            "Required instructions and recent context exceed model input limit"
        )
    with run._lock:
        cancellation_signal.check()
        run._state.checkpoint = checkpoint
    return _limit_output(llm, request)


def _limit_output(llm: LLM, request: GenerationRequest) -> GenerationRequest:
    allowance = resolve_token_budget(llm).output_allowance(request_tokens(request))
    if allowance is not None:
        request.options.max_tokens = (
            min(request.options.max_tokens, allowance)
            if request.options.max_tokens is not None
            else allowance
        )
    return request


def _execute_tools(run: Run) -> bool:
    progress = run._progress
    completed = _step_result(
        run, progress.message_index, progress.options, progress.step_index
    )
    if run._prepared_step is None:
        available = {tool.name: tool for tool in run._defaults.tools}
        tools: list[AgentTool] = []
        for declaration in progress.tools:
            tool = available.get(declaration.name)
            if tool is None or tool.definition != declaration:
                raise ValueError("Restored tools do not match the saved step")
            tools.append(tool)
        run._prepared_step = PreparedStep(tools=tools, options=completed.options)
    if progress.message_index is None:
        raise ValueError("Tool phase requires a message index")
    result = ToolBatch(
        run,
        run._prepared_step,
        completed,
        working_messages(
            [
                *run._history.messages,
                *run._state.input_messages,
                *run._state.messages[: progress.message_index],
            ],
            run._state.checkpoint,
        ),
        before_tool_call=run._before_tool_call,
        after_tool_call=run._after_tool_call,
    ).execute()
    if result is None:
        return False
    with run._lock:
        progress.action = RunAction.AFTER_STEP
        run._state.revision += 1
    return True


def _complete_step(run: Run, completed: StepResult) -> None:
    cancellation_signal = run._cancellation_signal
    after_step = run._after_step
    should_continue = (
        run._work.blocking(
            lambda after_step=after_step, completed=completed: after_step(completed),
            cancellation_signal,
        )
        if after_step
        else bool(completed.message.tool_calls)
        and not (
            completed.tool_results
            and all(result.terminate for result in completed.tool_results)
        )
    )
    cancellation_signal.check()
    with run._lock:
        progress = run._progress
        progress.previous_message_index = progress.message_index
        progress.previous_options = progress.options
        if not should_continue or progress.step_index + 1 >= progress.step_limit:
            progress.outcome = (
                RunStatus.LIMIT if should_continue else RunStatus.COMPLETE
            )
            progress.action = RunAction.FINISH
            if not should_continue:
                run._state.answer_message_index = progress.message_index
        else:
            progress.step_index += 1
            progress.action = RunAction.PREPARE
            progress.finalized_tools = 0
            progress.pending_tool_calls = {}
            progress.options = None
            progress.tools = []
            progress.message_index = None
        run._state.revision += 1


def _step_result(
    run: Run, index: int | None, options: GenerationOptions | None, step_index: int
) -> StepResult:
    if index is None or options is None:
        raise ValueError("Saved step is missing its message or generation options")
    message = run._state.messages[index]
    if not isinstance(message, AssistantMessage):
        raise ValueError("Saved step does not point to an assistant message")
    results: list[ToolResultMessage] = []
    for item in run._state.messages[index + 1 :]:
        if not isinstance(item, ToolResultMessage):
            break
        results.append(item.model_copy(deep=True))
    return StepResult(
        step=AgentStep(index=step_index, limit=run._progress.step_limit),
        message=message.model_copy(deep=True),
        tool_results=results,
        options=options.model_copy(deep=True),
    )
