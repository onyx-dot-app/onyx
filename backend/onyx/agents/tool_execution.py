"""Advance parallel tools and finalize completed results on the execution thread."""

import threading
from collections.abc import Sequence
from concurrent.futures import Future
from typing import TYPE_CHECKING

from pydantic import JsonValue

from onyx.agents.events import ToolUpdateEvent
from onyx.agents.models import (
    AgentStep,
    RunProgress,
    RunState,
    StepRecord,
    ToolCallContext,
)
from onyx.agents.tools import (
    AgentTool,
    ChildRunWait,
    InputDecision,
    InputMode,
    PendingToolInput,
    ToolExecutionMode,
    ToolInvocation,
    ToolOutcome,
    ToolProgress,
)
from onyx.llm.models import (
    Message,
    ToolCall,
    ToolChoiceOptions,
    ToolResult,
)
from onyx.utils.logger import setup_logger

if TYPE_CHECKING:
    from onyx.agents.runtime import Run

logger = setup_logger()

MAX_TOOL_CALLS_PER_STEP = 64


class ToolBatch:
    """Schedule tools using borrowed step data; Run owns all recorded changes."""

    def __init__(
        self,
        run: "Run",
        *,
        tools: Sequence[AgentTool],
        progress: RunProgress,
        record: StepRecord,
        history: list[Message],
    ) -> None:
        if progress.options is None:
            raise ValueError("Saved step is missing generation options")
        self.run = run
        self.progress = progress
        self.record = record
        self.step = AgentStep(index=progress.step_index, limit=progress.step_limit)
        self.message = record.message
        if self.message.id is None:
            raise ValueError("Tool execution requires a message ID")
        self.message_id = self.message.id
        self.options = progress.options
        self.context_messages = history
        self.calls = self.message.tool_calls
        if len(self.calls) > MAX_TOOL_CALLS_PER_STEP or len(
            {call.id for call in self.calls}
        ) != len(self.calls):
            raise ValueError(
                f"A step requires unique tool call IDs and at most {MAX_TOOL_CALLS_PER_STEP} calls"
            )
        self.tools = {tool.name: tool for tool in tools}
        self.call_indices = {call.id: index for index, call in enumerate(self.calls)}
        self.futures: dict[str, Future[ToolOutcome]] = {}

    def _context(self, call: ToolCall) -> ToolCallContext:
        return ToolCallContext(
            step=self.step,
            call=call.model_copy(deep=True),
            options=self.options.model_copy(deep=True),
            messages=[item.model_copy(deep=True) for item in self.context_messages],
        )

    def _completed_call_ids(self) -> set[str]:
        with self.run.execution_lock:
            return {
                call_id
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
                self.run.record_tool_results(outcome, calls)
            return outcome

        future = self.run.work.start(operation)
        for member in calls:
            self.futures[member.id] = future
        future.add_done_callback(lambda _future: self.run.notify_tool_activity())

    def _collect_results(self) -> None:
        for call_id, future in tuple(self.futures.items()):
            if not future.done():
                continue
            del self.futures[call_id]
            result = future.result()
            index = self.call_indices[call_id]
            call = self.calls[index]
            if not isinstance(result, ToolResult):
                self.run.record_pending_tool(call, result)

    def execute(self) -> bool:
        try:
            with self.run.cancellation_signal.on_cancel(self.run.notify_tool_activity):
                while True:
                    self.run.cancellation_signal.check()
                    self.run.begin_work_cycle()
                    self._collect_results()
                    completed_call_ids = self._completed_call_ids()
                    for call in self.calls:
                        if (
                            call.id in self.progress.finalized_tool_call_ids
                            or call.id not in completed_call_ids
                        ):
                            continue
                        self.run.finish_tool(
                            call,
                            self._context(call)
                            if self.run.after_tool_call is not None
                            else None,
                        )
                    completed_call_ids = self._completed_call_ids()
                    if len(self.progress.finalized_tool_call_ids) == len(self.calls):
                        return True
                    blocked_tool_names: set[str] = set()
                    for index, call in enumerate(self.calls):
                        if call.id in self.progress.finalized_tool_call_ids:
                            continue
                        tool = self.tools.get(call.name)
                        if tool and tool.execution_mode == ToolExecutionMode.SEQUENTIAL:
                            if call.name in blocked_tool_names:
                                continue
                            # Pending input and child waits retain their place in order.
                            blocked_tool_names.add(call.name)
                        if call.id in completed_call_ids or call.id in self.futures:
                            continue
                        with self.run.execution_lock:
                            pending = self.progress.pending_tool_calls.get(call.id)
                            suspend = self.run.suspension_requested
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
                            self.run.resolve_tool_wait(call)
                            if answer.decision == InputDecision.APPROVE:
                                self._start([call], approved=True)
                            else:
                                output = answer.result or ToolResult(
                                    content="Tool execution was denied.", is_error=True
                                )
                                self.run.record_tool_results(output, [call])
                            continue
                        if isinstance(pending, ChildRunWait):
                            if self.run.coordination is None:
                                raise ValueError(
                                    "Child dependency requires an execution coordinator"
                                )
                            children = self.run.coordination.completed_child_states(
                                pending.run_ids
                            )
                            if children is None:
                                self.run.watch_children(pending.run_ids)
                                continue
                            self.run.resolve_tool_wait(call)
                            self._start([call], children=children)
                            continue
                        self._start_compatible_calls(call, index, completed_call_ids)
                    if not self.futures:
                        if len(self._completed_call_ids()) > len(completed_call_ids):
                            continue
                        return False
                    self.run.wait_for_tool_activity(
                        lambda: any(future.done() for future in self.futures.values())
                    )
        except BaseException:
            self.run.cancellation_signal.cancel()
            self.run.notify_tool_activity()
            raise

    def _start_compatible_calls(
        self, call: ToolCall, index: int, completed_call_ids: set[str]
    ) -> None:
        tool = self.tools.get(call.name)
        if (
            tool is None
            or tool.merge_arguments is None
            or self.run.before_tool_call is not None
            or not call.arguments_complete
            or call.argument_error
            or self.message.stop_reason == "length"
        ):
            self._start([call])
            return
        group = [call]
        arguments = call.model_copy(deep=True).arguments
        for candidate in self.calls[index + 1 :]:
            if candidate.name != call.name:
                continue
            eligible = (
                candidate.id not in completed_call_ids
                and candidate.id not in self.futures
                and candidate.id not in self.progress.pending_tool_calls
                and candidate.arguments_complete
                and not candidate.argument_error
            )
            if not eligible:
                if tool.execution_mode == ToolExecutionMode.SEQUENTIAL:
                    break
                continue
            merged = tool.merge_arguments(
                arguments, candidate.model_copy(deep=True).arguments
            )
            if merged is None:
                if tool.execution_mode == ToolExecutionMode.SEQUENTIAL:
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
        cancellation_signal = self.run.cancellation_signal
        step = self.step
        options = self.options
        tool = self.tools.get(call.name)
        self.run.start_tool_calls(calls)
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
        before_tool_call = self.run.before_tool_call
        if before_tool_call and not approved and children is None:
            context = self._context(call)
            result = before_tool_call(context)
            if result is not None:
                return result
        cancellation_signal.check()
        active = threading.Event()
        active.set()

        def update(progress: ToolProgress) -> None:
            with self.run.execution_lock:
                if not active.is_set() or not self.run.is_accepting:
                    logger.debug("Ignoring late tool progress: %s", call.id)
                    return
                cancellation_signal.check()
                for member in calls:
                    self.run.publish_event(
                        ToolUpdateEvent(
                            **self.run.event_context,
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
            agents=self.run.coordination.for_tool(call.id, self.message_id, active)
            if self.run.coordination
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
                if self.run.coordination is not None:
                    self.run.coordination.observe_children(
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
            with self.run.execution_lock:
                active.clear()
