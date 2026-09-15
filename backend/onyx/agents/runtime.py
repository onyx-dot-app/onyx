"""Shared agent execution with owned children, context, and cancellation."""

import asyncio
import threading
import time
from collections.abc import Awaitable, Callable, Generator, Sequence
from concurrent.futures import Future
from contextlib import closing
from contextvars import Context, copy_context
from queue import Empty, Full, Queue
from typing import Literal, TypedDict
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, SerializeAsAny

from onyx.agents.compaction import (
    ContextLimitError,
    checkpoint_matches,
    compact_history,
    context_budget,
    request_tokens,
    working_messages,
)
from onyx.agents.events import (
    AgentEndEvent,
    AgentEvent,
    AgentStartEvent,
    InputConsumedEvent,
    InputKind,
    MessageEndEvent,
    MessageStartEvent,
    MessageUpdateEvent,
    StepEndEvent,
    StepStartEvent,
    ToolEndEvent,
    ToolStartEvent,
    ToolUpdateEvent,
)
from onyx.agents.tools import (
    AgentTool,
    BlockingRunner,
    ToolExecutionMode,
    ToolInvocation,
    ToolProgress,
)
from onyx.agents.transcript import (
    AgentTranscript,
    CompactionCheckpoint,
    OperationSnapshot,
    RunStatus,
    messages_for_model,
)
from onyx.llm.cancellation import (
    AgentCancelled,
    CancellationSignal,
    cancellation_scope,
    current_cancellation,
)
from onyx.llm.exceptions import LLMContextLimitError
from onyx.llm.interfaces import LLM, GenerationContext
from onyx.llm.models import (
    AssistantMessage,
    GenerationOptions,
    GenerationRequest,
    GenerationRequestParams,
    Message,
    ToolCall,
    ToolChoiceOptions,
    ToolResult,
    ToolResultMessage,
)
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import ContextThreadPoolExecutor

logger = setup_logger()
DEFAULT_MAX_PARALLEL_OPERATIONS = 8
MAX_CHILD_DEPTH = 8
MAX_ACTIVE_CHILDREN = 64
MAX_TOOL_CALLS_PER_STEP = 64
OPERATION_TIMEOUT_SECONDS = 1800.0
EXECUTION_POLL_SECONDS = 0.01
EVENT_QUEUE_CAPACITY = 1024
EVENT_CLEANUP_SECONDS = 2.0
DEFAULT_IDLE_WAIT_SECONDS = 60.0


class AgentStep(BaseModel):
    model_config = ConfigDict(frozen=True)
    index: int = Field(ge=0)
    limit: int = Field(gt=0)

    @property
    def is_last(self) -> bool:
        return self.index + 1 == self.limit


class AgentContext(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)
    messages: list[Message] = Field(default_factory=list)
    system_prompt: str = ""
    tools: list[AgentTool] = Field(default_factory=list)
    options: GenerationOptions = Field(default_factory=GenerationOptions)
    execution: GenerationContext = Field(default_factory=GenerationContext)
    checkpoint: CompactionCheckpoint | None = None
    output_metadata: SerializeAsAny[BaseModel] | None = None

    def generation_request(self) -> GenerationRequest:
        return GenerationRequest(
            messages=messages_for_model(self.messages),
            system_prompt=self.system_prompt,
            tools=[tool.definition.model_copy(deep=True) for tool in self.tools],
            options=self.options.model_copy(deep=True),
        )

    def snapshot(self) -> "AgentContext":
        return AgentContext(
            messages=[message.model_copy(deep=True) for message in self.messages],
            system_prompt=self.system_prompt,
            tools=list(self.tools),
            options=self.options.model_copy(deep=True),
            execution=self.execution.model_copy(),
            checkpoint=self.checkpoint.model_copy() if self.checkpoint else None,
            output_metadata=self.output_metadata.model_copy(deep=True)
            if self.output_metadata is not None
            else None,
        )


class ToolCallContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    step: AgentStep
    call: ToolCall
    context: AgentContext


class StepResult(BaseModel):
    step: AgentStep
    message: AssistantMessage
    tool_results: list[ToolResultMessage]


class RunResult(BaseModel):
    """Completed output for one run; conversation history remains on Agent.context."""

    run_id: str
    steps: int
    stop_reason: Literal[RunStatus.COMPLETE, RunStatus.LIMIT]
    output: AssistantMessage


