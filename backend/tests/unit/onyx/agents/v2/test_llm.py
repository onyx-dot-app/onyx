from __future__ import annotations

import json
import threading
from typing import Any

import pytest

from onyx.agents.v2.llm import (
    BudgetedLLM,
    BudgetExceeded,
    BudgetLedger,
    OnyxDecisionModel,
)
from onyx.agents.v2.models import (
    ExecutionContext,
    HarnessPolicy,
    RegisteredTool,
    ToolOutput,
)
from onyx.agents.v2.runner import AgentHarness
from onyx.llm.cost import ModelPrice
from onyx.llm.interfaces import (
    LLM,
    LanguageModelInput,
    LLMConfig,
    LLMUserIdentity,
    ReasoningEffort,
    ToolChoice,
)
from onyx.llm.model_response import (
    ChatCompletionMessageToolCall,
    Choice,
    FunctionCall,
    Message,
    ModelResponse,
    Usage,
)
from onyx.llm.models import ToolChoiceOptions


class FakeLLM(LLM):
    def __init__(
        self,
        response: ModelResponse | None = None,
        error: Exception | None = None,
        max_input_tokens: int = 1000,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self._response = response or _text_response("ok")
        self._error = error
        self._max_input_tokens = max_input_tokens

    @property
    def config(self) -> LLMConfig:
        return LLMConfig(
            model_provider="openai",
            model_name="gpt-5-mini",
            temperature=0,
            max_input_tokens=self._max_input_tokens,
        )

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
        self.calls.append(
            {
                "prompt": prompt,
                "tools": tools,
                "tool_choice": tool_choice,
                "structured_response_format": structured_response_format,
                "timeout_override": timeout_override,
                "max_tokens": max_tokens,
                "reasoning_effort": reasoning_effort,
                "user_identity": user_identity,
                "total_timeout_override": total_timeout_override,
            }
        )
        if self._error is not None:
            raise self._error
        return self._response


class SequencedFakeLLM(FakeLLM):
    def __init__(
        self,
        responses: list[ModelResponse],
        max_input_tokens: int = 1000,
    ) -> None:
        super().__init__(responses[0], max_input_tokens=max_input_tokens)
        self._responses = responses

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
        self._response = self._responses.pop(0)
        return super().invoke(
            prompt=prompt,
            tools=tools,
            tool_choice=tool_choice,
            structured_response_format=structured_response_format,
            timeout_override=timeout_override,
            max_tokens=max_tokens,
            reasoning_effort=reasoning_effort,
            user_identity=user_identity,
            total_timeout_override=total_timeout_override,
        )


def test_decision_model_sends_runner_owned_tools_without_duplicates() -> None:
    llm = FakeLLM(
        _tool_response(
            "finish_task",
            {
                "outcome": "completed",
                "answer_ref": "result_0001",
                "reason": "search answer is complete",
            },
        )
    )
    model = OnyxDecisionModel(llm, user_id="user-1")

    decision = model.decide(
        task="answer the user",
        context='{"receipts":[]}',
        tools=[_tool_definition("internal_search"), _tool_definition("finish_task")],
        remaining_seconds=8.5,
        remaining_tokens=400,
        max_output_tokens=123,
    )

    assert decision.outcome == "completed"
    assert decision.answer_ref == "result_0001"
    call = llm.calls[0]
    assert call["tool_choice"] == ToolChoiceOptions.AUTO
    assert call["max_tokens"] == 123
    assert call["reasoning_effort"] == ReasoningEffort.LOW
    assert call["total_timeout_override"] == 8.5
    assert call["user_identity"] == LLMUserIdentity(user_id="user-1")

    tools = call["tools"]
    assert [tool["function"]["name"] for tool in tools] == [
        "internal_search",
        "finish_task",
    ]
    user_message = call["prompt"][1]
    payload = json.loads(user_message.content)
    assert payload["task"] == "answer the user"
    assert payload["budget"]["remaining_tokens"] == 400
    assert payload["tools_provider_list"][0]["name"] == "internal_search"
    assert payload["tools_provider_list"][1]["name"] == "finish_task"


def test_decision_model_rejects_duplicate_tool_names_before_dispatch() -> None:
    llm = FakeLLM()

    with pytest.raises(ValueError, match="Duplicate tool definition: finish_task"):
        OnyxDecisionModel(llm).decide(
            task="task",
            context="{}",
            tools=[_tool_definition("finish_task"), _tool_definition("finish_task")],
            remaining_seconds=10,
            remaining_tokens=1000,
            max_output_tokens=200,
        )

    assert llm.calls == []


def test_agent_harness_with_decision_model_sends_one_finish_tool() -> None:
    llm = FakeLLM(
        _tool_response(
            "finish_task",
            {
                "outcome": "completed",
                "answer": "done",
                "reason": "done",
            },
        )
    )
    policy = HarnessPolicy(max_total_tokens=5000, max_context_tokens=2000)
    ledger = BudgetLedger(policy, token_counter=lambda _: 10)

    result = AgentHarness(
        model=OnyxDecisionModel(BudgetedLLM(llm, ledger)),
        tools=[
            RegisteredTool(
                name="internal_search",
                description="search",
                parameters={"type": "object", "properties": {}},
                execute=_unused_tool,
                pinned=True,
                requires_approval=False,
            )
        ],
        policy=policy,
        usage=ledger.snapshot,
        token_counter=lambda _: 10,
    ).run("answer the task")

    assert result.outcome == "completed", result.reason
    tools = llm.calls[0]["tools"]
    assert [tool["function"]["name"] for tool in tools].count("finish_task") == 1


def test_agent_harness_shrinks_large_tool_context_before_second_model_call() -> None:
    llm = SequencedFakeLLM(
        [
            _tool_response("internal_search", {"objective": "find details"}),
            _tool_response(
                "finish_task",
                {
                    "outcome": "completed",
                    "answer": "done",
                    "reason": "done",
                },
            ),
        ],
        max_input_tokens=4000,
    )
    policy = HarnessPolicy(
        max_model_calls=4,
        max_llm_calls=10,
        max_context_tokens=4000,
        max_total_tokens=10000,
        max_output_tokens=128,
    )
    ledger = BudgetLedger(policy, token_counter=_char_token_counter)

    result = AgentHarness(
        model=OnyxDecisionModel(BudgetedLLM(llm, ledger)),
        tools=[
            RegisteredTool(
                name="internal_search",
                description="search",
                parameters={"type": "object", "properties": {}},
                execute=_large_partial_tool,
                pinned=True,
                requires_approval=False,
            )
        ],
        policy=policy,
        usage=ledger.snapshot,
        token_counter=_char_token_counter,
    ).run("answer the task")

    assert result.outcome == "completed", result.reason
    assert len(llm.calls) == 2
    second_call = llm.calls[1]
    second_prompt_tokens = ledger.estimate_tokens(
        second_call["prompt"],
        second_call["tools"],
    )
    assert policy.max_context_tokens is not None
    assert second_prompt_tokens + second_call["max_tokens"] <= policy.max_context_tokens


def test_decision_model_rejects_mixed_finish_and_actions() -> None:
    llm = FakeLLM(
        _multi_tool_response(
            [
                ("internal_search", {"objective": "find impact"}),
                ("finish_task", {"outcome": "completed", "reason": "done"}),
            ]
        )
    )

    decision = OnyxDecisionModel(llm).decide(
        task="task",
        context="{}",
        tools=[_tool_definition("internal_search")],
        remaining_seconds=10,
        remaining_tokens=1000,
        max_output_tokens=200,
    )

    assert decision.outcome == "blocked"
    assert "mixed finish_task" in decision.reason


def test_decision_model_rejects_invalid_tool_json() -> None:
    llm = FakeLLM(_raw_tool_response("internal_search", "{bad-json"))

    decision = OnyxDecisionModel(llm).decide(
        task="task",
        context="{}",
        tools=[_tool_definition("internal_search")],
        remaining_seconds=10,
        remaining_tokens=1000,
        max_output_tokens=200,
    )

    assert decision.outcome == "blocked"
    assert "invalid tool-call JSON" in decision.reason


def test_normal_final_answer_completes_without_finish_tool() -> None:
    llm = FakeLLM(_text_response("free-form answer"))

    decision = OnyxDecisionModel(llm).decide(
        task="task",
        context="{}",
        tools=[],
        remaining_seconds=10,
        remaining_tokens=1000,
        max_output_tokens=200,
    )

    assert decision.outcome == "completed"
    assert decision.answer == "free-form answer"


@pytest.mark.parametrize(
    "text,finish_reason",
    [
        ("", "stop"),
        ("   ", "stop"),
        ("blocked text", "content_filter"),
        ("refused", "refusal"),
        ("unfinished", "unknown"),
    ],
)
def test_empty_or_abnormal_final_response_does_not_complete(
    text: str, finish_reason: str
) -> None:
    decision = OnyxDecisionModel(
        FakeLLM(_text_response(text, finish_reason=finish_reason))
    ).decide(
        task="task",
        context="{}",
        tools=[],
        remaining_seconds=10,
        remaining_tokens=1000,
        max_output_tokens=None,
    )
    assert decision.outcome != "completed"


def test_output_limit_is_partial() -> None:
    llm = FakeLLM(_text_response("cut off", finish_reason="length"))

    decision = OnyxDecisionModel(llm).decide(
        task="task",
        context="{}",
        tools=[],
        remaining_seconds=10,
        remaining_tokens=1000,
        max_output_tokens=200,
    )

    assert decision.outcome == "partial"
    assert "output token limit" in decision.reason


def test_default_output_uses_model_limit_not_input_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from onyx.agents.v2 import llm as module

    monkeypatch.setattr(module, "get_llm_max_output_tokens", lambda *_: 9000)
    policy = HarnessPolicy(max_context_tokens=1000)
    assert policy.max_output_tokens is None
    ledger = BudgetLedger(policy, token_counter=lambda _: 400)
    inner = SequencedFakeLLM([_text_response("answer")], max_input_tokens=32000)
    BudgetedLLM(inner, ledger).invoke(prompt=[])
    assert inner.calls[0]["max_tokens"] == 9000


def test_search_input_uses_model_window_not_outer_loop_context_budget() -> None:
    ledger = BudgetLedger(
        HarnessPolicy(max_context_tokens=1000), token_counter=lambda _: 4000
    )
    inner = SequencedFakeLLM([_text_response("answer")], max_input_tokens=10000)
    BudgetedLLM(inner, ledger).invoke(prompt=[])
    assert inner.calls[0]["max_tokens"] == 6000


def test_search_input_cannot_exceed_model_window() -> None:
    ledger = BudgetLedger(HarnessPolicy(), token_counter=lambda _: 10001)
    inner = SequencedFakeLLM([_text_response("answer")], max_input_tokens=10000)
    with pytest.raises(BudgetExceeded, match="context budget"):
        BudgetedLLM(inner, ledger).invoke(prompt=[])
    assert not inner.calls


def test_model_output_limit_cannot_bypass_task_token_budget() -> None:
    ledger = BudgetLedger(
        HarnessPolicy(max_total_tokens=2000),
        token_counter=lambda _: 200,
    )
    inner = SequencedFakeLLM([_text_response("answer")], max_input_tokens=32000)
    BudgetedLLM(inner, ledger).invoke(prompt=[])
    assert inner.calls[0]["max_tokens"] == 1800


def test_model_output_respects_context_remaining_after_search_input() -> None:
    ledger = BudgetLedger(HarnessPolicy(), token_counter=lambda _: 900)
    inner = SequencedFakeLLM([_text_response("answer")], max_input_tokens=2500)
    BudgetedLLM(inner, ledger).invoke(prompt=[])
    assert inner.calls[0]["max_tokens"] == 1600


def test_parallel_native_calls_wait_for_unused_reservation() -> None:
    from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel

    ledger = BudgetLedger(HarnessPolicy(max_total_tokens=1000), lambda _: 100)
    inner = FakeLLM(_text_response("answer", usage=_usage(prompt=100, completion=20)))
    first = ledger.reserve_llm_call(
        prompt_tokens=100, requested_max_output_tokens=None, llm_config=inner.config
    )
    started = threading.Event()
    returned = threading.Event()

    def waiting_call() -> None:
        started.set()
        BudgetedLLM(inner, ledger).invoke(prompt=[])
        returned.set()

    def release_first_call() -> None:
        assert started.wait(1)
        assert not returned.wait(0.05)
        ledger.record_success(first, _usage(prompt=100, completion=20))

    run_functions_tuples_in_parallel(
        [(waiting_call, ()), (release_first_call, ())], max_workers=2, timeout=2
    )
    assert returned.is_set()
    assert inner.calls[0]["max_tokens"] == 780
    assert ledger.snapshot().total_tokens == 240


def test_capacity_wait_respects_task_deadline() -> None:
    ledger = BudgetLedger(
        HarnessPolicy(
            duration_mode="hard", max_total_tokens=1000, max_elapsed_seconds=0.05
        ),
        lambda _: 100,
    )
    inner = FakeLLM()
    ledger.reserve_llm_call(
        prompt_tokens=100, requested_max_output_tokens=None, llm_config=inner.config
    )
    with pytest.raises(BudgetExceeded, match="time budget"):
        BudgetedLLM(inner, ledger).invoke(prompt=[])
    assert not inner.calls
    assert ledger.snapshot().calls == 1


def test_budgeted_llm_caps_tokens_and_deadline() -> None:
    now = [0.0]
    ledger = BudgetLedger(
        HarnessPolicy(
            duration_mode="hard",
            max_elapsed_seconds=10,
            max_total_tokens=1000,
            max_output_tokens=64,
        ),
        token_counter=lambda _: 20,
        clock=lambda: now[0],
    )
    now[0] = 7.0
    llm = FakeLLM(_text_response("ok", usage=_usage(prompt=12, completion=5)))

    BudgetedLLM(llm, ledger).invoke(
        prompt=[],
        max_tokens=80,
        total_timeout_override=100,
    )

    call = llm.calls[0]
    assert call["max_tokens"] == 64
    assert call["total_timeout_override"] == 3.0
    assert ledger.snapshot().calls == 1
    assert ledger.snapshot().total_tokens == 17


def test_budget_reservation_blocks_parallel_overspend() -> None:
    ledger = BudgetLedger(
        HarnessPolicy(max_model_calls=20, max_total_tokens=1000, max_output_tokens=300),
        token_counter=lambda _: 200,
    )
    config = FakeLLM().config

    first = ledger.reserve_llm_call(
        prompt_tokens=200,
        requested_max_output_tokens=300,
        llm_config=config,
    )
    second = ledger.reserve_llm_call(
        prompt_tokens=200,
        requested_max_output_tokens=300,
        llm_config=config,
    )

    assert first.max_output_tokens == 300
    assert second.max_output_tokens == 300
    with pytest.raises(BudgetExceeded):
        ledger.reserve_llm_call(
            prompt_tokens=200,
            requested_max_output_tokens=300,
            llm_config=config,
        )


def test_failed_call_is_recorded_and_releases_reservation() -> None:
    ledger = BudgetLedger(
        HarnessPolicy(max_total_tokens=1000, max_output_tokens=64),
        token_counter=lambda _: 11,
    )
    llm = FakeLLM(error=RuntimeError("provider failed"))

    with pytest.raises(RuntimeError):
        BudgetedLLM(llm, ledger).invoke(prompt=[], max_tokens=25)

    snapshot = ledger.snapshot()
    assert snapshot.calls == 1
    assert snapshot.total_tokens == 36
    assert snapshot.unpriced_calls == 1
    assert ledger.remaining_tokens() == 964


def test_failed_call_charges_reserved_output_budget() -> None:
    ledger = BudgetLedger(
        HarnessPolicy(max_total_tokens=1000, max_output_tokens=100),
        token_counter=lambda _: 900,
    )
    llm = FakeLLM(error=RuntimeError("provider failed"))

    with pytest.raises(RuntimeError):
        BudgetedLLM(llm, ledger).invoke(prompt=[], max_tokens=100)

    assert ledger.snapshot().total_tokens == 1000
    with pytest.raises(BudgetExceeded, match="token budget"):
        BudgetedLLM(FakeLLM(), ledger).invoke(prompt=[], max_tokens=100)


def test_unknown_pricing_is_disclosed(monkeypatch: pytest.MonkeyPatch) -> None:
    import onyx.agents.v2.llm as llm_module

    monkeypatch.setattr(
        llm_module,
        "get_model_price_per_million",
        lambda model, provider: ModelPrice(
            model=model,
            provider=provider,
            input_per_mtok=None,
            output_per_mtok=None,
            cache_per_mtok=None,
        ),
    )
    monkeypatch.setattr(
        llm_module,
        "compute_cost_cents",
        lambda **_: (1.0, 2.0),
    )
    ledger = BudgetLedger(
        HarnessPolicy(max_total_tokens=1000, max_output_tokens=64),
        token_counter=lambda _: 10,
    )
    llm = FakeLLM(_text_response("ok", usage=_usage(prompt=7, completion=3)))

    BudgetedLLM(llm, ledger).invoke(prompt=[], max_tokens=25)

    snapshot = ledger.snapshot()
    assert snapshot.total_tokens == 10
    assert snapshot.cost_cents == 3.0
    assert snapshot.unpriced_calls == 1


def test_explicit_cost_budget_rejects_unknown_pricing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import onyx.agents.v2.llm as llm_module

    monkeypatch.setattr(
        llm_module,
        "get_model_price_per_million",
        lambda model, provider: ModelPrice(
            model=model,
            provider=provider,
            input_per_mtok=None,
            output_per_mtok=None,
            cache_per_mtok=None,
        ),
    )
    monkeypatch.setattr(llm_module, "compute_cost_cents", lambda **_: (0.0, 0.0))
    ledger = BudgetLedger(
        HarnessPolicy(max_cost_cents=1, max_total_tokens=1000, max_output_tokens=64),
        token_counter=lambda _: 10,
    )
    llm = FakeLLM(_text_response("ok"))

    with pytest.raises(BudgetExceeded, match="unpriced model"):
        BudgetedLLM(llm, ledger).invoke(prompt=[], max_tokens=25)

    assert llm.calls == []


def _tool_definition(name: str) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": "test tool",
            "parameters": {"type": "object", "properties": {}},
        },
    }


