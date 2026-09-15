from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any, cast

from onyx.agents.v2.models import (
    HarnessPolicy,
    ModelDecision,
    ToolInvocation,
    UsageSnapshot,
)
from onyx.llm.cost import compute_cost_cents, get_model_price_per_million
from onyx.llm.interfaces import (
    LLM,
    LanguageModelInput,
    LLMConfig,
    LLMUserIdentity,
    ReasoningEffort,
    ToolChoice,
)
from onyx.llm.model_capabilities import get_llm_max_output_tokens, get_model_map
from onyx.llm.model_response import ModelResponse, ModelResponseStream, Usage
from onyx.llm.models import SystemMessage, ToolChoiceOptions, UserMessage
from onyx.prompts.harness_v2 import AGENT_SYSTEM_PROMPT
from onyx.tracing.flows import LLMFlow
from onyx.tracing.llm_utils import llm_generation_span, record_llm_response

_FINISH_TASK_TOOL_NAME = "finish_task"


class BudgetExceeded(RuntimeError):
    pass


class TaskCancelled(RuntimeError):
    pass


class ReservationWaitTimeout(TimeoutError):
    pass


@dataclass(frozen=True)
class _Reservation:
    prompt_tokens: int
    max_output_tokens: int
    token_reservation: int
    cost_reservation_cents: float
    cost_estimated: bool
    llm_config: LLMConfig