class AgentHooks(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)
    prepare_step: Callable[[AgentContext, AgentStep], AgentContext | None] | None = None
    build_request: Callable[[AgentContext], GenerationRequest] | None = None
    before_tool_call: Callable[[ToolCallContext], ToolResult | None] | None = None
    after_tool_call: Callable[[ToolCallContext, ToolResult], ToolResult] | None = None
    after_step: Callable[[StepResult], bool | None] | None = None


class PendingInput(BaseModel):
    id: str
    run_id: str
    kind: InputKind
    message: Message


class RunSnapshot(BaseModel):
    """One run’s initial input and subsequent messages, including partial work.

    Operation indices address messages; input_messages is a separate prefix.
    """

    input_messages: list[Message] = Field(default_factory=list)
    run_id: str
    parent_run_id: str | None = None
    parent_tool_call_id: str | None = None
    parent_message_id: str | None = None
    status: RunStatus
    messages: list[Message]
    operations: list[OperationSnapshot] = Field(default_factory=list)
    children: list["RunSnapshot"] = Field(default_factory=list)
    request_params: GenerationRequestParams | None = None
    delivery_failed: bool = False
    checkpoint: CompactionCheckpoint | None = None

    def transcript(self) -> AgentTranscript:
        input_messages = [
            message.model_copy(deep=True) for message in self.input_messages
        ]
        messages = [message.model_copy(deep=True) for message in self.messages]
        for message in [*input_messages, *messages]:
            message.metadata = None
            if isinstance(message, ToolResultMessage):
                message.details = None
        return AgentTranscript(
            run_id=self.run_id,
            parent_run_id=self.parent_run_id,
            parent_tool_call_id=self.parent_tool_call_id,
            parent_message_id=self.parent_message_id,
            operations=[operation.model_copy() for operation in self.operations],
            children=[child.transcript() for child in self.children],
            status=self.status,
            input_messages=input_messages,
            messages=messages,
            checkpoint=self.checkpoint.model_copy(deep=True)
            if self.checkpoint
            else None,
        )


class _Ancestry(TypedDict):
    run_id: str
    parent_run_id: str | None
    parent_tool_call_id: str | None
    parent_message_id: str | None


class _Notification:
    def __init__(
        self, event: AgentEvent, listeners: Sequence[Callable[[AgentEvent], None]]
    ) -> None:
        self.event = event
        self.listeners = tuple(listeners)
        self.context: Context = copy_context()

    def send(self) -> bool:
        delivered = True
        for listener in self.listeners:
            try:
                listener(self.event.model_copy(deep=True))
            except AgentCancelled:
                delivered = False
                logger.debug(
                    "Observer cancelled during event delivery: %s", self.event.type
                )
            except Exception:
                delivered = False
                logger.exception("Agent observer failed: %s", self.event.type)
        return delivered


class _ExecutionScope:
    def __init__(self, capacity: int) -> None:
        self.loop = asyncio.get_running_loop()
        self.capacity = asyncio.Semaphore(capacity)
        self.active_children = 0
        self.workers = ContextThreadPoolExecutor(capacity, "agent-operation")
        self.observers = ContextThreadPoolExecutor(1, "agent-events")
        self.events: Queue[_Notification] = Queue(EVENT_QUEUE_CAPACITY)
        self.closed = threading.Event()
        self.delivery_failed = threading.Event()
        self.pump = asyncio.create_task(self._deliver())

    async def blocking[T](
        self, operation: Callable[[], T], signal: CancellationSignal
    ) -> T:
        deadline = time.monotonic() + OPERATION_TIMEOUT_SECONDS
        while True:
            signal.check()
            if time.monotonic() >= deadline:
                raise TimeoutError("Agent operation exceeded its execution bound")
            try:
                await asyncio.wait_for(self.capacity.acquire(), EXECUTION_POLL_SECONDS)
                break
            except TimeoutError:
                continue
        try:
            signal.check()
            future = self.workers.submit(operation)
        except BaseException:
            self.capacity.release()
            raise

        def release(_future: Future[T]) -> None:
            if not self.closed.is_set():
                try:
                    self.loop.call_soon_threadsafe(self.capacity.release)
                except RuntimeError:
                    if not self.closed.is_set():
                        raise

        future.add_done_callback(release)
        while not future.done():
            signal.check()
            if time.monotonic() >= deadline:
                raise TimeoutError("Agent operation exceeded its execution bound")
            await asyncio.sleep(EXECUTION_POLL_SECONDS)
        signal.check()
        return future.result()

    def publish(self, notification: _Notification) -> None:
        if self.delivery_failed.is_set():
            return
        try:
            self.events.put_nowait(notification)
        except Full:
            self.delivery_failed.set()
            logger.error(
                "Agent observer backlog exceeded its bound; use the saved execution state"
            )

    async def _deliver(self) -> None:
        while True:
            try:
                item = self.events.get_nowait()
            except Empty:
                if self.closed.is_set():
                    return
                await asyncio.sleep(EXECUTION_POLL_SECONDS)
                continue
            future = self.observers.submit(
                lambda item=item: item.context.run(item.send)
            )
            while not future.done():
                await asyncio.sleep(EXECUTION_POLL_SECONDS)
            if not future.result():
                self.delivery_failed.set()

    async def close(self) -> None:
        self.closed.set()
        try:
            await asyncio.wait_for(self.pump, EVENT_CLEANUP_SECONDS)
        except TimeoutError:
            self.delivery_failed.set()
            logger.warning("Agent observer cleanup exceeded its bound")
        finally:
            self.workers.shutdown(wait=False, cancel_futures=True)
            self.observers.shutdown(wait=False, cancel_futures=True)