def _unused_tool(
    _arguments: dict[str, Any],
    _context: ExecutionContext,
) -> ToolOutput:
    return ToolOutput(content="unused")


def _large_partial_tool(
    _arguments: dict[str, Any],
    _context: ExecutionContext,
) -> ToolOutput:
    large_answer = '{"acceptance":"criteria","notes":["quoted","json"]}\n' * 1200
    return ToolOutput(
        status="partial",
        content=large_answer,
        answer=large_answer,
        receipt={"answer_finish_reason": "length"},
    )


def _char_token_counter(text: str) -> int:
    return max((len(text) + 3) // 4, 1)


def _tool_response(
    name: str,
    arguments: dict[str, Any],
) -> ModelResponse:
    return _raw_tool_response(name, json.dumps(arguments))


def _multi_tool_response(calls: list[tuple[str, dict[str, Any]]]) -> ModelResponse:
    return ModelResponse(
        id="response-id",
        created="now",
        choice=Choice(
            finish_reason="tool_calls",
            message=Message(
                tool_calls=[
                    ChatCompletionMessageToolCall(
                        id=f"call-{index}",
                        function=FunctionCall(
                            name=name,
                            arguments=json.dumps(arguments),
                        ),
                    )
                    for index, (name, arguments) in enumerate(calls)
                ]
            ),
        ),
    )


def _raw_tool_response(name: str, arguments: str) -> ModelResponse:
    return ModelResponse(
        id="response-id",
        created="now",
        choice=Choice(
            finish_reason="tool_calls",
            message=Message(
                tool_calls=[
                    ChatCompletionMessageToolCall(
                        id="call-1",
                        function=FunctionCall(name=name, arguments=arguments),
                    )
                ]
            ),
        ),
    )


def _text_response(
    content: str,
    *,
    finish_reason: str = "stop",
    usage: Usage | None = None,
) -> ModelResponse:
    return ModelResponse(
        id="response-id",
        created="now",
        usage=usage,
        choice=Choice(
            finish_reason=finish_reason,
            message=Message(content=content),
        ),
    )


def _usage(prompt: int, completion: int) -> Usage:
    return Usage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=prompt + completion,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    )