class BudgetLedger:
    def __init__(
        self,
        policy: HarnessPolicy,
        token_counter: Callable[[str], int],
        clock: Callable[[], float] = time.monotonic,
        cancelled: Callable[[], bool] = lambda: False,
        started_at: float | None = None,
    ) -> None:
        self._policy = policy
        self._token_counter = token_counter
        self._clock = clock
        self._cancelled = cancelled
        self._started_at = clock() if started_at is None else started_at
        self._lock = threading.Condition()
        self._used_tokens = 0
        self._reserved_tokens = 0
        self._cost_cents = 0.0
        self._reserved_cost_cents = 0.0
        self._unpriced_calls = 0
        self._calls = 0

    def snapshot(self) -> UsageSnapshot:
        with self._lock:
            return UsageSnapshot(
                total_tokens=self._used_tokens,
                cost_cents=self._cost_cents,
                unpriced_calls=self._unpriced_calls,
                calls=self._calls,
            )

    def remaining_seconds(self) -> float:
        return max(self._policy.max_elapsed_seconds - self._elapsed_seconds(), 0.0)

    def operation_timeout_seconds(self) -> float:
        if self._policy.duration_mode == "soft":
            return self._policy.model_timeout_seconds
        return self.remaining_seconds()

    def _raise_if_cancelled(self) -> None:
        if self._cancelled():
            if self._policy.duration_mode == "soft":
                raise TaskCancelled("Task was cancelled")
            raise BudgetExceeded("Task was cancelled")

    def remaining_tokens(self) -> int:
        with self._lock:
            return max(
                self._policy.max_total_tokens
                - self._used_tokens
                - self._reserved_tokens,
                0,
            )

    def estimate_tokens(
        self,
        prompt: LanguageModelInput,
        tools: list[dict] | None,
    ) -> int:
        return self._token_counter(
            _json({"messages": _dump_prompt(prompt), "tools": tools})
        )

    def reserve_llm_call(
        self,
        *,
        prompt_tokens: int,
        requested_max_output_tokens: int | None,
        llm_config: LLMConfig,
        wait_for_capacity: bool = False,
        protected_tokens: int = 0,
    ) -> _Reservation:
        self._raise_if_cancelled()

        max_context_tokens = llm_config.max_input_tokens
        if prompt_tokens > max_context_tokens:
            raise BudgetExceeded("LLM prompt exceeds the per-call context budget")

        output_limit = get_llm_max_output_tokens(
            get_model_map(), llm_config.model_name, llm_config.model_provider
        )
        if self._policy.max_output_tokens is not None:
            output_limit = min(output_limit, self._policy.max_output_tokens)
        max_output_tokens = min(
            requested_max_output_tokens or output_limit, output_limit
        )
        if max_output_tokens < 1:
            raise BudgetExceeded("No output token budget remains")

        wait_started = self._clock()
        with self._lock:
            while True:
                self._raise_if_cancelled()
                remaining_seconds = self.remaining_seconds()
                if self._policy.duration_mode == "soft":
                    remaining_seconds = self._policy.reservation_wait_seconds - (
                        self._clock() - wait_started
                    )
                    if remaining_seconds <= 0:
                        raise ReservationWaitTimeout(
                            "Reservation capacity wait timed out"
                        )
                elif remaining_seconds <= 0:
                    raise BudgetExceeded("Task time budget is exhausted")
                if self._calls >= self._policy.max_llm_calls:
                    raise BudgetExceeded("Task LLM-call budget is exhausted")

                unreserved_tokens = (
                    self._policy.max_total_tokens
                    - self._used_tokens
                    - prompt_tokens
                    - max(0, protected_tokens)
                )
                output_tokens = min(
                    max_output_tokens,
                    unreserved_tokens,
                    llm_config.max_input_tokens - prompt_tokens,
                )
                if output_tokens < 1:
                    raise BudgetExceeded("Task token budget is exhausted")
                if unreserved_tokens - self._reserved_tokens < output_tokens:
                    if wait_for_capacity and self._reserved_tokens:
                        self._lock.wait(min(0.1, remaining_seconds))
                        continue
                    raise BudgetExceeded("Task token budget is exhausted")

                cost_reservation_cents, cost_estimated = _estimate_cost_cents(
                    llm_config,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=output_tokens,
                )
                if self._policy.max_cost_cents is not None:
                    if cost_estimated:
                        raise BudgetExceeded(
                            "Task cost budget cannot be enforced for unpriced model"
                        )
                    projected_cost = (
                        self._cost_cents
                        + self._reserved_cost_cents
                        + cost_reservation_cents
                    )
                    if projected_cost > self._policy.max_cost_cents:
                        if wait_for_capacity and self._reserved_cost_cents:
                            self._lock.wait(min(0.1, remaining_seconds))
                            continue
                        raise BudgetExceeded("Task cost budget is exhausted")
                break

            token_reservation = prompt_tokens + output_tokens
            self._reserved_tokens += token_reservation
            self._reserved_cost_cents += cost_reservation_cents
            self._calls += 1

            return _Reservation(
                prompt_tokens=prompt_tokens,
                max_output_tokens=output_tokens,
                token_reservation=token_reservation,
                cost_reservation_cents=cost_reservation_cents,
                cost_estimated=cost_estimated,
                llm_config=llm_config,
            )

    def record_success(self, reservation: _Reservation, usage: Usage | None) -> None:
        usage_tokens = (
            usage.total_tokens if usage is not None else reservation.token_reservation
        )
        prompt_tokens = (
            usage.prompt_tokens if usage is not None else reservation.prompt_tokens
        )
        completion_tokens = (
            usage.completion_tokens
            if usage is not None
            else reservation.max_output_tokens
        )
        cache_read_tokens = usage.cache_read_input_tokens if usage is not None else 0
        cache_creation_tokens = (
            usage.cache_creation_input_tokens if usage is not None else 0
        )

        cost_cents, cost_estimated = _estimate_cost_cents(
            config=reservation.llm_config,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_creation_tokens=cache_creation_tokens,
        )
        self._release_reservation(
            reservation,
            used_tokens=usage_tokens,
            cost_cents=cost_cents,
            unpriced=usage is None or cost_estimated,
        )

    def record_failure(self, reservation: _Reservation) -> None:
        self._release_reservation(
            reservation,
            used_tokens=reservation.token_reservation,
            cost_cents=0.0,
            unpriced=True,
        )

    def raise_if_exhausted(self) -> None:
        with self._lock:
            if self._policy.duration_mode == "soft":
                self._raise_if_cancelled()
            if (
                self._policy.duration_mode == "hard"
                and self._elapsed_seconds() > self._policy.max_elapsed_seconds
            ):
                raise BudgetExceeded("Task time budget is exhausted")
            if self._used_tokens > self._policy.max_total_tokens:
                raise BudgetExceeded("Task token budget is exhausted")
            if (
                self._policy.max_cost_cents is not None
                and self._cost_cents > self._policy.max_cost_cents
            ):
                raise BudgetExceeded("Task cost budget is exhausted")

    def _release_reservation(
        self,
        reservation: _Reservation,
        *,
        used_tokens: int,
        cost_cents: float,
        unpriced: bool,
    ) -> None:
        with self._lock:
            self._reserved_tokens = max(
                self._reserved_tokens - reservation.token_reservation,
                0,
            )
            self._reserved_cost_cents = max(
                self._reserved_cost_cents - reservation.cost_reservation_cents,
                0.0,
            )
            self._used_tokens += used_tokens
            self._cost_cents += cost_cents
            if unpriced:
                self._unpriced_calls += 1
            self._lock.notify_all()

    def _elapsed_seconds(self) -> float:
        return self._clock() - self._started_at