class _ChildExecution(Awaitable[RunResult]):
    def __init__(self, task: asyncio.Task[RunResult]) -> None:
        self.task = task
        self.observed = False

    def __await__(self) -> Generator[None, None, RunResult]:
        try:
            return (yield from self.task.__await__())
        finally:
            self.observed = True

    def log_unobserved_failure(self, task: asyncio.Task[RunResult]) -> None:
        if self.observed:
            return
        self.observed = True
        if task.cancelled():
            logger.debug("Child execution cancelled during cleanup")
            return
        error = task.exception()
        if isinstance(error, AgentCancelled):
            logger.debug("Child execution cancelled during cleanup")
        elif error is not None:
            logger.error(
                "Unobserved child execution failure",
                exc_info=(type(error), error, error.__traceback__),
            )


async def _join_children(children: list[_ChildExecution]) -> None:
    tasks = [child.task for child in children if not child.observed]
    if not tasks:
        return
    done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
    for child in children:
        if child.task in done:
            child.observed = True
            child.task.result()


async def _close_children(children: list[_ChildExecution]) -> None:
    for child in children:
        if not child.task.done():
            child.task.cancel()
    if not children:
        return
    tasks = [child.task for child in children]
    done, pending = await asyncio.wait(tasks, timeout=EVENT_CLEANUP_SECONDS)
    for child in children:
        if child.task in done:
            child.log_unobserved_failure(child.task)
        else:
            child.task.add_done_callback(child.log_unobserved_failure)
            child.task.cancel()
    if pending:
        logger.warning("Child cleanup exceeded its bound: %s children", len(pending))


class _InvocationRunner(BlockingRunner):
    def __init__(self, scope: _ExecutionScope, signal: CancellationSignal) -> None:
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
                self.scope.blocking(clean_up, signal), EVENT_CLEANUP_SECONDS
            )
        finally:
            signal.cancel()


