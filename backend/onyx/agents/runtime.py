"""Stateful agents with one execution path and independent run records."""

import threading
import time
from collections.abc import Callable, Collection, Mapping, Sequence
from concurrent.futures import Future
from contextlib import ExitStack, closing
from contextvars import copy_context
from datetime import datetime, timezone
from functools import partial
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal, Protocol, TypedDict, cast
from uuid import uuid4

from pydantic import JsonValue, TypeAdapter

from onyx.agents.compaction import (
    CheckpointMismatchError,
    ContextLimitError,
    cached_request_tokens,
    compact_history,
    context_budget,
    count_tokens,
    history_boundaries,
    is_input_context,
    messages_after_compaction,
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
    InputEndedEvent,
    InputRequiredEvent,
    MessageEndEvent,
    MessageStartEvent,
    MessageUpdateEvent,
    ToolEndEvent,
    ToolResultAmendedEvent,
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
    InputMessageMetadata,
    PreparedStep,
    ReleaseFailed,
    ReleaseHook,
    RunAction,
    RunConfig,
    RunFailure,
    RunFailureKind,
    RunHooks,
    RunOutcome,
    RunProgress,
    RunResult,
    RunState,
    RunStatus,
    StepInput,
    StepRecord,
    StepResult,
    ToolCallContext,
    ToolExecutionRecord,
    ToolResultAmendment,
    ToolResultContext,
    cancellation_failure,
    messages_from_steps,
)
from onyx.agents.tool_execution import DENIED_CALL_MESSAGE, ToolBatch
from onyx.agents.tools import (
    AgentTool,
    ChildRunWait,
    HumanToolAnswer,
    InputDecision,
    InputMode,
    NestedInputRequest,
    NestedInputWait,
    PendingToolInput,
    ToolProgress,
)
from onyx.llm.cancellation import (
    AgentCancelled,
    CancellationSignal,
    CancelReason,
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
    NamedToolChoice,
    ToolCall,
    ToolChoiceOptions,
    ToolDefinition,
    ToolResult,
    ToolResultMessage,
    UserMessage,
    apply_generation_event,
)
from onyx.llm.token_budget import TokenBudget, resolve_token_budget
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import start_thread_with_context

if TYPE_CHECKING:
    from onyx.agents.agent_coordination import (
        AgentCoordinator,
        RunCoordination,
        ToolApprovals,
    )

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


class InputNotWaiting(ValueError):
    """The run no longer waits for the request that an answer names."""


class AgentBusy(RuntimeError):
    """The agent cannot start a run now; a later attempt can."""


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


class AgentFeature(Protocol):
    """Application state and decisions of an agent, such as chat's citations
    and code cells. A feature never holds its Agent or a Run, so a finished
    agent and its runs are freed by reference counting."""

    def bind(self) -> RunHooks:
        """The tools and hooks of a run that starts now."""
        ...

    def restore_state(self, state: Mapping[str, JsonValue]) -> None:
        """Before the run starts again elsewhere, restore what `capture_state`
        saved; read borrowed state without changing it."""
        ...