class BudgetedLLM(LLM):
    def __init__(
        self,
        inner: LLM,
        ledger: BudgetLedger,
        *,
        max_output_tokens: int | None = None,
        min_output_tokens: int | None = None,
        protected_tokens: int = 0,
    ) -> None:
        self._inner = inner
        self._ledger = ledger
        self._max_output_tokens = max_output_tokens
        self._min_output_tokens = min_output_tokens
        self.protected_tokens = max(0, protected_tokens)

    def with_token_reserve(self, tokens: int) -> BudgetedLLM:
        return BudgetedLLM(
            self._inner,
            self._ledger,
            max_output_tokens=self._max_output_tokens,
            min_output_tokens=self._min_output_tokens,
            protected_tokens=tokens,
        )

    def available_tokens(self) -> int:
        return max(0, self._ledger.remaining_tokens() - self.protected_tokens)

    @property
    def config(self) -> LLMConfig:
        return self._inner.config

    def invoke(
        self,
        prompt: LanguageModelInput,
        tools: list[dict] | None = None,
        tool_choice: ToolChoice | None = None,
        structured_response_format: dict | None = None,
        timeout_override: int | None = None,
        max_tokens: int | None = None,
        reasoning_effort: ReasoningEffort = ReasoningEffort.AUTO,
        user_identity: LLMUserIdentity | None = None,
        total_timeout_override: float | None = None,
    ) -> ModelResponse:
        # Reasoning consumes the same output allowance as visible text. Apply
        # the opt-in experiment floor before reservation so accounting remains
        # accurate even for legacy selection calls that request only 256 tokens.
        if self._min_output_tokens is not None:
            max_tokens = max(
                max_tokens or self._min_output_tokens, self._min_output_tokens
            )
        if self._max_output_tokens is not None:
            max_tokens = min(
                max_tokens or self._max_output_tokens, self._max_output_tokens
            )
        prompt_tokens = self._ledger.estimate_tokens(prompt, tools)
        reservation = self._ledger.reserve_llm_call(
            prompt_tokens=prompt_tokens,
            requested_max_output_tokens=max_tokens,
            llm_config=self._inner.config,
            wait_for_capacity=True,
            protected_tokens=self.protected_tokens,
        )
        remaining_seconds = self._ledger.operation_timeout_seconds()
        if remaining_seconds <= 0:
            self._ledger.record_failure(reservation)
            raise BudgetExceeded("Task time budget is exhausted")

        call_timeout = remaining_seconds
        if total_timeout_override is not None:
            call_timeout = min(total_timeout_override, call_timeout)

        with llm_generation_span(
            self._inner,
            flow=LLMFlow.AGENT_HARNESS_V2_DECISION,
            input_messages=prompt,
            tools=tools,
        ) as span:
            try:
                response = self._inner.invoke(
                    prompt=prompt,
                    tools=tools,
                    tool_choice=tool_choice,
                    structured_response_format=structured_response_format,
                    timeout_override=timeout_override,
                    max_tokens=reservation.max_output_tokens,
                    reasoning_effort=reasoning_effort,
                    user_identity=user_identity,
                    total_timeout_override=call_timeout,
                )
            except Exception:
                self._ledger.record_failure(reservation)
                raise

            self._ledger.record_success(reservation, response.usage)
            self._ledger.raise_if_exhausted()
            record_llm_response(span, response)
            return response

    def stream(
        self,
        prompt: LanguageModelInput,
        tools: list[dict] | None = None,
        tool_choice: ToolChoice | None = None,
        structured_response_format: dict | None = None,
        timeout_override: int | None = None,
        max_tokens: int | None = None,
        reasoning_effort: ReasoningEffort = ReasoningEffort.AUTO,
        user_identity: LLMUserIdentity | None = None,
    ) -> Iterator[ModelResponseStream]:
        raise NotImplementedError("BudgetedLLM does not support streaming yet")