class Agent:
    def __init__(
        self,
        llm: LLM,
        *,
        context: AgentContext | None = None,
        hooks: AgentHooks | None = None,
        max_parallel_operations: int = DEFAULT_MAX_PARALLEL_OPERATIONS,
    ) -> None:
        if max_parallel_operations < 1:
            raise ValueError("max_parallel_operations must be positive")
        self.llm = llm
        self._context = (context or AgentContext()).snapshot()
        self.hooks = hooks or AgentHooks()
        self.max_parallel_operations = max_parallel_operations
        self._lock = threading.RLock()
        self._idle = threading.Event()
        self._idle.set()
        self._listeners: list[Callable[[AgentEvent], None]] = []
        self._pending_inputs: list[PendingInput] = []
        self._signal: CancellationSignal | None = None
        self._scope: _ExecutionScope | None = None
        self._run_id: str | None = None
        self._status: RunStatus | None = None
        self._run_start = 0
        self._run_input_start = 0
        self._step_start: int | None = None
        self._generating = False
        self._operations: list[OperationSnapshot] = []
        self._children: list[Agent] = []
        self._parent_events: Callable[[AgentEvent], None] | None = None
        self._request_params: GenerationRequestParams | None = None
        self._parent_run_id: str | None = None
        self._parent_tool_call_id: str | None = None
        self._parent_message_id: str | None = None

    @property
    def context(self) -> AgentContext:
        with self._lock:
            return self._context.snapshot()

    def snapshot(self, *, cancelled: bool = False) -> RunSnapshot | None:
        with self._lock:
            if self._run_id is None or self._status is None:
                return None
            status = (
                RunStatus.CANCELLED
                if cancelled and self._status == RunStatus.RUNNING
                else self._status
            )
            messages = [
                m.model_copy(deep=True)
                for m in self._context.messages[self._run_start :]
            ]
            operations = [operation.model_copy() for operation in self._operations]
            if status == RunStatus.CANCELLED:
                for operation in operations:
                    if operation.status == RunStatus.RUNNING:
                        operation.status = RunStatus.CANCELLED
                if self._generating and self._step_start is not None:
                    partial = messages[self._step_start - self._run_start]
                    if isinstance(partial, AssistantMessage):
                        partial.stop_reason = "aborted"
            children = list(self._children)
            snapshot = RunSnapshot(
                input_messages=[
                    m.model_copy(deep=True)
                    for m in self._context.messages[
                        self._run_input_start : self._run_start
                    ]
                ],
                run_id=self._run_id,
                status=status,
                messages=messages,
                parent_run_id=self._parent_run_id,
                parent_tool_call_id=self._parent_tool_call_id,
                parent_message_id=self._parent_message_id,
                operations=operations,
                request_params=self._request_params.model_copy(deep=True)
                if self._request_params
                else None,
                delivery_failed=self._scope.delivery_failed.is_set()
                if self._scope
                else False,
                checkpoint=self._context.checkpoint.model_copy(deep=True)
                if self._context.checkpoint
                else None,
            )

        snapshot.children = [
            child_snapshot
            for child in children
            if (child_snapshot := child.snapshot(cancelled=cancelled)) is not None
        ]
        return snapshot

    def subscribe(self, listener: Callable[[AgentEvent], None]) -> Callable[[], None]:
        with self._lock:
            self._listeners.append(listener)

        def unsubscribe() -> None:
            with self._lock:
                self._listeners.remove(listener)

        return unsubscribe

    def abort(self) -> None:
        with self._lock:
            signal = self._signal
        if signal:
            signal.cancel()

    def wait_for_idle(self, timeout: float = DEFAULT_IDLE_WAIT_SECONDS) -> bool:
        if timeout < 0:
            raise ValueError("timeout must be nonnegative")
        return self._idle.wait(timeout)

    @property
    def active_run_id(self) -> str | None:
        with self._lock:
            return self._run_id if self._status == RunStatus.RUNNING else None

    @property
    def pending_inputs(self) -> list[PendingInput]:
        with self._lock:
            return [item.model_copy(deep=True) for item in self._pending_inputs]

    def steer(self, message: Message, *, expected_run_id: str) -> str:
        return self._enqueue(message, InputKind.STEER, expected_run_id)

    def follow_up(self, message: Message) -> str:
        return self._enqueue(message, InputKind.FOLLOW_UP)

    def _enqueue(
        self, message: Message, kind: InputKind, expected: str | None = None
    ) -> str:
        with self._lock:
            if self._status != RunStatus.RUNNING or self._run_id is None:
                raise RuntimeError("Agent has no active execution")
            if expected is not None and expected != self._run_id:
                raise RuntimeError("Agent execution does not match expected execution")
            if self._signal:
                self._signal.check()
            item = PendingInput(
                id=str(uuid4()),
                run_id=self._run_id,
                kind=kind,
                message=message.model_copy(deep=True),
            )
            self._pending_inputs.append(item)
            return item.id

    def remove_pending_input(self, input_id: str) -> bool:
        with self._lock:
            for index, item in enumerate(self._pending_inputs):
                if item.id == input_id:
                    self._pending_inputs.pop(index)
                    return True
            return False

    def _emit(self, event: AgentEvent) -> None:
        with self._lock:
            if event.run_id != self._run_id or self._idle.is_set():
                logger.debug(
                    "Ignoring event from inactive agent execution: %s", event.run_id
                )
                return
            scope = self._scope
            if scope is None:
                raise RuntimeError("Agent event requires an execution scope")
            if isinstance(event, MessageStartEvent):
                self._operations.append(
                    OperationSnapshot(
                        step_index=event.step_index,
                        message_index=len(self._context.messages) - self._run_start - 1,
                        status=RunStatus.RUNNING,
                    )
                )
            elif isinstance(event, ToolStartEvent):
                if self._step_start is None:
                    raise RuntimeError("Tool execution requires an assistant message")
                self._operations.append(
                    OperationSnapshot(
                        step_index=event.step_index,
                        message_index=self._step_start - self._run_start,
                        tool_call_id=event.tool_call.id,
                        status=RunStatus.RUNNING,
                    )
                )
            elif isinstance(event, (MessageEndEvent, ToolEndEvent)):
                call_id = (
                    event.tool_call.id if isinstance(event, ToolEndEvent) else None
                )
                for operation in self._operations:
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
                for operation in self._operations:
                    if operation.status == RunStatus.RUNNING:
                        operation.status = event.outcome
            scope.publish(_Notification(event, self._listeners))
            if self._parent_events is not None:
                self._parent_events(event)

    def _forward_child_event(self, event: AgentEvent, *, parent_run_id: str) -> None:
        with self._lock:
            if parent_run_id != self._run_id or self._idle.is_set():
                logger.debug(
                    "Ignoring child event from inactive parent execution: %s",
                    parent_run_id,
                )
                return
            scope = self._scope
            if scope is None:
                raise RuntimeError("Child event requires an execution scope")
            scope.publish(_Notification(event, self._listeners))
            if self._parent_events is not None:
                self._parent_events(event)

    def run(
        self,
        *,
        max_steps: int,
        cancellation: CancellationSignal | None = None,
        messages: Sequence[Message] = (),
    ) -> RunResult:
        signal = (
            cancellation
            or current_cancellation()
            or self._context.execution.cancellation
            or CancellationSignal()
        )

        async def execute() -> RunResult:
            scope = _ExecutionScope(self.max_parallel_operations)
            try:
                return await self._run(scope, signal, max_steps, messages=messages)
            finally:
                await scope.close()

        return asyncio.run(execute())

    async def _run(
        self,
        scope: _ExecutionScope,
        signal: CancellationSignal,
        max_steps: int,
        *,
        messages: Sequence[Message] = (),
        parent_run_id: str | None = None,
        parent_tool_call_id: str | None = None,
        parent_message_id: str | None = None,
        depth: int = 0,
        parent_events: Callable[[AgentEvent], None] | None = None,
    ) -> RunResult:
        AgentStep(index=0, limit=max_steps)
        if depth > MAX_CHILD_DEPTH:
            raise ValueError("Agent child nesting limit exceeded")
        run_id = str(uuid4())
        with self._lock:
            if not self._idle.is_set():
                raise RuntimeError("Agent is already running; use steer or follow_up")
            self._idle.clear()
            self._scope, self._signal, self._run_id = scope, signal, run_id
            self._status = RunStatus.RUNNING
            self._operations = []
            self._children = []
            self._parent_events = parent_events
            self._request_params = None
            self._parent_run_id = parent_run_id
            self._parent_tool_call_id = parent_tool_call_id
            self._parent_message_id = parent_message_id
            self._run_input_start = len(self._context.messages)
            self._context.messages.extend(m.model_copy(deep=True) for m in messages)
            self._run_start = len(self._context.messages)
            self._step_start = None
        ancestry = _Ancestry(
            run_id=run_id,
            parent_run_id=parent_run_id,
            parent_tool_call_id=parent_tool_call_id,
            parent_message_id=parent_message_id,
        )
        outcome = RunStatus.ERROR
        completed: StepResult | None = None
        try:
            with cancellation_scope(signal):
                signal.check()
                self._emit(AgentStartEvent(**ancestry))
                continuation = True
                index = 0
                for index in range(max_steps):
                    signal.check()
                    step = AgentStep(index=index, limit=max_steps)
                    with self._lock:
                        eligible = [
                            item
                            for item in self._pending_inputs
                            if item.run_id == run_id
                            and (item.kind == InputKind.STEER or not continuation)
                        ]
                        # Follow-ups enter one at a time after the current task settles.
                        steering = [
                            item for item in eligible if item.kind == InputKind.STEER
                        ]
                        inputs = steering or eligible[:1]
                        ids = {item.id for item in inputs}
                        self._pending_inputs = [
                            item for item in self._pending_inputs if item.id not in ids
                        ]
                        self._context.messages.extend(item.message for item in inputs)
                        for item in inputs:
                            self._emit(
                                InputConsumedEvent(
                                    **ancestry,
                                    step_index=index,
                                    input_id=item.id,
                                    kind=item.kind,
                                )
                            )
                        request = self._context.snapshot()
                    if request.checkpoint and not checkpoint_matches(
                        request.messages, request.checkpoint
                    ):
                        logger.info(
                            "Discarding a checkpoint from another history branch"
                        )
                        request.checkpoint = None
                    request.messages = working_messages(
                        request.messages, request.checkpoint
                    )
                    prepare_step = self.hooks.prepare_step
                    prepared = (
                        await scope.blocking(
                            lambda request=request, step=step, prepare_step=prepare_step: (
                                prepare_step(request, step)
                            ),
                            signal,
                        )
                        if prepare_step
                        else request
                    )
                    if prepared is None:
                        if index == 0:
                            raise ValueError(
                                "Feature completed before producing a response"
                            )
                        outcome = RunStatus.COMPLETE
                        break
                    self._emit(
                        StepStartEvent(
                            **ancestry,
                            step_index=index,
                            input_messages=[i.message for i in inputs],
                        )
                    )
                    completed = await self._step(
                        scope, signal, prepared, step, ancestry, depth
                    )
                    after_step = self.hooks.after_step
                    decision = (
                        await scope.blocking(
                            lambda completed=completed, after_step=after_step: (
                                after_step(completed.model_copy(deep=True))
                            ),
                            signal,
                        )
                        if after_step
                        else None
                    )
                    continuation = (
                        decision
                        if decision is not None
                        else (
                            bool(completed.message.tool_calls)
                            and not (
                                completed.tool_results
                                and all(
                                    result.terminate
                                    for result in completed.tool_results
                                )
                            )
                        )
                    )
                    self._emit(
                        StepEndEvent(
                            **ancestry,
                            step_index=index,
                            message=completed.message,
                            tool_results=completed.tool_results,
                        )
                    )
                    with self._lock:
                        signal.check()
                        pending = any(
                            item.run_id == run_id for item in self._pending_inputs
                        )
                        if not continuation and not pending:
                            outcome = RunStatus.COMPLETE
                            break
                    outcome = RunStatus.LIMIT
                if completed is None:
                    raise RuntimeError("Execution ended without a completed step")
                if outcome not in (RunStatus.COMPLETE, RunStatus.LIMIT):
                    raise RuntimeError("Execution ended without a successful status")
                return RunResult(
                    run_id=run_id,
                    steps=index + 1,
                    stop_reason=outcome,
                    output=completed.message.model_copy(deep=True),
                )
        except (AgentCancelled, asyncio.CancelledError):
            outcome = RunStatus.CANCELLED
            signal.cancel()
            raise
        except BaseException:
            signal.cancel()
            raise
        finally:
            with self._lock:
                self._status = outcome
                if self._generating and self._step_start is not None:
                    partial = self._context.messages[self._step_start]
                    if isinstance(partial, AssistantMessage):
                        partial.stop_reason = (
                            "aborted" if outcome == RunStatus.CANCELLED else "error"
                        )
                self._generating = False
                self._emit(AgentEndEvent(**ancestry, outcome=outcome))
                self._signal = None
                self._idle.set()

    async def _step(
        self,
        scope: _ExecutionScope,
        signal: CancellationSignal,
        prepared: AgentContext,
        step: AgentStep,
        ancestry: _Ancestry,
        depth: int,
    ) -> StepResult:
        if len({tool.name for tool in prepared.tools}) != len(prepared.tools):
            raise ValueError("Agent tool names must be unique")
        prepared.execution = prepared.execution.model_copy(
            update={"cancellation": signal}
        )
        request = await self._fit_context(scope, signal, prepared)
        with self._lock:
            signal.check()
            start = len(self._context.messages)
            self._step_start = start
            self._generating = True
            metadata = prepared.output_metadata
            self._context.messages.append(AssistantMessage(metadata=metadata))
            self._emit(
                MessageStartEvent(**ancestry, step_index=step.index, metadata=metadata)
            )

        def generate() -> AssistantMessage:
            final: AssistantMessage | None = None
            with closing(self.llm.stream(request, prepared.execution)) as events:
                for event in events:
                    with self._lock:
                        signal.check()
                        if event.request_params is not None:
                            self._request_params = event.request_params.model_copy(
                                deep=True
                            )
                        event.message.metadata = (
                            prepared.output_metadata.model_copy(deep=True)
                            if prepared.output_metadata is not None
                            else None
                        )
                        self._context.messages[start] = event.message.model_copy(
                            deep=True
                        )
                        self._emit(
                            MessageUpdateEvent(
                                **ancestry,
                                step_index=step.index,
                                generation_event=event,
                            )
                        )
                    if event.type == "done":
                        final = event.message.model_copy(deep=True)
            if final is None:
                raise RuntimeError("Model stream ended without a completed message")
            return final

        try:
            message = await scope.blocking(generate, signal)
        except LLMContextLimitError:
            with self._lock:
                partial = self._context.messages[start]
                if partial.text or (
                    isinstance(partial, AssistantMessage) and partial.tool_calls
                ):
                    raise
            logger.info("Retrying context-rejected generation after compaction")
            request = await self._fit_context(scope, signal, prepared, force=True)
            message = await scope.blocking(generate, signal)
        with self._lock:
            signal.check()
            self._context.messages[start] = message
            self._generating = False
            self._emit(
                MessageEndEvent(**ancestry, step_index=step.index, message=message)
            )
        results = await self._tools(
            scope, signal, prepared, step, message, ancestry, depth
        )
        return StepResult(
            step=step, message=message.model_copy(deep=True), tool_results=results
        )

    async def _fit_context(
        self,
        scope: _ExecutionScope,
        signal: CancellationSignal,
        prepared: AgentContext,
        *,
        force: bool = False,
    ) -> GenerationRequest:
        build_request = self.hooks.build_request
        request = (
            await scope.blocking(lambda: build_request(prepared.snapshot()), signal)
            if build_request
            else prepared.generation_request()
        )
        budget = context_budget(self.llm)
        size = request_tokens(request)
        if not force and size <= budget.trigger:
            return request
        with self._lock:
            source = self._context.snapshot()
            if self._generating and self._step_start is not None:
                source.messages = source.messages[: self._step_start]
        previous = source.checkpoint
        if previous and not checkpoint_matches(source.messages, previous):
            logger.info("Ignoring compaction checkpoint from another history branch")
            previous = None
        try:
            checkpoint = await scope.blocking(
                lambda: compact_history(
                    self.llm, source.messages, previous, prepared.execution
                ),
                signal,
            )
        except ContextLimitError:
            if not force and size <= budget.input_limit:
                logger.warning(
                    "Proactive compaction failed; the request still fits", exc_info=True
                )
                return request
            raise
        rebuilt = prepared.snapshot()
        rebuilt.messages = working_messages(source.messages, checkpoint)
        request = (
            await scope.blocking(lambda: build_request(rebuilt), signal)
            if build_request
            else rebuilt.generation_request()
        )
        if request_tokens(request) > budget.input_limit:
            raise ContextLimitError(
                "Required instructions and recent context exceed the model input limit"
            )
        with self._lock:
            signal.check()
            self._context.checkpoint = checkpoint
        return request

    async def _tools(
        self,
        scope: _ExecutionScope,
        signal: CancellationSignal,
        request: AgentContext,
        step: AgentStep,
        message: AssistantMessage,
        ancestry: _Ancestry,
        depth: int,
    ) -> list[ToolResultMessage]:
        calls = message.tool_calls
        if len(calls) > MAX_TOOL_CALLS_PER_STEP:
            raise ValueError("Model exceeded the tool call limit for one step")
        if len({call.id for call in calls}) != len(calls):
            raise ValueError("Model returned duplicate tool call IDs")
        tools = {tool.name: tool for tool in request.tools}
        tasks: list[asyncio.Task[ToolResult]] = []

        sequential = any(
            tool.execution_mode == ToolExecutionMode.SEQUENTIAL
            for call in calls
            if (tool := tools.get(call.name)) is not None
        )
        failure: asyncio.Future[BaseException] = scope.loop.create_future()

        def completed(task: asyncio.Task[ToolResult]) -> None:
            error = AgentCancelled() if task.cancelled() else task.exception()
            if error is not None and not failure.done():
                failure.set_result(error)

        def start(call: ToolCall, index: int) -> asyncio.Task[ToolResult]:
            task = asyncio.create_task(
                self._execute_tool(
                    scope=scope,
                    signal=signal,
                    context=ToolCallContext(
                        step=step, call=call, context=request.snapshot()
                    ),
                    tool=tools.get(call.name),
                    index=index,
                    ancestry=ancestry,
                    depth=depth,
                    is_truncated=message.stop_reason == "length",
                )
            )
            task.add_done_callback(completed)
            tasks.append(task)
            return task

        def cancel_tasks() -> None:
            for task in tasks:
                if not task.done():
                    task.cancel()

        results: list[ToolResultMessage] = []
        try:
            if not sequential:
                for index, call in enumerate(calls):
                    start(call, index)
            with signal.on_cancel(
                lambda: scope.loop.call_soon_threadsafe(cancel_tasks)
            ):
                for index, call in enumerate(calls):
                    signal.check()
                    task = start(call, index) if sequential else tasks[index]
                    await asyncio.wait(
                        {task, failure}, return_when=asyncio.FIRST_COMPLETED
                    )
                    if failure.done():
                        signal.check()
                        raise failure.result()
                    result = await task
                    after_tool_call = self.hooks.after_tool_call
                    if after_tool_call:
                        context = ToolCallContext(
                            step=step, call=call, context=request.snapshot()
                        )
                        result = await scope.blocking(
                            lambda context=context, result=result, after_tool_call=after_tool_call: (
                                after_tool_call(context, result.model_copy(deep=True))
                            ),
                            signal,
                        )
                    item = ToolResultMessage(
                        content=result.content,
                        details=result.details,
                        is_error=result.is_error,
                        terminate=result.terminate,
                        tool_call_id=call.id,
                        tool_name=call.name,
                    )
                    with self._lock:
                        signal.check()
                        self._context.messages.append(item.model_copy(deep=True))
                        self._emit(
                            ToolEndEvent(
                                **ancestry,
                                step_index=step.index,
                                tool_call=call,
                                result=result,
                            )
                        )
                    results.append(item)
            return results
        except asyncio.CancelledError as error:
            signal.cancel()
            raise AgentCancelled() from error
        except BaseException:
            signal.cancel()
            raise
        finally:
            cancel_tasks()
            if tasks:
                _, pending = await asyncio.wait(tasks, timeout=EVENT_CLEANUP_SECONDS)
                if pending:
                    logger.warning(
                        "Tool cleanup exceeded its bound: %s operations", len(pending)
                    )
                    for task in pending:
                        task.cancel()

    async def _execute_tool(
        self,
        *,
        scope: _ExecutionScope,
        signal: CancellationSignal,
        context: ToolCallContext,
        tool: AgentTool | None,
        is_truncated: bool,
        index: int,
        ancestry: _Ancestry,
        depth: int,
    ) -> ToolResult:
        call = context.call
        step = context.step
        request = context.context
        self._emit(ToolStartEvent(**ancestry, step_index=step.index, tool_call=call))
        signal.check()
        context = ToolCallContext(
            step=step, call=call.model_copy(deep=True), context=request.snapshot()
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
        before_tool_call = self.hooks.before_tool_call
        if before_tool_call:
            result = await scope.blocking(lambda: before_tool_call(context), signal)
            if result is not None:
                return result
        active = threading.Event()
        active.set()

        def update(progress: ToolProgress) -> None:
            with self._lock:
                if not active.is_set():
                    logger.debug("Ignoring late tool progress: %s", call.id)
                    return
                signal.check()
                self._emit(
                    ToolUpdateEvent(
                        **ancestry,
                        step_index=step.index,
                        tool_call=call,
                        progress=progress,
                    )
                )

        children: list[_ChildExecution] = []

        async def execute_child(
            agent: Agent, max_steps: int, messages: Sequence[Message]
        ) -> RunResult:
            child_signal = CancellationSignal()
            with signal.on_cancel(child_signal.cancel):
                return await agent._run(
                    scope,
                    child_signal,
                    max_steps,
                    messages=messages,
                    parent_run_id=ancestry["run_id"],
                    parent_tool_call_id=call.id,
                    parent_message_id=f"{ancestry['run_id']}:{step.index}",
                    depth=depth + 1,
                    parent_events=lambda event: self._forward_child_event(
                        event, parent_run_id=ancestry["run_id"]
                    ),
                )

        def child_finished(_task: asyncio.Task[RunResult]) -> None:
            scope.active_children -= 1

        def run_child(
            agent: Agent, max_steps: int, messages: Sequence[Message]
        ) -> Awaitable[RunResult]:
            signal.check()
            if not active.is_set():
                raise RuntimeError("Child execution requires an active tool invocation")
            loop = asyncio.get_running_loop()
            if scope.active_children >= MAX_ACTIVE_CHILDREN:
                raise ValueError("Agent active child limit exceeded")
            scope.active_children += 1
            with self._lock:
                self._children.append(agent)
            child = _ChildExecution(
                loop.create_task(
                    execute_child(
                        agent,
                        max_steps,
                        [message.model_copy(deep=True) for message in messages],
                    )
                )
            )
            child.task.add_done_callback(child_finished)
            children.append(child)
            return child

        invocation = ToolInvocation(
            call_id=call.id,
            call_index=index,
            arguments=call.arguments,
            cancellation=signal,
            update=update,
            messages=request.messages,
            run_child=run_child,
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
            await _join_children(children)
            return result
        finally:
            try:
                await _close_children(children)
            finally:
                active.clear()
