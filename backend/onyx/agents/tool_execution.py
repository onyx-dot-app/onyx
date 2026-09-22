"""Advance parallel tools and ordered finalizers without parking completed workers."""

from concurrent.futures import Future
from typing import TYPE_CHECKING

from onyx.agents.concurrency import OPERATION_TIMEOUT_SECONDS
from onyx.agents.events import InputRequiredEvent
from onyx.agents.models import PreparedStep, RunSnapshot, StepResult, ToolCallContext
from onyx.agents.tools import (
    ChildRunWait,
    InputDecision,
    PendingToolInput,
    ToolExecutionMode,
    ToolOutcome,
)
from onyx.llm.models import Message, ToolCall, ToolResult, ToolResultMessage

if TYPE_CHECKING:
    from onyx.agents.runtime import _Execution

MAX_TOOL_CALLS_PER_STEP = 64


class ToolBatch:
    def __init__(
        self,
        execution: "_Execution",
        prepared: PreparedStep,
        completed: StepResult,
        messages: list[Message],
    ) -> None:
        self.execution = execution
        self.scope = execution.work
        self.signal = execution.state.signal
        self.step = completed.step
        self.message = completed.message
        self.ancestry = execution.ancestry
        self.options = completed.options
        self.messages = messages
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
        if self.execution.step_start is None:
            raise RuntimeError("Tool phase requires a generation")
        self.result_start = self.execution.step_start + 1
        self.call_indices = {call.id: index for index, call in enumerate(self.calls)}
        self.futures: dict[str, Future[ToolOutcome]] = {}

    def _context(self, call: ToolCall) -> ToolCallContext:
        return ToolCallContext(
            step=self.step,
            call=call,
            options=self.options.model_copy(deep=True),
            messages=[item.model_copy(deep=True) for item in self.messages],
        )

    def _wake(self, _future: Future[ToolOutcome] | None = None) -> None:
        with self.execution.state.changed:
            self.execution.state.changed.notify_all()

    def _raw_results(self) -> dict[str, ToolResultMessage]:
        return {
            item.tool_call_id: item
            for item in self.execution.messages[self.result_start :]
            if isinstance(item, ToolResultMessage)
        }

    def _start(
        self,
        call: ToolCall,
        index: int,
        approved: bool = False,
        children: list[RunSnapshot] | None = None,
    ) -> None:

        def operation() -> ToolOutcome:
            with self.signal.on_operation(self.scope.track_operation):
                outcome = self.execution._execute_tool(
                    signal=self.signal,
                    context=self._context(call),
                    tool=self.tools.get(call.name),
                    index=index,
                    ancestry=self.ancestry,
                    is_truncated=self.message.stop_reason == "length",
                    approved=approved,
                    children=children,
                )
                if isinstance(outcome, ToolResult):
                    self.execution._record_tool_result(
                        outcome,
                        call,
                        self.result_start,
                        self.call_indices,
                        index,
                        self.step,
                    )
                return outcome

        future = self.scope.start(operation)
        self.futures[call.id] = future
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
                with self.execution.state.lock:
                    if isinstance(result, PendingToolInput):
                        if result.request_id in self.execution.progress.answers or any(
                            (
                                isinstance(pending, PendingToolInput)
                                and pending.request_id == result.request_id
                                for pending in self.execution.progress.pending.values()
                            )
                        ):
                            raise ValueError(
                                "Input request IDs must be unique within a run"
                            )
                    self.execution.progress.pending[call.id] = result.model_copy(
                        deep=True
                    )
                    self.execution.state.record.revision += 1
                if isinstance(result, PendingToolInput):
                    self.execution.publish_event(
                        InputRequiredEvent(
                            **self.ancestry, tool_call_id=call.id, request=result
                        )
                    )

    def _finalize_ready(self) -> None:
        results = self._raw_results()
        while self.execution.progress.finalized_tools < len(self.calls):
            call = self.calls[self.execution.progress.finalized_tools]
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
            try:
                after = self.execution.after_tool_call
                if after:
                    result = self.scope.blocking(
                        lambda after=after, call=call, result=result: after(
                            self._context(call), result.model_copy(deep=True)
                        ),
                        self.signal,
                    )
            finally:
                self.execution._finalize_tool_result(
                    result, call, self.step, self.result_start
                )
            with self.execution.state.lock:
                self.execution.progress.finalized_tools += 1
                self.execution.state.record.revision += 1

    def run(self) -> list[ToolResultMessage] | None:
        try:
            with self.signal.on_cancel(self._wake):
                while True:
                    self.signal.check()
                    with self.execution.state.lock:
                        self.execution.state.wake_requested = False
                    self._collect_results()
                    self._finalize_ready()
                    results = self._raw_results()
                    if self.execution.progress.finalized_tools == len(self.calls):
                        results = self._raw_results()
                        return [
                            results[call.id].model_copy(deep=True)
                            for call in self.calls
                        ]
                    for index, call in enumerate(self.calls):
                        if call.id in results or call.id in self.futures:
                            continue
                        if (
                            self.sequential
                            and index != self.execution.progress.finalized_tools
                        ):
                            break
                        with self.execution.state.lock:
                            pending = self.execution.progress.pending.get(call.id)
                            suspend = self.execution.state.suspend_requested
                            answer = (
                                self.execution.progress.answers.get(pending.request_id)
                                if isinstance(pending, PendingToolInput)
                                else None
                            )
                        if suspend:
                            continue
                        if isinstance(pending, PendingToolInput):
                            if answer is None:
                                continue
                            with self.execution.state.lock:
                                del self.execution.progress.pending[call.id]
                            if answer.decision == InputDecision.APPROVE:
                                self._start(call, index, approved=True)
                            else:
                                output = answer.result or ToolResult(
                                    content="Tool execution was denied.", is_error=True
                                )
                                self.execution._record_tool_result(
                                    output,
                                    call,
                                    self.result_start,
                                    self.call_indices,
                                    index,
                                    self.step,
                                )
                            continue
                        if isinstance(pending, ChildRunWait):
                            if self.execution.coordination is None:
                                raise ValueError(
                                    "Child dependency requires an execution coordinator"
                                )
                            children = self.execution.coordination.child_runs(
                                pending.run_ids
                            )
                            if any(
                                (
                                    not child._state.completed.done()
                                    for child in children
                                )
                            ):
                                self.execution.watch_children(children)
                                continue
                            with self.execution.state.lock:
                                del self.execution.progress.pending[call.id]
                            self._start(
                                call,
                                index,
                                children=[child.snapshot() for child in children],
                            )
                            continue
                        self._start(call, index)
                    if not self.futures:
                        if len(self._raw_results()) > len(results):
                            continue
                        return None
                    with self.execution.state.changed:
                        ready = self.execution.state.changed.wait_for(
                            lambda: (
                                self.signal.cancelled
                                or self.execution.state.wake_requested
                                or any((f.done() for f in self.futures.values()))
                            ),
                            OPERATION_TIMEOUT_SECONDS,
                        )
                    if not ready:
                        raise TimeoutError("Agent tool exceeded its execution bound")
        except BaseException:
            self.signal.cancel()
            self._wake()
            raise
