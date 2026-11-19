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
    BeforeToolCallFailed,
    ChildRunWait,
    InputDecision,
    InputMode,
    NestedCallGate,
    NestedInputAnswer,
    NestedInputRequest,
    NestedInputWait,
    PendingToolInput,
    ToolExecutionMode,
    ToolInvocation,
    ToolOutcome,
    ToolProgress,
)
from onyx.llm.models import (
    Message,
    NamedToolChoice,
    ToolCall,
    ToolChoiceOptions,
    ToolResult,
    ToolResultMessage,
)
from onyx.utils.logger import setup_logger

if TYPE_CHECKING:
    from onyx.agents.runtime import Run

logger = setup_logger()

# The result of a call on a step where no tool can run. It asks the model for
# its final answer.
NO_TOOL_CAN_RUN_RESULT = (
    "No more tools can run in this response. Write your final answer now."
)


def _tool_view(message: Message) -> Message:
    """An owned copy of a conversation message for a tool. Result details stay
    with the runtime; tools read them from `recorded_results`."""
    if isinstance(message, ToolResultMessage) and message.details is not None:
        message = message.model_copy(update={"details": None})
    return message.model_copy(deep=True)


MAX_TOOL_CALLS_PER_STEP = 64
# What the model sees for a call whose request was denied without a result.
DENIED_CALL_MESSAGE = "The tool call was not approved, so it did not run."
# What the model sees for an approved call whose tool was removed, or whose
# parameters changed, while the call waited.
UNAVAILABLE_CALL_MESSAGE = "This tool is no longer available, so this call did not run."


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
        recorded: Sequence[Message],
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
        # Every recorded tool result before this step.
        self.recorded_results = tuple(
            message for message in recorded if isinstance(message, ToolResultMessage)
        )
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
            messages=[_tool_view(item) for item in self.context_messages],
        )

    def decide_call(
        self, tool_call: ToolCall, nested_call: ToolCall | None
    ) -> ToolResult | PendingToolInput | None:
        """The decision on `tool_call`, a call of this step, or on `nested_call`,
        a call that its tool makes for the model, such as a program's: the
        run's before_tool_call hook, then the user's approval when the call
        requires it."""
        call = nested_call or tool_call
        if self.run.before_tool_call is not None:
            decision = self.run.before_tool_call(self._context(call))
            if decision is not None:
                return decision
        if call.name not in self.run.approval_required:
            return None
        approvals = self.run.approvals
        if approvals is None:
            return ToolResult(
                content=(
                    f"The {call.name} call needs the user's approval, and this "
                    "run cannot ask for it, so it did not run."
                ),
                is_error=True,
            )
        decision = approvals.request_approval(self.run, tool_call, nested_call)
        if isinstance(decision, PendingToolInput):
            return decision.model_copy(update={"approval": True})
        return decision

    def _recorded_before(self) -> tuple[ToolResultMessage, ...]:
        """Recorded tool results before a call: earlier steps, then this step's
        completed results in call order."""
        with self.run.execution_lock:
            results = [
                execution.result
                for call in self.calls
                if (execution := self.record.tools.get(call.id)) is not None
                and execution.result is not None
            ]
        return (*self.recorded_results, *results)

    def _was_started(self, call: ToolCall) -> bool:
        with self.run.execution_lock:
            return call.id in self.record.tools

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
        nested_answers: list[NestedInputAnswer] | None = None,
        merged_arguments: dict[str, JsonValue] | None = None,
    ) -> None:

        def operation() -> ToolOutcome:
            outcome = self._execute_tool(
                calls=calls,
                approved=approved,
                children=children,
                nested_answers=nested_answers,
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
                    blocked_sequences: set[str] = set()
                    for index, call in enumerate(self.calls):
                        if call.id in self.progress.finalized_tool_call_ids:
                            continue
                        tool = self.tools.get(call.name)
                        if tool and tool.execution_mode == ToolExecutionMode.SEQUENTIAL:
                            sequence = tool.sequence_group or call.name
                            if sequence in blocked_sequences:
                                continue
                            # Pending input and child waits retain their place in order.
                            blocked_sequences.add(sequence)
                        if call.id in completed_call_ids or call.id in self.futures:
                            continue
                        with self.run.execution_lock:
                            pending = self.progress.pending_tool_calls.get(call.id)
                            suspend = self.run.suspension_requested
                        if suspend:
                            continue
                        if isinstance(pending, (PendingToolInput, NestedInputWait)):
                            self._continue_input_wait(call, pending)
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
                    if not self.run.suspension_requested:
                        self._continue_open_inputs()
                    if not self.futures:
                        if len(self._completed_call_ids()) > len(completed_call_ids):
                            continue
                        # See ToolInvocation.run_work.
                        unsubscribe = self.run.work.held.on_idle(
                            self.run.notify_tool_activity
                        )
                        try:
                            if self.run.work.held.idle:
                                return False
                            self.run.wait_for_tool_activity(
                                lambda: self.run.work.held.idle
                            )
                        finally:
                            unsubscribe()
                        continue
                    self.run.wait_for_tool_activity(
                        lambda: any(future.done() for future in self.futures.values())
                    )
        except BaseException:
            self.run.cancellation_signal.cancel()
            self.run.notify_tool_activity()
            raise

    def _continue_input_wait(
        self, call: ToolCall, pending: PendingToolInput | NestedInputWait
    ) -> None:
        """Continue a call once each of its requests has an answer: run it,
        record its denial, or continue its tool with the answers."""
        requests = (
            [nested.request for nested in pending.requests]
            if isinstance(pending, NestedInputWait)
            else [pending]
        )
        with self.run.execution_lock:
            answers = self.progress.human_tool_answers
            found = [
                answer
                for request in requests
                if (answer := answers.get(request.request_id)) is not None
            ]
        if len(found) < len(requests):
            return
        self.run.resolve_tool_wait(call)
        if isinstance(pending, PendingToolInput) and (
            found[0].decision != InputDecision.APPROVE
        ):
            self.run.record_tool_results(
                found[0].result
                or ToolResult(content=DENIED_CALL_MESSAGE, is_error=True),
                [call],
            )
        elif call.name not in self.tools:
            self.run.record_tool_results(
                ToolResult(content=UNAVAILABLE_CALL_MESSAGE, is_error=True), [call]
            )
        elif isinstance(pending, PendingToolInput):
            self._start([call], approved=True)
        else:
            self._start(
                [call],
                nested_answers=[
                    NestedInputAnswer(request=request, answer=answer)
                    for request, answer in zip(pending.requests, found, strict=True)
                ],
            )

    def _continue_open_inputs(self) -> None:
        """Give the answers of open requests to the tools that made their
        calls, one call's requests at a time; see
        AgentTool.continue_open_input."""
        with self.run.execution_lock:
            answers = self.progress.human_tool_answers
            by_call: dict[str, list[NestedInputAnswer]] = {}
            for request_id, request in self.progress.open_inputs.items():
                answer = answers.get(request_id)
                if answer is not None:
                    by_call.setdefault(request.tool_call.id, []).append(
                        NestedInputAnswer(request=request, answer=answer)
                    )
        for answered in by_call.values():
            # Later requests show at the place of the call, as the first did.
            opened = answered[0].request
            call = opened.tool_call
            tool = self.tools.get(call.name)
            if tool is None or tool.continue_open_input is None:
                continue
            invocation = ToolInvocation(
                call_id=call.id,
                call_index=self.call_indices.get(call.id, 0),
                arguments=call.model_copy(deep=True).arguments,
                cancellation=self.run.cancellation_signal,
                # Nothing observes the call, which already returned.
                update=lambda _progress: None,
                messages=[_tool_view(message) for message in self.context_messages],
                recorded_results=self._recorded_before(),
                nested_calls=_NestedCallGate(
                    self, call, opened.message_id, opened.step_index
                ),
                run_work=self.run.work,
            )
            try:
                taken = tool.continue_open_input(invocation, answered)
            except Exception:
                # The requests stay open with their answers.
                logger.exception("Tool %s did not take its answers", call.name)
                continue
            self.run.resolve_open_inputs(taken)

    def _start_compatible_calls(
        self, call: ToolCall, index: int, completed_call_ids: set[str]
    ) -> None:
        tool = self.tools.get(call.name)
        if (
            tool is not None
            and tool.interrupted_result is not None
            and self._was_started(call)
        ):
            # A lost execution owner left the call running. The result ends the
            # call through `finish_tool`, as a completed call does.
            self.run.record_tool_results(tool.interrupted_result, [call])
            return
        if (
            tool is None
            or tool.merge_arguments is None
            or self.run.before_tool_call is not None
            or call.name in self.run.approval_required
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
        nested_answers: list[NestedInputAnswer] | None = None,
        merged_arguments: dict[str, JsonValue] | None = None,
    ) -> ToolOutcome:
        """`approved` starts a call whose request the user approved.
        `nested_answers` continue a call that waited for the requests of calls
        that its tool made."""
        call = calls[0]
        cancellation_signal = self.run.cancellation_signal
        step = self.step
        options = self.options
        tool = self.tools.get(call.name)
        self.run.start_tool_calls(calls, tool.display_name if tool else None)
        cancellation_signal.check()
        if (
            tool is None
            or options.tool_choice == ToolChoiceOptions.NONE
            or (
                isinstance(options.tool_choice, NamedToolChoice)
                and call.name != options.tool_choice.name
            )
        ):
            content = (
                NO_TOOL_CAN_RUN_RESULT
                if options.tool_choice == ToolChoiceOptions.NONE
                else f"Tool {call.name} is unavailable for this step."
            )
            # A call of a tool that runs only inside an offered tool's calls,
            # such as a code mode function, says how to call it there.
            if tool is None and options.tool_choice != ToolChoiceOptions.NONE:
                for offered in self.tools.values():
                    hint = (
                        offered.inner_call_hint(call.name)
                        if offered.inner_call_hint is not None
                        else None
                    )
                    if hint is not None:
                        content = hint
                        break
            return ToolResult(content=content, is_error=True)
        if (
            call.argument_error
            or not call.arguments_complete
            or self.message.stop_reason == "length"
        ):
            return ToolResult(
                content=call.argument_error or "Tool arguments were truncated.",
                is_error=True,
            )
        if not approved and children is None and nested_answers is None:
            decision = self.decide_call(call, None)
            if decision is not None:
                return decision
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
            messages=[_tool_view(message) for message in self.context_messages],
            recorded_results=self._recorded_before(),
            agents=self.run.coordination.for_tool(call.id, self.message_id, active)
            if self.run.coordination
            else None,
            nested_calls=_NestedCallGate(self, call, self.message_id, self.step.index)
            if self.run.before_tool_call is not None or self.run.approval_required
            else None,
            run_work=self.run.work,
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
                if nested_answers is None:
                    outcome = tool.execute(invocation)
                elif tool.resume_with_input is None:
                    raise ValueError("Tool does not support continuing after input")
                else:
                    outcome = tool.resume_with_input(invocation, nested_answers)
            except BeforeToolCallFailed as failed:
                # As when the hook raises for a direct call: the run fails.
                raise failed.error
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


class _NestedCallGate(NestedCallGate):
    """Decides the calls that one direct call makes for the model. Its
    requests show at `message_id` and `step_index`, the place of the call."""

    def __init__(
        self, batch: ToolBatch, call: ToolCall, message_id: str, step_index: int
    ) -> None:
        self._batch = batch
        self._call = call
        self._message_id = message_id
        self._step_index = step_index

    def decide(self, call: ToolCall) -> ToolResult | NestedInputRequest | None:
        batch = self._batch
        try:
            decision = batch.decide_call(self._call, call)
        except Exception as error:
            # As when the hook raises for a direct call: the run fails.
            raise BeforeToolCallFailed(error) from error
        if not isinstance(decision, PendingToolInput):
            return decision
        request = NestedInputRequest(
            message_id=self._message_id,
            step_index=self._step_index,
            tool_call=self._call,
            nested_call=call,
            request=decision,
        )
        batch.run.open_nested_input(request)
        return request

    def withdraw(self, request: NestedInputRequest) -> None:
        self._batch.run.withdraw_nested_input(request)
