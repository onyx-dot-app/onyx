"""Stateful agents with one execution path and independent run records."""

import threading
from collections.abc import Callable, Sequence
from concurrent.futures import Future
from contextlib import closing
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
    CLEANUP_SECONDS,
    OPERATION_TIMEOUT_SECONDS,
    EventDelivery,
    ExecutionWork,
)
from onyx.agents.events import (
    AgentEndEvent,
    AgentEvent,
    AgentStartEvent,
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
    PreparedStep,
    RunResult,
    RunSnapshot,
    StepInput,
    StepResult,
    ToolCallContext,
)
from onyx.agents.tools import (
    AgentTool,
    ToolExecutionMode,
    ToolInvocation,
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
)
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import start_thread_with_context

if TYPE_CHECKING:
    from onyx.agents.coordination import AgentCoordinator, RunCoordination

logger = setup_logger()
MAX_TOOL_CALLS_PER_STEP = 64


class _Ancestry(TypedDict):
    agent_id: str
    run_id: str
    parent_run_id: str | None
    parent_tool_call_id: str | None
    parent_message_id: str | None


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
    def __init__(self, record: RunSnapshot, signal: CancellationSignal) -> None:
        self.lock = threading.RLock()
        self.record = record
        self.signal = signal
        self.accepting = True
        self.completed: Future[None] = Future()
        self.idle: Future[None] = Future()
        self.delivery: EventDelivery | None = EventDelivery()
        self.delivery_failed = False


