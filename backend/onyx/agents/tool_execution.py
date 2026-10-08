"""Advance parallel tools and ordered finalizers without parking completed workers."""

import threading
from concurrent.futures import Future
from typing import TYPE_CHECKING

from pydantic import JsonValue

from onyx.agents.compaction import working_messages
from onyx.agents.events import (
    InputRequiredEvent,
    ToolEndEvent,
    ToolStartEvent,
    ToolUpdateEvent,
)
from onyx.agents.execution_records import ExecutionStatus
from onyx.agents.models import (
    AgentStep,
    ExecutionRequest,
    RunState,
    ToolCallContext,
    ToolExecutionRecord,
    messages_from_steps,
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
from onyx.llm.cancellation import AgentCancelled
from onyx.llm.models import (
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

    def __init__(self, run: "Run") -> None:
        prepared = run._prepared_step
        if prepared is None:
            raise RuntimeError("Tool execution requires a prepared step")
        progress = run._progress
        if progress.options is None:
            raise ValueError("Saved step is missing generation options")
        self.run = run
        self.step = AgentStep(index=progress.step_index, limit=progress.step_limit)
        self.record = run._state.steps[progress.step_index]
        self.message = self.record.message
        if self.message.id is None:
            raise ValueError("Tool execution requires a message ID")
        self.message_id = self.message.id
        self.options = progress.options
        self.context_messages = working_messages(
            [
                *run._history.messages,
                *run._state.input_messages,
                *messages_from_steps(run._state.steps[: progress.step_index]),
            ],
            run._state.checkpoint,
        )
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
        self.call_indices = {call.id: index for index, call in enumerate(self.calls)}
        self.futures: dict[str, Future[ToolOutcome]] = {}

    def _context(self, call: ToolCall) -> ToolCallContext:
        return ToolCallContext(
            step=self.step,
            call=call.model_copy(deep=True),
            options=self.options.model_copy(deep=True),
            messages=[item.model_copy(deep=True) for item in self.context_messages],
        )

    def _wake(self, _future: Future[ToolOutcome] | None = None) -> None:
        with self.run._execution_condition:
            self.run._execution_condition.notify_all()

    def _raw_results(self) -> dict[str, ToolResultMessage]:
        with self.run._lock:
            return {
                call_id: execution.result
                for call_id, execution in self.record.tools.items()
                if execution.result is not None
            }

    def _start(
        self,
        calls: list[ToolCall],
        *,
        approved: bool = False,
        children: list[RunState] | None = None,
        merged_arguments: dict[str, JsonValue] | None = None,
    ) -> None:

        def operation() -> ToolOutcome:
            outcome = self._execute_tool(
                calls=calls,
                approved=approved,
                children=children,
                merged_arguments=merged_arguments,
            )
            if len(calls) > 1 and not isinstance(outcome, ToolResult):
                raise ValueError("Batched tools must return a completed result")
            if isinstance(outcome, ToolResult):
                # Checkpoint capture must not split a completed batch.
                with self.run._lock:
                    for member in calls:
                        self._record_tool_result(outcome, member)
            return outcome

        future = self.run._work.start(operation)
        for member in calls:
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
        while self.run._progress.finalized_tools < len(self.calls):
            call = self.calls[self.run._progress.finalized_tools]
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
            self._finish_tool(result, call)

    def execute(self) -> bool:
        try:
            with self.run._cancellation_signal.on_cancel(self._wake):
                while True:
                    self.run._cancellation_signal.check()
                    self.run._begin_work_cycle()
                    self._collect_results()
                    self._finalize_ready()
                    results = self._raw_results()
                    if self.run._progress.finalized_tools == len(self.calls):
                        return True
                    for index, call in enumerate(self.calls):
                        if call.id in results or call.id in self.futures:
                            continue
                        if (
                            self.sequential
                            and index != self.run._progress.finalized_tools
                        ):
                            break
                        with self.run._lock:
                            pending = self.run._progress.pending_tool_calls.get(call.id)
                            suspend = (
                                self.run._execution_request == ExecutionRequest.SUSPEND
                            )
                            answer = (
                                self.run._progress.human_tool_answers.get(
                                    pending.request_id
                                )
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
                                self._start([call], approved=True)
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
                            self._start([call], children=children)
                            continue
                        self._start_compatible_calls(call, index, results)
                    if not self.futures:
                        if len(self._raw_results()) > len(results):
                            continue
                        return False
                    self.run._wait_for_tool_activity(
                        lambda: any(future.done() for future in self.futures.values())
                    )
        except BaseException:
            self.run._cancellation_signal.cancel()
            self._wake()
            raise

    def _start_compatible_calls(
        self, call: ToolCall, index: int, results: dict[str, ToolResultMessage]
    ) -> None:
        tool = self.tools.get(call.name)
        if (
            tool is None
            or tool.merge_arguments is None
            or self.run._before_tool_call is not None
            or not call.arguments_complete
            or call.argument_error
            or self.message.stop_reason == "length"
        ):
            self._start([call])
            return
        group = [call]
        arguments = call.model_copy(deep=True).arguments
        for candidate in self.calls[index + 1 :]:
            eligible = (
                candidate.name == call.name
                and candidate.id not in results
                and candidate.id not in self.futures
                and candidate.id not in self.run._progress.pending_tool_calls
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
            group,
            merged_arguments=arguments if len(group) > 1 else None,
        )

    def _execute_tool(
        self,
        *,
        calls: list[ToolCall],
        approved: bool = False,
        children: list[RunState] | None = None,
        merged_arguments: dict[str, JsonValue] | None = None,
    ) -> ToolOutcome:
        call = calls[0]
        cancellation_signal = self.run._cancellation_signal
        step = self.step
        options = self.options
        tool = self.tools.get(call.name)
        with self.run._lock:
            cancellation_signal.check()
            for member in calls:
                if member.id not in self.record.tools:
                    self.record.tools[member.id] = ToolExecutionRecord(
                        status=ExecutionStatus.RUNNING,
                    )
                    if self.run._delivery:
                        self.run._delivery.publish(
                            ToolStartEvent(
                                **self.run._ancestry,
                                message_id=self.message_id,
                                step_index=step.index,
                                tool_call=member,
                            )
                        )
        cancellation_signal.check()
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
        context: ToolCallContext | None = None
        before_tool_call = self.run._before_tool_call
        if before_tool_call and not approved and children is None:
            context = self._context(call)
            result = before_tool_call(context)
            if result is not None:
                return result
        cancellation_signal.check()
        active = threading.Event()
        active.set()

        def update(progress: ToolProgress) -> None:
            with self.run._lock:
                if not active.is_set() or not self.run._accepting:
                    logger.debug("Ignoring late tool progress: %s", call.id)
                    return
                cancellation_signal.check()
                if self.run._delivery:
                    for member in calls:
                        self.run._delivery.publish(
                            ToolUpdateEvent(
                                **self.run._ancestry,
                                message_id=self.message_id,
                                step_index=step.index,
                                tool_call=member,
                                progress=progress,
                            )
                        )

        invocation = ToolInvocation(
            call_id=call.id,
            call_index=self.call_indices[call.id],
            arguments=merged_arguments
            if merged_arguments is not None
            else call.model_copy(deep=True).arguments,
            cancellation=cancellation_signal,
            update=update,
            messages=[
                message.model_copy(deep=True)
                for message in (context.messages if context else self.context_messages)
            ],
            agents=self.run._coordination.for_tool(call.id, self.message_id, active)
            if self.run._coordination
            else None,
        )
        try:
            if children is not None:
                if tool.result_from_children is None:
                    raise ValueError(
                        "Tool does not support completing child dependencies"
                    )
                try:
                    result = tool.result_from_children(invocation, children)
                except Exception as error:
                    logger.exception("Tool completion failed for %s", call.name)
                    result = ToolResult(
                        content=f"Tool failed with error: {error}", is_error=True
                    )
                if self.run._coordination is not None:
                    self.run._coordination.observe_children(
                        [child.run_id for child in children]
                    )
                return result
            try:
                outcome = tool.execute(invocation)
            except Exception as error:
                logger.exception("Tool execution failed for %s", call.name)
                return ToolResult(
                    content=f"Tool failed with error: {error}", is_error=True
                )
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
        event = ToolUpdateEvent(
            **self.run._ancestry,
            message_id=self.message_id,
            step_index=self.step.index,
            tool_call=call,
            progress=ToolProgress(content=result.text, details=result.details),
        )
        with self.run._lock:
            if not self.run._accepting:
                logger.warning("Tool completed after its run closed: %s", call.id)
                raise AgentCancelled()
            execution = self.record.tools[call.id]
            execution.result = _tool_result_message(result, call, self.message_id)
            execution.status = (
                ExecutionStatus.ERROR if result.is_error else ExecutionStatus.COMPLETE
            )
            if self.run._delivery:
                self.run._delivery.publish(event)

    def _resolve_tool_wait(self, call: ToolCall) -> None:
        with self.run._lock:
            del self.run._progress.pending_tool_calls[call.id]
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
                pending.request_id in self.run._progress.human_tool_answers
                or any(
                    isinstance(existing, PendingToolInput)
                    and existing.request_id == pending.request_id
                    for existing in self.run._progress.pending_tool_calls.values()
                )
            ):
                raise ValueError("Input request IDs must be unique within a run")
            self.run._progress.pending_tool_calls[call.id] = pending.model_copy(
                deep=True
            )
            self.run._state.revision += 1
            if event is not None and self.run._accepting and self.run._delivery:
                self.run._delivery.publish(event)

    def _finish_tool(self, result: ToolResult, call: ToolCall) -> None:
        try:
            after = self.run._after_tool_call
            if after:
                context = self._context(call)
                self.run._cancellation_signal.check()
                result = after(context, result.model_copy(deep=True))
                self.run._cancellation_signal.check()
        finally:
            self._finalize_tool_result(result, call)
        with self.run._lock:
            self.run._progress.finalized_tools += 1
            self.run._state.revision += 1

    def _finalize_tool_result(
        self,
        result: ToolResult,
        call: ToolCall,
    ) -> None:
        event = ToolEndEvent(
            **self.run._ancestry,
            message_id=self.message_id,
            step_index=self.step.index,
            tool_call=call,
            result=result,
        )
        with self.run._lock:
            if not self.run._accepting or self.run._cancellation_signal.cancelled:
                logger.debug("Ignoring late tool finalization: %s", call.id)
                return
            execution = self.record.tools[call.id]
            if execution.result is None:
                raise RuntimeError("Completed tool result is missing from history")
            if self.run._after_tool_call is not None:
                execution.result = _tool_result_message(result, call, self.message_id)
                execution.status = (
                    ExecutionStatus.ERROR
                    if result.is_error
                    else ExecutionStatus.COMPLETE
                )
            if self.run._delivery:
                self.run._delivery.publish(event)


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
