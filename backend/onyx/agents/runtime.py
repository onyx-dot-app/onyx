"""Stateful agents with one execution path and independent run records."""

import threading
from collections.abc import Callable, Sequence
from concurrent.futures import Future
from contextlib import ExitStack, closing
from contextvars import copy_context
from typing import TYPE_CHECKING, Literal, TypedDict
from uuid import uuid4

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
    ToolEndEvent,
    ToolStartEvent,
    ToolUpdateEvent,
)
from onyx.agents.models import (
    AgentContext,
    AgentStep,
    ExecutionCheckpoint,
    PreparedStep,
    RunAction,
    RunProgress,
    RunResult,
    RunSnapshot,
    StepInput,
    StepResult,
    ToolCallContext,
)
from onyx.agents.tool_execution import ToolBatch
from onyx.agents.tools import (
    AgentTool,
    InputDecision,
    InputMode,
    PendingToolInput,
    ToolAnswer,
    ToolInvocation,
    ToolOutcome,
    ToolProgress,
)
from onyx.agents.transcript import (
    OperationSnapshot,
    RunFailure,
    RunFailureKind,
    RunStatus,
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
    GenerationEvent,
    GenerationOptions,
    GenerationRequest,
    Message,
    ToolCall,
    ToolChoiceOptions,
    ToolResult,
    ToolResultMessage,
    UserMessage,
)
from onyx.llm.token_budget import resolve_token_budget
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import start_thread_with_context

if TYPE_CHECKING:
    from onyx.agents.coordination import AgentCoordinator, RunCoordination
    from onyx.agents.restoration import FeatureRestoration

logger = setup_logger()


class _Ancestry(TypedDict):
    agent_id: str
    run_id: str
    parent_run_id: str | None
    parent_tool_call_id: str | None
    parent_message_id: str | None


class RunNotTransferable(RuntimeError):
    """Execution changed before its owner could release a suspended run."""


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


def result_from_snapshot(record: RunSnapshot) -> RunResult:
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


class _RunState:
    def __init__(
        self,
        record: RunSnapshot,
        signal: CancellationSignal,
        event_dispatcher: EventDispatcher | None = None,
    ) -> None:
        self.lock = threading.RLock()
        self.record = record
        self.signal = signal
        self.accepting = True
        self.completed: Future[None] = Future()
        self.idle: Future[None] = Future()
        self.delivery: EventDelivery | None = EventDelivery(event_dispatcher)
        self.delivery_failed = False
        self.changed = threading.Condition(self.lock)
        self.settled: Future[None] = Future()
        self.segment_active = True
        self.wake_requested = False
        self.watched_children: set[str] = set()
        self.suspend_requested = False
        self.model_input_closed = False
        self.restart: Callable[[], None] | None = None
        self.detach: Callable[[], None] | None = None
        self.validate_handoff: Callable[[], None] | None = None
        self.handoff: ExecutionCheckpoint | None = None
        self.remote_cancel: Callable[[], None] | None = None
        self.shutdown_requested = False
        self.terminal_callbacks: list[Callable[[Run], None]] = []
        self.finalization_started = False
        self.finalization_context = copy_context()

    def wake(self) -> None:
        with self.changed:
            if not self.accepting:
                return
            self.wake_requested = True
            self.changed.notify_all()
            restart = self.restart
        if restart is not None:
            restart()