class OnyxDecisionModel:
    def __init__(
        self,
        llm: LLM,
        user_id: str | None = None,
        reasoning_effort: ReasoningEffort = ReasoningEffort.LOW,
        completion_llm: LLM | None = None,
        minimal_decision_llm: LLM | None = None,
        operation_timeout_seconds: float | None = None,
        source_cards: bool = False,
    ) -> None:
        self._llm = llm
        self._user_id = user_id
        self._reasoning_effort = reasoning_effort
        self._completion_llm = completion_llm
        self._minimal_decision_llm = minimal_decision_llm
        self._operation_timeout_seconds = operation_timeout_seconds
        self._source_cards = source_cards

    def decide(
        self,
        *,
        task: str,
        context: str,
        tools: list[dict[str, Any]],
        remaining_seconds: float,
        remaining_tokens: int,
        max_output_tokens: int | None,
    ) -> ModelDecision:
        if self._source_cards:
            from onyx.agents.v2.evidence_context import source_card_context

            context = source_card_context(context)
        _validate_unique_tool_names(tools)
        compact_context = (
            compact_completion_context(context) if self._completion_llm else None
        )
        use_minimal = compact_context is not None and self._completion_llm is not None
        selected_llm = (
            self._completion_llm
            if use_minimal
            else self._minimal_decision_llm or self._llm
        )
        assert selected_llm is not None
        prompt = build_decision_prompt(
            task=task,
            context=compact_context if compact_context is not None else context,
            tools=tools,
            remaining_seconds=remaining_seconds,
            remaining_tokens=remaining_tokens,
            max_output_tokens=max_output_tokens,
        )
        response = selected_llm.invoke(
            prompt=prompt,
            tools=tools,
            tool_choice=ToolChoiceOptions.AUTO,
            max_tokens=max_output_tokens,
            # The dedicated client's model_kwargs explicitly carry minimal reasoning.
            reasoning_effort=ReasoningEffort.OFF
            if use_minimal or self._minimal_decision_llm is not None
            else self._reasoning_effort,
            user_identity=LLMUserIdentity(user_id=self._user_id),
            total_timeout_override=self._operation_timeout_seconds
            if self._operation_timeout_seconds is not None
            else remaining_seconds,
        )
        return _parse_decision_response(response).model_copy(
            update={
                "decision_mode": "minimal_compact"
                if use_minimal
                else "minimal"
                if self._minimal_decision_llm is not None
                else "standard"
            }
        )


def compact_completion_context(context: str) -> str | None:
    try:
        payload = json.loads(context)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    state = payload.get("current_turn_state")
    if not isinstance(state, dict):
        return None
    results = state.get("results")
    if not isinstance(results, list) or not results:
        return None
    latest = results[0]
    if (
        not isinstance(latest, dict)
        or latest.get("tool_name") != "internal_search"
        or latest.get("status") != "success"
        or not isinstance(latest.get("answer"), str)
        or not latest["answer"].strip()
    ):
        return None
    for result in results:
        if (
            isinstance(result, dict)
            and result.get("tool_name") == "internal_search"
            and result.get("status") == "success"
            and result.get("answer")
        ):
            result.pop("content_preview", None)
            if isinstance(result.get("read_more"), dict):
                result["read_more"]["offset"] = 0
    return _json(payload)