class Run:
    """Controls and accepted output for one execution."""

    def __init__(self, state: _RunState) -> None:
        self._state = state
        self.id = state.record.run_id
        if state.record.agent_id is None:
            raise ValueError("Executable run requires an agent identity")
        self.agent_id = state.record.agent_id

    @property
    def status(self) -> RunStatus:
        with self._state.lock:
            return self._state.record.status

    def snapshot(self) -> RunSnapshot:
        with self._state.lock:
            return self._state.record.model_copy(deep=True)

    @property
    def delivery_failed(self) -> bool:
        delivery = self._state.delivery
        return delivery.failed.is_set() if delivery else self._state.delivery_failed

    def cancel(self) -> None:
        if not self._state.completed.done():
            self._state.signal.cancel()

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
        if record.status != RunStatus.RUNNING:
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
        before_tool_call: Callable[[ToolCallContext], ToolResult | None] | None = None,
        after_tool_call: Callable[[ToolCallContext, ToolResult], ToolResult]
        | None = None,
        agent_id: str | None = None,
        previous_run_id: str | None = None,
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
    ) -> Run:
        AgentStep(index=0, limit=max_steps)
        with self._lock:
            if self._reserved:
                raise RuntimeError("Agent is already running or draining")
            history = self._context.snapshot()
            signal = (
                cancellation
                or current_cancellation()
                or self.execution.cancellation
                or CancellationSignal()
            )
            state = _RunState(
                RunSnapshot(
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
            )
            self._active = state
            self._reserved = True
        run = Run(state)
        if on_event is not None:
            run.subscribe(on_event)
        try:
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
            )
            if coordinator is not None:
                executor.coordination = coordinator.bind(
                    run, executor.work, executor.publish_child, signal
                )
        except BaseException:
            with self._lock:
                self._active = None
                self._reserved = False
            if state.delivery:
                state.delivery.close()
            raise
        try:
            start_thread_with_context(
                lambda: executor.execute(max_steps), name="agent-run", daemon=True
            )
        except BaseException:
            if executor.coordination is not None:
                executor.coordination.release()
            with self._lock:
                self._active = None
                self._reserved = False
            if state.delivery:
                state.delivery.close()
            raise
        return run

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

    def run(
        self,
        *,
        max_steps: int,
        messages: Sequence[Message] = (),
        cancellation: CancellationSignal | None = None,
        coordinator: "AgentCoordinator | None" = None,
    ) -> RunResult:
        run = self.start(
            max_steps=max_steps,
            messages=messages,
            cancellation=cancellation,
            coordinator=coordinator,
        )
        try:
            return run.result()
        except TimeoutError:
            run.cancel()
            raise
        finally:
            try:
                run._state.idle.result(timeout=CLEANUP_SECONDS)
            except TimeoutError:
                logger.warning("Agent returned while cancelled work is still draining")


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
        before_tool_call: Callable[[ToolCallContext], ToolResult | None] | None,
        after_tool_call: Callable[[ToolCallContext, ToolResult], ToolResult] | None,
        commit: Callable[[RunSnapshot], None],
        release: Callable[[], None],
        inherited_event_sink: Callable[[AgentEvent], None] | None,
    ) -> None:
        self.state = state
        self.history = history
        self.llm = llm
        self.defaults = defaults
        self.execution = execution
        self.prepare_step = prepare_step
        self.after_step = after_step
        self.before_tool_call = before_tool_call
        self.after_tool_call = after_tool_call
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

    def publish_child(self, event: AgentEvent) -> None:
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
            self.inherited_event_sink(event)
        except Exception:
            if self.state.delivery:
                self.state.delivery.failed.set()
            logger.exception("Inherited agent event delivery failed")

    def _emit(self, event: AgentEvent) -> None:
        with self.state.lock:
            if not self.state.accepting:
                return
            record = self.state.record
            if isinstance(event, MessageStartEvent):
                record.operations.append(
                    OperationSnapshot(
                        step_index=event.step_index,
                        message_index=len(self.messages) - 1,
                        status=RunStatus.RUNNING,
                    )
                )
            elif isinstance(event, ToolStartEvent):
                if self.step_start is None:
                    raise RuntimeError("Tool requires an assistant message")
                record.operations.append(
                    OperationSnapshot(
                        step_index=event.step_index,
                        message_index=self.step_start,
                        tool_call_id=event.tool_call.id,
                        status=RunStatus.RUNNING,
                    )
                )
            elif isinstance(event, (MessageEndEvent, ToolEndEvent)):
                call_id = (
                    event.tool_call.id if isinstance(event, ToolEndEvent) else None
                )
                for operation in record.operations:
                    if (
                        operation.step_index == event.step_index
                        and operation.tool_call_id == call_id
                    ):
                        operation.status = (
                            RunStatus.ERROR
                            if isinstance(event, ToolEndEvent) and event.result.is_error
                            else RunStatus.COMPLETE
                        )
                        break
            elif isinstance(event, AgentEndEvent):
                for operation in record.operations:
                    if operation.status == RunStatus.RUNNING:
                        operation.status = event.outcome
            if self.state.delivery:
                self.state.delivery.publish(event)
        self._publish_inherited(event)

    def execute(self, max_steps: int) -> None:
        signal = self.state.signal
        previous: StepResult | None = None
        outcome = RunStatus.ERROR
        try:
            with (
                cancellation_scope(signal),
                signal.on_operation(self.work.track_operation),
            ):
                signal.check()
                self._emit(AgentStartEvent(**self.ancestry))
                for index in range(max_steps):
                    signal.check()
                    decision = StepInput(
                        history=[m.model_copy(deep=True) for m in self.history],
                        input_messages=[
                            m.model_copy(deep=True)
                            for m in self.state.record.input_messages
                        ],
                        messages=[m.model_copy(deep=True) for m in self.messages],
                        step=AgentStep(index=index, limit=max_steps),
                        previous=previous.model_copy(deep=True) if previous else None,
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
                    previous = self._step(prepared, decision.step)
                    after_step = self.after_step
                    completed = previous.model_copy(deep=True)
                    should_continue = (
                        self.work.blocking(
                            lambda after_step=after_step, completed=completed: (
                                after_step(completed)
                            ),
                            signal,
                        )
                        if after_step
                        else bool(completed.message.tool_calls)
                        and not (
                            bool(completed.tool_results)
                            and all(
                                result.terminate for result in completed.tool_results
                            )
                        )
                    )
                    signal.check()
                    if not should_continue:
                        with self.state.lock:
                            self.state.record.answer_message_index = self.step_start
                        outcome = RunStatus.COMPLETE
                        break
                    if decision.step.is_last:
                        outcome = RunStatus.LIMIT
                if self.coordination:
                    children = self.coordination.finish(cancel=False)
                    with self.state.lock:
                        self.state.record.child_runs = children
                if previous is None:
                    raise RuntimeError("Execution ended without output")
                if outcome not in (RunStatus.COMPLETE, RunStatus.LIMIT):
                    raise RuntimeError("Execution ended without a terminal outcome")
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
            self._finish(outcome)

    def _finish(
        self,
        outcome: Literal[
            RunStatus.COMPLETE, RunStatus.LIMIT, RunStatus.CANCELLED, RunStatus.ERROR
        ],
    ) -> None:
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
            record = self.state.record.model_copy(deep=True)
        self._publish_inherited(terminal)
        self.commit(record)
        self.state.completed.set_result(None)
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
            self.state.idle.set_result(None)

        self.work.tracker.on_idle(release)

    def _step(self, prepared: PreparedStep, step: AgentStep) -> StepResult:
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
        execution = self.execution.model_copy(
            update={
                "cancellation": signal,
                "timeout": prepared.timeout or self.execution.timeout,
            }
        )
        request = self._fit_context(prepared, execution)
        with self.state.lock:
            self.step_start = len(self.messages)
            start = self.step_start
            self.generating = True
            self.messages.append(
                AssistantMessage(
                    id=f"{self.state.record.run_id}:{step.index}",
                    metadata=prepared.output_metadata,
                )
            )
        self._emit(
            MessageStartEvent(
                **self.ancestry,
                step_index=step.index,
                metadata=prepared.output_metadata,
            )
        )

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
            self._emit(
                MessageUpdateEvent(
                    **self.ancestry, step_index=step.index, generation_event=event
                )
            )

        def generate() -> AssistantMessage:
            final: AssistantMessage | None = None
            with closing(self.llm.stream(request, execution)) as events:
                for event in events:
                    signal.check()
                    accept(event)
                    if event.type == "done":
                        final = event.message.model_copy(deep=True)
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
            self.messages[start] = message
            self.generating = False
        self._emit(
            MessageEndEvent(**self.ancestry, step_index=step.index, message=message)
        )
        tool_messages = working_messages(
            [*self.history, *self.state.record.input_messages, *self.messages[:start]],
            self.state.record.checkpoint,
        )
        results = self._tools(
            self.work,
            signal,
            prepared,
            step,
            message,
            self.ancestry,
            request=request,
            messages=tool_messages,
        )
        return StepResult(
            step=step,
            message=message.model_copy(deep=True),
            tool_results=results,
            request=request,
        )

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
            return request
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
                return request
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
        return request

    def _tools(
        self,
        scope: ExecutionWork,
        signal: CancellationSignal,
        prepared: PreparedStep,
        step: AgentStep,
        message: AssistantMessage,
        ancestry: _Ancestry,
        *,
        request: GenerationRequest,
        messages: list[Message],
    ) -> list[ToolResultMessage]:
        calls = message.tool_calls
        if len(calls) > MAX_TOOL_CALLS_PER_STEP or len(
            {call.id for call in calls}
        ) != len(calls):
            raise ValueError(
                f"A step requires unique tool call IDs and at most {MAX_TOOL_CALLS_PER_STEP} calls"
            )
        tools = {tool.name: tool for tool in prepared.tools}
        sequential = any(
            tool.execution_mode == ToolExecutionMode.SEQUENTIAL
            for call in calls
            if (tool := tools.get(call.name)) is not None
        )
        result_start = len(self.messages)
        call_indices = {call.id: index for index, call in enumerate(calls)}
        condition = threading.Condition()
        futures: list[Future[ToolResultMessage]] = []
        finalized = 0

        def context(call: ToolCall) -> ToolCallContext:
            return ToolCallContext(
                step=step,
                call=call,
                request=request.model_copy(deep=True),
                messages=[item.model_copy(deep=True) for item in messages],
            )

        def execute(call: ToolCall, index: int) -> ToolResultMessage:
            nonlocal finalized
            result = self._execute_tool(
                signal=signal,
                context=context(call),
                tool=tools.get(call.name),
                index=index,
                ancestry=ancestry,
                is_truncated=message.stop_reason == "length",
            )
            item = self._record_tool_result(
                result, call, result_start, call_indices, index
            )
            self._emit(
                ToolUpdateEvent(
                    **ancestry,
                    step_index=step.index,
                    tool_call=call,
                    progress=ToolProgress(content=result.text, details=result.details),
                )
            )
            try:
                with condition:
                    ready = condition.wait_for(
                        lambda: finalized == index or signal.cancelled,
                        OPERATION_TIMEOUT_SECONDS,
                    )
                signal.check()
                if not ready:
                    raise TimeoutError("Tool result finalization exceeded its bound")
                if self.after_tool_call:
                    result = self.after_tool_call(
                        context(call), result.model_copy(deep=True)
                    )
                    item = ToolResultMessage(
                        content=result.content,
                        details=result.details,
                        is_error=result.is_error,
                        terminate=result.terminate,
                        tool_call_id=call.id,
                        tool_name=call.name,
                    )
                    self._replace_tool_result(item, result_start)
                return item
            finally:
                try:
                    self._emit(
                        ToolEndEvent(
                            **ancestry,
                            step_index=step.index,
                            tool_call=call,
                            result=result,
                        )
                    )
                finally:
                    with condition:
                        if finalized == index:
                            finalized += 1
                        condition.notify_all()

        def wake(_future: Future[ToolResultMessage] | None = None) -> None:
            with condition:
                condition.notify_all()

        def start(call: ToolCall, index: int) -> None:
            def operation() -> ToolResultMessage:
                with signal.on_operation(scope.track_operation):
                    return execute(call, index)

            future = scope.start(operation)
            futures.append(future)
            future.add_done_callback(wake)

        results: list[ToolResultMessage] = []
        try:
            if not sequential:
                for index, call in enumerate(calls):
                    signal.check()
                    start(call, index)
            with signal.on_cancel(wake):
                for index, call in enumerate(calls):
                    signal.check()
                    if sequential:
                        start(call, index)
                    future = futures[index]
                    with condition:
                        ready = condition.wait_for(
                            lambda future=future: (
                                signal.cancelled
                                or future.done()
                                or any(
                                    item.done() and item.exception() is not None
                                    for item in futures
                                )
                            ),
                            OPERATION_TIMEOUT_SECONDS,
                        )
                    signal.check()
                    if not ready:
                        raise TimeoutError("Agent tool exceeded its execution bound")
                    for item in futures:
                        if item.done() and (error := item.exception()) is not None:
                            raise error
                    results.append(future.result())
            return results
        except BaseException:
            signal.cancel()
            wake()
            raise

    def _replace_tool_result(self, item: ToolResultMessage, result_start: int) -> None:
        with self.state.lock:
            self.state.signal.check()
            for offset, stored in enumerate(
                self.messages[result_start:], start=result_start
            ):
                if (
                    isinstance(stored, ToolResultMessage)
                    and stored.tool_call_id == item.tool_call_id
                ):
                    self.messages[offset] = item.model_copy(deep=True)
                    return
            raise RuntimeError("Completed tool result is missing from history")

    def _record_tool_result(
        self,
        result: ToolResult,
        call: ToolCall,
        result_start: int,
        call_indices: dict[str, int],
        index: int,
    ) -> ToolResultMessage:
        item = ToolResultMessage(
            content=result.content,
            details=result.details,
            is_error=result.is_error,
            terminate=result.terminate,
            tool_call_id=call.id,
            tool_name=call.name,
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
            self.messages.insert(result_start + offset, item.model_copy(deep=True))
            for operation in reversed(self.state.record.operations):
                if (
                    operation.message_index == self.step_start
                    and operation.tool_call_id == call.id
                ):
                    operation.status = (
                        RunStatus.ERROR if result.is_error else RunStatus.COMPLETE
                    )
                    break
        return item

    def _execute_tool(
        self,
        *,
        signal: CancellationSignal,
        context: ToolCallContext,
        tool: AgentTool | None,
        is_truncated: bool,
        index: int,
        ancestry: _Ancestry,
    ) -> ToolResult:
        call = context.call
        step = context.step
        request = context.request
        self._emit(ToolStartEvent(**ancestry, step_index=step.index, tool_call=call))
        signal.check()
        context = ToolCallContext(
            step=step,
            call=call.model_copy(deep=True),
            request=request.model_copy(deep=True),
            messages=[message.model_copy(deep=True) for message in context.messages],
        )
        if tool is None or request.options.tool_choice == ToolChoiceOptions.NONE:
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
        if before_tool_call:
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
            return tool.execute(invocation)
        finally:
            with self.state.lock:
                active.clear()