class Run:
    """Controls and accepted output for one execution."""

    def __init__(self, state: _RunState) -> None:
        self._state = state
        self.id = state.record.run_id
        if state.record.agent_id is None:
            raise ValueError("Executable run requires an agent identity")
        self.agent_id = state.record.agent_id

    @classmethod
    def from_snapshot(cls, snapshot: RunSnapshot) -> "Run":
        """Reattach a terminal child result without starting execution."""
        if snapshot.status in (RunStatus.RUNNING, RunStatus.SUSPENDED):
            raise ValueError("Only terminal snapshots can become completed handles")
        state = _RunState(snapshot.model_copy(deep=True), CancellationSignal())
        state.delivery = None
        state.accepting = False
        state.segment_active = False
        state.completed.set_result(None)
        state.idle.set_result(None)
        state.settled.set_result(None)
        return cls(state)

    @property
    def status(self) -> RunStatus:
        with self._state.lock:
            return self._state.record.status

    @property
    def is_remote(self) -> bool:
        """Whether this handle delegates cancellation to another execution owner."""
        with self._state.lock:
            return self._state.remote_cancel is not None

    @property
    def pending_inputs(self) -> list[PendingToolInput]:
        """Copy unanswered tool requests without copying execution history."""
        with self._state.lock:
            progress = self._state.record.progress
            return (
                [
                    pending.model_copy(deep=True)
                    for pending in progress.pending.values()
                    if isinstance(pending, PendingToolInput)
                ]
                if progress is not None
                else []
            )

    def snapshot(self) -> RunSnapshot:
        with self._state.lock:
            return self._state.record.model_copy(deep=True)

    @property
    def delivery_failed(self) -> bool:
        delivery = self._state.delivery
        return delivery.failed.is_set() if delivery else self._state.delivery_failed

    def _cancel_if_local(self) -> bool:
        """Reserve local shutdown without forwarding cancellation to another owner."""
        with self._state.lock:
            if self._state.remote_cancel is not None:
                return False
            self._state.shutdown_requested = True
        self.cancel()
        return True

    def cancel(self) -> None:
        with self._state.lock:
            remote_cancel = self._state.remote_cancel
        if remote_cancel is not None:
            if not self._state.completed.done():
                remote_cancel()
            return
        if self._state.completed.done():
            return
        self._state.signal.cancel()
        with self._state.lock:
            remote_cancel = self._state.remote_cancel
        if remote_cancel is not None:
            remote_cancel()
            return
        with self._state.lock:
            idle = self._state.idle
            delivery = self._state.delivery
            transferred = (
                not self._state.segment_active
                and self._state.handoff is not None
                and self._state.restart is None
                and self._state.accepting
            )
            if transferred:
                self._state.accepting = False
                self._state.handoff = None
                self._state.record.status = RunStatus.CANCELLED
                self._state.record.revision += 1
                for operation in self._state.record.operations:
                    if operation.status == RunStatus.RUNNING:
                        operation.status = RunStatus.CANCELLED
                self._state.idle = Future()
                idle = self._state.idle
                delivery = self._state.delivery
                if delivery is not None:
                    delivery.publish(
                        AgentEndEvent(
                            agent_id=self.agent_id,
                            run_id=self.id,
                            parent_run_id=self._state.record.parent_run_id,
                            parent_tool_call_id=self._state.record.parent_tool_call_id,
                            parent_message_id=self._state.record.parent_message_id,
                            outcome=RunStatus.CANCELLED,
                            answer_message_id=None,
                        )
                    )
            restart = self._state.restart
        if not transferred:
            if restart is not None:
                restart()
            return
        self._state.completed.set_result(None)
        if delivery is not None:
            delivery.pause()

            def drained() -> None:
                delivery.close()
                with self._state.lock:
                    self._state.delivery_failed = delivery.failed.is_set()
                    self._state.delivery = None
                idle.set_result(None)

            delivery.tracker.on_idle(drained)
        else:
            idle.set_result(None)
        start_thread_with_context(
            self._finalize,
            name="agent-finalize",
            daemon=True,
            context=self._state.finalization_context.copy(),
        )

    def claim_resume(
        self, snapshot: RunSnapshot, context: AgentContext
    ) -> Callable[[], None]:
        """Claim an explicitly transferred owner while retaining this logical handle."""
        with self._state.lock:
            transferred = self._state.handoff
            if (
                self._state.segment_active
                or transferred is None
                or not self._state.accepting
            ):
                raise RuntimeError("Run has not transferred execution ownership")
            if self._state.remote_cancel is not None:
                # The durable store can replace local file data with stored references.
                if (
                    snapshot.run_id != self.id
                    or snapshot.revision < transferred.snapshot.revision
                ):
                    raise ValueError("Resume does not match the transferred revision")
                self._state.record = snapshot.model_copy(deep=True)
            elif transferred.snapshot != snapshot or transferred.context != context:
                raise ValueError("Resume does not match the transferred checkpoint")
            remote_cancel = self._state.remote_cancel
            self._state.remote_cancel = None
            self._state.segment_active = True
            self._state.idle = Future()
            self._state.settled = Future()

        def rollback() -> None:
            with self._state.lock:
                self._state.remote_cancel = remote_cancel
                self._state.restart = None
                self._state.detach = None
                self._state.segment_active = False
                self._state.record.status = RunStatus.SUSPENDED
                idle, settled = self._state.idle, self._state.settled
                delivery = self._state.delivery
            if delivery is not None:
                delivery.pause()
            idle.set_result(None)
            settled.set_result(None)

        return rollback

    def suspend(self) -> None:
        """Request suspension at the next safe execution boundary."""
        with self._state.changed:
            if self._state.remote_cancel is not None:
                raise RuntimeError(
                    "Input must be delivered to the current owner after transfer"
                )
            if self._state.completed.done():
                raise ValueError("Cannot suspend a terminal run")
            self._state.suspend_requested = True
            self._state.changed.notify_all()

    def resume(self) -> None:
        """Continue a resident suspended run without changing its identity."""
        with self._state.lock:
            if self._state.completed.done():
                raise ValueError("Cannot resume a terminal run")
            self._state.suspend_requested = False
            restart = self._state.restart
        if restart is None:
            raise RuntimeError("Run has no execution owner")
        restart()

    def submit(self, answer: ToolAnswer) -> None:
        with self._state.changed:
            if self._state.remote_cancel is not None:
                raise RuntimeError(
                    "Input must be delivered to the current owner after transfer"
                )
            progress = self._state.record.progress
            if progress is None:
                raise ValueError("Run has no input state")
            existing = progress.answers.get(answer.request_id)
            if existing is not None:
                if existing != answer:
                    raise ValueError("Conflicting answer for request")
                if not self._state.accepting:
                    return
            else:
                if not self._state.accepting:
                    raise ValueError("Run is not accepting input")
                request = next(
                    (
                        pending
                        for pending in progress.pending.values()
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
                progress.answers[answer.request_id] = answer.model_copy(deep=True)
                self._state.record.revision += 1
            self._state.suspend_requested = False
            restart = self._state.restart
            self._state.changed.notify_all()
        if restart is not None:
            restart()

    def steer(self, message: UserMessage) -> None:
        with self._state.changed:
            if self._state.remote_cancel is not None:
                raise RuntimeError(
                    "Input must be delivered to the current owner after transfer"
                )
            progress = self._state.record.progress
            if (
                progress is None
                or not self._state.accepting
                or progress.action == RunAction.FINISH
            ):
                raise ValueError("Run is not accepting steering")
            if progress.step_index + 1 >= progress.step_limit and (
                progress.action != RunAction.PREPARE or self._state.model_input_closed
            ):
                raise ValueError("No model steps remain for steering")
            progress.steering.append(message.model_copy(deep=True))
            self._state.record.revision += 1
            self._state.suspend_requested = False
            restart = self._state.restart
            self._state.changed.notify_all()
        if restart is not None:
            restart()

    def wait_until_settled(
        self, timeout: float = OPERATION_TIMEOUT_SECONDS
    ) -> RunSnapshot:
        """Wait until execution suspends or finishes; this does not wait for user input."""
        with self._state.lock:
            settled = self._state.settled
        settled.result(timeout=timeout)
        return self.snapshot()

    def add_done_callback(self, callback: Callable[[RunSnapshot], None]) -> None:
        self._state.completed.add_done_callback(
            lambda _future: callback(self.snapshot())
        )

    def _add_terminal_callback(self, callback: Callable[["Run"], None]) -> None:
        with self._state.lock:
            if self._state.finalization_started:
                raise RuntimeError("Terminal handling has already started")
            self._state.terminal_callbacks.append(callback)

    def _finalize(self) -> None:
        """Run application completion on an execution or finalization worker."""
        with self._state.lock:
            if self._state.finalization_started:
                return
            self._state.finalization_started = True
            callbacks = self._state.terminal_callbacks
            self._state.terminal_callbacks = []
        for callback in callbacks:
            try:
                callback(self)
            except Exception:
                logger.exception("Agent terminal handling failed")

    def subscribe(self, listener: Callable[[AgentEvent], None]) -> Callable[[], None]:
        delivery = self._state.delivery
        if delivery is None:
            return lambda: None
        return delivery.subscribe(listener)

    def result(self, timeout: float = OPERATION_TIMEOUT_SECONDS) -> RunResult:
        """Wait for terminal output; cleanup can still be in progress."""
        self._state.completed.result(timeout=timeout)
        return result_from_snapshot(self.snapshot())

    def add_idle_callback(self, callback: Callable[[], None]) -> None:
        """Call once owned work finishes; callbacks must not block."""
        self._state.idle.add_done_callback(lambda _future: callback())

    def wait_for_idle(self, timeout: float = OPERATION_TIMEOUT_SECONDS) -> bool:
        delivery = self._state.delivery
        if delivery is not None and delivery.is_dispatch_thread:
            raise RuntimeError("An observer cannot wait for its own run to become idle")
        if timeout < 0:
            raise ValueError("Idle timeout must be nonnegative")
        if self._state.idle.done():
            return True
        try:
            self._state.idle.result(timeout=timeout)
        except TimeoutError:
            return False
        return True


def _capture_unsettled_child(run: Run) -> RunSnapshot:
    """Retain accepted output after settlement fails without changing live execution."""
    snapshot = run.snapshot()
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


class Agent:
    """A conversation with resolved model, tools, and optional step decisions."""

    def __init__(
        self,
        llm: LLM,
        *,
        context: AgentContext | None = None,
        system_prompt: str = "",
        tools: Sequence[AgentTool] = (),
        options: GenerationOptions | None = None,
        execution: GenerationContext | None = None,
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
        self.id = agent_id or str(uuid4())
        self.llm = llm
        self.tools = list(tools)
        self.system_prompt = system_prompt
        self.options = options or GenerationOptions()
        self.execution = execution or GenerationContext()
        self.prepare_step = prepare_step
        self.after_step = after_step
        self.before_tool_call = before_tool_call
        self.after_tool_call = after_tool_call
        self.restoration = restoration
        self._context = (context or AgentContext()).snapshot()
        self._previous_run_id = previous_run_id
        self._lock = threading.RLock()
        self._reserved = False
        self._active: _RunState | None = None

    @property
    def context(self) -> AgentContext:
        with self._lock:
            context = self._context.snapshot()
            active = self._active
            if active is not None:
                with active.lock:
                    context.messages.extend(
                        message.model_copy(deep=True)
                        for message in [
                            *active.record.input_messages,
                            *active.record.messages,
                        ]
                    )
                    context.checkpoint = (
                        active.record.checkpoint.model_copy(deep=True)
                        if active.record.checkpoint
                        else None
                    )
            return context

    def start(
        self,
        *,
        max_steps: int,
        messages: Sequence[Message] = (),
        cancellation: CancellationSignal | None = None,
        coordinator: "AgentCoordinator | None" = None,
        parent_run_id: str | None = None,
        parent_tool_call_id: str | None = None,
        parent_message_id: str | None = None,
        inherited_event_sink: Callable[[AgentEvent], None] | None = None,
        on_event: Callable[[AgentEvent], None] | None = None,
        on_terminal: Callable[[Run], None] | None = None,
        event_dispatcher: EventDispatcher | None = None,
        _snapshot: RunSnapshot | None = None,
    ) -> Run:
        return self._start(
            max_steps=max_steps,
            messages=messages,
            cancellation=cancellation,
            coordinator=coordinator,
            parent_run_id=parent_run_id,
            parent_tool_call_id=parent_tool_call_id,
            parent_message_id=parent_message_id,
            inherited_event_sink=inherited_event_sink,
            on_event=on_event,
            on_terminal=on_terminal,
            event_dispatcher=event_dispatcher,
            _snapshot=_snapshot,
            background=True,
        )

    def execute(
        self,
        *,
        max_steps: int,
        messages: Sequence[Message] = (),
        cancellation: CancellationSignal | None = None,
        coordinator: "AgentCoordinator | None" = None,
        parent_run_id: str | None = None,
        parent_tool_call_id: str | None = None,
        parent_message_id: str | None = None,
        inherited_event_sink: Callable[[AgentEvent], None] | None = None,
        on_event: Callable[[AgentEvent], None] | None = None,
        on_terminal: Callable[[Run], None] | None = None,
        event_dispatcher: EventDispatcher | None = None,
        _snapshot: RunSnapshot | None = None,
    ) -> Run:
        """Execute the first segment here; return when it finishes or suspends."""
        return self._start(
            max_steps=max_steps,
            messages=messages,
            cancellation=cancellation,
            coordinator=coordinator,
            parent_run_id=parent_run_id,
            parent_tool_call_id=parent_tool_call_id,
            parent_message_id=parent_message_id,
            inherited_event_sink=inherited_event_sink,
            on_event=on_event,
            on_terminal=on_terminal,
            event_dispatcher=event_dispatcher,
            _snapshot=_snapshot,
            background=False,
        )

    def _start(
        self,
        *,
        max_steps: int,
        background: bool,
        messages: Sequence[Message] = (),
        cancellation: CancellationSignal | None = None,
        coordinator: "AgentCoordinator | None" = None,
        parent_run_id: str | None = None,
        parent_tool_call_id: str | None = None,
        parent_message_id: str | None = None,
        inherited_event_sink: Callable[[AgentEvent], None] | None = None,
        on_event: Callable[[AgentEvent], None] | None = None,
        on_terminal: Callable[[Run], None] | None = None,
        event_dispatcher: EventDispatcher | None = None,
        _snapshot: RunSnapshot | None = None,
    ) -> Run:
        AgentStep(index=0, limit=max_steps)
        rollback_resume: Callable[[], None] | None = None
        _run: Run | None = None
        with self._lock:
            if self._reserved:
                raise RuntimeError("Agent is already running or draining")
            if _snapshot is not None and coordinator is not None:
                _run, rollback_resume = coordinator.claim_resume(
                    _snapshot, self._context
                )
            history = self._context.snapshot()
            signal = (
                cancellation
                or current_cancellation()
                or self.execution.cancellation
                or CancellationSignal()
            )
            state = (
                _run._state
                if _run is not None
                else _RunState(
                    _snapshot.model_copy(deep=True)
                    if _snapshot is not None
                    else RunSnapshot(
                        progress=RunProgress(step_limit=max_steps),
                        run_id=str(uuid4()),
                        agent_id=self.id,
                        previous_run_id=self._previous_run_id,
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
                    signal,
                    event_dispatcher,
                )
            )
            state.record.status = RunStatus.RUNNING
            self._active = state
            self._reserved = True
        run = _run if _run is not None else Run(state)
        signal = state.signal
        if on_event is not None:
            run.subscribe(on_event)
        executor: _Execution | None = None
        rollback_start: Callable[[], None] | None = None
        try:
            if _snapshot is not None and _snapshot.progress is not None:
                feature_state = _snapshot.progress.feature_state
                if feature_state is not None:
                    if self.restoration is None:
                        raise ValueError(
                            "Feature restoration is required for this snapshot"
                        )
                    self.restoration.restore_state(feature_state)
            executor = _Execution(
                state=state,
                history=history.messages,
                llm=self.llm,
                defaults=PreparedStep(
                    system_prompt=self.system_prompt,
                    tools=list(self.tools),
                    options=self.options.model_copy(deep=True),
                ),
                execution=self.execution.model_copy(
                    update={
                        "user_identity": self.execution.user_identity.model_copy()
                        if self.execution.user_identity
                        else None,
                    }
                ),
                prepare_step=self.prepare_step,
                after_step=self.after_step,
                before_tool_call=self.before_tool_call,
                after_tool_call=self.after_tool_call,
                commit=self._commit,
                release=self._release,
                inherited_event_sink=inherited_event_sink,
                restoration=self.restoration,
            )
            state.detach = executor.detach
            if coordinator is not None:
                executor.coordination = coordinator.bind(
                    run, executor.work, executor.publish_event, signal
                )
                coordinator.bind_agent(self)
                state.validate_handoff = executor.coordination.validate_handoff
                if _snapshot is not None and _snapshot.progress is not None:
                    executor.coordination.attach_children(
                        _snapshot.progress.child_run_ids
                    )
                    executor.coordination.observe_children(
                        _snapshot.progress.observed_child_run_ids
                    )
                rollback_start = coordinator.notify_start(self, run)
            if on_terminal is not None:
                run._add_terminal_callback(on_terminal)
        except BaseException:
            if (
                _run is None
                and executor is not None
                and executor.coordination is not None
            ):
                executor.coordination.release()
            with self._lock:
                self._active = None
                self._reserved = False
            if rollback_resume is not None:
                rollback_resume()
            elif state.delivery:
                state.delivery.close()
            raise
        try:
            executor.begin(max_steps, background=background)
        except BaseException:
            executor.detach()
            if rollback_start is not None:
                try:
                    rollback_start()
                except Exception:
                    logger.exception("Agent start registration rollback failed")
            if _run is None and executor.coordination is not None:
                executor.coordination.release()
            with self._lock:
                self._active = None
                self._reserved = False
            if rollback_resume is not None:
                rollback_resume()
            elif state.delivery:
                state.delivery.close()
            raise
        return run

    def resume(
        self,
        snapshot: RunSnapshot,
        *,
        coordinator: "AgentCoordinator | None" = None,
        on_event: Callable[[AgentEvent], None] | None = None,
    ) -> Run:
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

    def handoff(
        self, *, remote_cancel: Callable[[], None] | None = None
    ) -> ExecutionCheckpoint:
        """Release a suspended owner; its coordinator retains controls and subscribers."""
        with self._lock:
            active = self._active
            if active is None:
                raise RunNotTransferable("Agent has no execution to transfer")
            with active.lock:
                if (
                    active.record.status != RunStatus.SUSPENDED
                    or active.signal.cancelled
                    or active.shutdown_requested
                    or active.segment_active
                    or not active.idle.done()
                ):
                    raise RunNotTransferable(
                        "Execution must be suspended and idle before transfer"
                    )
                if active.validate_handoff is not None:
                    active.validate_handoff()
                captured = ExecutionCheckpoint(
                    context=self._context.snapshot(),
                    snapshot=active.record.model_copy(deep=True),
                )
                active.handoff = captured.model_copy(deep=True)
                active.remote_cancel = remote_cancel
                active.restart = None
                active.validate_handoff = None
                self._active = None
                self._reserved = True
                detach = active.detach
                active.detach = None
        if detach is not None:
            detach()
        return captured

    def capture(self) -> ExecutionCheckpoint:
        """Capture the active run with its history prefix under the same locks."""
        with self._lock:
            active = self._active
            if active is None:
                raise ValueError("Agent has no active execution to capture")
            with active.lock:
                active.record.revision += 1
                return ExecutionCheckpoint(
                    context=self._context.snapshot(),
                    snapshot=active.record.model_copy(deep=True),
                )

    def _commit(self, record: RunSnapshot) -> None:
        with self._lock:
            self._context.messages.extend(
                message.model_copy(deep=True)
                for message in [*record.input_messages, *record.messages]
            )
            self._context.checkpoint = (
                record.checkpoint.model_copy(deep=True) if record.checkpoint else None
            )
            self._previous_run_id = record.run_id
            self._active = None

    def _release(self) -> None:
        with self._lock:
            self._reserved = False


class _Execution:
    def __init__(
        self,
        *,
        state: _RunState,
        history: list[Message],
        llm: LLM,
        defaults: PreparedStep,
        execution: GenerationContext,
        prepare_step: Callable[[StepInput], PreparedStep] | None,
        after_step: Callable[[StepResult], bool] | None,
        before_tool_call: Callable[
            [ToolCallContext], ToolResult | PendingToolInput | None
        ]
        | None,
        after_tool_call: Callable[[ToolCallContext, ToolResult], ToolResult] | None,
        commit: Callable[[RunSnapshot], None],
        release: Callable[[], None],
        inherited_event_sink: Callable[[AgentEvent], None] | None,
        restoration: "FeatureRestoration | None",
    ) -> None:
        self.state = state
        self._thread_context = copy_context()
        self._cancellation_link = ExitStack()
        self.history = history
        self.llm = llm
        self.defaults = defaults
        self.execution = execution
        self.prepare_step = prepare_step
        self.after_step = after_step
        self.before_tool_call = before_tool_call
        self.after_tool_call = after_tool_call
        self.restoration = restoration
        self.prepared: PreparedStep | None = None
        self.work = ExecutionWork()
        self.commit = commit
        self.release = release
        self.inherited_event_sink = inherited_event_sink
        self.coordination: RunCoordination | None = None
        self.step_start: int | None = None
        self.generating = False
        self.ancestry = _Ancestry(
            agent_id=state.record.agent_id or "",
            run_id=state.record.run_id,
            parent_run_id=state.record.parent_run_id,
            parent_tool_call_id=state.record.parent_tool_call_id,
            parent_message_id=state.record.parent_message_id,
        )

    @property
    def messages(self) -> list[Message]:
        return self.state.record.messages

    def context_messages(self) -> list[Message]:
        return [*self.history, *self.state.record.input_messages, *self.messages]

    def publish_event(self, event: AgentEvent) -> None:
        with self.state.lock:
            if not self.state.accepting:
                return
            if self.state.delivery:
                self.state.delivery.publish(event)
        self._publish_inherited(event)

    def _publish_inherited(self, event: AgentEvent) -> None:
        if self.inherited_event_sink is None:
            return
        try:
            self.inherited_event_sink(event.model_copy(deep=True))
        except Exception:
            if self.state.delivery:
                self.state.delivery.failed.set()
            logger.exception("Inherited agent event delivery failed")

    @property
    def progress(self) -> RunProgress:
        progress = self.state.record.progress
        if progress is None:
            raise RuntimeError("Execution requires recorded progress")
        return progress

    def detach(self) -> None:
        self._cancellation_link.close()
        if self.coordination is not None:
            self.coordination.coordinator.release_execution(Run(self.state))

    def begin(self, max_steps: int, *, background: bool) -> None:
        self.state.restart = self.start_segment
        self._cancellation_link.enter_context(
            self.state.signal.on_cancel(self.state.wake)
        )
        if self.state.delivery is not None:
            self.state.delivery.resume()
        with self.state.lock:
            self.state.handoff = None
        if background:
            start_thread_with_context(
                lambda: self.execute(max_steps),
                name="agent-run",
                daemon=True,
                context=self._thread_context.copy(),
            )
        else:
            self.execute(max_steps)

    def start_segment(self) -> None:
        with self.state.changed:
            if not self.state.accepting:
                return
            self.state.wake_requested = True
            self.state.changed.notify_all()
            if self.state.segment_active:
                return
            self.state.segment_active = True
            self.state.wake_requested = False
            self.state.idle = Future()
            self.state.settled = Future()
            self.state.record.status = RunStatus.RUNNING
            if self.state.delivery is not None:
                self.state.delivery.resume()
            self.work = ExecutionWork()
            if self.coordination is not None:
                self.coordination.rebind(
                    self.work, self.publish_event, self.state.signal
                )
            try:
                start_thread_with_context(
                    lambda: self.execute(self.progress.step_limit),
                    name="agent-run",
                    daemon=True,
                    context=self._thread_context.copy(),
                )
            except BaseException:
                self.state.segment_active = False
                self.state.record.status = RunStatus.SUSPENDED
                if self.state.delivery is not None:
                    self.state.delivery.pause()
                self.state.idle.set_result(None)
                self.state.settled.set_result(None)
                raise

    def _suspend(self) -> None:
        if self.restoration is not None:
            feature_state = self.work.blocking(
                self.restoration.capture_state, self.state.signal
            )
            with self.state.lock:
                self.progress.feature_state = feature_state.model_copy(deep=True)
        if self.coordination is not None:
            with self.state.lock:
                self.progress.child_run_ids = list(self.coordination.children)
                self.progress.observed_child_run_ids = (
                    self.coordination.observed_children()
                )
        idle = self.state.idle
        settled = self.state.settled

        def released() -> None:
            with self.state.lock:
                self.state.record.status = RunStatus.SUSPENDED
                self.state.record.revision += 1
                self.state.segment_active = False
                restart = self.state.wake_requested or self.state.signal.cancelled
            idle.set_result(None)
            settled.set_result(None)
            if restart:
                self.start_segment()

        def drained() -> None:
            with self.state.lock:
                self.state.record.status = RunStatus.SUSPENDED
            self.publish_event(AgentSuspendedEvent(**self.ancestry))
            delivery = self.state.delivery
            if delivery is not None:
                delivery.pause()
                delivery.tracker.on_idle(released)
            else:
                released()

        self.work.tracker.on_idle(drained)

    def _step_result(
        self, index: int | None, options: GenerationOptions | None, step_index: int
    ) -> StepResult:
        if index is None or options is None:
            raise ValueError("Saved step is missing its message or generation options")
        message = self.messages[index]
        if not isinstance(message, AssistantMessage):
            raise ValueError("Saved step does not point to an assistant message")
        results: list[ToolResultMessage] = []
        for item in self.messages[index + 1 :]:
            if not isinstance(item, ToolResultMessage):
                break
            results.append(item.model_copy(deep=True))
        return StepResult(
            step=AgentStep(index=step_index, limit=self.progress.step_limit),
            message=message.model_copy(deep=True),
            tool_results=results,
            options=options.model_copy(deep=True),
        )

    def watch_children(self, children: list[Run]) -> None:
        for child in children:
            with self.state.lock:
                if child.id in self.state.watched_children:
                    continue
                self.state.watched_children.add(child.id)
            child.add_done_callback(lambda _record, state=self.state: state.wake())

    def execute(self, max_steps: int) -> None:
        signal = self.state.signal
        outcome = RunStatus.ERROR
        suspended = False
        try:
            with (
                cancellation_scope(signal),
                signal.on_operation(self.work.track_operation),
            ):
                signal.check()
                if not self.messages:
                    self.publish_event(AgentStartEvent(**self.ancestry))
                while self.progress.step_index < max_steps:
                    signal.check()
                    progress = self.progress
                    if progress.action == RunAction.FINISH:
                        with self.state.lock:
                            if self.state.suspend_requested:
                                self.state.wake_requested = False
                                suspended = True
                                return
                        if self.coordination:
                            pending = self.coordination.pending_children()
                            if pending:
                                self.watch_children(pending)
                                suspended = True
                                return
                            children = self.coordination.finish(cancel=False)
                            with self.state.lock:
                                self.state.record.child_runs = children
                        if progress.outcome not in (
                            RunStatus.COMPLETE,
                            RunStatus.LIMIT,
                        ):
                            raise RuntimeError(
                                "Execution is missing its terminal decision"
                            )
                        outcome = progress.outcome
                        break
                    if progress.action == RunAction.PREPARE:
                        with self.state.lock:
                            self.messages.extend(progress.steering)
                            progress.steering = []
                            suspend = self.state.suspend_requested
                            self.state.wake_requested = False
                            self.state.model_input_closed = not suspend
                        if suspend:
                            suspended = True
                            return
                        previous = (
                            self._step_result(
                                progress.previous_message_index,
                                progress.previous_options,
                                progress.step_index - 1,
                            )
                            if progress.previous_message_index is not None
                            else None
                        )
                        decision = StepInput(
                            history=[m.model_copy(deep=True) for m in self.history],
                            input_messages=[
                                m.model_copy(deep=True)
                                for m in self.state.record.input_messages
                            ],
                            messages=[m.model_copy(deep=True) for m in self.messages],
                            step=AgentStep(index=progress.step_index, limit=max_steps),
                            previous=previous,
                        )
                        prepare = self.prepare_step
                        prepared = (
                            self.work.blocking(
                                lambda prepare=prepare, decision=decision: prepare(
                                    decision
                                ),
                                signal,
                            )
                            if prepare
                            else self.defaults
                        )
                        self.prepared = prepared
                        completed = self._step(prepared, decision.step)
                        if completed is None:
                            suspended = True
                            return
                    elif progress.action == RunAction.TOOLS:
                        self.step_start = progress.message_index
                        completed = self._continue_tools()
                        if completed is None:
                            suspended = True
                            return
                    if progress.action == RunAction.AFTER_STEP:
                        completed = self._step_result(
                            progress.message_index,
                            progress.options,
                            progress.step_index,
                        )
                        self._complete_step(completed)
        except AgentCancelled:
            outcome = RunStatus.CANCELLED
            signal.cancel()
        except Exception as error:
            logger.exception("Agent execution failed")
            with self.state.lock:
                self.state.record.failure = _failure(error, self.llm)
            outcome = RunStatus.ERROR
            signal.cancel()
        finally:
            if suspended:
                try:
                    self._suspend()
                except AgentCancelled:
                    self._finish(RunStatus.CANCELLED)
                except Exception as error:
                    logger.exception("Agent suspension failed")
                    with self.state.lock:
                        self.state.record.failure = _failure(error, self.llm)
                    signal.cancel()
                    self._finish(RunStatus.ERROR)
            else:
                self._finish(outcome)

    def _complete_step(self, completed: StepResult) -> None:
        signal = self.state.signal
        progress = self.progress
        after_step = self.after_step
        should_continue = (
            self.work.blocking(
                lambda after_step=after_step, completed=completed: after_step(
                    completed
                ),
                signal,
            )
            if after_step
            else bool(completed.message.tool_calls)
            and not (
                completed.tool_results
                and all(result.terminate for result in completed.tool_results)
            )
        )
        signal.check()
        with self.state.lock:
            if progress.steering:
                should_continue = True
            progress.previous_message_index = progress.message_index
            progress.previous_options = progress.options
            if not should_continue or completed.step.is_last:
                progress.outcome = (
                    RunStatus.COMPLETE if not should_continue else RunStatus.LIMIT
                )
                progress.action = RunAction.FINISH
                if not should_continue:
                    self.state.record.answer_message_index = progress.message_index
            else:
                progress.step_index += 1
                progress.action = RunAction.PREPARE
                self.state.model_input_closed = False
                progress.finalized_tools = 0
                progress.pending = {}
                progress.options = None
                progress.tools = []
                progress.message_index = None
            self.state.record.revision += 1

    def _finish(
        self,
        outcome: Literal[
            RunStatus.COMPLETE, RunStatus.LIMIT, RunStatus.CANCELLED, RunStatus.ERROR
        ],
    ) -> None:
        self._cancellation_link.close()
        if self.coordination and outcome in (RunStatus.ERROR, RunStatus.CANCELLED):
            try:
                children = self.coordination.finish(cancel=True)
            except Exception as error:
                logger.exception("Child executions did not reach terminal output")
                outcome = RunStatus.ERROR
                children = [
                    _capture_unsettled_child(child.run)
                    for child in self.coordination.children.values()
                ]
                with self.state.lock:
                    self.state.record.failure = _failure(error, self.llm)
            with self.state.lock:
                self.state.record.child_runs = children
        with self.state.lock:
            self.state.record.status = outcome
            if self.generating and self.step_start is not None:
                partial = self.messages[self.step_start]
                if isinstance(partial, AssistantMessage):
                    partial.stop_reason = (
                        "aborted" if outcome == RunStatus.CANCELLED else "error"
                    )
            answer_message_id = None
            if self.state.record.answer_message_index is not None:
                answer = self.messages[self.state.record.answer_message_index]
                if not isinstance(answer, AssistantMessage):
                    raise RuntimeError("Selected answer is not an assistant message")
                answer_message_id = answer.id
            terminal = AgentEndEvent(
                **self.ancestry,
                outcome=outcome,
                answer_message_id=answer_message_id,
            )
            for operation in self.state.record.operations:
                if operation.status == RunStatus.RUNNING:
                    operation.status = outcome
            if self.state.delivery:
                self.state.delivery.publish(terminal)
            self.state.accepting = False
            self.state.record.revision += 1
            record = self.state.record.model_copy(deep=True)
        self._publish_inherited(terminal)
        self.commit(record)
        self.state.completed.set_result(None)
        self.state.settled.set_result(None)
        delivery = self.state.delivery
        if delivery is not None:
            delivery.close()
            self.work.tracker.follow(delivery.tracker)

        def release() -> None:
            if delivery is not None:
                self.state.delivery_failed = delivery.failed.is_set()
                self.state.delivery = None
            if self.coordination is not None:
                self.coordination.release()
            self.release()
            self.state.restart = None
            self.state.detach = None
            self.state.validate_handoff = None
            self.state.segment_active = False
            self.state.idle.set_result(None)

        self.work.tracker.on_idle(release)
        Run(self.state)._finalize()

    def _step(self, prepared: PreparedStep, step: AgentStep) -> StepResult | None:
        signal = self.state.signal
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
        self.prepared = prepared
        execution = self.execution.model_copy(
            update={
                "cancellation": signal,
                "timeout": prepared.timeout or self.execution.timeout,
            }
        )
        request = self._fit_context(prepared, execution)
        started = MessageStartEvent(
            **self.ancestry, step_index=step.index, metadata=prepared.output_metadata
        )
        with self.state.lock:
            signal.check()
            self.step_start = len(self.messages)
            start = self.step_start
            self.generating = True
            self.messages.append(
                AssistantMessage(
                    id=f"{self.state.record.run_id}:{step.index}",
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
            self.state.record.operations.append(generation)
            if self.state.delivery:
                self.state.delivery.publish(started)
        self._publish_inherited(started)

        def accept(event: GenerationEvent) -> None:
            with self.state.lock:
                if not self.state.accepting:
                    raise AgentCancelled()
                if event.request_params:
                    self.state.record.request_params = event.request_params.model_copy(
                        deep=True
                    )
                event.message.id = f"{self.state.record.run_id}:{step.index}"
                event.message.metadata = (
                    prepared.output_metadata.model_copy(deep=True)
                    if prepared.output_metadata
                    else None
                )
                self.messages[start] = event.message.model_copy(deep=True)
                update = MessageUpdateEvent(
                    **self.ancestry, step_index=step.index, generation_event=event
                )
                if self.state.delivery:
                    self.state.delivery.publish(update)
            self._publish_inherited(update)

        def generate() -> AssistantMessage:
            final: AssistantMessage | None = None
            try:
                with closing(self.llm.stream(request, execution)) as events:
                    for event in events:
                        signal.check()
                        accept(event)
                        if event.type == "done":
                            final = event.message.model_copy(deep=True)
            except Exception:
                signal.check()
                raise
            signal.check()
            if final is None:
                raise RuntimeError("Model stream ended without completed output")
            return final

        try:
            message = generate()
        except LLMContextLimitError:
            partial = self.messages[start]
            if partial.text or (
                isinstance(partial, AssistantMessage) and partial.tool_calls
            ):
                raise
            request = self._fit_context(prepared, execution, force=True)
            message = generate()
        with self.state.lock:
            signal.check()
            message.id = f"{self.state.record.run_id}:{step.index}"
            self.messages[start] = message.model_copy(deep=True)
            self.generating = False
            generation.status = RunStatus.COMPLETE
            ended = MessageEndEvent(
                **self.ancestry, step_index=step.index, message=message
            )
            if self.state.delivery:
                self.state.delivery.publish(ended)
        self._publish_inherited(ended)
        with self.state.lock:
            self.progress.message_index = start
            self.progress.options = request.options.model_copy(deep=True)
            self.progress.tools = [tool.model_copy(deep=True) for tool in request.tools]
            self.progress.action = RunAction.TOOLS
            self.state.record.revision += 1
        return self._continue_tools()

    def _continue_tools(self) -> StepResult | None:
        progress = self.progress
        completed = self._step_result(
            progress.message_index, progress.options, progress.step_index
        )
        if self.prepared is None:
            available = {tool.name: tool for tool in self.defaults.tools}
            tools: list[AgentTool] = []
            for declaration in progress.tools:
                tool = available.get(declaration.name)
                if tool is None or tool.definition != declaration:
                    raise ValueError("Restored tools do not match the saved step")
                tools.append(tool)
            self.prepared = PreparedStep(tools=tools, options=completed.options)
        if progress.message_index is None:
            raise ValueError("Tool phase requires a message index")
        results = ToolBatch(
            self,
            self.prepared,
            completed,
            working_messages(
                [
                    *self.history,
                    *self.state.record.input_messages,
                    *self.messages[: progress.message_index],
                ],
                self.state.record.checkpoint,
            ),
        ).run()
        if results is None:
            return None
        with self.state.lock:
            progress.action = RunAction.AFTER_STEP
            self.state.record.revision += 1
        return completed.model_copy(update={"tool_results": results})

    def _fit_context(
        self,
        prepared: PreparedStep,
        execution: GenerationContext,
        *,
        force: bool = False,
    ) -> GenerationRequest:
        signal = self.state.signal
        source = self.context_messages()
        if self.generating and self.step_start is not None:
            source = [
                *self.history,
                *self.state.record.input_messages,
                *self.messages[: self.step_start],
            ]
        previous = self.state.record.checkpoint
        if previous and not checkpoint_matches(source, previous):
            logger.info("Ignoring checkpoint from another history branch")
            previous = None
            with self.state.lock:
                self.state.record.checkpoint = None
        request = self.work.blocking(
            lambda: prepared.generation_request(working_messages(source, previous)),
            signal,
        )
        budget = context_budget(self.llm)
        size = request_tokens(request)
        if not force and size <= budget.trigger:
            return self._limit_output(request)
        try:
            checkpoint = self.work.blocking(
                lambda: compact_history(self.llm, source, previous, execution),
                signal,
            )
        except ContextLimitError:
            if not force and size <= budget.input_limit:
                logger.warning(
                    "Proactive compaction failed while request still fits",
                    exc_info=True,
                )
                return self._limit_output(request)
            raise
        request = self.work.blocking(
            lambda: prepared.generation_request(working_messages(source, checkpoint)),
            signal,
        )
        if request_tokens(request) > budget.input_limit:
            raise ContextLimitError(
                "Required instructions and recent context exceed model input limit"
            )
        with self.state.lock:
            signal.check()
            self.state.record.checkpoint = checkpoint
        return self._limit_output(request)

    def _limit_output(self, request: GenerationRequest) -> GenerationRequest:
        allowance = resolve_token_budget(self.llm.info).output_allowance(
            request_tokens(request)
        )
        if allowance is not None:
            request.options.max_tokens = (
                min(request.options.max_tokens, allowance)
                if request.options.max_tokens is not None
                else allowance
            )
        return request

    def _finalize_tool_result(
        self,
        result: ToolResult,
        call: ToolCall,
        step: AgentStep,
        result_start: int,
    ) -> ToolResultMessage:
        item = ToolResultMessage(
            content=result.content,
            metadata=result.metadata,
            cacheable=result.cacheable,
            details=result.details,
            is_error=result.is_error,
            terminate=result.terminate,
            tool_call_id=call.id,
            tool_name=call.name,
        )
        event = ToolEndEvent(
            **self.ancestry, step_index=step.index, tool_call=call, result=result
        )
        with self.state.lock:
            if not self.state.accepting or self.state.signal.cancelled:
                logger.debug("Ignoring late tool finalization: %s", call.id)
                return item
            offset = next(
                (
                    offset
                    for offset, stored in enumerate(
                        self.messages[result_start:], start=result_start
                    )
                    if isinstance(stored, ToolResultMessage)
                    and stored.tool_call_id == call.id
                ),
                None,
            )
            if offset is None:
                raise RuntimeError("Completed tool result is missing from history")
            operation = next(
                operation
                for operation in self.state.record.operations
                if operation.message_index == self.step_start
                and operation.tool_call_id == call.id
            )
            self.messages[offset] = item.model_copy(deep=True)
            operation.status = (
                RunStatus.ERROR if result.is_error else RunStatus.COMPLETE
            )
            if self.state.delivery:
                self.state.delivery.publish(event)
        self._publish_inherited(event)
        return item

    def _record_tool_result(
        self,
        result: ToolResult,
        call: ToolCall,
        result_start: int,
        call_indices: dict[str, int],
        index: int,
        step: AgentStep,
    ) -> None:
        item = ToolResultMessage(
            content=result.content,
            metadata=result.metadata,
            cacheable=result.cacheable,
            details=result.details,
            is_error=result.is_error,
            terminate=result.terminate,
            tool_call_id=call.id,
            tool_name=call.name,
        )
        event = ToolUpdateEvent(
            **self.ancestry,
            step_index=step.index,
            tool_call=call,
            progress=ToolProgress(content=result.text, details=result.details),
        )
        with self.state.lock:
            if not self.state.accepting:
                logger.warning("Tool completed after its run closed: %s", call.id)
                raise AgentCancelled()
            # Accept outcomes on completion; keep model history in call order.
            offset = sum(
                call_indices[previous.tool_call_id] < index
                for previous in self.messages[result_start:]
                if isinstance(previous, ToolResultMessage)
            )
            operation = next(
                operation
                for operation in self.state.record.operations
                if operation.message_index == self.step_start
                and operation.tool_call_id == call.id
            )
            self.messages.insert(result_start + offset, item.model_copy(deep=True))
            operation.status = (
                RunStatus.ERROR if result.is_error else RunStatus.COMPLETE
            )
            if self.state.delivery:
                self.state.delivery.publish(event)
        self._publish_inherited(event)

    def _execute_tool(
        self,
        *,
        signal: CancellationSignal,
        context: ToolCallContext,
        tool: AgentTool | None,
        is_truncated: bool,
        index: int,
        ancestry: _Ancestry,
        approved: bool = False,
        children: list[RunSnapshot] | None = None,
    ) -> ToolOutcome:
        call = context.call
        step = context.step
        options = context.options
        started = ToolStartEvent(**ancestry, step_index=step.index, tool_call=call)
        with self.state.lock:
            signal.check()
            if self.step_start is None:
                raise RuntimeError("Tool requires an assistant message")
            first_start = not any(
                operation.message_index == self.step_start
                and operation.tool_call_id == call.id
                for operation in self.state.record.operations
            )
            if first_start:
                self.state.record.operations.append(
                    OperationSnapshot(
                        step_index=step.index,
                        message_index=self.step_start,
                        tool_call_id=call.id,
                        status=RunStatus.RUNNING,
                    )
                )
                if self.state.delivery:
                    self.state.delivery.publish(started)
        if first_start:
            self._publish_inherited(started)
        signal.check()
        context = ToolCallContext(
            step=step,
            call=call.model_copy(deep=True),
            options=options.model_copy(deep=True),
            messages=[message.model_copy(deep=True) for message in context.messages],
        )
        if tool is None or options.tool_choice == ToolChoiceOptions.NONE:
            return ToolResult(
                content=f"Tool {call.name} is unavailable for this step.",
                is_error=True,
            )
        if call.argument_error or not call.arguments_complete or is_truncated:
            return ToolResult(
                content=call.argument_error or "Tool arguments were truncated.",
                is_error=True,
            )
        before_tool_call = self.before_tool_call
        if before_tool_call and not approved and children is None:
            result = before_tool_call(context)
            if result is not None:
                return result
        active = threading.Event()
        active.set()

        def update(progress: ToolProgress) -> None:
            with self.state.lock:
                if not active.is_set() or not self.state.accepting:
                    logger.debug("Ignoring late tool progress: %s", call.id)
                    return
                signal.check()
                event = ToolUpdateEvent(
                    **ancestry, step_index=step.index, tool_call=call, progress=progress
                )
                if self.state.delivery:
                    self.state.delivery.publish(event)
            self._publish_inherited(event)

        invocation = ToolInvocation(
            call_id=call.id,
            call_index=index,
            arguments=call.model_copy(deep=True).arguments,
            cancellation=signal,
            update=update,
            messages=[message.model_copy(deep=True) for message in context.messages],
            agents=self.coordination.for_tool(
                call.id, f"{self.state.record.run_id}:{step.index}", active
            )
            if self.coordination
            else None,
        )
        try:
            if children is not None:
                if tool.complete_children is None:
                    raise ValueError(
                        "Tool does not support completing child dependencies"
                    )
                result = tool.complete_children(invocation, children)
                if self.coordination is not None:
                    self.coordination.observe_children(
                        [child.run_id for child in children]
                    )
                return result
            outcome = tool.execute(invocation)
            if (
                isinstance(outcome, PendingToolInput)
                and outcome.mode == InputMode.EXECUTE
            ):
                raise ValueError("Execution approval belongs in before_tool_call")
            return outcome
        finally:
            with self.state.lock:
                active.clear()
