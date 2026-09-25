"""Advance parallel tools and ordered finalizers without parking completed workers."""

import threading
from collections.abc import Callable
from concurrent.futures import Future
from typing import TYPE_CHECKING

from pydantic import JsonValue

from onyx.agents.events import (
    InputRequiredEvent,
    ToolEndEvent,
    ToolStartEvent,
    ToolUpdateEvent,
)
from onyx.agents.models import (
    ExecutionRequest,
    PreparedStep,
    RunProgress,
    RunState,
    StepResult,
    ToolCallContext,
)
from onyx.agents.tools import (
    ChildRunWait,
    InputDecision,
    InputMode,
    PendingToolInput,
    ToolExecutionMode,
    ToolInvocation,
    ToolOutcome,
    ToolProgress,
)
from onyx.agents.transcript import OperationSnapshot, RunStatus
from onyx.llm.cancellation import AgentCancelled
from onyx.llm.models import (
    Message,
    ToolCall,
    ToolChoiceOptions,
    ToolResult,
    ToolResultMessage,
)
from onyx.utils.logger import setup_logger

if TYPE_CHECKING:
    from onyx.agents.runtime import Run

logger = setup_logger()

MAX_TOOL_CALLS_PER_STEP = 64


class ToolBatch:
    """Execute one step's tools and commit their results to the run."""

    def __init__(
        self,
        run: "Run",
        prepared: PreparedStep,
        completed: StepResult,
        context_messages: list[Message],
        *,
        before_tool_call: Callable[
            [ToolCallContext], ToolResult | PendingToolInput | None
        ]
        | None,
        after_tool_call: Callable[[ToolCallContext, ToolResult], ToolResult] | None,
    ) -> None:
        self.run = run
        self.scope = run._work
        self.signal = run._cancellation_signal
        self.completed = completed
        self.before_tool_call = before_tool_call
        self.after_tool_call = after_tool_call
        self.step = completed.step
        self.message = completed.message
        self.options = completed.options
        self.context_messages = context_messages
        self.calls = self.message.tool_calls
        if len(self.calls) > MAX_TOOL_CALLS_PER_STEP or len(
            {call.id for call in self.calls}
        ) != len(self.calls):
            raise ValueError(
                f"A step requires unique tool call IDs and at most {MAX_TOOL_CALLS_PER_STEP} calls"
            )
        self.tools = {tool.name: tool for tool in prepared.tools}
        self.sequential = any(
            (
                tool.execution_mode == ToolExecutionMode.SEQUENTIAL
                for call in self.calls
                if (tool := self.tools.get(call.name)) is not None
            )
        )
        message_index = self.progress.message_index
        if message_index is None:
            raise RuntimeError("Tool phase requires a generation")
        self.step_start = message_index
        self.result_start = message_index + 1
        self.call_indices = {call.id: index for index, call in enumerate(self.calls)}
        self.futures: dict[str, Future[ToolOutcome]] = {}

    @property
    def messages(self) -> list[Message]:
        return self.run._state.messages

    @property
    def progress(self) -> RunProgress:
        progress = self.run._state.progress
        if progress is None:
            raise RuntimeError("Tool execution requires recorded progress")
        return progress

    def _context(self, call: ToolCall) -> ToolCallContext:
        return ToolCallContext(
            step=self.step,
            call=call,
            options=self.options.model_copy(deep=True),
            messages=[item.model_copy(deep=True) for item in self.context_messages],
        )

    def _wake(self, _future: Future[ToolOutcome] | None = None) -> None:
        with self.run._execution_condition:
            self.run._execution_condition.notify_all()

    def _raw_results(self) -> dict[str, ToolResultMessage]:
        return {
            item.tool_call_id: item
            for item in self.messages[self.result_start :]
            if isinstance(item, ToolResultMessage)
        }

    def _start(
        self,
        call: ToolCall,
        index: int,
        approved: bool = False,
        children: list[RunState] | None = None,
        grouped_calls: list[ToolCall] | None = None,
        merged_arguments: dict[str, JsonValue] | None = None,
    ) -> None:

        def operation() -> ToolOutcome:
            with self.signal.on_operation(self.scope.track_operation):
                outcome = self._execute_tool(
                    call=call,
                    index=index,
                    approved=approved,
                    children=children,
                    grouped_calls=grouped_calls,
                    merged_arguments=merged_arguments,
                )
                if grouped_calls and not isinstance(outcome, ToolResult):
                    raise ValueError("Batched tools must return a completed result")
                if isinstance(outcome, ToolResult):
                    # Checkpoint capture must not split a completed batch.
                    with self.run._lock:
                        for member in grouped_calls or [call]:
                            self._record_tool_result(outcome, member)
                return outcome

        future = self.scope.start(operation)
        for member in grouped_calls or [call]:
            self.futures[member.id] = future
        future.add_done_callback(self._wake)

    def _collect_results(self) -> None:
        for call_id, future in tuple(self.futures.items()):
            if not future.done():
                continue
            del self.futures[call_id]
            result = future.result()
            index = self.call_indices[call_id]
            call = self.calls[index]
            if not isinstance(result, ToolResult):
                self._record_pending_tool(call, result)

    def _finalize_ready(self) -> None:
        results = self._raw_results()
        while self.progress.finalized_tools < len(self.calls):
            call = self.calls[self.progress.finalized_tools]
            result_message = results.get(call.id)
            if result_message is None:
                break
            result = ToolResult(
                content=result_message.content,
                metadata=result_message.metadata,
                cacheable=result_message.cacheable,
                details=result_message.details,
                is_error=result_message.is_error,
                terminate=result_message.terminate,
            )
            self._finish_tool(result, self._context(call))

    def execute(self) -> StepResult | None:
        try:
            with self.signal.on_cancel(self._wake):
                while True:
                    self.signal.check()
                    self.run._begin_work_cycle()
                    self._collect_results()
                    self._finalize_ready()
                    results = self._raw_results()
                    if self.progress.finalized_tools == len(self.calls):
                        results = self._raw_results()
                        return self.completed.model_copy(
                            update={
                                "tool_results": [
                                    results[call.id].model_copy(deep=True)
                                    for call in self.calls
                                ]
                            }
                        )
                    for index, call in enumerate(self.calls):
                        if call.id in results or call.id in self.futures:
                            continue
                        if self.sequential and index != self.progress.finalized_tools:
                            break
                        with self.run._lock:
                            pending = self.progress.pending_tool_calls.get(call.id)
                            suspend = (
                                self.run._execution_request == ExecutionRequest.SUSPEND
                            )
                            answer = (
                                self.progress.human_tool_answers.get(pending.request_id)
                                if isinstance(pending, PendingToolInput)
                                else None
                            )
                        if suspend:
                            continue
                        if isinstance(pending, PendingToolInput):
                            if answer is None:
                                continue
                            self._resolve_tool_wait(call)
                            if answer.decision == InputDecision.APPROVE:
                                self._start(call, index, approved=True)
                            else:
                                output = answer.result or ToolResult(
                                    content="Tool execution was denied.", is_error=True
                                )
                                self._record_tool_result(output, call)
                            continue
                        if isinstance(pending, ChildRunWait):
                            if self.run._coordination is None:
                                raise ValueError(
                                    "Child dependency requires an execution coordinator"
                                )
                            children = self.run._coordination.child_states(
                                pending.run_ids
                            )
                            if any(not child.status.is_terminal for child in children):
                                self.run._watch_children(pending.run_ids)
                                continue
                            self._resolve_tool_wait(call)
                            self._start(
                                call,
                                index,
                                children=children,
                            )
                            continue
                        self._start_compatible_calls(call, index, results)
                    if not self.futures:
                        if len(self._raw_results()) > len(results):
                            continue
                        return None
                    self.run._wait_for_tool_activity(
                        lambda: any(future.done() for future in self.futures.values())
                    )
        except BaseException:
            self.signal.cancel()
            self._wake()
            raise

    def _start_compatible_calls(
        self, call: ToolCall, index: int, results: dict[str, ToolResultMessage]
    ) -> None:
        group = [call]
        arguments = call.model_copy(deep=True).arguments
        tool = self.tools.get(call.name)
        if (
            tool is not None
            and tool.merge_arguments is not None
            and self.before_tool_call is None
            and call.arguments_complete
            and not call.argument_error
            and self.message.stop_reason != "length"
        ):
            for candidate in self.calls[index + 1 :]:
                eligible = (
                    candidate.name == call.name
                    and candidate.id not in results
                    and candidate.id not in self.futures
                    and candidate.id not in self.progress.pending_tool_calls
                    and candidate.arguments_complete
                    and not candidate.argument_error
                )
                if not eligible:
                    if self.sequential:
                        break
                    continue
                merged = tool.merge_arguments(
                    arguments, candidate.model_copy(deep=True).arguments
                )
                if merged is None:
                    if self.sequential:
                        break
                    continue
                arguments = merged
                group.append(candidate)
        self._start(
            call,
            index,
            grouped_calls=group if len(group) > 1 else None,
            merged_arguments=arguments if len(group) > 1 else None,
        )

    def _execute_tool(
        self,
        *,
        call: ToolCall,
        index: int,
        approved: bool = False,
        children: list[RunState] | None = None,
        grouped_calls: list[ToolCall] | None = None,
        merged_arguments: dict[str, JsonValue] | None = None,
    ) -> ToolOutcome:
        cancellation_signal = self.signal
        context = self._context(call)
        step = context.step
        options = context.options
        tool = self.tools.get(call.name)
        with self.run._lock:
            cancellation_signal.check()
            for member in grouped_calls or [call]:
                first_start = not any(
                    operation.message_index == self.step_start
                    and operation.tool_call_id == member.id
                    for operation in self.run._state.operations
                )
                if first_start:
                    self.run._state.operations.append(
                        OperationSnapshot(
                            step_index=step.index,
                            message_index=self.step_start,
                            tool_call_id=member.id,
                            status=RunStatus.RUNNING,
                        )
                    )
                    if self.run._delivery:
                        self.run._delivery.publish(
                            ToolStartEvent(
                                **self.run._ancestry,
                                step_index=step.index,
                                tool_call=member,
                            )
                        )
        cancellation_signal.check()
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
        if (
            call.argument_error
            or not call.arguments_complete
            or self.message.stop_reason == "length"
        ):
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
            with self.run._lock:
                if not active.is_set() or not self.run._accepting:
                    logger.debug("Ignoring late tool progress: %s", call.id)
                    return
                cancellation_signal.check()
                if self.run._delivery:
                    for member in grouped_calls or [call]:
                        self.run._delivery.publish(
                            ToolUpdateEvent(
                                **self.run._ancestry,
                                step_index=step.index,
                                tool_call=member,
                                progress=progress,
                            )
                        )

        invocation = ToolInvocation(
            call_id=call.id,
            call_index=index,
            arguments=merged_arguments
            if merged_arguments is not None
            else call.model_copy(deep=True).arguments,
            cancellation=cancellation_signal,
            update=update,
            messages=[message.model_copy(deep=True) for message in context.messages],
            agents=self.run._coordination.for_tool(
                call.id, f"{self.run._state.run_id}:{step.index}", active
            )
            if self.run._coordination
            else None,
        )
        try:
            if children is not None:
                if tool.complete_children is None:
                    raise ValueError(
                        "Tool does not support completing child dependencies"
                    )
                result = tool.complete_children(invocation, children)
                if self.run._coordination is not None:
                    self.run._coordination.observe_children(
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
            with self.run._lock:
                active.clear()

    def _record_tool_result(
        self,
        result: ToolResult,
        call: ToolCall,
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
            **self.run._ancestry,
            step_index=self.step.index,
            tool_call=call,
            progress=ToolProgress(content=result.text, details=result.details),
        )
        with self.run._lock:
            if not self.run._accepting:
                logger.warning("Tool completed after its run closed: %s", call.id)
                raise AgentCancelled()
            # Accept outcomes on completion; keep model history in call order.
            offset = sum(
                self.call_indices[previous.tool_call_id] < self.call_indices[call.id]
                for previous in self.messages[self.result_start :]
                if isinstance(previous, ToolResultMessage)
            )
            operation = next(
                operation
                for operation in self.run._state.operations
                if operation.message_index == self.step_start
                and operation.tool_call_id == call.id
            )
            self.messages.insert(self.result_start + offset, item.model_copy(deep=True))
            operation.status = (
                RunStatus.ERROR if result.is_error else RunStatus.COMPLETE
            )
            if self.run._delivery:
                self.run._delivery.publish(event)

    def _resolve_tool_wait(self, call: ToolCall) -> None:
        with self.run._lock:
            del self.progress.pending_tool_calls[call.id]
            self.run._state.revision += 1

    def _record_pending_tool(
        self, call: ToolCall, pending: PendingToolInput | ChildRunWait
    ) -> None:
        event = (
            InputRequiredEvent(
                **self.run._ancestry, tool_call_id=call.id, request=pending
            )
            if isinstance(pending, PendingToolInput)
            else None
        )
        with self.run._lock:
            if isinstance(pending, PendingToolInput) and (
                pending.request_id in self.progress.human_tool_answers
                or any(
                    isinstance(existing, PendingToolInput)
                    and existing.request_id == pending.request_id
                    for existing in self.progress.pending_tool_calls.values()
                )
            ):
                raise ValueError("Input request IDs must be unique within a run")
            self.progress.pending_tool_calls[call.id] = pending.model_copy(deep=True)
            self.run._state.revision += 1
            if event is not None and self.run._accepting and self.run._delivery:
                self.run._delivery.publish(event)

    def _finish_tool(self, result: ToolResult, context: ToolCallContext) -> None:
        try:
            after = self.after_tool_call
            if after:
                result = self.run._work.blocking(
                    lambda: after(context, result.model_copy(deep=True)),
                    self.run._cancellation_signal,
                )
        finally:
            self._finalize_tool_result(result, context.call)
        with self.run._lock:
            self.progress.finalized_tools += 1
            self.run._state.revision += 1

    def _finalize_tool_result(
        self,
        result: ToolResult,
        call: ToolCall,
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
            **self.run._ancestry,
            step_index=self.step.index,
            tool_call=call,
            result=result,
        )
        with self.run._lock:
            if not self.run._accepting or self.run._cancellation_signal.cancelled:
                logger.debug("Ignoring late tool finalization: %s", call.id)
                return item
            offset = next(
                (
                    offset
                    for offset, stored in enumerate(
                        self.messages[self.result_start :], start=self.result_start
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
                for operation in self.run._state.operations
                if operation.message_index == self.step_start
                and operation.tool_call_id == call.id
            )
            self.messages[offset] = item.model_copy(deep=True)
            operation.status = (
                RunStatus.ERROR if result.is_error else RunStatus.COMPLETE
            )
            if self.run._delivery:
                self.run._delivery.publish(event)
        return item