def create_search_llm(llm: LLM, model_name: str | None) -> LLM:
    """Use an approved OpenAI model without reasoning for search."""
    if model_name is None:
        return llm
    from onyx.llm.factory import get_llm

    config = llm.config
    if config.model_provider != "openai" or config.deployment_name:
        raise ValueError("Separate search model currently requires native OpenAI")
    if model_name not in {"gpt-5.6-luna", "gpt-5.6-sol"}:
        raise ValueError(
            "Separate search model currently supports gpt-5.6-luna and gpt-5.6-sol only"
        )
    return get_llm(
        provider=config.model_provider,
        model=model_name,
        deployment_name=None,
        max_input_tokens=config.max_input_tokens,
        api_key=config.api_key,
        api_base=config.api_base,
        api_version=config.api_version,
        custom_config=config.custom_config,
        temperature=config.temperature,
        # The installed Onyx wrapper already emits Sol's required native
        # reasoning={"effort": "none", ...} shape for OFF. Luna is not yet
        # recognized by that capability path, so it still needs the explicit
        # passthrough override.
        model_kwargs=(
            {"reasoning": {"effort": "none"}} if model_name == "gpt-5.6-luna" else {}
        ),
        reasoning_effort_default=ReasoningEffort.OFF,
        reasoning_effort_user_default=ReasoningEffort.OFF,
        reasoning_effort_max=ReasoningEffort.OFF,
    )


def create_minimal_completion_llm(llm: LLM) -> LLM:
    from onyx.llm.factory import get_llm

    config = llm.config
    if config.model_provider != "openai" or not re.fullmatch(
        r"gpt-5-mini(?:-\d{4}-\d{2}-\d{2})?", config.model_name
    ):
        raise ValueError(
            "Minimal completion mode currently supports native OpenAI GPT-5 mini only"
        )
    if config.reasoning_effort_max is ReasoningEffort.OFF:
        raise ValueError("The configured reasoning ceiling prohibits minimal reasoning")
    return get_llm(
        provider=config.model_provider,
        model=config.model_name,
        max_input_tokens=config.max_input_tokens,
        deployment_name=config.deployment_name,
        api_key=config.api_key,
        api_base=config.api_base,
        api_version=config.api_version,
        custom_config=config.custom_config,
        temperature=config.temperature,
        model_kwargs={"reasoning": {"effort": "minimal"}},
        reasoning_effort_default=config.reasoning_effort_default,
        reasoning_effort_user_default=config.reasoning_effort_user_default,
        reasoning_effort_max=config.reasoning_effort_max,
    )


def build_decision_prompt(
    *,
    task: str,
    context: str,
    tools: list[dict[str, Any]],
    remaining_seconds: float,
    remaining_tokens: int,
    max_output_tokens: int | None,
) -> LanguageModelInput:
    return [
        SystemMessage(content=AGENT_SYSTEM_PROMPT),
        UserMessage(
            content=_json(
                {
                    "task": task,
                    "context": context,
                    "budget": {
                        "remaining_seconds": remaining_seconds,
                        "remaining_tokens": remaining_tokens,
                        "max_output_tokens": max_output_tokens,
                    },
                    "tools_provider_list": _tool_summaries(tools),
                }
            )
        ),
    ]


def estimate_decision_prompt_tokens(
    *,
    token_counter: Callable[[str], int],
    task: str,
    context: str,
    tools: list[dict[str, Any]],
    remaining_seconds: float,
    remaining_tokens: int,
    max_output_tokens: int | None,
) -> int:
    prompt = build_decision_prompt(
        task=task,
        context=context,
        tools=tools,
        remaining_seconds=remaining_seconds,
        remaining_tokens=remaining_tokens,
        max_output_tokens=max_output_tokens,
    )
    return token_counter(_json({"messages": _dump_prompt(prompt), "tools": tools}))


def _estimate_cost_cents(
    config: LLMConfig,
    *,
    prompt_tokens: int,
    completion_tokens: int,
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
) -> tuple[float, bool]:
    price = get_model_price_per_million(
        config.model_name,
        config.model_provider,
    )
    cost = compute_cost_cents(
        model=config.model_name,
        provider=config.model_provider,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_creation_tokens=cache_creation_tokens,
    )
    return sum(cost), price.input_per_mtok is None or price.output_per_mtok is None


