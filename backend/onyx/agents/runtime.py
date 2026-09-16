"""Stateful agents with one execution path and independent run records."""

import asyncio
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
    ExecutionServices,
    ExecutionWork,
    WorkTracker,
)
from onyx.agents.events import (
    AgentEndEvent,
    AgentEvent,
    AgentStartEvent,
    MessageEndEvent,
    MessageStartEvent,
    MessageUpdateEvent,
    StepEndEvent,
    StepStartEvent,
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
    BlockingRunner,
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
from onyx.utils.threadpool_concurrency import get_background_event_loop

if TYPE_CHECKING:
    from onyx.agents.coordination import AgentCoordinator, RunCoordination

logger = setup_logger()
DEFAULT_MAX_PARALLEL_OPERATIONS = 8
MAX_TOOL_CALLS_PER_STEP = 64


def _cancel_tasks[T](tasks: Sequence[asyncio.Task[T]]) -> None:
    for task in tasks:
        # A second cancellation would interrupt the task's cleanup handler.
        if not task.cancelling():
            task.cancel()


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
    if isinstance(error, LLMTimeoutError):
        return RunFailure(
            kind=RunFailureKind.LLM_TIMEOUT, message="Model generation timed out"
        )
    if isinstance(error, LLMRateLimitError):
        return RunFailure(
            kind=RunFailureKind.LLM_RATE_LIMIT, message="Model rate limit reached"
        )
    info = litellm_exception_to_safe_error(error, llm, fallback_to_error_msg=False)
    return RunFailure(
        kind=RunFailureKind.EXECUTION, message=info.message, llm_error=info
    )


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
        self.loop = asyncio.get_running_loop()
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
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is self._state.loop:
            raise RuntimeError("Use await run.wait() on the agent's event loop")
        self._state.completed.result(timeout=timeout)
        return result_from_snapshot(self.snapshot())

    def add_idle_callback(self, callback: Callable[[], None]) -> None:
        """Call once admitted work finishes; callbacks must not block."""
        self._state.idle.add_done_callback(lambda _future: callback())

    async def wait(self, timeout: float = OPERATION_TIMEOUT_SECONDS) -> RunResult:
        await asyncio.wait_for(
            asyncio.shield(asyncio.wrap_future(self._state.completed)), timeout
        )
        return result_from_snapshot(self.snapshot())

    async def wait_for_idle(self, timeout: float = OPERATION_TIMEOUT_SECONDS) -> bool:
        delivery = self._state.delivery
        if delivery is not None and delivery.is_dispatch_thread:
            raise RuntimeError("An observer cannot wait for its own run to become idle")
        if timeout < 0:
            raise ValueError("Idle timeout must be nonnegative")
        if self._state.idle.done():
            return True
        try:
            await asyncio.wait_for(
                asyncio.shield(asyncio.wrap_future(self._state.idle)), timeout
            )
        except TimeoutError:
            return False
        return True


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
        max_parallel_operations: int = DEFAULT_MAX_PARALLEL_OPERATIONS,
        agent_id: str | None = None,
        previous_run_id: str | None = None,
    ) -> None:
        if max_parallel_operations < 1:
            raise ValueError("Parallel operation capacity must be positive")
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
        self.max_parallel_operations = max_parallel_operations
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
        execution_services: ExecutionServices | None = None,
        parent_run_id: str | None = None,
        parent_tool_call_id: str | None = None,
        parent_message_id: str | None = None,
        inherited_event_sink: Callable[[AgentEvent], None] | None = None,
        on_event: Callable[[AgentEvent], None] | None = None,
    ) -> Run:
        AgentStep(index=0, limit=max_steps)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:

            async def start() -> Run:
                return self.start(
                    max_steps=max_steps,
                    messages=messages,
                    cancellation=cancellation,
                    coordinator=coordinator,
                    execution_services=execution_services,
                    parent_run_id=parent_run_id,
                    parent_tool_call_id=parent_tool_call_id,
                    parent_message_id=parent_message_id,
                    inherited_event_sink=inherited_event_sink,
                    on_event=on_event,
                )

            submitted = asyncio.run_coroutine_threadsafe(
                start(), get_background_event_loop()
            )
            return submitted.result(timeout=OPERATION_TIMEOUT_SECONDS)
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
        services = execution_services
        try:
            services = execution_services or ExecutionServices(
                self.max_parallel_operations
            )
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
                services=services,
                own_services=execution_services is None,
                commit=self._commit,
                release=self._release,
                inherited_event_sink=inherited_event_sink,
            )
            if coordinator is not None:
                executor.coordination = coordinator.bind(
                    run, services, executor.publish_child, signal
                )
        except BaseException:
            with self._lock:
                self._active = None
                self._reserved = False
            if execution_services is None and services is not None:
                services.close()
            if state.delivery:
                loop.create_task(state.delivery.close())
            raise
        loop.call_soon(lambda: asyncio.create_task(executor.execute(max_steps)))
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
        services: ExecutionServices,
        own_services: bool,
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
        self.services = services
        self.own_services = own_services
        self.work = ExecutionWork(services)
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
        if self.state.completed.done():
            return
        if self.state.delivery:
            self.state.delivery.publish(event)
        if self.inherited_event_sink:
            self.inherited_event_sink(event)

    def _emit(self, event: AgentEvent) -> None:
        with self.state.lock:
            if self.state.completed.done():
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
            self.publish_child(event)

    async def execute(self, max_steps: int) -> None:
        signal = self.state.signal
        previous: StepResult | None = None
        outcome = RunStatus.ERROR
        try:
            with cancellation_scope(signal):
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
                        await self.work.blocking(
                            lambda prepare=prepare, decision=decision: prepare(
                                decision
                            ),
                            signal,
                        )
                        if prepare
                        else self.defaults
                    )
                    self._emit(StepStartEvent(**self.ancestry, step_index=index))
                    previous = await self._step(prepared, decision.step)
                    self._emit(
                        StepEndEvent(
                            **self.ancestry,
                            step_index=index,
                            message=previous.message,
                            tool_results=previous.tool_results,
                        )
                    )
                    after_step = self.after_step
                    completed = previous.model_copy(deep=True)
                    should_continue = (
                        await self.work.blocking(
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
                        outcome = RunStatus.COMPLETE
                        break
                    if decision.step.is_last:
                        outcome = RunStatus.LIMIT
                if self.coordination:
                    children = await self.coordination.finish(cancel=False)
                    with self.state.lock:
                        self.state.record.child_runs = children
                if previous is None:
                    raise RuntimeError("Execution ended without output")
                if outcome not in (RunStatus.COMPLETE, RunStatus.LIMIT):
                    raise RuntimeError("Execution ended without a terminal outcome")
        except (AgentCancelled, asyncio.CancelledError):
            outcome = RunStatus.CANCELLED
            signal.cancel()
        except Exception as error:
            logger.exception("Agent execution failed")
            with self.state.lock:
                self.state.record.failure = _failure(error, self.llm)
            outcome = RunStatus.ERROR
            signal.cancel()
        finally:
            await self._finish(outcome)

    async def _finish(
        self,
        outcome: Literal[
            RunStatus.COMPLETE, RunStatus.LIMIT, RunStatus.CANCELLED, RunStatus.ERROR
        ],
    ) -> None:
        if self.coordination and outcome in (RunStatus.ERROR, RunStatus.CANCELLED):
            try:
                children = await self.coordination.finish(cancel=True)
            except Exception as error:
                logger.exception("Child executions did not reach terminal output")
                outcome = RunStatus.ERROR
                children = [
                    child.run.snapshot()
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
            self._emit(AgentEndEvent(**self.ancestry, outcome=outcome))
            record = self.state.record.model_copy(deep=True)
        self.commit(record)
        self.state.completed.set_result(None)
        delivery = self.state.delivery
        if delivery is not None:
            await delivery.close()
        pending = WorkTracker()
        pending.started()
        if delivery is not None:
            pending.started()
        if self.coordination is not None:
            pending.started()
        if self.own_services:
            pending.started()
        self.work.tracker.on_idle(pending.finished)
        if delivery is not None:
            delivery.tracker.on_idle(pending.finished)
        if self.coordination is not None:
            self.coordination.add_idle_callback(pending.finished)
        if self.own_services:
            self.services.tracker.on_idle(pending.finished)

        def release() -> None:
            if delivery is not None:
                self.state.delivery_failed = delivery.failed.is_set()
                self.state.delivery = None
            if self.coordination is not None:
                self.coordination.release()
            if self.own_services:
                self.services.close()
            self.release()
            self.state.idle.set_result(None)

        pending.on_idle(release)

    async def _step(self, prepared: PreparedStep, step: AgentStep) -> StepResult:
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
        request = await self._fit_context(prepared, execution)
        with self.state.lock:
            self.step_start = len(self.messages)
            start = self.step_start
            self.generating = True
            self.messages.append(AssistantMessage(metadata=prepared.output_metadata))
            self._emit(
                MessageStartEvent(
                    **self.ancestry,
                    step_index=step.index,
                    metadata=prepared.output_metadata,
                )
            )

        def accept(event: GenerationEvent) -> None:
            with self.state.lock:
                if self.state.completed.done():
                    raise AgentCancelled()
                if event.request_params:
                    self.state.record.request_params = event.request_params.model_copy(
                        deep=True
                    )
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
                    self.work.accept(lambda event=event: accept(event), signal)
                    if event.type == "done":
                        final = event.message.model_copy(deep=True)
            if final is None:
                raise RuntimeError("Model stream ended without completed output")
            return final

        try:
            message = await self.work.blocking(generate, signal)
        except LLMContextLimitError:
            partial = self.messages[start]
            if partial.text or (
                isinstance(partial, AssistantMessage) and partial.tool_calls
            ):
                raise
            request = await self._fit_context(prepared, execution, force=True)
            message = await self.work.blocking(generate, signal)
        with self.state.lock:
            signal.check()
            self.messages[start] = message
            self.generating = False
            self._emit(
                MessageEndEvent(**self.ancestry, step_index=step.index, message=message)
            )
        tool_messages = working_messages(
            [*self.history, *self.state.record.input_messages, *self.messages[:start]],
            self.state.record.checkpoint,
        )
        results = await self._tools(
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

    async def _fit_context(
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
        request = await self.work.blocking(
            lambda: prepared.generation_request(working_messages(source, previous)),
            signal,
        )
        budget = context_budget(self.llm)
        size = request_tokens(request)
        if not force and size <= budget.trigger:
            return request
        try:
            checkpoint = await self.work.blocking(
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
        request = await self.work.blocking(
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

    async def _tools(
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
        tasks: list[asyncio.Task[ToolResultMessage]] = []

        sequential = any(
            tool.execution_mode == ToolExecutionMode.SEQUENTIAL
            for call in calls
            if (tool := tools.get(call.name)) is not None
        )
        failure: asyncio.Future[BaseException] = scope.loop.create_future()
        cancelled: asyncio.Future[None] = scope.loop.create_future()

        def completed(task: asyncio.Task[ToolResultMessage]) -> None:
            error = AgentCancelled() if task.cancelled() else task.exception()
            if error is not None and not failure.done():
                failure.set_result(error)

        result_start = len(self.messages)
        call_indices = {call.id: index for index, call in enumerate(calls)}
        finalize_lock = asyncio.Lock()
        tool_capacity = asyncio.Semaphore(self.services.parallelism)

        async def execute(call: ToolCall, index: int) -> ToolResultMessage:
            async with tool_capacity:
                result = await self._execute_tool(
                    scope=scope,
                    signal=signal,
                    context=ToolCallContext(
                        step=step,
                        call=call,
                        request=request.model_copy(deep=True),
                        messages=[
                            message.model_copy(deep=True) for message in messages
                        ],
                    ),
                    tool=tools.get(call.name),
                    index=index,
                    ancestry=ancestry,
                    is_truncated=message.stop_reason == "length",
                )
            item = self._record_tool_result(
                result, call, result_start, call_indices, index
            )
            try:
                async with finalize_lock:
                    after_tool_call = self.after_tool_call
                    if after_tool_call:
                        context = ToolCallContext(
                            step=step,
                            call=call,
                            request=request.model_copy(deep=True),
                            messages=[
                                message.model_copy(deep=True) for message in messages
                            ],
                        )
                        enriched = await scope.blocking(
                            lambda: after_tool_call(
                                context, result.model_copy(deep=True)
                            ),
                            signal,
                        )
                        item = ToolResultMessage(
                            content=enriched.content,
                            details=enriched.details,
                            is_error=enriched.is_error,
                            terminate=enriched.terminate,
                            tool_call_id=call.id,
                            tool_name=call.name,
                        )
                        self._replace_tool_result(item, result_start)
                        result = enriched
                return item
            finally:
                self._emit(
                    ToolEndEvent(
                        **ancestry, step_index=step.index, tool_call=call, result=result
                    )
                )

        def start(call: ToolCall, index: int) -> asyncio.Task[ToolResultMessage]:
            task = asyncio.create_task(execute(call, index))
            scope.track_task(task)
            task.add_done_callback(completed)
            tasks.append(task)
            return task

        def interrupt() -> None:
            _cancel_tasks(tasks)
            cancelled.set_result(None)

        results: list[ToolResultMessage] = []
        try:
            if not sequential:
                for index, call in enumerate(calls):
                    start(call, index)
            with signal.on_cancel(lambda: scope.loop.call_soon_threadsafe(interrupt)):
                for index, call in enumerate(calls):
                    signal.check()
                    task = start(call, index) if sequential else tasks[index]
                    done, _ = await asyncio.wait(
                        {task, failure, cancelled},
                        return_when=asyncio.FIRST_COMPLETED,
                        timeout=OPERATION_TIMEOUT_SECONDS,
                    )
                    if not done:
                        raise TimeoutError("Agent tool exceeded its execution bound")
                    signal.check()
                    if failure.done():
                        raise failure.result()
                    results.append(await task)
            return results
        except asyncio.CancelledError as error:
            signal.cancel()
            raise AgentCancelled() from error
        except BaseException:
            signal.cancel()
            raise
        finally:
            _cancel_tasks(tasks)
            if tasks:
                _, pending = await asyncio.wait(tasks, timeout=CLEANUP_SECONDS)
                if pending:
                    logger.warning(
                        "Tool cleanup exceeded its bound: %s operations", len(pending)
                    )
                    _cancel_tasks(list(pending))

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
            if self.state.completed.done():
                logger.warning("Tool completed after its run closed: %s", call.id)
                raise AgentCancelled()
            # Accept outcomes on completion; keep model history in call order.
            offset = sum(
                call_indices[previous.tool_call_id] < index
                for previous in self.messages[result_start:]
                if isinstance(previous, ToolResultMessage)
            )
            self.messages.insert(result_start + offset, item.model_copy(deep=True))
        return item

    async def _execute_tool(
        self,
        *,
        scope: ExecutionWork,
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
        if call.argument_error or is_truncated:
            return ToolResult(
                content=call.argument_error or "Tool arguments were truncated.",
                is_error=True,
            )
        before_tool_call = self.before_tool_call
        if before_tool_call:
            result = await scope.blocking(lambda: before_tool_call(context), signal)
            if result is not None:
                return result
        active = threading.Event()
        active.set()

        def update(progress: ToolProgress) -> None:
            with self.state.lock:
                if not active.is_set():
                    logger.debug("Ignoring late tool progress: %s", call.id)
                    return
                signal.check()
                event = ToolUpdateEvent(
                    **ancestry, step_index=step.index, tool_call=call, progress=progress
                )
            scope.accept(lambda: self._emit(event), signal)

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
            run_blocking=_InvocationRunner(scope, signal),
        )
        try:
            if tool.execute_async is not None:
                result = await tool.execute_async(invocation)
            else:
                execute_sync = tool.execute
                if execute_sync is None:
                    raise RuntimeError("Tool has no execution implementation")
                result = await scope.blocking(lambda: execute_sync(invocation), signal)
            return result
        finally:
            active.clear()


class _InvocationRunner(BlockingRunner):
    def __init__(self, scope: ExecutionWork, signal: CancellationSignal) -> None:
        self.scope = scope
        self.signal = signal

    async def __call__[T](
        self, operation: Callable[[], T], *, cleanup: bool = False
    ) -> T:
        if not cleanup:
            return await self.scope.blocking(operation, self.signal)
        signal = CancellationSignal()

        def clean_up() -> T:
            with cancellation_scope(signal):
                return operation()

        try:
            return await asyncio.wait_for(
                self.scope.blocking(clean_up, signal), CLEANUP_SECONDS
            )
        finally:
            signal.cancel()