class Agent:
    """A conversation with resolved model, tools, and an optional feature that
    decides its steps. One run executes at a time."""

    def __init__(
        self,
        llm: LLM,
        *,
        generation_context: GenerationContext,
        state: AgentState | None = None,
        system_prompt: str = "",
        tools: Sequence[AgentTool] = (),
        tool_phases: Mapping[str, Sequence[str]] | None = None,
        options: GenerationOptions | None = None,
        feature: AgentFeature | None = None,
        on_drained: Callable[[], None] | None = None,
        agent_id: str | None = None,
        previous_run_id: str | None = None,
    ) -> None:
        """`on_drained`: see RunConfig."""
        if generation_context.flow is None:
            raise ValueError("Agent generation context requires an LLMFlow")
        self._id = agent_id or str(uuid4())
        self.llm = llm
        self._tools = tuple(tool.snapshot() for tool in tools)
        phases: dict[str, frozenset[str]] = {}
        for name, names in (tool_phases or {}).items():
            selected = frozenset(names)
            if not name or len(selected) != len(names):
                raise ValueError("Tool phases require unique configured tool names")
            phases[name] = selected
        self._tool_phases = MappingProxyType(phases)
        self.system_prompt = system_prompt
        self.options = options or GenerationOptions()
        self.generation_context = generation_context
        self.feature = feature
        self.on_drained = on_drained
        self._state = (state or AgentState()).snapshot()
        for message in self._state.messages:
            if message.id is None:
                message.id = str(uuid4())
        self._previous_run_id = previous_run_id
        self._lock = threading.RLock()
        self._latest_run: Run | None = None

    def _bind(self) -> tuple[RunHooks, tuple[AgentTool, ...]]:
        """The feature's hooks for a new run, and the run's tools: the agent's,
        then the feature's."""
        hooks = self.feature.bind() if self.feature is not None else RunHooks()
        tools = (*self._tools, *hooks.tools)
        names = {tool.name for tool in tools}
        if len(names) != len(tools):
            raise ValueError("Tool names must be unique")
        if not all(phase <= names for phase in self._tool_phases.values()):
            raise ValueError("Tool phases require unique configured tool names")
        return hooks, tools

    @property
    def tools(self) -> tuple[AgentTool, ...]:
        """Detached inspection copies of the tools that a run starting now gets."""
        return tuple(tool.snapshot() for tool in self._bind()[1])

    @property
    def id(self) -> str:
        return self._id

    @property
    def latest_run_id(self) -> str | None:
        with self._lock:
            return (
                self._latest_run.id
                if self._latest_run is not None
                else self._previous_run_id
            )

    @property
    def state(self) -> AgentState:
        with self._lock:
            latest_run = self._latest_run
            if latest_run is None:
                return self._state.snapshot()
            return latest_run.conversation()

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
        deadline_at: datetime | None = None,
    ) -> "Run":
        """Start a worker, or execute here until suspension or completion with background=False.

        At `deadline_at` the run is cancelled and records a `DEADLINE` failure.
        `max_steps` bounds the steps, with one exception; see "Preparing and
        completing steps" in the agents README.
        """
        AgentStep(index=0, limit=max_steps)
        hooks, tools = self._bind()
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
                        raise AgentBusy("Agent is already running or draining")
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
                            step_limit=max_steps,
                            deadline_at=deadline_at,
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
        config = RunConfig(
            llm=self.llm,
            defaults=PreparedStep(
                system_prompt=self.system_prompt,
                options=self.options.model_copy(deep=True),
            ),
            tools=tools,
            tool_phases=self._tool_phases,
            approval_required=frozenset(
                name for tool in tools for name in tool.approval_required
            ),
            generation_context=self.generation_context.model_copy(
                update={
                    "cancellation": run.cancellation_signal,
                    "user_identity": self.generation_context.user_identity.model_copy()
                    if self.generation_context.user_identity
                    else None,
                }
            ),
            hooks=hooks,
            on_drained=self.on_drained,
        )
        try:
            run._start(
                self,
                config,
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
        answers: Sequence[HumanToolAnswer] = (),
        deadline_at: datetime | None = None,
        coordinator: "AgentCoordinator | None" = None,
        on_event: Callable[[AgentEvent], None] | None = None,
        event_dispatcher: EventDispatcher | None = None,
    ) -> "Run":
        """Restore a suspended run after its previous owner has released execution.

        `answers` answer saved requests before execution starts, as `Run.submit`
        does. `deadline_at` replaces the saved deadline. The feature's state is
        restored before the run starts, so a start that fails leaves it
        restored; resume a freshly built agent.
        """
        if snapshot.status != RunStatus.SUSPENDED or snapshot.progress is None:
            raise ValueError("Only a suspended execution snapshot can resume")
        if snapshot.agent_id != self.id:
            raise ValueError("Snapshot belongs to another agent")
        snapshot = snapshot.model_copy(deep=True)
        progress = snapshot.progress
        if progress is None:
            raise ValueError("Only a suspended execution snapshot can resume")
        for answer in answers:
            _record_answer(progress, answer, progress.input_requests)
        if deadline_at is not None:
            progress.deadline_at = deadline_at
        if progress.finalized_tool_call_ids:
            if not 0 <= progress.step_index < len(snapshot.steps):
                raise ValueError("Finalized tools require a recorded current step")
            step = snapshot.steps[progress.step_index]
            call_ids = {call.id for call in step.message.tool_calls}
            for call_id in progress.finalized_tool_call_ids:
                execution = step.tools.get(call_id)
                if (
                    call_id not in call_ids
                    or execution is None
                    or execution.result is None
                    or execution.result.tool_call_id != call_id
                ):
                    raise ValueError(
                        "Finalized tool must have a call and result in the current step"
                    )
        if progress.feature_state is not None:
            if self.feature is None:
                raise ValueError("Feature restoration is required for this state")
            self.feature.restore_state(progress.feature_state)
        return self.start(
            max_steps=progress.step_limit,
            coordinator=coordinator,
            on_event=on_event,
            event_dispatcher=event_dispatcher,
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
        # Tool call IDs of the conversation and this run; built on the first step.
        self._tool_call_ids: set[str] | None = None
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
        self._watched_children: dict[str, Future[RunState]] = {}
        # Set while the run can execute; see RunConfig.
        self._config: RunConfig | None = None
        # Serializes prepare_tool_result and recording, so each call of the
        # hook sees every result recorded before it.
        self._result_lock = threading.Lock()
        self._step_tools: list[AgentTool] | None = None
        self.work = ExecutionWork(self._execution_condition)
        self.coordination: RunCoordination | None = None
        self._thread_context = copy_context()
        self._cancellation_link = ExitStack()
        self._released = False

    @property
    def config(self) -> RunConfig:
        """The configuration of the run's current execution."""
        config = self._config
        if config is None:
            raise RuntimeError("Run has no execution owner")
        return config

    def conversation(self) -> AgentState:
        """An isolated copy of the conversation through this run: the history
        before it, its input and its output."""
        with self.execution_lock:
            return AgentState(
                messages=[
                    message.model_copy(deep=True)
                    for message in [
                        *self._history.messages,
                        *self._state.input_messages,
                        *self._state.messages,
                    ]
                ],
                checkpoint=self._state.checkpoint.model_copy(deep=True)
                if self._state.checkpoint
                else None,
            )

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
            if progress is None:
                return []
            return [
                request.model_copy(deep=True)
                for request in progress.input_requests
                if request.request_id not in progress.human_tool_answers
            ]

    @property
    def approvals(self) -> "ToolApprovals | None":
        """The application's gate for calls that wait for the user's approval."""
        coordination = self.coordination
        return coordination.coordinator.approvals if coordination is not None else None

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

    def cancel(self, reason: CancelReason = "requested") -> None:
        with self.execution_lock:
            if self._released or self._completed.done():
                return
        self.cancellation_signal.cancel(reason)
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
            if self._config is None:
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
            if self._state.status.is_terminal:
                if existing is None:
                    raise InputNotWaiting("Run is not accepting input")
                if _conflicts(existing, answer):
                    raise ValueError("Conflicting answer for request")
                return
            if _record_answer(progress, answer, progress.input_requests):
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

    @property
    def is_done(self) -> bool:
        """Whether execution has completed or released ownership."""
        return self._completed.done()

    def wait_for_completion(self, timeout: float = OPERATION_TIMEOUT_SECONDS) -> None:
        """Wait for terminal handling without copying output or waiting for cleanup."""
        self._completed.result(timeout=timeout)

    @property
    def idle(self) -> Future[None]:
        """Resolves when the current execution's work has drained."""
        return self._idle

    def track_child_work(self, child: "Run") -> None:
        """Keep this execution busy until the child's current workers drain."""
        self.work.track_operation(child.idle)

    @property
    def suspension_requested(self) -> bool:
        with self.execution_lock:
            return self._execution_request == ExecutionRequest.SUSPEND

    def start_tool_calls(
        self, calls: Sequence[ToolCall], display_name: str | None
    ) -> None:
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
                    status=ExecutionStatus.RUNNING, display_name=display_name
                )
                self.publish_event(
                    ToolStartEvent(
                        **self.event_context,
                        message_id=message_id,
                        step_index=self._progress.step_index,
                        tool_call=call,
                        display_name=display_name,
                    )
                )

    def record_tool_results(
        self, result: ToolResult, calls: Sequence[ToolCall]
    ) -> None:
        """Record the result of calls, after `prepare_tool_result` replaces
        it; `finish_tool` later ends them. Call without the execution lock."""
        config = self._config
        prepare = config.hooks.prepare_tool_result if config is not None else None
        if prepare is None:
            with self.execution_lock:
                record, message_id = self._accepting_tool_step()
                self._store_tool_results(record, message_id, result, calls)
            return
        with self._result_lock:
            with self.execution_lock:
                record, message_id = self._accepting_tool_step()
                step_results = tuple(
                    execution.result
                    for execution in record.tools.values()
                    if execution.result is not None
                )
            result = prepare(
                ToolResultContext(
                    message_id=message_id,
                    calls=tuple(calls),
                    result=result,
                    step_results=step_results,
                )
            )
            # Checkpoint capture must not split a completed batch.
            with self.execution_lock:
                self._accepting_tool_step()
                self._store_tool_results(record, message_id, result, calls)

    def _accepting_tool_step(self) -> tuple[StepRecord, str]:
        """The step that a completed tool batch records into; the caller holds
        the execution lock. A batch that ends after the run closed records
        nothing, and the hook does no work for it."""
        self.cancellation_signal.check()
        if not self.is_accepting:
            logger.warning("Tool batch completed after its run closed: %s", self.id)
            raise AgentCancelled()
        record = self._state.steps[self._progress.step_index]
        message_id = record.message.id
        if message_id is None:
            raise RuntimeError("Tool execution requires a message ID")
        return record, message_id

    def _store_tool_results(
        self,
        record: StepRecord,
        message_id: str,
        result: ToolResult,
        calls: Sequence[ToolCall],
    ) -> None:
        """The caller holds the execution lock."""
        for call in calls:
            execution = record.tools[call.id]
            recorded = execution.result = _tool_result_message(result, call, message_id)
            execution.status = (
                ExecutionStatus.ERROR if result.is_error else ExecutionStatus.COMPLETE
            )
            # The recorded copy: the tool still holds `result`.
            self.publish_event(
                ToolUpdateEvent(
                    **self.event_context,
                    message_id=message_id,
                    step_index=self._progress.step_index,
                    tool_call=call,
                    progress=ToolProgress(
                        content="" if recorded.is_error else recorded.text,
                        details=recorded.details,
                    ),
                )
            )

    def record_pending_tool(
        self, call: ToolCall, pending: PendingToolInput | ChildRunWait | NestedInputWait
    ) -> None:
        # Events show the run's copy: the tool still holds `pending`.
        pending = pending.model_copy(deep=True)
        with self.execution_lock:
            self.cancellation_signal.check()
            shown: list[NestedInputRequest] = []
            if isinstance(pending, PendingToolInput):
                self._check_new_request_id(pending.request_id)
                shown = self._input_waits(call, pending)
            elif isinstance(pending, NestedInputWait):
                request_ids = {nested.request.request_id for nested in pending.requests}
                if len(request_ids) != len(pending.requests):
                    raise ValueError("Input request IDs must be unique within a run")
                for nested in pending.requests:
                    # A request that the gate opened is already shown.
                    if (
                        self._progress.open_inputs.pop(nested.request.request_id, None)
                        is None
                    ):
                        self._check_new_request_id(nested.request.request_id)
                        shown.append(nested)
            self._progress.pending_tool_calls[call.id] = pending
            self._state.revision += 1
            if self.is_accepting and self.event_delivery:
                for wait in shown:
                    self.event_delivery.publish(
                        InputRequiredEvent(**self.event_context, **dict(wait))
                    )

    def _check_new_request_id(self, request_id: str) -> None:
        """Reject a request ID that an open, saved or answered request of this
        run already uses. Call under the execution lock."""
        progress = self._progress
        if request_id in progress.human_tool_answers or any(
            request.request_id == request_id for request in progress.input_requests
        ):
            raise ValueError("Input request IDs must be unique within a run")

    def open_nested_input(self, request: NestedInputRequest) -> None:
        """Show an open request of a call that a tool makes for the model; see
        NestedCallGate."""
        # Events show the run's copy: the tool still holds `request`.
        request = request.model_copy(deep=True)
        with self.execution_lock:
            self.cancellation_signal.check()
            self._check_new_request_id(request.request.request_id)
            self._progress.open_inputs[request.request.request_id] = request
            self._state.revision += 1
            self.publish_event(
                InputRequiredEvent(**self.event_context, **dict(request))
            )

    def withdraw_nested_input(self, request: NestedInputRequest) -> None:
        """End an open request whose call stopped waiting, for example because
        its program ended, with the answer that the run recorded for it, if
        any; no-op once a NestedInputWait saved it or it ended.

        The end event goes out under the lock that removes the request, so
        either this call or the run's end reports it, exactly once."""
        request_id = request.request.request_id
        with self.execution_lock:
            if self._progress.open_inputs.pop(request_id, None) is None:
                return
            self._state.revision += 1
            if self.event_delivery:
                self.event_delivery.publish(
                    InputEndedEvent(
                        **self.event_context,
                        **dict(request),
                        answer=self._progress.human_tool_answers.get(request_id),
                    )
                )
        approvals = self.approvals
        if request.request.approval and approvals is not None:
            try:
                # The gate saves how the request ended; a gate that fails is
                # logged, so the call still ends.
                approvals.withdraw_approval(request_id)
            except Exception:
                logger.exception(
                    "Run %s could not withdraw approval request %s", self.id, request_id
                )

    def _input_waits(
        self, call: ToolCall, pending: PendingToolInput | ChildRunWait | NestedInputWait
    ) -> list[NestedInputRequest]:
        """The input requests that `call` of the current step waits for. Call
        under the execution lock."""
        if isinstance(pending, NestedInputWait):
            return list(pending.requests)
        if not isinstance(pending, PendingToolInput):
            return []
        step_index = self._progress.step_index
        message_id = self._state.steps[step_index].message.id
        if message_id is None:
            raise RuntimeError("Tool execution requires a message ID")
        return [
            NestedInputRequest(
                message_id=message_id,
                step_index=step_index,
                tool_call=call,
                nested_call=None,
                request=pending,
            )
        ]

    def _withdraw_pending_inputs(self) -> None:
        """Report the requests that end with the run: saved ones and those that
        tools opened, with the answers that the run recorded, such as the
        user's rejection when the user stopped it. A direct call whose answer
        denies it or supplies its result keeps that result, so later runs see
        it. Call under the execution lock."""
        ended: list[NestedInputRequest] = []
        progress = self._state.progress
        answers = progress.human_tool_answers if progress is not None else {}
        if progress is not None and progress.pending_tool_calls:
            step = self._state.steps[progress.step_index]
            for call in step.message.tool_calls:
                pending = progress.pending_tool_calls.get(call.id)
                if pending is None:
                    continue
                waits = self._input_waits(call, pending)
                ended.extend(waits)
                answer = (
                    answers.get(pending.request_id)
                    if isinstance(pending, PendingToolInput)
                    else None
                )
                if answer is None or answer.decision == InputDecision.APPROVE:
                    continue
                result = answer.result or ToolResult(
                    content=DENIED_CALL_MESSAGE, is_error=True
                )
                execution = step.tools.setdefault(
                    call.id, ToolExecutionRecord(status=ExecutionStatus.ERROR)
                )
                execution.result = _tool_result_message(
                    result, call, waits[0].message_id
                )
                execution.status = (
                    ExecutionStatus.ERROR
                    if result.is_error
                    else ExecutionStatus.COMPLETE
                )
        if progress is not None:
            ended.extend(progress.open_inputs.values())
            progress.open_inputs.clear()
        if self.event_delivery:
            for wait in ended:
                self.event_delivery.publish(
                    InputEndedEvent(
                        **self.event_context,
                        **dict(wait),
                        answer=answers.get(wait.request.request_id),
                    )
                )

    def resolve_tool_wait(self, call: ToolCall) -> None:
        """Stop the call's wait; an input request ends with its recorded answer."""
        with self.execution_lock:
            progress = self._progress
            pending = progress.pending_tool_calls.pop(call.id)
            self._state.revision += 1
            for wait in self._input_waits(call, pending):
                self.publish_event(
                    InputEndedEvent(
                        **self.event_context,
                        **dict(wait),
                        answer=progress.human_tool_answers.get(wait.request.request_id),
                    )
                )

    def resolve_open_inputs(self, request_ids: Collection[str]) -> None:
        """End open requests whose tool took their answers
        (`AgentTool.continue_open_input`)."""
        with self.execution_lock:
            progress = self._progress
            for request_id in request_ids:
                request = progress.open_inputs.pop(request_id, None)
                if request is None:
                    continue
                self._state.revision += 1
                self.publish_event(
                    InputEndedEvent(
                        **self.event_context,
                        **dict(request),
                        answer=progress.human_tool_answers.get(request_id),
                    )
                )

    def finish_tool(self, call: ToolCall, context: ToolCallContext | None) -> None:
        with self.execution_lock:
            record = self._state.steps[self._progress.step_index]
            execution = record.tools[call.id]
            result_message = execution.result
            if result_message is None:
                raise RuntimeError("Completed tool result is missing from history")
            message_id = record.message.id
            if message_id is None:
                raise RuntimeError("Tool execution requires a message ID")
            result = ToolResult(
                content=result_message.content,
                metadata=result_message.metadata,
                cacheable=result_message.cacheable,
                details=result_message.details,
                is_error=result_message.is_error,
                terminate=result_message.terminate,
            )
        finalized = False
        after_tool_call = self.config.hooks.after_tool_call
        try:
            if after_tool_call is not None:
                if context is None:
                    raise RuntimeError("Tool finalization requires callback context")
                self.cancellation_signal.check()
                result = after_tool_call(context, result)
                self.cancellation_signal.check()
            finalized = True
        finally:
            with self.execution_lock:
                if self.is_accepting and not self.cancellation_signal.cancelled:
                    if finalized and after_tool_call is not None:
                        execution.result = _tool_result_message(
                            result, call, message_id
                        )
                        execution.status = (
                            ExecutionStatus.ERROR
                            if result.is_error
                            else ExecutionStatus.COMPLETE
                        )
                    if finalized:
                        self._progress.finalized_tool_call_ids.add(call.id)
                        self._state.revision += 1
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
        config: RunConfig,
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
                    external_cancellation.on_cancel(
                        lambda: self.cancellation_signal.cancel(
                            external_cancellation.reason or "requested"
                        )
                    )
                )
            self._config = config
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
                    self.cancel("deadline")
                else:
                    timer = threading.Timer(remaining, self.cancel, ("deadline",))
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
                self.work = ExecutionWork(self._execution_condition)
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
            if not self.is_accepting or self._config is None:
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
            self.work.begin_cycle()
            if self._execution_request == ExecutionRequest.SUSPEND:
                return False
            self._execution_request = ExecutionRequest.NONE
            return True

    def wait_for_tool_activity(self) -> None:
        """Wait for work activity, an accepted input, or cancellation."""
        ready = self.work.wait_for_activity(
            lambda: (
                self.cancellation_signal.cancelled
                or self._execution_request == ExecutionRequest.WAKE
            ),
            OPERATION_TIMEOUT_SECONDS,
        )
        if not ready:
            raise TimeoutError("Agent tool exceeded its execution bound")

    def _execute(self) -> None:
        llm = self.config.llm
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

    @property
    def watched_run_ids(self) -> tuple[str, ...]:
        """The runs that this run has watched for completion. Read without the
        execution lock: the coordinator reads it under its own lock, which
        holders of that lock can wait for."""
        return tuple(self._watched_children)

    def watch_children(self, run_ids: list[str]) -> None:
        if self.coordination is None:
            raise RuntimeError("Child dependencies require a coordinator")
        coordinator = self.coordination.coordinator
        for run_id in run_ids:
            with self.execution_lock:
                watched = self._watched_children.get(run_id)
                if watched is not None and (
                    not watched.done() or watched.exception() is None
                ):
                    continue
            completion = coordinator.child_completion(run_id, self.agent_id)
            with self.execution_lock:
                if self._watched_children.get(run_id) is completion:
                    continue
                self._watched_children[run_id] = completion
            completion.add_done_callback(lambda _future: self._wake_execution())

    def _suspend(self) -> None:
        amendments, failure = self._release_amendments(self.config.hooks.on_suspend)
        if amendments:
            with self.execution_lock:
                self._apply_amendments(amendments)
        # A run cancelled while the hook ran finishes instead of suspending,
        # as cancelled even when the hook failed.
        self.cancellation_signal.check()
        if failure is not None:
            # The run fails instead of suspending.
            raise failure
        capture_state = self.config.hooks.capture_state
        if capture_state is not None:
            feature_state = _FEATURE_STATE.validate_python(
                capture_state().model_dump(mode="json")
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
            # The hook runs only when no foreground child waits or works;
            # otherwise the run's later end runs it, after their work drains.
            coordination = self.coordination
            if coordination is None or (
                not coordination.pending_children()
                and coordination.coordinator.children_idle(list(coordination.children))
            ):
                self._work_drained()
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

    def _finish(self, outcome: RunOutcome, llm: LLM) -> None:
        self._cancellation_link.close()
        amendments, failure = self._release_amendments(self.config.hooks.on_finish)
        if failure is not None:
            if outcome == RunStatus.CANCELLED:
                # A Stop or deadline wins: the run stays cancelled.
                logger.warning(
                    "Run %s was cancelled; its release hook also failed: %s",
                    self.id,
                    failure,
                )
            else:
                with self.execution_lock:
                    if self._state.failure is None:
                        self._state.failure = _failure(failure, llm)
                        outcome = RunStatus.ERROR
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
            # After partial messages end, so live events keep the saved order.
            self._apply_amendments(amendments)
            self._withdraw_pending_inputs()
            if outcome == RunStatus.CANCELLED and self._state.failure is None:
                # Deadlines and user stops are reported; a plain request is not.
                self._state.failure = cancellation_failure(
                    self.cancellation_signal.reason or "requested"
                )
            self._state.status = outcome
            if self.event_delivery:
                self.event_delivery.publish(
                    AgentEndEvent(
                        **self.event_context,
                        outcome=outcome,
                        failure=self._state.failure,
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

    def _release_amendments(
        self, hook: ReleaseHook | None
    ) -> tuple[list[ToolResultAmendment], Exception | None]:
        """Ask a finish or suspend hook for the final results of this run's calls,
        and the error that fails the run, if the hook raised ReleaseFailed.

        The hook runs without the execution lock, since it can wait for tool work.
        A hook that fails otherwise or stops for cancellation sets no results, so
        the run still ends or suspends normally.
        """
        if hook is None:
            return [], None
        with self.execution_lock:
            # Not copied: the hook reads them and must not change them.
            results = [
                message
                for message in self._state.messages
                if isinstance(message, ToolResultMessage)
            ]
        error: Exception | None = None
        try:
            amendments = hook(results)
        except ReleaseFailed as failed:
            amendments, error = failed.amendments, failed.error
        except AgentCancelled:
            logger.info("Run release hook stopped for cancellation: %s", self.id)
            return [], None
        except Exception:
            logger.exception("Run release hook failed: %s", self.id)
            return [], None
        prepare = self.config.hooks.prepare_tool_result
        if prepare is None or not amendments:
            return amendments, error
        # Amended results go through prepare_tool_result as recorded ones do,
        # under the run's signal: a stopped run's amendments apply as the hook
        # made them.
        prepared: list[ToolResultAmendment] = []
        with cancellation_scope(self.cancellation_signal), self._result_lock:
            for amendment in amendments:
                with self.execution_lock:
                    message_id, call = next(
                        (
                            (step.message.id, call)
                            for step in self._state.steps
                            for call in step.message.tool_calls
                            if call.id == amendment.call_id
                        ),
                        (None, None),
                    )
                if message_id is None or call is None:
                    # _apply_amendments logs and skips it.
                    prepared.append(amendment)
                    continue
                try:
                    result = prepare(
                        ToolResultContext(
                            message_id=message_id,
                            calls=(call,),
                            result=amendment.result,
                            step_results=(),
                            amended=True,
                        )
                    )
                except AgentCancelled:
                    # The call gets the amendment as the hook made it.
                    logger.info(
                        "Run %s stopped preparing the amendment of %s",
                        self.id,
                        amendment.call_id,
                    )
                    prepared.append(amendment)
                    continue
                except Exception:
                    logger.exception(
                        "Run %s could not prepare the amendment of %s",
                        self.id,
                        amendment.call_id,
                    )
                    prepared.append(amendment)
                    continue
                prepared.append(amendment.model_copy(update={"result": result}))
        return prepared, error

    def _apply_amendments(self, amendments: Sequence[ToolResultAmendment]) -> None:
        """Set the final results of started calls; the caller holds the execution lock.

        An amendment replaces a recorded result, or gives a call that ended without
        one its result. The call keeps its execution status. An amendment that names
        no started call of this run is logged and skipped. A compaction summary that
        covers an amended result describes the replaced one, so it is dropped and
        the next request builds its context from the amended result.
        """
        started = {
            call.id: (index, message_id, step.tools[call.id], call)
            for index, step in enumerate(self._state.steps)
            if (message_id := step.message.id) is not None
            for call in step.message.tool_calls
            if call.id in step.tools
        }
        amended_ids: set[str | None] = set()
        for amendment in amendments:
            located = started.get(amendment.call_id)
            if located is None:
                logger.warning(
                    "Ignoring amendment of a call this run did not start: %s",
                    amendment.call_id,
                )
                continue
            index, message_id, execution, call = located
            execution.result = _tool_result_message(amendment.result, call, message_id)
            amended_ids.add(execution.result.id)
            if self.event_delivery:
                self.event_delivery.publish(
                    ToolResultAmendedEvent(
                        **self.event_context,
                        message_id=message_id,
                        step_index=index,
                        tool_call=call,
                        result=amendment.result,
                        display_name=execution.display_name,
                    )
                )
        checkpoint = self._state.checkpoint
        if checkpoint is None or not amended_ids:
            return
        order = [message.id for message in self._state.messages]
        if checkpoint.covered_through_message_id in order:
            covered = order[: order.index(checkpoint.covered_through_message_id) + 1]
            if amended_ids.intersection(covered):
                self._state.checkpoint = None

    def _work_drained(self) -> None:
        """Call the agent's on_drained hook; the run's work has drained."""
        hook = self._config.on_drained if self._config is not None else None
        if hook is None:
            return
        # Cleanup goes on whatever the hook raises: the run must still become
        # idle and reusable.
        try:
            hook()
        except AgentCancelled:
            logger.info(
                "Run on_drained hook stopped for cancellation: %s",
                self.id,
            )
        except Exception:
            logger.exception("Run on_drained hook failed: %s", self.id)

    def _clear_execution_config(self) -> None:
        self._token_counts.clear()
        self._step_tools = None
        self._config = None

    def _drain_workers(self) -> None:
        delivery = self.event_delivery
        if delivery is not None:
            self.work.tracker.follow(delivery.tracker)

        if self.coordination is not None:
            self.coordination.close()
        self._execution_active = False

        def finish_cleanup() -> None:
            self._work_drained()
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
                coordination.coordinator.release_execution(
                    self, watched_run_ids=list(self._watched_children)
                )
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
    # _complete_step can raise or lower the limit so that an extra step is the
    # run's last step.
    while run._progress.step_index < run._progress.step_limit:
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
        if progress.action == RunAction.WAIT_CHILDREN:
            if not run.begin_work_cycle():
                return RunStatus.SUSPENDED
            if run.coordination is None:
                raise RuntimeError("Waiting for delegated work requires a coordinator")
            if run.coordination.wait_for_delegations():
                return RunStatus.SUSPENDED
            with run.execution_lock:
                progress.action = RunAction.PREPARE
                run._state.revision += 1
        if progress.action == RunAction.PREPARE:
            if not run.begin_work_cycle():
                return RunStatus.SUSPENDED
            step = AgentStep(index=progress.step_index, limit=progress.step_limit)
            prepare = run.config.hooks.prepare_step
            prepared = run.config.defaults
            ownership = (
                run.coordination.coordinator.ownership if run.coordination else None
            )
            received = ownership.receive_inputs(run) if ownership is not None else []
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
                # Built from recorded, validated objects: not validated again.
                prepared = prepare(
                    StepInput.model_construct(
                        history=tuple(run._history.messages),
                        input_messages=tuple(run._state.input_messages),
                        messages=tuple(run._state.messages),
                        step=step,
                        previous=previous,
                        received_inputs=tuple(received),
                    )
                )
                cancellation_signal.check()
            if prepared.input_messages is None:
                prepared = prepared.model_copy(update={"input_messages": received})
            if not _advance_step(run, llm, prepared, step):
                continue
        if progress.action == RunAction.TOOLS:
            if not _execute_tools(run):
                return RunStatus.SUSPENDED
        if progress.action == RunAction.AFTER_STEP:
            _complete_step(run)
    raise RuntimeError("Run exhausted its steps without a terminal decision")


def _resolve_step_tools(
    run: Run, prepared: PreparedStep
) -> tuple[tuple[AgentTool, ...], PreparedStep]:
    """Resolve fixed schemas and validate step permissions before model or tool effects."""
    phase_names = None
    if prepared.tool_phase is not None:
        phase_names = run.config.tool_phases.get(prepared.tool_phase)
        if phase_names is None:
            raise ValueError(f"Unknown tool phase {prepared.tool_phase!r}")
    phase_tools = tuple(
        tool
        for tool in run.config.tools
        if phase_names is None or tool.name in phase_names
    )
    advertised_names = frozenset(tool.name for tool in phase_tools)
    allowed = prepared.allowed_tool_names
    if allowed is None:
        allowed = advertised_names
    elif not allowed <= advertised_names:
        raise ValueError("Step permissions must select tools in the configured phase")
    options = prepared.options
    if isinstance(options.tool_choice, NamedToolChoice):
        if options.tool_choice.name not in allowed:
            raise ValueError("Named tool choice must be allowed for this step")
    elif not allowed:
        if options.tool_choice == ToolChoiceOptions.REQUIRED:
            raise ValueError("Required tool choice needs an allowed tool")
        options = options.model_copy(update={"tool_choice": ToolChoiceOptions.NONE})
    prepared = prepared.model_copy(
        update={
            "allowed_tool_names": frozenset()
            if options.tool_choice == ToolChoiceOptions.NONE
            else prepared.allowed_tool_names,
            "options": options,
        }
    )
    return phase_tools, prepared


def _advance_step(
    run: Run,
    llm: LLM,
    prepared: PreparedStep,
    step: AgentStep,
) -> bool:
    """Record the step and generate; return False when another owner took its input."""
    cancellation_signal = run.cancellation_signal
    phase_tools, prepared = _resolve_step_tools(run, prepared)
    allowed = prepared.allowed_tool_names
    run._step_tools = [
        tool for tool in phase_tools if allowed is None or tool.name in allowed
    ]
    definitions = tuple(tool.definition for tool in phase_tools)
    generation_context = run.config.generation_context.model_copy(
        update={
            "stall_timeout_s": prepared.stall_timeout_s
            or run.config.generation_context.stall_timeout_s,
        }
    )
    # Compaction tells the task question from later input by this metadata.
    if any(
        not isinstance(message.metadata, InputMessageMetadata)
        and not is_input_context(message)
        for message in prepared.input_messages or []
    ):
        raise ValueError("Between-step input needs InputMessageMetadata")
    inputs = [
        message.model_copy(
            deep=True,
            update={
                "id": message.id or f"{run.id}:{step.index}:input:{index}",
                # History keeps provenance only; content metadata served preparation.
                "metadata": message.metadata.model_copy(
                    update={"content_metadata": None}
                )
                if isinstance(message.metadata, InputMessageMetadata)
                else message.metadata,
            },
        )
        for index, message in enumerate(prepared.input_messages or [])
    ]
    source = [
        *run._history.messages,
        *run._state.input_messages,
        *run._state.messages,
        *inputs,
    ]
    call_ids = run._tool_call_ids
    if call_ids is None:
        call_ids = run._tool_call_ids = {
            call.id
            for message in source
            if isinstance(message, AssistantMessage)
            for call in message.tool_calls
        }
    # Compaction can leave calls out of the request; new calls must not reuse them.
    reserved = frozenset(call_ids)
    request = (
        _compact_context(
            run, llm, source, prepared, generation_context, tools=definitions
        ).model_copy(update={"reserved_tool_call_ids": reserved})
        if not inputs
        else None
    )
    message_id = f"{run._state.run_id}:{step.index}"
    started = MessageStartEvent(
        message_id=message_id,
        **run.event_context,
        step_index=step.index,
        metadata=prepared.output_metadata,
        input_messages=inputs,
    )
    with run.execution_lock:
        cancellation_signal.check()
        recorded_step = StepRecord(
            input_messages=inputs,
            message=AssistantMessage(id=message_id, metadata=prepared.output_metadata),
            generation_status=ExecutionStatus.RUNNING,
        )
        ownership = run.coordination.coordinator.ownership if run.coordination else None
        if (
            ownership is not None
            and inputs
            and not ownership.accept_inputs(run, recorded_step)
        ):
            return False
        run._state.steps.append(recorded_step)
        if run.event_delivery:
            run.event_delivery.publish(started)

    if request is None:
        request = _compact_context(
            run, llm, source, prepared, generation_context, tools=definitions
        ).model_copy(update={"reserved_tool_call_ids": reserved})
    execution_options = request.options

    timeout = generation_context.total_timeout_s
    deadline = time.monotonic() + min(
        timeout if timeout is not None else OPERATION_TIMEOUT_SECONDS,
        OPERATION_TIMEOUT_SECONDS,
    )

    def generate() -> None:
        cancellation_signal.check()
        if time.monotonic() >= deadline:
            raise LLMTimeoutError("Model generation exceeded its total timeout")
        logger.debug(
            "Agent run %s step %d: generation started", run._state.run_id, step.index
        )
        generation_started = time.monotonic()
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
        logger.debug(
            "Agent run %s step %d: generation ended after %.1fs with %d tool calls",
            run._state.run_id,
            step.index,
            time.monotonic() - generation_started,
            len(recorded_step.message.tool_calls or []),
        )

    try:
        generate()
    except LLMContextLimitError:
        partial = recorded_step.message
        if partial.content:
            raise
        request = _compact_context(
            run,
            llm,
            source,
            prepared,
            generation_context,
            tools=definitions,
            force=True,
        ).model_copy(update={"reserved_tool_call_ids": reserved})
        execution_options = request.options
        with run.execution_lock:
            recorded_step.message = AssistantMessage(
                id=message_id, metadata=recorded_step.message.metadata
            )
        generate()
    with run.execution_lock:
        cancellation_signal.check()
        recorded_step.generation_status = ExecutionStatus.COMPLETE
        call_ids.update(call.id for call in recorded_step.message.tool_calls)
        ended = MessageEndEvent(
            **run.event_context,
            message_id=message_id,
            step_index=step.index,
            message=recorded_step.message,
            status=ExecutionStatus.COMPLETE,
        )
        if run.event_delivery:
            run.event_delivery.publish(ended)
        run._progress.options = execution_options
        run._progress.tools = list(definitions)
        run._progress.allowed_tool_names = allowed
        run._progress.action = RunAction.TOOLS
        run._state.revision += 1
    return True


def _compact_context(
    run: Run,
    llm: LLM,
    source: list[Message],
    prepared: PreparedStep,
    generation_context: GenerationContext,
    *,
    force: bool = False,
    tools: Sequence[ToolDefinition] = (),
) -> GenerationRequest:
    cancellation_signal = run.cancellation_signal
    previous = run._state.checkpoint
    input_start = len(run._history.messages) if run._state.input_messages else None
    try:
        messages = working_messages(source, previous, input_start=input_start)
    except CheckpointMismatchError as error:
        logger.info("Ignoring compaction checkpoint: %s", error)
        previous = None
        messages = list(source)
        with run.execution_lock:
            run._state.checkpoint = None
    cancellation_signal.check()
    request = prepared.generation_request(messages, tools=tools)
    cancellation_signal.check()
    budget = context_budget(llm)
    output = resolve_token_budget(llm)
    if not force and not run._token_counts:
        # Each cl100k token consumes at least one byte. UTF-8 uses at most
        # four bytes per character, and one for ASCII.
        upper_bound = request_tokens(
            request, lambda text: len(text) * (1 if text.isascii() else 4)
        )
        if (
            upper_bound <= budget.trigger
            and output.output_allowance(upper_bound) == output.max_output_tokens
        ):
            return _limit_output(output, request, upper_bound)
    original_size = cached_request_tokens(request, run._token_counts)
    if not force and original_size <= budget.trigger:
        return _limit_output(output, request, original_size)

    selected_checkpoint = None
    try:
        selected_checkpoint = compact_history(
            llm,
            source,
            previous,
            generation_context,
            partial(count_tokens, cached_counts=run._token_counts),
            input_start=input_start,
        )
        cancellation_signal.check()
    except Exception:
        cancellation_signal.check()
        if not force and original_size <= budget.input_limit:
            logger.warning(
                "Proactive compaction failed while request still fits",
                exc_info=True,
            )
            return _limit_output(output, request, original_size)
        logger.warning("Compaction failed; truncating older turns", exc_info=True)

    candidate_request = request
    candidate_size = original_size
    if selected_checkpoint is not None:
        cancellation_signal.check()
        candidate_request = prepared.generation_request(
            working_messages(source, selected_checkpoint, input_start=input_start),
            tools=tools,
        )
        cancellation_signal.check()
        candidate_size = cached_request_tokens(candidate_request, run._token_counts)

    if selected_checkpoint is None or candidate_size > budget.input_limit:
        selected_checkpoint, candidate_request, candidate_size = _truncate_context(
            cancellation_signal,
            source,
            prepared,
            tools=tools,
            token_counts=run._token_counts,
            input_limit=budget.input_limit,
            original_size=original_size,
            input_start=input_start,
        )

    with run.execution_lock:
        cancellation_signal.check()
        run._state.checkpoint = selected_checkpoint
    return _limit_output(output, candidate_request, candidate_size)


def _truncate_context(
    cancellation_signal: CancellationSignal,
    source: list[Message],
    prepared: PreparedStep,
    *,
    tools: Sequence[ToolDefinition] = (),
    token_counts: dict[str, int],
    input_limit: int,
    original_size: int,
    input_start: int | None = None,
) -> tuple[CompactionCheckpoint, GenerationRequest, int]:
    """Find the first smaller request that fits after removing older turns."""
    boundaries = set(history_boundaries(source, input_start=input_start))
    for index, message in enumerate(source):
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
        candidate_request = prepared.generation_request(
            messages_after_compaction(source, index, summary=""), tools=tools
        )
        cancellation_signal.check()
        candidate_size = cached_request_tokens(candidate_request, token_counts)
        if candidate_size <= input_limit and candidate_size < original_size:
            return checkpoint, candidate_request, candidate_size
    raise ContextLimitError(
        "Required instructions and current turn exceed model input limit"
    )


def _limit_output(
    budget: TokenBudget, request: GenerationRequest, input_tokens: int
) -> GenerationRequest:
    allowance = budget.output_allowance(input_tokens)
    if allowance is None:
        return request
    max_tokens = request.options.max_tokens
    return request.model_copy(
        update={
            "options": request.options.model_copy(
                update={
                    "max_tokens": min(max_tokens, allowance)
                    if max_tokens is not None
                    else allowance
                }
            )
        }
    )


def _execute_tools(run: Run) -> bool:
    progress = run._progress
    if run._step_tools is None:
        available = {tool.name: tool for tool in run.config.tools}
        allowed = progress.allowed_tool_names
        if allowed is not None and not allowed <= {
            tool.name for tool in progress.tools
        }:
            raise ValueError("Restored tool permissions exceed the saved declarations")
        # A restored step runs only the tools whose parameters its calls were
        # made with; descriptions and other tools can differ.
        run._step_tools = [
            tool
            for declaration in progress.tools
            if (tool := available.get(declaration.name)) is not None
            and tool.definition.parameters == declaration.parameters
            and (allowed is None or tool.name in allowed)
        ]
    recorded = [
        *run._history.messages,
        *run._state.input_messages,
        *messages_from_steps(run._state.steps[: progress.step_index]),
        *run._state.steps[progress.step_index].input_messages,
    ]
    batch = ToolBatch(
        run,
        tools=run._step_tools,
        progress=progress,
        record=run._state.steps[progress.step_index],
        history=working_messages(
            recorded,
            run._state.checkpoint,
            input_start=len(run._history.messages)
            if run._state.input_messages
            else None,
        ),
        recorded=recorded,
    )
    if not batch.execute():
        return False
    with run.execution_lock:
        progress.action = RunAction.AFTER_STEP
        run._state.revision += 1
    return True


def _complete_step(run: Run) -> None:
    cancellation_signal = run.cancellation_signal
    after_step = run.config.hooks.after_step
    cancellation_signal.check()
    progress = run._progress
    step = run._state.steps[progress.step_index]
    calls = step.message.tool_calls
    results = [
        execution.result
        for call in calls
        if (execution := step.tools.get(call.id)) is not None
        and execution.result is not None
    ]
    # A step whose tool results all set `terminate` ends the run.
    terminated = bool(results) and all(result.terminate for result in results)
    should_continue = (
        after_step(_step_result(run, progress.options, progress.step_index))
        if after_step is not None
        else bool(calls)
    ) and not terminated
    step_limit = progress.step_limit
    # A step that declares tools but lets none run; the rule is in "Preparing
    # and completing steps" in the agents README.
    if (
        progress.tools
        and progress.options is not None
        and progress.options.tool_choice == ToolChoiceOptions.NONE
    ):
        previous = (
            run._state.steps[progress.step_index - 1] if progress.step_index else None
        )
        took_extra_step = (
            previous is not None
            and progress.previous_options is not None
            and progress.previous_options.tool_choice == ToolChoiceOptions.NONE
            and bool(previous.message.tool_calls)
        )
        should_continue = bool(calls) and not took_extra_step
        if should_continue:
            step_limit = progress.step_index + 2
        elif not step.message.text.strip():
            raise RuntimeError(
                "The model did not return a final answer after tool execution."
            )
    cancellation_signal.check()
    has_delegated_work = run.coordination is not None and bool(
        run.coordination.delegated_runs()
    )
    # Collect delegated results before accepting an early answer or using the last step.
    wait_for_children = has_delegated_work and (
        not should_continue or progress.step_index + 2 >= step_limit
    )
    should_continue = should_continue or has_delegated_work
    ownership = run.coordination.coordinator.ownership if run.coordination else None
    with run.execution_lock:
        progress.previous_options = progress.options
        progress.step_limit = step_limit
        can_continue = progress.step_index + 1 < progress.step_limit
        if (
            not should_continue
            and can_continue
            and ownership is not None
            and not terminated
        ):
            # Unread messages continue the run while steps remain; after a
            # terminating step they wait for the next run.
            should_continue = ownership.has_unread_inputs(run)
        if not should_continue or not can_continue:
            progress.outcome = (
                RunStatus.LIMIT if should_continue else RunStatus.COMPLETE
            )
            progress.action = RunAction.FINISH
            if not should_continue:
                run._state.answer_step_index = progress.step_index
        else:
            progress.step_index += 1
            progress.action = (
                RunAction.WAIT_CHILDREN if wait_for_children else RunAction.PREPARE
            )
            progress.finalized_tool_call_ids.clear()
            progress.pending_tool_calls = {}
            progress.options = None
            progress.tools = []
            progress.allowed_tool_names = None
        run._state.revision += 1


def _step_result(
    run: Run, options: GenerationOptions | None, step_index: int
) -> StepResult:
    """The recorded output of a step, not a copy."""
    if options is None:
        raise ValueError("Saved step is missing generation options")
    step = run._state.steps[step_index]
    return StepResult.model_construct(
        step=AgentStep(index=step_index, limit=run._progress.step_limit),
        message=step.message,
        tool_results=tuple(
            execution.result
            for call in step.message.tool_calls
            if (execution := step.tools.get(call.id)) is not None
            and execution.result is not None
        ),
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


def _record_answer(
    progress: RunProgress,
    answer: HumanToolAnswer,
    requests: Sequence[PendingToolInput],
) -> bool:
    """Record an answer to one of `requests`; False when it repeats the
    recorded answer. An answer that only makes the recorded one standing,
    such as an approval that the user later approves for the chat, replaces
    it; one that only drops `standing` repeats it. Raises ValueError for a
    conflicting or unmatched answer."""
    existing = progress.human_tool_answers.get(answer.request_id)
    if existing is not None:
        if _conflicts(existing, answer):
            raise ValueError("Conflicting answer for request")
        if existing.standing or not answer.standing:
            return False
        progress.human_tool_answers[answer.request_id] = answer.model_copy(deep=True)
        return True
    request = next(
        (item for item in requests if item.request_id == answer.request_id), None
    )
    if request is None:
        raise InputNotWaiting("Unknown input request")
    if (request.mode == InputMode.RESULT) != (answer.decision == InputDecision.RESULT):
        raise ValueError("Answer does not match the request mode")
    progress.human_tool_answers[answer.request_id] = answer.model_copy(deep=True)
    return True


def _conflicts(recorded: HumanToolAnswer, answer: HumanToolAnswer) -> bool:
    """Whether `answer` differs from the recorded answer in more than
    `standing`."""
    return recorded.model_copy(update={"standing": answer.standing}) != answer