@pytest.mark.parametrize(
    "requested, expected", [(None, 16384), (500, 500), (32000, 16384)]
)
def test_search_output_cap_preserves_outer_allowance(monkeypatch, requested, expected):
    from onyx.agents.v2 import llm as module

    monkeypatch.setattr(module, "get_llm_max_output_tokens", lambda *_: 128000)
    policy = HarnessPolicy(max_total_tokens=500000)
    ledger = BudgetLedger(policy, token_counter=lambda _: 400)
    inner = SequencedFakeLLM(
        [_text_response("search"), _text_response("answer")], max_input_tokens=200000
    )
    BudgetedLLM(
        inner, ledger, max_output_tokens=policy.search_max_output_tokens
    ).invoke(prompt=[], max_tokens=requested)
    BudgetedLLM(inner, ledger).invoke(prompt=[])
    assert inner.calls[0]["max_tokens"] == expected
    assert inner.calls[1]["max_tokens"] == 128000
    assert ledger.snapshot().calls == 2


def test_reasoning_output_floor_is_reserved_before_call(monkeypatch):
    from onyx.agents.v2 import llm as module

    monkeypatch.setattr(module, "get_llm_max_output_tokens", lambda *_: 128000)
    policy = HarnessPolicy(max_total_tokens=500000)
    ledger = BudgetLedger(policy, token_counter=lambda _: 400)
    reserved = []
    original = ledger.reserve_llm_call

    def reserve(**kwargs):
        reserved.append(kwargs["requested_max_output_tokens"])
        return original(**kwargs)

    monkeypatch.setattr(ledger, "reserve_llm_call", reserve)
    inner = SequencedFakeLLM([_text_response("selection")], max_input_tokens=200000)
    BudgetedLLM(inner, ledger, max_output_tokens=16384, min_output_tokens=16384).invoke(
        prompt=[], max_tokens=256
    )
    assert reserved == [16384]
    assert inner.calls[0]["max_tokens"] == 16384
