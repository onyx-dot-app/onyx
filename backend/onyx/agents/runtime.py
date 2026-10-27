"""Stateful agents with one execution path and independent run records."""

import threading
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Future
from contextlib import ExitStack, closing
from contextvars import copy_context
from datetime import datetime, timezone
from functools import partial
from typing import TYPE_CHECKING, Literal, Protocol, TypedDict, cast
from uuid import uuid4

from pydantic import BaseModel, JsonValue, TypeAdapter

from onyx.agents.compaction import (
    CheckpointMismatchError,
    ContextLimitError,
    compact_history,
    context_budget,
    count_tokens,
    history_boundaries,
    request_tokens,
    working_messages,
)
from onyx.agents.concurrency import (
    OPERATION_TIMEOUT_SECONDS,
    EventDelivery,
    EventDispatcher,
    ExecutionWork,
    wait_operation,
)
from onyx.agents.events import (
    AgentEndEvent,
    AgentEvent,
    AgentStartEvent,
    AgentSuspendedEvent,
    InputRequiredEvent,
    MessageEndEvent,
    MessageStartEvent,
    MessageUpdateEvent,
    ToolEndEvent,
    ToolStartEvent,
    ToolUpdateEvent,
)
from onyx.agents.execution_records import run_input_message_id
from onyx.agents.models import (
    AgentState,
    AgentStep,
    CompactionCheckpoint,
    ExecutionCheckpoint,
    ExecutionRequest,
    ExecutionStatus,
    PreparedStep,
    RunAction,
    RunFailure,
    RunFailureKind,
    RunProgress,
    RunResult,
    RunState,
    RunStatus,
    StepInput,
    StepRecord,
    StepResult,
    ToolCallContext,
    ToolExecutionRecord,
    messages_from_steps,
)
from onyx.agents.tool_execution import ToolBatch
from onyx.agents.tools import (
    AgentTool,
    ChildRunWait,
    HumanToolAnswer,
    InputDecision,
    InputMode,
    PendingToolInput,
    ToolProgress,
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
    LLMRateLimitError,
    LLMTimeoutError,
    litellm_exception_to_safe_error,
)
from onyx.llm.interfaces import LLM, GenerationContext
from onyx.llm.models import (
    AssistantMessage,
    GenerationDoneEvent,
    GenerationLifecycleEvent,
    GenerationOptions,
    GenerationRequest,
    Message,
    SystemMessage,
    ToolCall,
    ToolResult,
    ToolResultMessage,
    UserMessage,
    apply_generation_event,
)
from onyx.llm.token_budget import resolve_token_budget
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import start_thread_with_context

if TYPE_CHECKING:
    from onyx.agents.agent_coordination import AgentCoordinator, RunCoordination

logger = setup_logger()
_FEATURE_STATE = TypeAdapter(dict[str, JsonValue])


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
    info = litellm_exception_to_safe_error(error, llm, fallback_to_error_msg=False)
    if isinstance(error, LLMTimeoutError):
        kind = RunFailureKind.LLM_TIMEOUT
    elif isinstance(error, LLMRateLimitError):
        kind = RunFailureKind.LLM_RATE_LIMIT
    elif isinstance(error, (LLMContextLimitError, ClassifiedLLMError)):
        kind = RunFailureKind.LLM
    else:
        kind = RunFailureKind.EXECUTION
    return RunFailure(kind=kind, message=info.message, llm_error=info)


def validate_run_completion(record: RunState) -> None:
    """Raise for failed, unfinished, or incomplete terminal records."""
    if record.status == RunStatus.CANCELLED:
        raise AgentCancelled()
    if record.status == RunStatus.ERROR:
        if record.failure is None:
            raise ValueError("Failed run is missing failure classification")
        raise RunFailed(record.failure)
    if record.status not in (RunStatus.COMPLETE, RunStatus.LIMIT):
        raise ValueError("Run is not terminal")
    if not record.steps:
        raise ValueError("Completed run is missing output or steps")


