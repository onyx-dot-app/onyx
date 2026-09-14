from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from typing import Any

from jsonschema import Draft202012Validator, SchemaError, ValidationError

from onyx.agents.v2.catalog import ToolCatalog
from onyx.agents.v2.context import ContextBudgetExceeded, ContextState
from onyx.agents.v2.llm import BudgetExceeded, estimate_decision_prompt_tokens
from onyx.agents.v2.models import (
    DecisionModel,
    ExecutionContext,
    HarnessEvent,
    HarnessPolicy,
    HarnessResult,
    ModelDecision,
    Outcome,
    RegisteredTool,
    ToolInvocation,
    ToolOutput,
    UsageSnapshot,
)
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel

CONTROL_DISCOVER_TOOLS = "discover_tools"
CONTROL_READ_RESULT = "read_result"
CONTROL_FINISH_TASK = "finish_task"
INTERNAL_SEARCH_TOOL = "internal_search"
MAX_ERROR_CHARS = 500
MAX_CONTROL_QUERY_CHARS = 300
PROMPT_BUDGET_SAFETY_TOKENS = 256
FINISH_OUTCOMES: set[Outcome] = {
    "completed",
    "partial",
    "needs_user_input",
    "blocked",
    "budget_exhausted",
    "cancelled",
}