def _parse_decision_response(response: ModelResponse) -> ModelDecision:
    choice = response.choice
    if choice.finish_reason == "length":
        return ModelDecision(
            outcome="partial",
            answer=response.choice.message.content or "",
            reason="The model hit its output token limit.",
        )

    tool_calls = choice.message.tool_calls or []
    if not tool_calls:
        text = choice.message.content or ""
        if choice.finish_reason == "stop" and text.strip():
            return ModelDecision(outcome="completed", answer=text)
        return ModelDecision(
            outcome="partial",
            answer=text,
            reason="The model returned no final answer."
            if choice.finish_reason == "stop"
            else f"The model stopped with reason '{choice.finish_reason}'.",
        )

    parsed_calls: list[ToolInvocation] = []
    finish_decisions: list[ModelDecision] = []
    for tool_call in tool_calls:
        name = tool_call.function.name
        arguments = tool_call.function.arguments
        if not name or arguments is None:
            return _blocked_decision("The model returned a malformed tool call.")

        try:
            parsed_arguments = json.loads(arguments or "{}")
        except json.JSONDecodeError:
            return _blocked_decision("The model returned invalid tool-call JSON.")
        if not isinstance(parsed_arguments, dict):
            return _blocked_decision("The model returned non-object tool arguments.")

        if name == _FINISH_TASK_TOOL_NAME:
            finish_decisions.append(_finish_decision(parsed_arguments))
        else:
            parsed_calls.append(ToolInvocation(name=name, arguments=parsed_arguments))

    if finish_decisions and parsed_calls:
        return _blocked_decision("The model mixed finish_task with other tool calls.")
    if len(finish_decisions) > 1:
        return _blocked_decision("The model returned multiple finish_task calls.")
    if finish_decisions:
        return finish_decisions[0]
    return ModelDecision(calls=parsed_calls)


def _finish_decision(arguments: dict[str, Any]) -> ModelDecision:
    outcome = arguments.get("outcome")
    if outcome not in {"completed", "partial", "needs_user_input", "blocked"}:
        return _blocked_decision("finish_task used an invalid outcome.")

    answer = arguments.get("answer") or ""
    answer_ref = arguments.get("answer_ref")
    reason = arguments.get("reason") or ""
    if not isinstance(answer, str):
        return _blocked_decision("finish_task answer must be a string.")
    if answer_ref is not None and not isinstance(answer_ref, str):
        return _blocked_decision("finish_task answer_ref must be a string.")
    if not isinstance(reason, str):
        return _blocked_decision("finish_task reason must be a string.")

    return ModelDecision(
        outcome=cast(Any, outcome),
        answer=answer,
        answer_ref=answer_ref,
        reason=reason,
    )


def _blocked_decision(reason: str) -> ModelDecision:
    return ModelDecision(outcome="blocked", reason=reason)


def _tool_summaries(tools: list[dict[str, Any]]) -> list[dict[str, str]]:
    summaries: list[dict[str, str]] = []
    for tool in tools:
        function = tool.get("function") or {}
        if not isinstance(function, dict):
            continue
        name = function.get("name")
        description = function.get("description")
        if isinstance(name, str):
            summaries.append(
                {
                    "name": name,
                    "description": description if isinstance(description, str) else "",
                }
            )
    return summaries


def _validate_unique_tool_names(tools: list[dict[str, Any]]) -> None:
    names: set[str] = set()
    for tool in tools:
        function = tool.get("function") or {}
        if not isinstance(function, dict):
            continue
        name = function.get("name")
        if not isinstance(name, str):
            continue
        if name in names:
            raise ValueError(f"Duplicate tool definition: {name}")
        names.add(name)


def _dump_prompt(prompt: LanguageModelInput) -> list[dict[str, Any]]:
    messages = prompt if isinstance(prompt, list) else [prompt]
    return [message.model_dump(exclude_none=True) for message in messages]


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


BudgetedLLM.invoke = BudgetedLLM.invoke.__wrapped__  # ty: ignore[unresolved-attribute]
