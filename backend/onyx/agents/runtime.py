"""Agent execution, message history, tool scheduling, and lifecycle hooks."""

import contextvars
import threading
from collections.abc import Callable, Sequence
from concurrent.futures import wait
from contextlib import closing
from copy import deepcopy
from typing import Literal, TypedDict
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from onyx.agents.events import (
    AgentEndEvent,
    AgentEvent,
    AgentEventType,
    AgentStartEvent,
    InputConsumedEvent,
    InputKind,
    MessageEndEvent,
    MessageStartEvent,
    MessageUpdateEvent,
    ToolEndEvent,
    ToolStartEvent,
    ToolUpdateEvent,
    TurnEndEvent,
    TurnStartEvent,
)
from onyx.agents.tools import AgentTool, ToolExecutionMode
from onyx.agents.transcript import AgentTranscript, RunStatus
from onyx.llm.cancellation import (
    AgentCancelled,
    CancellationSignal,
    cancellation_scope,
    current_cancellation,
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
    ToolDefinition,
    ToolResult,
    ToolResultMessage,
)
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import ContextThreadPoolExecutor

logger = setup_logger()

DEFAULT_MAX_PARALLEL_TOOLS = 8
TOOL_CANCELLATION_POLL_SECONDS = 0.05
DEFAULT_IDLE_WAIT_SECONDS = 60.0


class _EventContext(TypedDict):
    run_id: str
    parent_run_id: str | None
    parent_tool_call_id: str | None


_active_execution: contextvars.ContextVar[tuple[str | None, str | None]] = (
    contextvars.ContextVar("agent_execution", default=(None, None))
)


class AgentTurn(BaseModel):
    model_config = ConfigDict(frozen=True)
    index: int = Field(ge=0)
    limit: int = Field(gt=0)

    @property
    def is_last(self) -> bool:
        return self.index + 1 == self.limit


class AgentContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messages: list[Message] = Field(default_factory=list)
    system_prompt: str = ""
    tools: list[AgentTool] = Field(default_factory=list)
    options: GenerationOptions = Field(default_factory=GenerationOptions)
    execution: GenerationContext = Field(default_factory=GenerationContext)

    def generation_request(self) -> GenerationRequest:
        return GenerationRequest(
            system_prompt=self.system_prompt,
            options=self.options.model_copy(deep=True),
            messages=self.messages,
            tools=[
                ToolDefinition(
                    name=tool.name,
                    description=tool.description,
                    parameters=deepcopy(tool.parameters),
                )
                for tool in self.tools
            ],
        )

    def snapshot(self) -> "AgentContext":
        return self.model_copy(
            update={
                "messages": [
                    message.model_copy(deep=True) for message in self.messages
                ],
                "tools": [
                    tool.model_copy(update={"parameters": deepcopy(tool.parameters)})
                    for tool in self.tools
                ],
                "options": self.options.model_copy(deep=True),
                "execution": self.execution.model_copy(
                    update={
                        "user_identity": self.execution.user_identity.model_copy(
                            deep=True
                        )
                        if self.execution.user_identity
                        else None,
                    }
                ),
            }
        )


class ToolCallContext(BaseModel):
    turn: AgentTurn
    call: ToolCall
    context: AgentContext


class TurnResult(BaseModel):
    turn: AgentTurn
    message: AssistantMessage
    tool_results: list[ToolResultMessage]


class AgentResult(BaseModel):
    messages: list[Message]
    turns: int
    stop_reason: Literal[RunStatus.COMPLETE, RunStatus.LIMIT]
    output: AssistantMessage


class AgentHooks(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)
    transform_context: Callable[[AgentContext, AgentTurn], AgentContext] | None = None
    before_tool_call: Callable[[ToolCallContext], ToolResult | None] | None = None
    after_tool_call: Callable[[ToolCallContext, ToolResult], ToolResult] | None = None
    after_turn: Callable[[TurnResult], None] | None = None
    should_stop_after_turn: Callable[[TurnResult], bool] | None = None