class AgentHarness:
    def __init__(
        self,
        *,
        model: DecisionModel,
        tools: list[RegisteredTool],
        policy: HarnessPolicy | None = None,
        usage: Callable[[], UsageSnapshot] | None = None,
        token_counter: Callable[[str], int] | None = None,
        clock: Callable[[], float] = time.monotonic,
        cancelled: Callable[[], bool] = lambda: False,
        started_at: float | None = None,
    ) -> None:
        self._model = model
        self._tools = tools
        self._policy = policy or HarnessPolicy()
        self._usage = usage or UsageSnapshot
        self._token_counter = token_counter or _rough_token_count
        self._clock = clock
        self._cancelled = cancelled
        self._started_at = started_at

    def run(self, task: str) -> HarnessResult:  # noqa: C901
        run_id = str(uuid.uuid4())
        start_time = self._clock() if self._started_at is None else self._started_at
        events: list[HarnessEvent] = []
        catalog = ToolCatalog(self._tools, self._policy.max_exposed_tools)
        context = ContextState(self._policy, self._token_counter)
        model_calls = 0
        tool_calls = 0
        best_answer = ""
        best_output: ToolOutput | None = None
        repeated_tool_failures = 0
        completion_reviewed = False

        def elapsed_seconds() -> float:
            return max(self._clock() - start_time, 0)

        def remaining_seconds() -> float:
            remaining = self._policy.max_elapsed_seconds - elapsed_seconds()
            return (
                remaining if self._policy.duration_mode == "soft" else max(remaining, 0)
            )

        def current_usage() -> UsageSnapshot:
            return self._usage()

        def event(kind: str, data: dict[str, Any] | None = None) -> None:
            events.append(
                HarnessEvent(
                    kind=kind,
                    elapsed_ms=elapsed_seconds() * 1000,
                    data=data or {},
                )
            )

        def exhausted_by_context(reason: str) -> HarnessResult:
            return _result(
                run_id=run_id,
                outcome="budget_exhausted",
                answer=best_answer,
                reason=reason,
                model_calls=model_calls,
                tool_calls=tool_calls,
                total_ms=elapsed_seconds() * 1000,
                usage=current_usage(),
                events=events,
                context=context,
                output=best_output,
            )

        event("start", {"exposed_tools": _exposed_names(catalog)})

        while True:
            stop = _budget_stop(
                policy=self._policy,
                usage=current_usage(),
                model_calls=model_calls,
                tool_calls=tool_calls,
                elapsed_seconds=elapsed_seconds(),
                cancelled=self._cancelled(),
                before_work=True,
            )
            if stop is not None:
                return _result(
                    run_id=run_id,
                    outcome=stop[0],
                    answer=best_answer,
                    reason=stop[1],
                    model_calls=model_calls,
                    tool_calls=tool_calls,
                    total_ms=elapsed_seconds() * 1000,
                    usage=current_usage(),
                    events=events,
                    context=context,
                    output=best_output,
                )

            usage_before_model = current_usage()
            remaining_tokens_before_model = _remaining_tokens(
                self._policy, usage_before_model
            )
            completion_only = (
                self._policy.completion_reserve_tokens > 0
                and remaining_tokens_before_model
                <= self._policy.completion_reserve_tokens
            )
            tools_for_model = [
                *([] if completion_only else catalog.definitions()),
                *_control_definitions(),
            ]
            context_started = self._clock()
            try:
                rendered_context = _render_context_for_model(
                    task=task,
                    context=context,
                    catalog=catalog,
                    policy=self._policy,
                    usage=usage_before_model,
                    remaining_seconds=remaining_seconds(),
                    remaining_tokens=remaining_tokens_before_model,
                    tools=tools_for_model,
                    token_counter=self._token_counter,
                )
            except ContextBudgetExceeded as e:
                event("context_budget_exceeded", {"reason": str(e)})
                return _result(
                    run_id=run_id,
                    outcome="budget_exhausted",
                    answer=best_answer,
                    reason=str(e),
                    model_calls=model_calls,
                    tool_calls=tool_calls,
                    total_ms=elapsed_seconds() * 1000,
                    usage=current_usage(),
                    events=events,
                    context=context,
                    output=best_output,
                )

            event(
                "context_preparation",
                {"duration_ms": max(self._clock() - context_started, 0) * 1000},
            )
            model_start = self._clock()
            try:
                decision = self._model.decide(
                    task=task,
                    context=_decision_context(
                        task=task,
                        context=rendered_context,
                        catalog=catalog,
                        policy=self._policy,
                        usage=usage_before_model,
                        remaining_seconds=remaining_seconds(),
                        remaining_tokens=remaining_tokens_before_model,
                    ),
                    tools=tools_for_model,
                    remaining_seconds=remaining_seconds(),
                    remaining_tokens=remaining_tokens_before_model,
                    max_output_tokens=_decision_output_tokens(self._policy),
                )
            except Exception as e:
                if self._policy.duration_mode == "soft" and self._cancelled():
                    return _result(
                        run_id=run_id,
                        outcome="cancelled",
                        answer=best_answer,
                        reason="run was cancelled",
                        model_calls=model_calls,
                        tool_calls=tool_calls,
                        total_ms=elapsed_seconds() * 1000,
                        usage=current_usage(),
                        events=events,
                        context=context,
                        output=best_output,
                    )
                if isinstance(e, BudgetExceeded):
                    event("model_budget_exceeded", {"reason": _safe_error(e)})
                    return _result(
                        run_id=run_id,
                        outcome="budget_exhausted",
                        answer=best_answer,
                        reason=_safe_error(e),
                        model_calls=model_calls,
                        tool_calls=tool_calls,
                        total_ms=elapsed_seconds() * 1000,
                        usage=current_usage(),
                        events=events,
                        context=context,
                        output=best_output,
                    )
                event("model_error", {"reason": _safe_error(e)})
                return _result(
                    run_id=run_id,
                    outcome="blocked",
                    answer=best_answer,
                    reason=f"model failed: {_safe_error(e)}",
                    model_calls=model_calls,
                    tool_calls=tool_calls,
                    total_ms=elapsed_seconds() * 1000,
                    usage=current_usage(),
                    events=events,
                    context=context,
                    output=best_output,
                )
            model_calls += 1
            event(
                "model_decision",
                {
                    "duration_ms": max(self._clock() - model_start, 0) * 1000,
                    "calls": [call.name for call in decision.calls],
                    "outcome": decision.outcome,
                    "decision_mode": decision.decision_mode,
                    "exposed_tools": _exposed_names(catalog),
                    "usage_before": usage_before_model.model_dump(),
                    "usage_after": current_usage().model_dump(),
                },
            )
            stop = _budget_stop_after_model(
                policy=self._policy,
                usage=current_usage(),
                elapsed_seconds=elapsed_seconds(),
                cancelled=self._cancelled(),
            )
            if stop is not None:
                return _result(
                    run_id=run_id,
                    outcome=stop[0],
                    answer=best_answer,
                    reason=stop[1],
                    model_calls=model_calls,
                    tool_calls=tool_calls,
                    total_ms=elapsed_seconds() * 1000,
                    usage=current_usage(),
                    events=events,
                    context=context,
                    output=best_output,
                )

            finish_result = _finish_from_decision(decision, context)
            if finish_result is not None:
                outcome, answer, reason, output = finish_result
                if (
                    outcome == "completed"
                    and self._policy.completion_review
                    and tool_calls > 0
                    and not completion_reviewed
                ):
                    completion_reviewed = True
                    if answer:
                        best_answer = answer
                    review_output = ToolOutput(
                        status="success",
                        content=json.dumps(
                            {
                                "draft_answer": best_answer,
                                "instruction": (
                                    "Perform one final evidence review. Treat the draft as "
                                    "provisional. Compare every candidate entity, event, and "
                                    "phase sequence against all identifying clues in the task; "
                                    "later evidence may disprove an earlier working hypothesis. "
                                    "Check that every requested subpart, exact value, owner, and "
                                    "qualification supported by the evidence is included. For "
                                    "follow-up or action questions, preserve every explicit "
                                    "deliverable, quantity, date, and deadline from the matching "
                                    "record. Revise the answer if needed, search only for a "
                                    "specific remaining gap, then finish."
                                ),
                            },
                            sort_keys=True,
                        ),
                    )
                    review_ref = _add_feedback(
                        context,
                        event,
                        "completion_review",
                        "Review the provisional answer against all collected evidence.",
                        review_output,
                    )
                    if review_ref is None:
                        return exhausted_by_context("context budget exhausted")
                    event("completion_review_requested", {"ref": review_ref})
                    continue
                if output is not None:
                    best_output = output
                if answer:
                    best_answer = answer
                return _result(
                    run_id=run_id,
                    outcome=outcome,
                    answer=best_answer,
                    reason=reason,
                    model_calls=model_calls,
                    tool_calls=tool_calls,
                    total_ms=elapsed_seconds() * 1000,
                    usage=current_usage(),
                    events=events,
                    context=context,
                    output=best_output,
                )

            if decision.outcome is not None and decision.calls:
                output = ToolOutput(
                    status="error",
                    content="A finish outcome cannot be combined with tool calls.",
                )
                if (
                    _add_feedback(
                        context, event, "finish_task", "invalid finish", output
                    )
                    is None
                ):
                    return exhausted_by_context("context budget exhausted")
                continue

            if _has_finish_call(decision.calls) and len(decision.calls) > 1:
                output = ToolOutput(
                    status="error",
                    content="finish_task cannot be combined with other tool calls.",
                )
                if (
                    _add_feedback(
                        context, event, "finish_task", "invalid finish", output
                    )
                    is None
                ):
                    return exhausted_by_context("context budget exhausted")
                continue

            if decision.continue_turn and not decision.calls:
                output = ToolOutput(
                    status="success",
                    content=(
                        "The last assistant message was commentary, not a final answer. "
                        "Continue with a useful action or deliver the supported final answer."
                    ),
                )
                if (
                    _add_feedback(
                        context,
                        event,
                        "assistant_commentary",
                        "Continue the turn",
                        output,
                    )
                    is None
                ):
                    return exhausted_by_context("context budget exhausted")
                continue

            if not decision.calls:
                return _result(
                    run_id=run_id,
                    outcome="partial",
                    answer=decision.answer,
                    reason=decision.reason or "model returned unstructured final text",
                    model_calls=model_calls,
                    tool_calls=tool_calls,
                    total_ms=elapsed_seconds() * 1000,
                    usage=current_usage(),
                    events=events,
                    context=context,
                    output=best_output,
                )

            for call in decision.calls:
                stop = _budget_stop(
                    policy=self._policy,
                    usage=current_usage(),
                    model_calls=model_calls,
                    tool_calls=tool_calls,
                    elapsed_seconds=elapsed_seconds(),
                    cancelled=self._cancelled(),
                    before_work=True,
                )
                if stop is not None:
                    return _result(
                        run_id=run_id,
                        outcome=stop[0],
                        answer=best_answer,
                        reason=stop[1],
                        model_calls=model_calls,
                        tool_calls=tool_calls,
                        total_ms=elapsed_seconds() * 1000,
                        usage=current_usage(),
                        events=events,
                        context=context,
                        output=best_output,
                    )

                handled_control = _handle_control_call(
                    call=call,
                    context=context,
                    catalog=catalog,
                    event=event,
                )
                if handled_control is not None:
                    outcome, answer, reason, output = handled_control
                    if outcome is not None:
                        if output is not None:
                            best_output = output
                        if answer:
                            best_answer = answer
                        return _result(
                            run_id=run_id,
                            outcome=outcome,
                            answer=best_answer,
                            reason=reason,
                            model_calls=model_calls,
                            tool_calls=tool_calls,
                            total_ms=elapsed_seconds() * 1000,
                            usage=current_usage(),
                            events=events,
                            context=context,
                            output=best_output,
                        )
                    continue

                tool = catalog.get_exposed(call.name)
                if tool is None:
                    output = ToolOutput(
                        status="error",
                        content=f"Tool '{call.name}' is not exposed. Use discover_tools first.",
                    )
                    if (
                        _add_feedback(
                            context, event, call.name, "unexposed tool", output
                        )
                        is None
                    ):
                        return exhausted_by_context("context budget exhausted")
                    repeated_tool_failures += 1
                    if repeated_tool_failures >= 2:
                        return _blocked_after_failures(
                            run_id,
                            best_answer,
                            model_calls,
                            tool_calls,
                            elapsed_seconds,
                            current_usage,
                            events,
                            context,
                            best_output,
                        )
                    continue

                validation_error = _validate_arguments(tool.parameters, call.arguments)
                if validation_error is not None:
                    output = ToolOutput(status="error", content=validation_error)
                    if (
                        _add_feedback(
                            context, event, tool.name, "invalid arguments", output
                        )
                        is None
                    ):
                        return exhausted_by_context("context budget exhausted")
                    repeated_tool_failures += 1
                    if repeated_tool_failures >= 2:
                        return _blocked_after_failures(
                            run_id,
                            best_answer,
                            model_calls,
                            tool_calls,
                            elapsed_seconds,
                            current_usage,
                            events,
                            context,
                            best_output,
                        )
                    continue

                if tool.requires_approval:
                    output = ToolOutput(
                        status="blocked",
                        content=f"Tool '{tool.name}' requires approval before execution.",
                    )
                    if (
                        _add_feedback(
                            context, event, tool.name, "approval required", output
                        )
                        is None
                    ):
                        return exhausted_by_context("context budget exhausted")
                    return _result(
                        run_id=run_id,
                        outcome="needs_user_input",
                        answer=best_answer,
                        reason=f"Tool '{tool.name}' requires approval.",
                        model_calls=model_calls,
                        tool_calls=tool_calls,
                        total_ms=elapsed_seconds() * 1000,
                        usage=current_usage(),
                        events=events,
                        context=context,
                        output=best_output,
                    )

                tool_calls += 1
                tool_start = self._clock()
                usage_before_tool = current_usage()
                tool_timeout = (
                    self._policy.tool_timeout_seconds
                    if self._policy.duration_mode == "soft"
                    else remaining_seconds()
                )
                operation_deadline = self._clock() + tool_timeout
                try:
                    execution_context = ExecutionContext(
                        run_id=run_id,
                        task=task,
                        remaining_seconds=tool_timeout,
                        remaining_tokens=_remaining_tokens(
                            self._policy, usage_before_tool
                        ),
                        cancelled=lambda deadline=operation_deadline: (
                            self._cancelled()
                            or (
                                self._clock() >= deadline
                                if self._policy.duration_mode == "soft"
                                else remaining_seconds() <= 0
                            )
                        ),
                    )
                    output = _execute_tool_with_timeout(
                        tool=tool,
                        arguments=call.arguments,
                        context=execution_context,
                        timeout=tool_timeout,
                    )
                    repeated_tool_failures = (
                        0 if output.status != "error" else repeated_tool_failures + 1
                    )
                except TimeoutError:
                    # The worker thread can keep running after this timeout.
                    # Do not continue the harness or accept late answers.
                    output = ToolOutput(
                        status="error",
                        content=(
                            f"Tool '{tool.name}' timed out. It may still be "
                            "running in the background."
                        ),
                        receipt={"timed_out_may_still_run": True},
                    )
                    ref = _add_feedback(
                        context,
                        event,
                        tool.name,
                        str(call.arguments.get("objective", task)),
                        output,
                    )
                    event(
                        "tool_timeout",
                        {
                            "tool": tool.name,
                            "ref": ref,
                            "timed_out_may_still_run": True,
                            "duration_ms": max(self._clock() - tool_start, 0) * 1000,
                            "usage_before": usage_before_tool.model_dump(),
                            "usage_after": current_usage().model_dump(),
                        },
                    )
                    if ref is None:
                        return exhausted_by_context("context budget exhausted")
                    return _result(
                        run_id=run_id,
                        outcome=("cancelled" if self._cancelled() else "blocked")
                        if self._policy.duration_mode == "soft"
                        else "budget_exhausted",
                        answer=best_answer,
                        reason=f"Tool '{tool.name}' timed out.",
                        model_calls=model_calls,
                        tool_calls=tool_calls,
                        total_ms=elapsed_seconds() * 1000,
                        usage=current_usage(),
                        events=events,
                        context=context,
                        output=best_output,
                    )
                except Exception as e:
                    repeated_tool_failures += 1
                    output = ToolOutput(
                        status="error",
                        content=f"Tool '{tool.name}' failed: {_safe_error(e)}",
                    )

                ref = _add_feedback(
                    context,
                    event,
                    tool.name,
                    str(call.arguments.get("objective", task)),
                    output,
                )
                if ref is None:
                    return exhausted_by_context("context budget exhausted")
                if output.answer:
                    best_answer = output.answer
                    best_output = output
                event(
                    "tool_call",
                    {
                        "tool": tool.name,
                        "ref": ref,
                        "status": output.status,
                        "duration_ms": max(self._clock() - tool_start, 0) * 1000,
                        "usage_before": usage_before_tool.model_dump(),
                        "usage_after": current_usage().model_dump(),
                    },
                )

                stop = _budget_stop(
                    policy=self._policy,
                    usage=current_usage(),
                    model_calls=model_calls,
                    tool_calls=tool_calls,
                    elapsed_seconds=elapsed_seconds(),
                    cancelled=self._cancelled(),
                    before_work=False,
                )
                if stop is not None:
                    return _result(
                        run_id=run_id,
                        outcome=stop[0],
                        answer=best_answer,
                        reason=stop[1],
                        model_calls=model_calls,
                        tool_calls=tool_calls,
                        total_ms=elapsed_seconds() * 1000,
                        usage=current_usage(),
                        events=events,
                        context=context,
                        output=best_output,
                    )

                if repeated_tool_failures >= 2:
                    return _blocked_after_failures(
                        run_id,
                        best_answer,
                        model_calls,
                        tool_calls,
                        elapsed_seconds,
                        current_usage,
                        events,
                        context,
                        best_output,
                    )