def result_from_snapshot(record: RunState) -> RunResult:
    validate_run_completion(record)
    output = record.steps[-1].message
    return RunResult(
        run_id=record.run_id,
        steps=len(record.steps),
        # validate_run_completion restricts successful outcomes to these statuses.
        stop_reason=cast(Literal[RunStatus.COMPLETE, RunStatus.LIMIT], record.status),
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
        for step in record.steps:
            if step.generation_status == ExecutionStatus.RUNNING:
                step.generation_status = ExecutionStatus.ERROR
            for execution in step.tools.values():
                if execution.status == ExecutionStatus.RUNNING:
                    execution.status = ExecutionStatus.ERROR
    return snapshot


class RestorableFeature(Protocol):
    """Capture and restore feature-owned state at safe execution boundaries."""

    def capture_state(self) -> BaseModel:
        """Return state for immediate serialization; nested values may be borrowed."""
        ...

    def restore_state(self, state: Mapping[str, JsonValue]) -> None:
        """Read borrowed state without mutation; validate into an owned feature model."""
        ...


class Agent:
    """A conversation with resolved model, tools, and optional step decisions."""

    def __init__(
        self,
        llm: LLM,
        *,
        generation_context: GenerationContext,
        state: AgentState | None = None,
        system_prompt: str = "",
        tools: Sequence[AgentTool] = (),
        options: GenerationOptions | None = None,
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
        restoration: "RestorableFeature | None" = None,
    ) -> None:
        if generation_context.flow is None:
            raise ValueError("Agent generation context requires an LLMFlow")
        if len({tool.name for tool in tools}) != len(tools):
            raise ValueError("Tool names must be unique")
        self._id = agent_id or str(uuid4())
        self.llm = llm
        self.tools = list(tools)
        self.system_prompt = system_prompt
        self.options = options or GenerationOptions()
        self.generation_context = generation_context
        self.prepare_step = prepare_step
        self.after_step = after_step
        self.before_tool_call = before_tool_call
        self.after_tool_call = after_tool_call
        self._restoration = restoration
        self._state = (state or AgentState()).snapshot()
        for message in self._state.messages:
            if message.id is None:
                message.id = str(uuid4())
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
            with latest_run.execution_lock:
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
        _deadline_at: datetime | None = None,
    ) -> "Run":
        """Start a worker, or execute here until suspension or completion with background=False."""
        AgentStep(index=0, limit=max_steps)
        with self._lock:
            previous = self._latest_run
            if previous is not None:
                with previous.execution_lock:
                    if previous._released:
                        raise RunReleased(
                            "Agent execution was released; restore it from saved state"
                        )
                    if (
                        not previous._state.status.is_terminal
                        or not previous._reusable.done()
                    ):
                        raise RuntimeError("Agent is already running or draining")
                    previous._reusable.result(timeout=0)
            history = self.state
            external_cancellation = (
                cancellation
                or current_cancellation()
                or self.generation_context.cancellation
            )
            previous_run_id = previous.id if previous else self._previous_run_id
            if _snapshot is not None:
                run_id = _snapshot.run_id
            elif coordinator is not None:
                run_id = coordinator.reserve_run_id(
                    agent_id=self.id,
                    messages=messages,
                    previous_run_id=previous_run_id,
                    parent_run_id=parent_run_id,
                    parent_message_id=parent_message_id,
                    parent_tool_call_id=parent_tool_call_id,
                )
            else:
                run_id = str(uuid4())
            try:
                run = Run(
                    _snapshot.model_copy(deep=True)
                    if _snapshot is not None
                    else RunState(
                        progress=RunProgress(
                            step_limit=max_steps, deadline_at=_deadline_at
                        ),
                        run_id=run_id,
                        agent_id=self.id,
                        previous_run_id=previous_run_id,
                        parent_run_id=parent_run_id,
                        parent_tool_call_id=parent_tool_call_id,
                        parent_message_id=parent_message_id,
                        status=RunStatus.RUNNING,
                        # Child instructions have identities within their own conversation.
                        input_messages=[
                            message.model_copy(
                                deep=True,
                                update={
                                    "id": message.id
                                    if parent_run_id is None and message.id
                                    else run_input_message_id(run_id, index)
                                },
                            )
                            for index, message in enumerate(messages)
                        ],
                        checkpoint=history.checkpoint,
                    ),
                    CancellationSignal(),
                    event_dispatcher,
                    history=history,
                    event_parent=_event_parent,
                )
                if on_event is not None:
                    run.subscribe(on_event)
            except BaseException:
                if coordinator is not None and _snapshot is None:
                    try:
                        coordinator.abort_start(run_id)
                    except Exception:
                        logger.exception("Agent start reservation rollback failed")
                raise
            self._latest_run = run
        try:
            run._start(
                self,
                coordinator=coordinator,
                background=background,
                external_cancellation=external_cancellation,
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
    """Own lifecycle, controls, and accepted output.

    Runtime collaborators lock borrowed step data with execution_lock and use
    recording methods to change it.
    """

    def __init__(
        self,
        state: RunState,
        cancellation_signal: CancellationSignal,
        event_dispatcher: EventDispatcher | None = None,
        *,
        history: AgentState | None = None,
        event_parent: EventDelivery | None = None,
    ) -> None:
        """Take ownership of the supplied run state and detached history."""
        if state.agent_id is None:
            raise ValueError("Executable run requires an agent identity")
        self.id = state.run_id
        self.agent_id = state.agent_id
        self.execution_lock = threading.RLock()
        self._state = state
        self._history = history if history is not None else AgentState()
        self._token_counts: dict[str, int] = {}
        self.cancellation_signal = cancellation_signal
        self._completed: Future[None] = Future()
        self._idle: Future[None] = Future()
        self._reusable: Future[None] = Future()
        self.event_delivery: EventDelivery | None = EventDelivery(
            event_dispatcher, parent=event_parent
        )
        self._delivery_failed = False
        self._execution_condition = threading.Condition(self.execution_lock)
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
        self.before_tool_call: (
            Callable[[ToolCallContext], ToolResult | PendingToolInput | None] | None
        ) = None
        self.after_tool_call: (
            Callable[[ToolCallContext, ToolResult], ToolResult] | None
        ) = None
        self._restoration: RestorableFeature | None = None
        self._prepared_step: PreparedStep | None = None
        self.work = ExecutionWork()
        self.coordination: RunCoordination | None = None
        self._thread_context = copy_context()
        self._cancellation_link = ExitStack()
        self._released = False

    @classmethod
    def from_snapshot(cls, snapshot: RunState) -> "Run":
        """Reattach a terminal child result without starting execution."""
        if snapshot.status in (RunStatus.RUNNING, RunStatus.SUSPENDED):
            raise ValueError("Only terminal snapshots can become completed handles")
        run = cls(snapshot.model_copy(deep=True), CancellationSignal())
        run.event_delivery = None
        run._execution_active = False
        run._completed.set_result(None)
        run._idle.set_result(None)
        run._reusable.set_result(None)
        run._settled.set_result(None)
        return run

    @property
    def previous_run_id(self) -> str | None:
        with self.execution_lock:
            return self._state.previous_run_id

    @property
    def parent_run_id(self) -> str | None:
        with self.execution_lock:
            return self._state.parent_run_id

    @property
    def status(self) -> RunStatus:
        with self.execution_lock:
            return self._state.status

    @property
    def pending_inputs(self) -> list[PendingToolInput]:
        """Copy unanswered tool requests without copying execution history."""
        with self.execution_lock:
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
        delivery = self.event_delivery
        return delivery.failed.is_set() if delivery else self._delivery_failed

    def snapshot(self, *, include_children: bool = True) -> RunState:
        """Copy run state, optionally omitting independently persisted child runs."""
        with self.execution_lock:
            state = self._state
            if not include_children:
                state = state.model_copy(update={"child_runs": []})
            return state.model_copy(deep=True)

    def cancel(self) -> None:
        with self.execution_lock:
            if self._released or self._completed.done():
                return
        self.cancellation_signal.cancel()
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
        with self.execution_lock:
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
        with self.execution_lock:
            return result_from_snapshot(self._state)

    def wait_until_settled(
        self, timeout: float = OPERATION_TIMEOUT_SECONDS
    ) -> RunState:
        """Wait until execution suspends or finishes; this does not wait for user input."""
        with self.execution_lock:
            settled = self._settled
        settled.result(timeout=timeout)
        return self.snapshot()

    def wait_for_idle(self, timeout: float = OPERATION_TIMEOUT_SECONDS) -> bool:
        delivery = self.event_delivery
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
        delivery = self.event_delivery
        if delivery is None:
            return lambda: None
        return delivery.subscribe(listener)

    def add_idle_callback(self, callback: Callable[[], None]) -> None:
        """Call once owned work finishes; callbacks must not block."""
        self._idle.add_done_callback(lambda _future: callback())

    def add_done_callback(self, callback: Callable[[], None]) -> None:
        """Notify after terminal output or release; cleanup can still be running."""
        self._completed.add_done_callback(lambda _future: callback())

    @property
    def is_done(self) -> bool:
        """Whether execution has completed or released ownership."""
        return self._completed.done()

    def wait_for_completion(self, timeout: float = OPERATION_TIMEOUT_SECONDS) -> None:
        """Wait for terminal handling without copying output or waiting for cleanup."""
        self._completed.result(timeout=timeout)

    def wait_until_reusable(self, cancellation: CancellationSignal) -> None:
        """Wait for ownership cleanup before another run uses this agent."""
        wait_operation(self._reusable, cancellation)

    def track_child_work(self, child: "Run") -> None:
        """Keep this execution busy until the child's current workers drain."""
        self.work.track_operation(child._idle)

    def notify_tool_activity(self) -> None:
        with self._execution_condition:
            self._execution_condition.notify_all()

    @property
    def suspension_requested(self) -> bool:
        with self.execution_lock:
            return self._execution_request == ExecutionRequest.SUSPEND

    def start_tool_calls(self, calls: Sequence[ToolCall]) -> None:
        with self.execution_lock:
            self.cancellation_signal.check()
            record = self._state.steps[self._progress.step_index]
            message_id = record.message.id
            if message_id is None:
                raise RuntimeError("Tool execution requires a message ID")
            for call in calls:
                if call.id in record.tools:
                    continue
                record.tools[call.id] = ToolExecutionRecord(
                    status=ExecutionStatus.RUNNING
                )
                self.publish_event(
                    ToolStartEvent(
                        **self.event_context,
                        message_id=message_id,
                        step_index=self._progress.step_index,
                        tool_call=call,
                    )
                )

    def record_tool_results(
        self, result: ToolResult, calls: Sequence[ToolCall]
    ) -> None:
        # Checkpoint capture must not split a completed batch.
        with self.execution_lock:
            self.cancellation_signal.check()
            if not self.is_accepting:
                logger.warning("Tool batch completed after its run closed: %s", self.id)
                raise AgentCancelled()
            record = self._state.steps[self._progress.step_index]
            message_id = record.message.id
            if message_id is None:
                raise RuntimeError("Tool execution requires a message ID")
            for call in calls:
                execution = record.tools[call.id]
                execution.result = _tool_result_message(result, call, message_id)
                execution.status = (
                    ExecutionStatus.ERROR
                    if result.is_error
                    else ExecutionStatus.COMPLETE
                )
                self.publish_event(
                    ToolUpdateEvent(
                        **self.event_context,
                        message_id=message_id,
                        step_index=self._progress.step_index,
                        tool_call=call,
                        progress=ToolProgress(
                            content="" if result.is_error else result.text,
                            details=result.details,
                        ),
                    )
                )

    def record_pending_tool(
        self, call: ToolCall, pending: PendingToolInput | ChildRunWait
    ) -> None:
        event = (
            InputRequiredEvent(
                **self.event_context, tool_call_id=call.id, request=pending
            )
            if isinstance(pending, PendingToolInput)
            else None
        )
        with self.execution_lock:
            self.cancellation_signal.check()
            if isinstance(pending, PendingToolInput) and (
                pending.request_id in self._progress.human_tool_answers
                or any(
                    isinstance(existing, PendingToolInput)
                    and existing.request_id == pending.request_id
                    for existing in self._progress.pending_tool_calls.values()
                )
            ):
                raise ValueError("Input request IDs must be unique within a run")
            self._progress.pending_tool_calls[call.id] = pending.model_copy(deep=True)
            self._state.revision += 1
            if event is not None and self.is_accepting and self.event_delivery:
                self.event_delivery.publish(event)

    def resolve_tool_wait(self, call: ToolCall) -> None:
        with self.execution_lock:
            del self._progress.pending_tool_calls[call.id]
            self._state.revision += 1

    def finish_tool(
        self, result: ToolResult, call: ToolCall, context: ToolCallContext | None
    ) -> None:
        try:
            if self.after_tool_call is not None:
                if context is None:
                    raise RuntimeError("Tool finalization requires callback context")
                self.cancellation_signal.check()
                result = self.after_tool_call(context, result.model_copy(deep=True))
                self.cancellation_signal.check()
        finally:
            with self.execution_lock:
                if self.is_accepting and not self.cancellation_signal.cancelled:
                    record = self._state.steps[self._progress.step_index]
                    execution = record.tools[call.id]
                    if execution.result is None:
                        raise RuntimeError(
                            "Completed tool result is missing from history"
                        )
                    message_id = record.message.id
                    if message_id is None:
                        raise RuntimeError("Tool execution requires a message ID")
                    if self.after_tool_call is not None:
                        execution.result = _tool_result_message(
                            result, call, message_id
                        )
                        execution.status = (
                            ExecutionStatus.ERROR
                            if result.is_error
                            else ExecutionStatus.COMPLETE
                        )
                    self.publish_event(
                        ToolEndEvent(
                            **self.event_context,
                            message_id=message_id,
                            step_index=self._progress.step_index,
                            tool_call=call,
                            result=result,
                        )
                    )
                else:
                    logger.debug("Ignoring late tool finalization: %s", call.id)
        with self.execution_lock:
            self._progress.finalized_tools += 1
            self._state.revision += 1

    @property
    def is_accepting(self) -> bool:
        return not self._released and not self._state.status.is_terminal

    @property
    def event_context(self) -> _Ancestry:
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
        external_cancellation: CancellationSignal | None,
    ) -> None:
        state = self._state
        is_resuming = state.status == RunStatus.SUSPENDED
        with self.execution_lock:
            self._state.status = RunStatus.RUNNING
        try:
            if external_cancellation is not None:
                self._cancellation_link.enter_context(
                    external_cancellation.on_cancel(self.cancellation_signal.cancel)
                )
            if state.progress is not None:
                feature_state = state.progress.feature_state
                if feature_state is not None:
                    if agent._restoration is None:
                        raise ValueError(
                            "Feature restoration is required for this state"
                        )
                    agent._restoration.restore_state(feature_state)
            self._llm = agent.llm
            self._defaults = PreparedStep(
                system_prompt=agent.system_prompt,
                tools=list(agent.tools),
                options=agent.options.model_copy(deep=True),
            )
            self._generation_context = agent.generation_context.model_copy(
                update={
                    "cancellation": self.cancellation_signal,
                    "user_identity": agent.generation_context.user_identity.model_copy()
                    if agent.generation_context.user_identity
                    else None,
                }
            )
            self._prepare_step = agent.prepare_step
            self._after_step = agent.after_step
            self.before_tool_call = agent.before_tool_call
            self.after_tool_call = agent.after_tool_call
            self._restoration = agent._restoration
            self._thread_context = copy_context()
            if coordinator is not None:
                self.coordination = coordinator.bind(self)
                coordinator.bind_agent(agent)
                if state.progress is not None:
                    self.coordination.attach_children(state.progress.child_run_ids)
                    self.coordination.observe_children(
                        state.progress.observed_child_run_ids
                    )
                coordinator.begin(self)
            self._cancellation_link.enter_context(
                self.cancellation_signal.on_cancel(self._wake_execution)
            )
            deadline_at = self._progress.deadline_at
            if deadline_at is not None:
                remaining = (deadline_at - datetime.now(timezone.utc)).total_seconds()
                if remaining <= 0:
                    self.cancel()
                else:
                    timer = threading.Timer(remaining, self.cancel)
                    timer.daemon = True
                    self._cancellation_link.callback(timer.cancel)
                    timer.start()
            self._start_execution(background=background)
        except BaseException:
            self._cancellation_link.close()
            if coordinator is not None and (
                self.coordination is not None or not is_resuming
            ):
                try:
                    coordinator.abort_start(self.id)
                except Exception:
                    logger.exception("Agent start registration rollback failed")
            if self.coordination is not None:
                self.coordination.release()
            if self.event_delivery is not None:
                self.event_delivery.close()
            raise

    def _start_execution(self, *, background: bool) -> None:
        with self.execution_lock:
            resuming = not self._execution_active
            if resuming:
                self._idle = Future()
                self._settled = Future()
                self.work = ExecutionWork()
            self._execution_active = True
            self._state.status = RunStatus.RUNNING
            if self.event_delivery is not None:
                self.event_delivery.resume()
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
                    if self.event_delivery is not None:
                        self.event_delivery.pause()
                    self._idle.set_result(None)
                    self._settled.set_result(None)
                    raise
                return
        self._execute()

    def _wake_execution(self, *, resume: bool = False) -> None:
        with self._execution_condition:
            if not self.is_accepting or self._llm is None:
                return
            if resume or self._execution_request != ExecutionRequest.SUSPEND:
                self._execution_request = ExecutionRequest.WAKE
            self._execution_condition.notify_all()
            if not self._execution_active and (
                self._execution_request == ExecutionRequest.WAKE
                or self.cancellation_signal.cancelled
            ):
                self._start_execution(background=True)

    def begin_work_cycle(self) -> bool:
        """Acknowledge pending wakeups and return whether new work may start."""
        with self.execution_lock:
            self.cancellation_signal.check()
            if self._execution_request == ExecutionRequest.SUSPEND:
                return False
            self._execution_request = ExecutionRequest.NONE
            return True

    def wait_for_tool_activity(self, completed: Callable[[], bool]) -> None:
        with self._execution_condition:
            ready = self._execution_condition.wait_for(
                lambda: (
                    self.cancellation_signal.cancelled
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
            with cancellation_scope(self.cancellation_signal):
                self.cancellation_signal.check()
                if not self._state.steps:
                    self.publish_event(AgentStartEvent(**self.event_context))
                boundary = _advance_loop(self, llm)
                if boundary == RunStatus.SUSPENDED or self._await_children():
                    self._suspend()
                    suspended = True
                    return
                outcome = boundary
        except AgentCancelled:
            outcome = RunStatus.CANCELLED
            self.cancellation_signal.cancel()
        except Exception as error:
            logger.exception("Agent run failed")
            with self.execution_lock:
                self._state.failure = _failure(error, llm)
            self.cancellation_signal.cancel()
        finally:
            if not suspended:
                self._finish(outcome, llm)

    def _await_children(self) -> bool:
        """Suspend until foreground children finish, without occupying a worker."""
        if self.coordination is None:
            return False
        pending = self.coordination.pending_children()
        if pending:
            self.watch_children(pending)
            return True
        children = self.coordination.finish(cancel=False)
        with self.execution_lock:
            self._state.child_runs = children
        return False

    def watch_children(self, run_ids: list[str]) -> None:
        if self.coordination is None:
            raise RuntimeError("Child dependencies require a coordinator")
        coordinator = self.coordination.coordinator
        for run_id in run_ids:
            with self.execution_lock:
                if run_id in self._watched_children:
                    continue
                self._watched_children.add(run_id)
            coordinator.child_completion(run_id, self.agent_id).add_done_callback(
                lambda _future: self._wake_execution()
            )

    def _suspend(self) -> None:
        if self._restoration is not None:
            self.cancellation_signal.check()
            feature_state = _FEATURE_STATE.validate_python(
                self._restoration.capture_state().model_dump(mode="json")
            )
            self.cancellation_signal.check()
            with self.execution_lock:
                self._progress.feature_state = feature_state
        if self.coordination is not None:
            with self.execution_lock:
                self._progress.child_run_ids = list(self.coordination.children)
                self._progress.observed_child_run_ids = (
                    self.coordination.observed_children()
                )
        idle = self._idle
        settled = self._settled

        def released() -> None:
            with self.execution_lock:
                self._state.status = RunStatus.SUSPENDED
                self._state.revision += 1
                self._execution_active = False
                restart = (
                    self._execution_request == ExecutionRequest.WAKE
                    or self.cancellation_signal.cancelled
                )
            idle.set_result(None)
            settled.set_result(None)
            if restart:
                self._wake_execution()

        def drained() -> None:
            with self.execution_lock:
                self._state.status = RunStatus.SUSPENDED
            self.publish_event(AgentSuspendedEvent(**self.event_context))
            delivery = self.event_delivery
            if delivery is not None:
                delivery.pause()
                delivery.tracker.on_idle(released)
            else:
                released()

        self.work.tracker.on_idle(drained)

    def _finish(
        self,
        outcome: Literal[
            RunStatus.COMPLETE, RunStatus.LIMIT, RunStatus.CANCELLED, RunStatus.ERROR
        ],
        llm: LLM,
    ) -> None:
        self._cancellation_link.close()
        if self.coordination and outcome in (
            RunStatus.ERROR,
            RunStatus.CANCELLED,
        ):
            try:
                children = self.coordination.finish(cancel=True)
            except Exception as error:
                logger.exception("Child executions did not reach terminal output")
                outcome = RunStatus.ERROR
                with self.execution_lock:
                    self._state.failure = _failure(error, llm)
                    child_run_ids = tuple(self.coordination.children)
                children = []
                for run_id in child_run_ids:
                    try:
                        state = self.coordination.coordinator.run_state(
                            run_id, self.agent_id
                        )
                        children.append(_capture_unsettled_child(state))
                    except Exception:
                        logger.exception(
                            "Could not retain child run %s while ending its parent",
                            run_id,
                        )
            with self.execution_lock:
                self._state.child_runs = children
        with self.execution_lock:
            for index, step in enumerate(self._state.steps):
                if step.generation_status == ExecutionStatus.RUNNING:
                    partial = step.message
                    partial.stop_reason = (
                        "aborted" if outcome == RunStatus.CANCELLED else "error"
                    )
                    if partial.id is None:
                        raise RuntimeError("Recorded generation has no message ID")
                    if self.event_delivery:
                        self.event_delivery.publish(
                            MessageEndEvent(
                                **self.event_context,
                                message_id=partial.id,
                                step_index=index,
                                message=partial,
                                status=ExecutionStatus(outcome.value),
                            )
                        )
                    step.generation_status = ExecutionStatus(outcome.value)
                for execution in step.tools.values():
                    if execution.status == ExecutionStatus.RUNNING:
                        execution.status = ExecutionStatus(outcome.value)
            self._state.status = outcome
            if self.event_delivery:
                self.event_delivery.publish(
                    AgentEndEvent(
                        **self.event_context,
                        outcome=outcome,
                    )
                )
            self._state.revision += 1
        self._completed.set_result(None)
        if not self._settled.done():
            self._settled.set_result(None)
        if self.event_delivery is not None:
            self.event_delivery.close()
        try:
            if self.coordination is not None:
                self.coordination.coordinator.complete(self)
        except Exception:
            logger.exception("Agent output persistence failed")
        finally:
            self._drain_workers()

    def _clear_execution_config(self) -> None:
        self._token_counts.clear()
        self._llm = None
        self._prepared_step = None
        self._defaults = PreparedStep()
        self._generation_context = GenerationContext()
        self._prepare_step = None
        self._after_step = None
        self.before_tool_call = None
        self.after_tool_call = None
        self._restoration = None

    def _drain_workers(self) -> None:
        delivery = self.event_delivery
        if delivery is not None:
            self.work.tracker.follow(delivery.tracker)

        if self.coordination is not None:
            self.coordination.close()
        self._execution_active = False

        def finish_cleanup() -> None:
            try:
                if self.coordination is not None:
                    self.coordination.coordinator.finish(self)
            except Exception as error:
                logger.exception("Agent ownership release failed")
                self._reusable.set_exception(error)
            else:
                self._reusable.set_result(None)
            if delivery is not None:
                self._delivery_failed = delivery.failed.is_set()
                self.event_delivery = None
            self._clear_execution_config()
            self.coordination = None
            error = self._reusable.exception()
            if error is not None:
                self._idle.set_exception(error)
            else:
                self._idle.set_result(None)

        self.work.tracker.on_idle(finish_cleanup)

    def capture(self) -> ExecutionCheckpoint:
        """Capture this run and its preceding conversation under one lock."""
        with self.execution_lock:
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
        with self.execution_lock:
            if (
                self._released
                or self._state.status != RunStatus.SUSPENDED
                or self.cancellation_signal.cancelled
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
            if self.coordination is not None:
                self.coordination.validate_handoff()
            checkpoint = ExecutionCheckpoint(
                agent_state=self._history.snapshot(),
                run_state=self._state.model_copy(deep=True),
            )
            if save is not None:
                save(checkpoint)
            self._released = True
            self._clear_execution_config()
            coordination = self.coordination
            self.coordination = None
            delivery = self.event_delivery
            self.event_delivery = None
        try:
            self._cancellation_link.close()
            if delivery is not None:
                delivery.close()
            if coordination is not None:
                coordination.coordinator.release_execution(self)
        except BaseException as error:
            self._reusable.set_exception(error)
            self._completed.set_exception(error)
            raise
        else:
            self._reusable.set_result(None)
            self._completed.set_exception(
                RunReleased("Local execution has been released")
            )
        return checkpoint

    def publish_event(self, event: AgentEvent) -> None:
        with self.execution_lock:
            if not self.is_accepting:
                return
            if self.event_delivery:
                self.event_delivery.publish(event)


def _advance_loop(
    run: Run, llm: LLM
) -> Literal[RunStatus.COMPLETE, RunStatus.LIMIT, RunStatus.SUSPENDED]:
    cancellation_signal = run.cancellation_signal
    max_steps = run._progress.step_limit
    while run._progress.step_index < max_steps:
        cancellation_signal.check()
        progress = run._progress
        if progress.action == RunAction.FINISH:
            if not run.begin_work_cycle():
                return RunStatus.SUSPENDED
            if progress.outcome not in (
                RunStatus.COMPLETE,
                RunStatus.LIMIT,
            ):
                raise RuntimeError("Execution is missing its terminal decision")
            return progress.outcome
        if progress.action == RunAction.PREPARE:
            if not run.begin_work_cycle():
                return RunStatus.SUSPENDED
            step = AgentStep(index=progress.step_index, limit=max_steps)
            prepare = run._prepare_step
            prepared = run._defaults
            if prepare is not None:
                previous = (
                    _step_result(
                        run,
                        progress.previous_options,
                        progress.step_index - 1,
                    )
                    if progress.step_index > 0
                    else None
                )
                decision = StepInput(
                    history=run._history.messages,
                    input_messages=run._state.input_messages,
                    messages=run._state.messages,
                    step=step,
                    previous=previous,
                ).model_copy(deep=True)
                prepared = prepare(decision)
                cancellation_signal.check()
            _advance_step(run, llm, prepared, step)
        if progress.action == RunAction.TOOLS:
            if not _execute_tools(run):
                return RunStatus.SUSPENDED
        if progress.action == RunAction.AFTER_STEP:
            _complete_step(run)
    raise RuntimeError("Run exhausted its steps without a terminal decision")


def _advance_step(run: Run, llm: LLM, prepared: PreparedStep, step: AgentStep) -> None:
    cancellation_signal = run.cancellation_signal
    if len({tool.name for tool in prepared.tools}) != len(prepared.tools):
        raise ValueError("Tool names must be unique")
    registered_tools = {tool.name: tool for tool in run._defaults.tools}
    for tool in prepared.tools:
        if registered_tools.get(tool.name) is not tool:
            raise ValueError(
                f"Prepared tool {tool.name!r} must be registered in Agent.tools"
            )
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
            "stall_timeout_s": prepared.stall_timeout_s
            or run._generation_context.stall_timeout_s,
        }
    )
    source = [*run._history.messages, *run._state.input_messages, *run._state.messages]
    request = _compact_context(run, llm, source, prepared, generation_context)
    message_id = f"{run._state.run_id}:{step.index}"
    started = MessageStartEvent(
        message_id=message_id,
        **run.event_context,
        step_index=step.index,
        metadata=prepared.output_metadata,
    )
    with run.execution_lock:
        cancellation_signal.check()
        recorded_step = StepRecord(
            message=AssistantMessage(
                id=message_id,
                metadata=prepared.output_metadata.model_copy(deep=True)
                if prepared.output_metadata
                else None,
            ),
            generation_status=ExecutionStatus.RUNNING,
        )
        run._state.steps.append(recorded_step)
        if run.event_delivery:
            run.event_delivery.publish(started)

    timeout = generation_context.total_timeout_s
    deadline = time.monotonic() + min(
        timeout if timeout is not None else OPERATION_TIMEOUT_SECONDS,
        OPERATION_TIMEOUT_SECONDS,
    )

    def generate() -> None:
        cancellation_signal.check()
        if time.monotonic() >= deadline:
            raise LLMTimeoutError("Model generation exceeded its total timeout")
        completed = False
        try:
            with closing(llm.stream(request, generation_context)) as events:
                for event in events:
                    cancellation_signal.check()
                    # Socket timeouts bound blocked reads; check the total budget between events.
                    if time.monotonic() >= deadline:
                        raise LLMTimeoutError(
                            "Model generation exceeded its total timeout"
                        )
                    with run.execution_lock:
                        cancellation_signal.check()
                        if not run.is_accepting:
                            raise AgentCancelled()
                        if event.request_params:
                            run._state.request_params = event.request_params.model_copy(
                                deep=True
                            )
                        message = recorded_step.message
                        apply_generation_event(message, event)
                        if run.event_delivery and not isinstance(
                            event, GenerationLifecycleEvent
                        ):
                            run.event_delivery.publish(
                                MessageUpdateEvent(
                                    message_id=message_id,
                                    **run.event_context,
                                    step_index=step.index,
                                    generation_event=event,
                                )
                            )
                        if isinstance(event, GenerationDoneEvent):
                            completed = True
        except Exception:
            cancellation_signal.check()
            raise
        cancellation_signal.check()
        if not completed:
            raise RuntimeError("Model stream ended without completed output")

    try:
        generate()
    except LLMContextLimitError:
        partial = recorded_step.message
        if partial.content:
            raise
        request = _compact_context(
            run, llm, source, prepared, generation_context, force=True
        )
        with run.execution_lock:
            recorded_step.message = AssistantMessage(
                id=message_id, metadata=recorded_step.message.metadata
            )
        generate()
    with run.execution_lock:
        cancellation_signal.check()
        recorded_step.generation_status = ExecutionStatus.COMPLETE
        ended = MessageEndEvent(
            **run.event_context,
            message_id=message_id,
            step_index=step.index,
            message=recorded_step.message,
            status=ExecutionStatus.COMPLETE,
        )
        if run.event_delivery:
            run.event_delivery.publish(ended)
        run._progress.options = request.options.model_copy(deep=True)
        run._progress.tools = [tool.model_copy(deep=True) for tool in request.tools]
        run._progress.action = RunAction.TOOLS
        run._state.revision += 1


def _compact_context(
    run: Run,
    llm: LLM,
    source: list[Message],
    prepared: PreparedStep,
    generation_context: GenerationContext,
    *,
    force: bool = False,
) -> GenerationRequest:
    cancellation_signal = run.cancellation_signal
    previous = run._state.checkpoint
    try:
        messages = working_messages(source, previous)
    except CheckpointMismatchError as error:
        logger.info("Ignoring compaction checkpoint: %s", error)
        previous = None
        messages = list(source)
        with run.execution_lock:
            run._state.checkpoint = None
    cancellation_signal.check()
    request = prepared.generation_request(messages)
    cancellation_signal.check()
    budget = context_budget(llm)
    original_size = request_tokens(request, run._token_counts)
    if not force and original_size <= budget.trigger:
        return _limit_output(llm, request, original_size)

    selected_checkpoint = None
    try:
        selected_checkpoint = compact_history(
            llm,
            source,
            previous,
            generation_context,
            partial(count_tokens, cached_counts=run._token_counts),
        )
        cancellation_signal.check()
    except Exception:
        cancellation_signal.check()
        if not force and original_size <= budget.input_limit:
            logger.warning(
                "Proactive compaction failed while request still fits",
                exc_info=True,
            )
            return _limit_output(llm, request, original_size)
        logger.warning("Compaction failed; truncating older turns", exc_info=True)

    candidate_request = request
    candidate_size = original_size
    if selected_checkpoint is not None:
        cancellation_signal.check()
        candidate_request = prepared.generation_request(
            working_messages(source, selected_checkpoint)
        )
        cancellation_signal.check()
        candidate_size = request_tokens(candidate_request, run._token_counts)

    if selected_checkpoint is None or candidate_size > budget.input_limit:
        selected_checkpoint, candidate_request, candidate_size = _truncate_context(
            cancellation_signal,
            source,
            prepared,
            token_counts=run._token_counts,
            input_limit=budget.input_limit,
            original_size=original_size,
        )

    with run.execution_lock:
        cancellation_signal.check()
        run._state.checkpoint = selected_checkpoint
    return _limit_output(llm, candidate_request, candidate_size)


def _truncate_context(
    cancellation_signal: CancellationSignal,
    source: list[Message],
    prepared: PreparedStep,
    *,
    token_counts: dict[str, int],
    input_limit: int,
    original_size: int,
) -> tuple[CompactionCheckpoint, GenerationRequest, int]:
    """Find the first smaller request that fits after removing older turns."""
    boundaries = set(history_boundaries(source))
    system_messages: list[Message] = []
    for index, message in enumerate(source):
        if isinstance(message, SystemMessage):
            system_messages.append(message)
        if not isinstance(message, UserMessage) or index not in boundaries:
            continue
        cutoff_message_id = source[index - 1].id
        if cutoff_message_id is None:
            raise ValueError("Truncation source message has no identity")
        checkpoint = CompactionCheckpoint(
            summary="",
            covered_through_message_id=cutoff_message_id,
        )
        cancellation_signal.check()
        # Each cutoff starts a user turn, so the suffix retains the current task.
        candidate_request = prepared.generation_request(
            [*system_messages, *source[index:]]
        )
        cancellation_signal.check()
        candidate_size = request_tokens(candidate_request, token_counts)
        if candidate_size <= input_limit and candidate_size < original_size:
            return checkpoint, candidate_request, candidate_size
    raise ContextLimitError(
        "Required instructions and current turn exceed model input limit"
    )


def _limit_output(
    llm: LLM, request: GenerationRequest, input_tokens: int
) -> GenerationRequest:
    allowance = resolve_token_budget(llm).output_allowance(input_tokens)
    if allowance is not None:
        request.options.max_tokens = (
            min(request.options.max_tokens, allowance)
            if request.options.max_tokens is not None
            else allowance
        )
    return request


def _execute_tools(run: Run) -> bool:
    progress = run._progress
    if run._prepared_step is None:
        if progress.options is None:
            raise ValueError("Saved step is missing generation options")
        available = {tool.name: tool for tool in run._defaults.tools}
        tools: list[AgentTool] = []
        for declaration in progress.tools:
            tool = available.get(declaration.name)
            if tool is None or tool.definition != declaration:
                raise ValueError("Restored tools do not match the saved step")
            tools.append(tool)
        run._prepared_step = PreparedStep(tools=tools, options=progress.options)
    batch = ToolBatch(
        run,
        prepared=run._prepared_step,
        progress=progress,
        record=run._state.steps[progress.step_index],
        history=working_messages(
            [
                *run._history.messages,
                *run._state.input_messages,
                *messages_from_steps(run._state.steps[: progress.step_index]),
            ],
            run._state.checkpoint,
        ),
    )
    if not batch.execute():
        return False
    with run.execution_lock:
        progress.action = RunAction.AFTER_STEP
        run._state.revision += 1
    return True


def _complete_step(run: Run) -> None:
    cancellation_signal = run.cancellation_signal
    after_step = run._after_step
    cancellation_signal.check()
    progress = run._progress
    if after_step is not None:
        should_continue = after_step(
            _step_result(run, progress.options, progress.step_index).model_copy(
                deep=True
            )
        )
    else:
        step = run._state.steps[progress.step_index]
        calls = step.message.tool_calls
        results = [
            execution.result
            for call in calls
            if (execution := step.tools.get(call.id)) is not None
            and execution.result is not None
        ]
        should_continue = bool(calls) and not (
            results and all(result.terminate for result in results)
        )
    cancellation_signal.check()
    with run.execution_lock:
        progress.previous_options = progress.options
        if not should_continue or progress.step_index + 1 >= progress.step_limit:
            progress.outcome = (
                RunStatus.LIMIT if should_continue else RunStatus.COMPLETE
            )
            progress.action = RunAction.FINISH
            if not should_continue:
                run._state.answer_step_index = progress.step_index
        else:
            progress.step_index += 1
            progress.action = RunAction.PREPARE
            progress.finalized_tools = 0
            progress.pending_tool_calls = {}
            progress.options = None
            progress.tools = []
        run._state.revision += 1


def _step_result(
    run: Run, options: GenerationOptions | None, step_index: int
) -> StepResult:
    """Reference recorded output; callers copy it before invoking feature callbacks."""
    if options is None:
        raise ValueError("Saved step is missing generation options")
    step = run._state.steps[step_index]
    return StepResult(
        step=AgentStep(index=step_index, limit=run._progress.step_limit),
        message=step.message,
        tool_results=[
            execution.result
            for call in step.message.tool_calls
            if (execution := step.tools.get(call.id)) is not None
            and execution.result is not None
        ],
        options=options,
    )


def _tool_result_message(
    result: ToolResult, call: ToolCall, message_id: str
) -> ToolResultMessage:
    return ToolResultMessage(
        id=f"{message_id}:result:{call.id}",
        content=result.content,
        metadata=result.metadata,
        cacheable=result.cacheable,
        details=result.details,
        is_error=result.is_error,
        terminate=result.terminate,
        tool_call_id=call.id,
        tool_name=call.name,
    ).model_copy(deep=True)