class PendingInput(BaseModel):
    """Input awaiting consumption by one execution."""

    model_config = ConfigDict(frozen=True)
    id: str
    run_id: str
    kind: InputKind
    message: Message


class Agent:
    """Own canonical history; hooks edit copies and subscribers observe copies."""

    def __init__(
        self,
        model: LLM,
        *,
        context: AgentContext | None = None,
        hooks: AgentHooks | None = None,
        max_parallel_tools: int = DEFAULT_MAX_PARALLEL_TOOLS,
    ) -> None:
        if max_parallel_tools < 1:
            raise ValueError("max_parallel_tools must be positive")
        self.model = model
        self._context = (context or AgentContext()).snapshot()
        self.hooks = hooks or AgentHooks()
        self.max_parallel_tools = max_parallel_tools
        self.state_lock = threading.RLock()
        self._idle = threading.Event()
        self._idle.set()
        self._signal: CancellationSignal | None = None
        self._execution_id: str | None = None
        self._listeners: list[Callable[[AgentEvent], None]] = []
        self._pending_inputs: list[PendingInput] = []
        self._status: RunStatus | None = None
        self._run_start = 0
        self._turn_start: int | None = None

    @property
    def context(self) -> AgentContext:
        """Return isolated history and request options. Use hooks to change requests."""
        with self.state_lock:
            return self._context.snapshot()

    @property
    def output_messages(self) -> list[Message]:
        """Copy current execution output, including accepted application details."""
        with self.state_lock:
            if self._status is None:
                return []
            return [
                message.model_copy(deep=True)
                for message in self._context.messages[self._run_start :]
            ]

    def snapshot(self, *, cancelled: bool = False) -> AgentTranscript | None:
        """Return current-run output without initial history or application metadata."""
        with self.state_lock:
            if self._status is None:
                return None
            status = RunStatus.CANCELLED if cancelled else self._status
            messages: list[Message] = []
            for index, source in enumerate(
                self._context.messages[self._run_start :], self._run_start
            ):
                message = source.model_copy(deep=True)
                message.metadata = None
                if isinstance(message, ToolResultMessage):
                    message.details = None
                if (
                    isinstance(message, AssistantMessage)
                    and index == self._turn_start
                    and status == RunStatus.CANCELLED
                ):
                    message.stop_reason = "aborted"
                messages.append(message)
            return AgentTranscript(status=status, messages=self._pair_results(messages))

    @staticmethod
    def _pair_results(messages: list[Message]) -> list[Message]:
        """Keep completed results in call order and fill missing results for replay."""
        output: list[Message] = []
        index = 0
        while index < len(messages):
            message = messages[index]
            output.append(message)
            index += 1
            if not isinstance(message, AssistantMessage) or not message.tool_calls:
                continue
            results: dict[str, ToolResultMessage] = {}
            while index < len(messages):
                result = messages[index]
                if not isinstance(result, ToolResultMessage):
                    break
                results[result.tool_call_id] = result
                index += 1
            output.extend(
                results.get(call.id)
                or ToolResultMessage(
                    tool_call_id=call.id,
                    tool_name=call.name,
                    content="Execution ended without an accepted tool result. External effects may have occurred.",
                    is_error=True,
                )
                for call in message.tool_calls
            )
        return output

    def subscribe(self, listener: Callable[[AgentEvent], None]) -> Callable[[], None]:
        """Subscribe synchronously. Listener exceptions are logged; cancellation propagates."""
        with self.state_lock:
            self._listeners.append(listener)

        def unsubscribe() -> None:
            with self.state_lock:
                if listener in self._listeners:
                    self._listeners.remove(listener)

        return unsubscribe

    def _check_execution(self, run_id: str, signal: CancellationSignal) -> None:
        """Check acceptance while state_lock protects execution ownership."""
        if self._execution_id != run_id:
            raise AgentCancelled()
        signal.check()

    def _close_execution(self, run_id: str) -> None:
        with self.state_lock:
            if self._execution_id == run_id:
                self._execution_id = None

    def abort(self) -> None:
        with self.state_lock:
            signal = self._signal
        if signal is not None:
            signal.cancel()

    def wait_for_idle(self, timeout: float = DEFAULT_IDLE_WAIT_SECONDS) -> bool:
        """Wait at most timeout seconds; return whether execution has ended."""
        if timeout < 0:
            raise ValueError("timeout must be nonnegative")
        return self._idle.wait(timeout)

    @property
    def execution_id(self) -> str | None:
        with self.state_lock:
            return self._execution_id

    @property
    def pending_inputs(self) -> list[PendingInput]:
        """Copy unconsumed input, including input retained after execution ends."""
        with self.state_lock:
            return [item.model_copy(deep=True) for item in self._pending_inputs]

    def steer(self, message: Message, *, expected_execution_id: str) -> str:
        """Queue input before the next model call in the specified active execution."""
        return self._enqueue_input(message, InputKind.STEER, expected_execution_id)

    def follow_up(self, message: Message) -> str:
        """Queue input for when the active execution would otherwise finish."""
        return self._enqueue_input(message, InputKind.FOLLOW_UP)

    def _enqueue_input(
        self,
        message: Message,
        kind: InputKind,
        expected_execution_id: str | None = None,
    ) -> str:
        with self.state_lock:
            run_id = self._execution_id
            if run_id is None:
                raise RuntimeError("Agent has no active execution")
            if expected_execution_id is not None and expected_execution_id != run_id:
                raise RuntimeError("Agent execution does not match expected execution")
            item = PendingInput(
                id=str(uuid4()),
                run_id=run_id,
                kind=kind,
                message=message.model_copy(deep=True),
            )
            self._pending_inputs.append(item)
            return item.id

    def remove_pending_input(self, input_id: str) -> bool:
        """Remove input if consumption has not started. Return whether it was removed."""
        with self.state_lock:
            for index, item in enumerate(self._pending_inputs):
                if item.id == input_id:
                    self._pending_inputs.pop(index)
                    return True
            return False

    def _consume_pending_inputs(
        self, run_id: str, allow_follow_up: bool
    ) -> list[PendingInput]:
        """Select and remove input while the caller holds state_lock."""
        pending = [
            item
            for item in self._pending_inputs
            if item.run_id == run_id and item.kind == InputKind.STEER
        ]
        if not pending and allow_follow_up:
            pending = [
                item
                for item in self._pending_inputs
                if item.run_id == run_id and item.kind == InputKind.FOLLOW_UP
            ][:1]
        consumed_ids = {item.id for item in pending}
        self._pending_inputs = [
            item for item in self._pending_inputs if item.id not in consumed_ids
        ]
        return pending

    def _emit(self, event: AgentEvent) -> None:
        with self.state_lock:
            # Model and turn events share their caller's commit boundary.
            if event.type in {
                AgentEventType.TOOL_START,
                AgentEventType.TOOL_UPDATE,
                AgentEventType.TOOL_END,
            }:
                if self._execution_id != event.run_id:
                    raise AgentCancelled()
                if self._signal is not None:
                    self._signal.check()
            if event.type == AgentEventType.TOOL_END:
                if self._turn_start is None or not isinstance(
                    assistant := self._context.messages[self._turn_start],
                    AssistantMessage,
                ):
                    raise RuntimeError("Tool result requires an active assistant turn")
                results = {
                    message.tool_call_id: message
                    for message in self._context.messages[self._turn_start + 1 :]
                    if isinstance(message, ToolResultMessage)
                }
                committed = event.result.model_copy(deep=True)
                results[event.tool_call.id] = ToolResultMessage(
                    content=committed.content,
                    details=committed.details,
                    is_error=committed.is_error,
                    terminate=committed.terminate,
                    tool_call_id=event.tool_call.id,
                    tool_name=event.tool_call.name,
                )
                self._context.messages[self._turn_start + 1 :] = [
                    results[call.id]
                    for call in assistant.tool_calls
                    if call.id in results
                ]
            for listener in tuple(self._listeners):
                try:
                    listener(event.model_copy(deep=True))
                except Exception:
                    logger.exception("Agent event observer failed: %s", event.type)

    def run(
        self,
        *,
        max_turns: int,
        cancellation: CancellationSignal | None = None,
        messages: Sequence[Message] = (),
    ) -> AgentResult:
        AgentTurn(index=0, limit=max_turns)
        signal = (
            cancellation
            or current_cancellation()
            or self._context.execution.cancellation
            or CancellationSignal()
        )
        run_id = str(uuid4())
        with self.state_lock:
            if not self._idle.is_set():
                raise RuntimeError("Agent is already running; use steer or follow_up")
            self._context.messages.extend(
                message.model_copy(deep=True) for message in messages
            )
            self._run_start = len(self._context.messages)
            self._turn_start = None
            self._status = RunStatus.RUNNING
            self._idle.clear()
            self._signal = signal
            self._execution_id = run_id
        parent_run_id, parent_tool_call_id = _active_execution.get()
        execution_token = _active_execution.set((run_id, None))
        outcome: Literal[
            RunStatus.COMPLETE, RunStatus.LIMIT, RunStatus.CANCELLED, RunStatus.ERROR
        ] = RunStatus.ERROR
        event_context = _EventContext(
            run_id=run_id,
            parent_run_id=parent_run_id,
            parent_tool_call_id=parent_tool_call_id,
        )

        emit = self._emit

        try:
            with (
                signal.on_cancel(lambda: self._close_execution(run_id)),
                cancellation_scope(signal),
            ):
                signal.check()
                emit(AgentStartEvent(**event_context))
                turn = AgentTurn(index=0, limit=max_turns)
                request = self._prepare_turn(turn, signal, event_context, False)
                completed = self._run_turn(turn, signal, event_context, request)
                while True:
                    signal.check()
                    stop = bool(
                        self.hooks.should_stop_after_turn
                        and self.hooks.should_stop_after_turn(
                            completed.model_copy(deep=True)
                        )
                    )
                    message = completed.message
                    results = completed.tool_results
                    requires_response = bool(message.tool_calls) and not (
                        results and all(result.terminate for result in results)
                    )
                    with self.state_lock:
                        self._check_execution(run_id, signal)
                        has_input = any(
                            item.run_id == run_id for item in self._pending_inputs
                        )
                        should_continue = requires_response or has_input
                        if stop or not should_continue or turn.is_last:
                            outcome = (
                                RunStatus.LIMIT
                                if should_continue and turn.is_last and not stop
                                else RunStatus.COMPLETE
                            )
                            self._execution_id = None
                            return AgentResult(
                                messages=self._context.snapshot().messages,
                                turns=turn.index + 1,
                                stop_reason=outcome,
                                output=message.model_copy(deep=True),
                            )
                        turn = AgentTurn(index=turn.index + 1, limit=max_turns)
                        # Decide continuation and accept its input under the same lock.
                        request = self._prepare_turn(
                            turn, signal, event_context, not requires_response
                        )
                    completed = self._run_turn(turn, signal, event_context, request)
        except AgentCancelled:
            outcome = RunStatus.CANCELLED
            raise
        finally:
            try:
                with self.state_lock:
                    self._execution_id = None
                    self._status = outcome
                    if (
                        outcome in {RunStatus.CANCELLED, RunStatus.ERROR}
                        and self._turn_start is not None
                    ):
                        partial = self._context.messages[self._turn_start]
                        if isinstance(partial, AssistantMessage):
                            partial.stop_reason = (
                                "aborted" if outcome == RunStatus.CANCELLED else "error"
                            )
                        self._context.messages[self._turn_start :] = self._pair_results(
                            self._context.messages[self._turn_start :]
                        )
                    try:
                        with cancellation_scope(signal):
                            emit(AgentEndEvent(**event_context, outcome=outcome))
                    except AgentCancelled:
                        self._status = RunStatus.CANCELLED
                        raise
            finally:
                with self.state_lock:
                    self._signal = None
                    self._idle.set()
                _active_execution.reset(execution_token)
        raise RuntimeError("Agent exited without a result")

    def _prepare_turn(
        self,
        turn: AgentTurn,
        signal: CancellationSignal,
        event_context: _EventContext,
        allow_follow_up: bool,
    ) -> AgentContext:
        emit = self._emit

        with self.state_lock:
            self._check_execution(event_context["run_id"], signal)
            pending = self._consume_pending_inputs(
                event_context["run_id"], allow_follow_up
            )
            inputs = [item.message for item in pending]
            self._context.messages.extend(inputs)
            self._turn_start = None
            for item in pending:
                emit(
                    InputConsumedEvent(
                        **event_context,
                        turn=turn.index,
                        input_id=item.id,
                        kind=item.kind,
                    )
                )
            emit(
                TurnStartEvent(**event_context, turn=turn.index, input_messages=inputs)
            )
            return self._context.snapshot()

    def _run_turn(
        self,
        turn: AgentTurn,
        signal: CancellationSignal,
        event_context: _EventContext,
        request: AgentContext,
    ) -> TurnResult:
        emit = self._emit

        if self.hooks.transform_context:
            request = self.hooks.transform_context(request, turn)
        self._validate_tools(request.tools)
        signal.check()
        with self.state_lock:
            self._check_execution(event_context["run_id"], signal)
            turn_start = len(self._context.messages)
            self._turn_start = turn_start
            self._context.messages.append(AssistantMessage())
            emit(MessageStartEvent(**event_context, turn=turn.index))
        signal.check()

        def update(event: GenerationEvent, turn_start: int = turn_start) -> None:
            with self.state_lock:
                self._check_execution(event_context["run_id"], signal)
                self._context.messages[turn_start] = event.message.model_copy(deep=True)
                emit(
                    MessageUpdateEvent(
                        **event_context,
                        turn=turn.index,
                        generation_event=event,
                    )
                )

        message = self._consume_generation(request, signal, update)
        signal.check()
        with self.state_lock:
            self._check_execution(event_context["run_id"], signal)
            self._context.messages[turn_start] = message
            emit(MessageEndEvent(**event_context, turn=turn.index, message=message))
        signal.check()
        results = self._execute_tools(
            request, turn, message, signal, event_context, emit
        )
        signal.check()
        completed = TurnResult(
            turn=turn,
            message=message.model_copy(deep=True),
            tool_results=[result.model_copy(deep=True) for result in results],
        )
        with self.state_lock:
            self._check_execution(event_context["run_id"], signal)
            if self.hooks.after_turn:
                self.hooks.after_turn(completed)
            self._check_execution(event_context["run_id"], signal)
            self._validate_turn(message, completed)
            self._context.messages[self._turn_start :] = [
                completed.message.model_copy(deep=True),
                *(result.model_copy(deep=True) for result in completed.tool_results),
            ]
            message = completed.message
            results = completed.tool_results
            emit(
                TurnEndEvent(
                    **event_context,
                    turn=turn.index,
                    message=message,
                    tool_results=results,
                )
            )
        return completed

    @staticmethod
    def _validate_turn(original: AssistantMessage, result: TurnResult) -> None:
        if result.message.tool_calls != original.tool_calls:
            raise ValueError("after_turn cannot change executed tool calls")
        if result.message != original:
            raise ValueError("after_turn cannot change the published assistant message")
        calls = original.tool_calls
        results = {item.tool_call_id: item for item in result.tool_results}
        if len(results) != len(result.tool_results) or set(results) != {
            call.id for call in calls
        }:
            raise ValueError(
                "after_turn must preserve one result per executed tool call"
            )
        if any(results[call.id].tool_name != call.name for call in calls):
            raise ValueError("after_turn cannot change tool identities")
        result.tool_results = [results[call.id] for call in calls]

    @staticmethod
    def _validate_tools(tools: Sequence[AgentTool]) -> None:
        if len({tool.name for tool in tools}) != len(tools):
            raise ValueError("Agent tool names must be unique")

    def _consume_generation(
        self,
        request: AgentContext,
        signal: CancellationSignal,
        on_event: Callable[[GenerationEvent], None],
    ) -> AssistantMessage:
        message: AssistantMessage | None = None
        with closing(
            self.model.stream(
                request.generation_request(),
                request.execution.model_copy(update={"cancellation": signal}),
            )
        ) as events:
            for event in events:
                signal.check()
                on_event(event)
                if event.type == "done":
                    message = event.message.model_copy(deep=True)
        if message is None:
            raise RuntimeError("Model stream ended without a completed message")
        return message

    def _execute_tools(
        self,
        request: AgentContext,
        turn: AgentTurn,
        message: AssistantMessage,
        signal: CancellationSignal,
        event_context: _EventContext,
        emit: Callable[[AgentEvent], None],
    ) -> list[ToolResultMessage]:
        calls = message.tool_calls
        if len({call.id for call in calls}) != len(calls):
            raise ValueError("Model returned duplicate tool call IDs")
        tools = {tool.name: tool for tool in request.tools}

        def execute_bound(call: ToolCall) -> ToolResultMessage:
            signal.check()
            emit(ToolStartEvent(**event_context, turn=turn.index, tool_call=call))
            signal.check()
            context = ToolCallContext(
                turn=turn, call=call.model_copy(deep=True), context=request.snapshot()
            )
            result: ToolResult | None = None
            tool = tools.get(call.name)
            if request.options.tool_choice == ToolChoiceOptions.NONE or tool is None:
                result = ToolResult(
                    content=f"Tool {call.name} is unavailable for this turn.",
                    is_error=True,
                )
            elif message.stop_reason == "length" or call.argument_error:
                result = ToolResult(
                    content=call.argument_error or "Tool arguments were truncated.",
                    is_error=True,
                )
            try:
                if result is None and self.hooks.before_tool_call:
                    result = self.hooks.before_tool_call(context)
                signal.check()
                if result is None:
                    if tool is None:
                        raise RuntimeError("Tool execution requires an available tool")
                    active = True

                    def update(partial: ToolResult) -> None:
                        with self.state_lock:
                            if not active:
                                logger.debug(
                                    "Ignoring progress after tool completion: %s",
                                    call.id,
                                )
                                return
                            signal.check()
                            emit(
                                ToolUpdateEvent(
                                    **event_context,
                                    turn=turn.index,
                                    tool_call=call,
                                    result=partial,
                                )
                            )

                    try:
                        result = tool.execute(
                            call.id,
                            call.model_copy(deep=True).arguments,
                            signal,
                            update,
                        )
                    finally:
                        with self.state_lock:
                            active = False
                signal.check()
                if self.hooks.after_tool_call:
                    result = self.hooks.after_tool_call(
                        context, result.model_copy(deep=True)
                    )
            except Exception:
                logger.exception("Agent tool execution failed: %s", call.name)
                result = ToolResult(content="Tool execution failed.", is_error=True)
            signal.check()
            result = result.model_copy(deep=True)
            emit(
                ToolEndEvent(
                    **event_context, turn=turn.index, tool_call=call, result=result
                )
            )
            return ToolResultMessage(
                content=result.content,
                details=result.details,
                is_error=result.is_error,
                terminate=result.terminate,
                tool_call_id=call.id,
                tool_name=call.name,
            )

        def execute(call: ToolCall) -> ToolResultMessage:
            run_id, _ = _active_execution.get()
            token = _active_execution.set((run_id, call.id))
            try:
                return execute_bound(call)
            finally:
                _active_execution.reset(token)

        sequential = any(
            tools[call.name].execution_mode == ToolExecutionMode.SEQUENTIAL
            for call in calls
            if call.name in tools
        )
        if sequential or len(calls) < 2:
            return [execute(call) for call in calls]
        executor = ContextThreadPoolExecutor(
            max_workers=min(self.max_parallel_tools, len(calls))
        )
        try:
            futures = [
                executor.submit(lambda call=call: execute(call)) for call in calls
            ]
            pending = set(futures)
            while pending:
                signal.check()
                _, pending = wait(pending, timeout=TOOL_CANCELLATION_POLL_SECONDS)
            return [future.result() for future in futures]
        finally:
            executor.shutdown(
                wait=not signal.cancelled, cancel_futures=signal.cancelled
            )