def _control_definition(
    name: str,
    description: str,
    parameters: dict[str, Any],
) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": parameters,
        },
    }


def _control_definitions() -> list[dict[str, Any]]:
    return [
        _control_definition(
            CONTROL_DISCOVER_TOOLS,
            "Find relevant tools by name and description.",
            _control_schema(CONTROL_DISCOVER_TOOLS),
        ),
        _control_definition(
            CONTROL_READ_RESULT,
            "Read a bounded slice of an earlier tool result.",
            _control_schema(CONTROL_READ_RESULT),
        ),
        _control_definition(
            CONTROL_FINISH_TASK,
            "Finish with an explicit outcome, answer, and optional answer_ref.",
            _control_schema(CONTROL_FINISH_TASK),
        ),
    ]


def _control_schema(name: str) -> dict[str, Any]:
    if name == CONTROL_DISCOVER_TOOLS:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 10},
            },
            "required": ["query"],
            "additionalProperties": False,
        }
    if name == CONTROL_READ_RESULT:
        return {
            "type": "object",
            "properties": {
                "result_ref": {"type": "string"},
                "offset": {"type": "integer", "minimum": 0},
                "max_chars": {"type": "integer", "minimum": 1, "maximum": 20000},
            },
            "required": ["result_ref"],
            "additionalProperties": False,
        }
    if name == CONTROL_FINISH_TASK:
        return {
            "type": "object",
            "properties": {
                "outcome": {
                    "type": "string",
                    "enum": sorted(FINISH_OUTCOMES),
                },
                "answer": {"type": "string"},
                "answer_ref": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["outcome"],
            "additionalProperties": False,
        }
    raise ValueError(f"Unknown control tool: {name}")


def _rough_token_count(text: str) -> int:
    return max((len(text) + 3) // 4, 1)


def _remaining_tokens(policy: HarnessPolicy, usage: UsageSnapshot) -> int:
    return max(policy.max_total_tokens - usage.total_tokens, 0)


def _decision_output_tokens(policy: HarnessPolicy) -> int | None:
    return policy.decision_max_output_tokens or policy.max_output_tokens


def _render_context_for_model(
    *,
    task: str,
    context: ContextState,
    catalog: ToolCatalog,
    policy: HarnessPolicy,
    usage: UsageSnapshot,
    remaining_seconds: float,
    remaining_tokens: int,
    tools: list[dict[str, Any]],
    token_counter: Callable[[str], int],
) -> str:
    output_reserve = min(_decision_output_tokens(policy) or 1, remaining_tokens)
    prompt_ceiling = min(
        (policy.max_context_tokens or remaining_tokens) - output_reserve,
        remaining_tokens - output_reserve,
    )
    if prompt_ceiling < 1:
        raise ContextBudgetExceeded("Prompt overhead exceeds the context budget")

    empty_context = json.dumps({"receipts": [], "results": []}, sort_keys=True)
    empty_wrapper = _decision_context(
        task=task,
        context=empty_context,
        catalog=catalog,
        policy=policy,
        usage=usage,
        remaining_seconds=remaining_seconds,
        remaining_tokens=remaining_tokens,
    )
    overhead = _estimate_runner_prompt_tokens(
        token_counter=token_counter,
        task=task,
        context=empty_wrapper,
        tools=tools,
        remaining_seconds=remaining_seconds,
        remaining_tokens=remaining_tokens,
        max_output_tokens=_decision_output_tokens(policy),
    )
    safety_tokens = min(
        PROMPT_BUDGET_SAFETY_TOKENS,
        max((prompt_ceiling - overhead) // 10, 0),
    )
    budget = prompt_ceiling - overhead - safety_tokens
    if budget < 1:
        raise ContextBudgetExceeded("Prompt overhead exceeds the context budget")

    best_context: str | None = None
    low = 1
    high = budget
    while low <= high:
        candidate_budget = (low + high) // 2
        try:
            rendered_context = context.render(candidate_budget)
        except ContextBudgetExceeded:
            low = candidate_budget + 1
            continue

        wrapper = _decision_context(
            task=task,
            context=rendered_context,
            catalog=catalog,
            policy=policy,
            usage=usage,
            remaining_seconds=remaining_seconds,
            remaining_tokens=remaining_tokens,
        )
        estimated_prompt_tokens = _estimate_runner_prompt_tokens(
            token_counter=token_counter,
            task=task,
            context=wrapper,
            tools=tools,
            remaining_seconds=remaining_seconds,
            remaining_tokens=remaining_tokens,
            max_output_tokens=_decision_output_tokens(policy),
        )
        if estimated_prompt_tokens <= prompt_ceiling:
            best_context = rendered_context
            low = candidate_budget + 1
            continue

        high = candidate_budget - 1

    if best_context is None:
        raise ContextBudgetExceeded("Prompt overhead exceeds the context budget")
    return best_context


def _estimate_runner_prompt_tokens(
    *,
    token_counter: Callable[[str], int],
    task: str,
    context: str,
    tools: list[dict[str, Any]],
    remaining_seconds: float,
    remaining_tokens: int,
    max_output_tokens: int | None,
) -> int:
    return estimate_decision_prompt_tokens(
        token_counter=token_counter,
        task=task,
        context=context,
        tools=tools,
        remaining_seconds=remaining_seconds,
        remaining_tokens=remaining_tokens,
        max_output_tokens=max_output_tokens,
    )


def _decision_context(
    *,
    task: str,
    context: str,
    catalog: ToolCatalog,
    policy: HarnessPolicy,
    usage: UsageSnapshot,
    remaining_seconds: float,
    remaining_tokens: int,
) -> str:
    return json.dumps(
        {
            "task": task,
            "current_turn_state": json.loads(context),
            "tool_catalog": catalog.summary(),
            "budget": {
                "remaining_seconds": remaining_seconds,
                "remaining_tokens": remaining_tokens,
                "max_model_calls": policy.max_model_calls,
                "max_tool_calls": policy.max_tool_calls,
                "max_output_tokens": _decision_output_tokens(policy),
                **(
                    {
                        "duration_guidance": {
                            "target_seconds": policy.max_elapsed_seconds,
                            "elapsed_seconds": policy.max_elapsed_seconds
                            - remaining_seconds,
                            "target_remaining_seconds": remaining_seconds,
                            "instruction": "Time is a soft target, not a deadline. Remaining seconds may be negative. Finish promptly when supported; continue useful work when needed. Passing the target does not prevent another action. Resource limits remain enforced.",
                        }
                    }
                    if policy.duration_mode == "soft"
                    else {}
                ),
            },
            "usage": usage.model_dump(),
            "contracts": {
                "followup_objective": (
                    "Pass a specific current objective to tools. Keep it distinct "
                    "from the overall task."
                ),
                "finish": (
                    "Finish with an explicit outcome. Use answer_ref to reuse a "
                    "tool answer without another synthesis pass."
                ),
                **(
                    {
                        "completion_only": (
                            "The completion reserve is active. Do not call information "
                            "tools again. Write the best supported final answer from the "
                            "evidence already collected and state any material gap."
                        )
                    }
                    if policy.completion_reserve_tokens > 0
                    and remaining_tokens <= policy.completion_reserve_tokens
                    else {}
                ),
            },
        },
        sort_keys=True,
    )


def _budget_stop(
    *,
    policy: HarnessPolicy,
    usage: UsageSnapshot,
    model_calls: int,
    tool_calls: int,
    elapsed_seconds: float,
    cancelled: bool,
    before_work: bool,
) -> tuple[Outcome, str] | None:
    if cancelled:
        return "cancelled", "run was cancelled"
    if policy.duration_mode == "hard" and elapsed_seconds >= policy.max_elapsed_seconds:
        return "budget_exhausted", "elapsed time budget exhausted"
    if usage.total_tokens >= policy.max_total_tokens:
        return "budget_exhausted", "token budget exhausted"
    if policy.max_cost_cents is not None and usage.unpriced_calls:
        return "blocked", "cost budget is configured but usage contains unpriced calls"
    if policy.max_cost_cents is not None and usage.cost_cents >= policy.max_cost_cents:
        return "budget_exhausted", "cost budget exhausted"
    if before_work and model_calls >= policy.max_model_calls:
        return "budget_exhausted", "model call budget exhausted"
    if before_work and tool_calls >= policy.max_tool_calls:
        return "budget_exhausted", "tool call budget exhausted"
    return None


def _budget_stop_after_model(
    *,
    policy: HarnessPolicy,
    usage: UsageSnapshot,
    elapsed_seconds: float,
    cancelled: bool,
) -> tuple[Outcome, str] | None:
    return _budget_stop(
        policy=policy,
        usage=usage,
        model_calls=0,
        tool_calls=0,
        elapsed_seconds=elapsed_seconds,
        cancelled=cancelled,
        before_work=False,
    )


def _finish_from_decision(
    decision: ModelDecision,
    context: ContextState,
) -> tuple[Outcome, str, str, ToolOutput | None] | None:
    if decision.outcome is None:
        return None
    if decision.calls:
        return None
    return _finish(
        outcome=decision.outcome,
        answer=decision.answer,
        answer_ref=decision.answer_ref,
        reason=decision.reason,
        context=context,
    )


def _handle_control_call(
    *,
    call: ToolInvocation,
    context: ContextState,
    catalog: ToolCatalog,
    event: Callable[[str, dict[str, Any] | None], None],
) -> tuple[Outcome | None, str, str, ToolOutput | None] | None:
    if call.name in {CONTROL_DISCOVER_TOOLS, CONTROL_READ_RESULT, CONTROL_FINISH_TASK}:
        validation_error = _validate_arguments(
            _control_schema(call.name),
            call.arguments,
        )
        if validation_error is not None:
            output = ToolOutput(status="error", content=validation_error)
            if (
                _add_feedback(
                    context, event, call.name, "invalid control arguments", output
                )
                is None
            ):
                return "budget_exhausted", "", "context budget exhausted", None
            return None, "", "", None

    if call.name == CONTROL_DISCOVER_TOOLS:
        query = str(call.arguments.get("query", ""))[:MAX_CONTROL_QUERY_CHARS]
        limit = _int_arg(call.arguments.get("limit", 3), default=3)
        discovered = catalog.discover(query, limit=limit)
        output = ToolOutput(
            status="success",
            content=json.dumps(
                {
                    "discovered": discovered,
                    "exposed_tools": _exposed_names(catalog),
                },
                sort_keys=True,
            ),
        )
        if _add_feedback(context, event, call.name, query, output) is None:
            return "budget_exhausted", "", "context budget exhausted", None
        return None, "", "", None

    if call.name == CONTROL_READ_RESULT:
        ref = str(call.arguments.get("result_ref", call.arguments.get("ref", "")))
        offset = _int_arg(call.arguments.get("offset", 0), default=0)
        max_chars = _int_arg(call.arguments.get("max_chars", 4000), default=4000)
        try:
            payload = context.read(ref, offset, max_chars)
            output = ToolOutput(
                status="success", content=json.dumps(payload, sort_keys=True)
            )
        except KeyError:
            output = ToolOutput(status="error", content=f"Unknown result ref '{ref}'.")
        if _add_feedback(context, event, call.name, ref, output) is None:
            return "budget_exhausted", "", "context budget exhausted", None
        return None, "", "", None

    if call.name == CONTROL_FINISH_TASK:
        outcome = call.arguments.get("outcome")
        if outcome not in FINISH_OUTCOMES:
            output = ToolOutput(
                status="error", content="finish_task outcome is invalid."
            )
            if (
                _add_feedback(context, event, call.name, "invalid finish", output)
                is None
            ):
                return "budget_exhausted", "", "context budget exhausted", None
            return None, "", "", None
        return _finish(
            outcome=outcome,
            answer=str(call.arguments.get("answer", "")),
            answer_ref=call.arguments.get("answer_ref"),
            reason=str(call.arguments.get("reason", "")),
            context=context,
        )

    return None


def _finish(
    *,
    outcome: Outcome,
    answer: str,
    answer_ref: Any,
    reason: str,
    context: ContextState,
) -> tuple[Outcome, str, str, ToolOutput | None]:
    referenced_output: ToolOutput | None = None
    if answer_ref:
        try:
            referenced_output = context.output(str(answer_ref))
        except KeyError:
            return (
                "blocked",
                "",
                f"finish referenced unknown result '{answer_ref}'",
                None,
            )
        if referenced_output.answer:
            answer = referenced_output.answer

    if outcome == "completed" and not answer.strip():
        return (
            "blocked",
            "",
            "completed outcome requires answer or answer_ref",
            referenced_output,
        )
    if outcome == "completed" and referenced_output is not None:
        receipt = _receipt_for_ref(context, str(answer_ref))
        if referenced_output.status != "success":
            return (
                "blocked",
                "",
                "completed outcome referenced non-success tool output",
                referenced_output,
            )
        # The top-level flag means stored evidence was clipped. A nested
        # tool-receipt flag only means verbose diagnostics were compacted.
        if bool(receipt.get("truncated")):
            return (
                "blocked",
                "",
                "completed outcome referenced truncated tool output",
                referenced_output,
            )

    if answer and not answer_ref:
        citations = context.citation_mapping
        referenced_output = ToolOutput(
            content="",
            answer=answer,
            citation_mapping=citations,
            document_ids=list(dict.fromkeys(citations.values())),
        )
    return outcome, answer, reason, referenced_output


def _validate_arguments(
    schema: dict[str, Any],
    arguments: dict[str, Any],
) -> str | None:
    ref_error = _find_external_ref(schema)
    if ref_error is not None:
        return ref_error
    try:
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(arguments)
    except SchemaError:
        return "Tool parameter schema is invalid."
    except ValidationError as e:
        return f"Tool arguments failed validation: {e.message}"
    return None


def _find_external_ref(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in ("$ref", "$dynamicRef", "$recursiveRef"):
            ref = value.get(key)
            if isinstance(ref, str) and ref and not ref.startswith("#"):
                return f"Tool parameter schema contains an external {key}."
        for child in value.values():
            found = _find_external_ref(child)
            if found is not None:
                return found
    if isinstance(value, list):
        for child in value:
            found = _find_external_ref(child)
            if found is not None:
                return found
    return None


def _add_feedback(
    context: ContextState,
    event: Callable[[str, dict[str, Any] | None], None],
    tool_name: str,
    objective: str,
    output: ToolOutput,
) -> str | None:
    try:
        ref = context.add(tool_name, objective, output)
    except ContextBudgetExceeded:
        compact_output = ToolOutput(
            status="error",
            content="Tool result was too large to retain in context.",
            receipt=output.receipt,
            document_ids=output.document_ids,
            citation_mapping=output.citation_mapping,
        )
        try:
            ref = context.add(tool_name, objective, compact_output)
        except ContextBudgetExceeded as e:
            event(
                "context_add_failed",
                {
                    "tool": tool_name,
                    "status": output.status,
                    "reason": str(e),
                },
            )
            return None
    event(
        "context_add",
        {
            "ref": ref,
            "tool": tool_name,
            "status": output.status,
            "document_ids": output.document_ids,
        },
    )
    return ref


def _execute_tool_with_timeout(
    *,
    tool: RegisteredTool,
    arguments: dict[str, Any],
    context: ExecutionContext,
    timeout: float,
) -> ToolOutput:
    results = run_functions_tuples_in_parallel(
        [(tool.execute, (arguments, context))],
        max_workers=1,
        timeout=max(timeout, 0.001),
    )
    output = results[0]
    if isinstance(output, ToolOutput):
        return output
    raise TypeError(f"Tool '{tool.name}' returned an invalid output")


def _has_finish_call(calls: list[ToolInvocation]) -> bool:
    return any(call.name == CONTROL_FINISH_TASK for call in calls)


def _int_arg(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _exposed_names(catalog: ToolCatalog) -> list[str]:
    summary = catalog.summary()
    return [
        *summary.get("pinned_tools", []),
        *summary.get("loaded_tools", []),
    ]


def _receipt_for_ref(context: ContextState, result_ref: str) -> dict[str, Any]:
    for receipt in context.receipts:
        if receipt.get("result_ref") == result_ref:
            return receipt
    return {}


def _safe_error(e: Exception) -> str:
    text = str(e) or e.__class__.__name__
    return text[:MAX_ERROR_CHARS]


def _blocked_after_failures(
    run_id: str,
    best_answer: str,
    model_calls: int,
    tool_calls: int,
    elapsed_seconds: Callable[[], float],
    current_usage: Callable[[], UsageSnapshot],
    events: list[HarnessEvent],
    context: ContextState,
    best_output: ToolOutput | None,
) -> HarnessResult:
    return _result(
        run_id=run_id,
        outcome="blocked",
        answer=best_answer,
        reason="repeated tool failures",
        model_calls=model_calls,
        tool_calls=tool_calls,
        total_ms=elapsed_seconds() * 1000,
        usage=current_usage(),
        events=events,
        context=context,
        output=best_output,
    )


def _result(
    *,
    run_id: str,
    outcome: Outcome,
    answer: str,
    reason: str,
    model_calls: int,
    tool_calls: int,
    total_ms: float,
    usage: UsageSnapshot,
    events: list[HarnessEvent],
    context: ContextState,
    output: ToolOutput | None,
) -> HarnessResult:
    return HarnessResult(
        run_id=run_id,
        outcome=outcome,
        answer=answer,
        reason=reason,
        model_calls=model_calls,
        tool_calls=tool_calls,
        total_ms=total_ms,
        usage=usage,
        events=events,
        receipts=context.receipts,
        document_ids=output.document_ids if output is not None else [],
        citation_mapping=output.citation_mapping if output is not None else {},
    )
