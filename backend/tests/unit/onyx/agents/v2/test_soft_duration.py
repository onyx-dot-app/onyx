from __future__ import annotations

import pytest
from test_llm import FakeLLM, _text_response, _usage  # ty: ignore[unresolved-import]
from test_runner import (  # ty: ignore[unresolved-import]
    ManualClock,
    ScriptedModel,
    _decision_call,
    _tool,
)

from onyx.agents.v2.llm import (
    BudgetedLLM,
    BudgetExceeded,
    BudgetLedger,
    OnyxDecisionModel,
    ReservationWaitTimeout,
    TaskCancelled,
)
from onyx.agents.v2.models import HarnessPolicy, ModelDecision, ToolOutput
from onyx.agents.v2.runner import AgentHarness


def test_soft_target_allows_new_tools_and_final_after_target():
    clock = ManualClock()
    contexts = []

    def after_decide(count, _decision):
        clock.now = 130 + count

    def execute(_args, context):
        contexts.append(context)
        assert not context.cancelled()
        return ToolOutput(content="Evidence [1]", citation_mapping={1: "doc-1"})

    model = ScriptedModel(
        [
            _decision_call("internal_search", {"objective": "first"}),
            _decision_call("internal_search", {"objective": "missing fact"}),
            ModelDecision(outcome="completed", answer="Supported [1]"),
        ],
        after_decide=after_decide,
    )
    result = AgentHarness(
        model=model,
        tools=[_tool("internal_search", execute, pinned=True)],
        policy=HarnessPolicy(tool_timeout_seconds=17),
        clock=clock,
    ).run("Question")
    assert result.outcome == "completed"
    assert result.tool_calls == 2
    assert result.total_ms > 120000
    assert all(context.remaining_seconds == 17 for context in contexts)
    assert model.calls[1]["remaining_seconds"] < 0
    assert (
        model.calls[1]["context"]["budget"]["duration_guidance"]["target_seconds"]
        == 120
    )


def test_model_timeout_does_not_shrink_after_soft_target():
    clock = ManualClock()
    policy = HarnessPolicy(duration_mode="soft", model_timeout_seconds=19)
    ledger = BudgetLedger(policy, lambda _: 20, clock=clock, started_at=0)
    inner = FakeLLM(_text_response("done", usage=_usage(20, 5)))
    model = OnyxDecisionModel(BudgetedLLM(inner, ledger), operation_timeout_seconds=19)
    for elapsed in (110, 500):
        clock.now = elapsed
        model.decide(
            task="q",
            context="{}",
            tools=[],
            remaining_seconds=120 - elapsed,
            remaining_tokens=10000,
            max_output_tokens=None,
        )
    assert [call["total_timeout_override"] for call in inner.calls] == [19, 19]
    assert ledger.snapshot().total_tokens == 50


def test_soft_capacity_wait_has_independent_timeout(monkeypatch):
    clock = ManualClock()
    ledger = BudgetLedger(
        HarnessPolicy(
            duration_mode="soft", max_total_tokens=1000, reservation_wait_seconds=3
        ),
        lambda _: 100,
        clock=clock,
    )
    inner = FakeLLM()
    ledger.reserve_llm_call(
        prompt_tokens=100, requested_max_output_tokens=None, llm_config=inner.config
    )
    clock.now = 200
    monkeypatch.setattr(
        ledger._lock, "wait", lambda _timeout: setattr(clock, "now", clock.now + 4)
    )
    with pytest.raises(ReservationWaitTimeout):
        BudgetedLLM(inner, ledger).invoke(prompt=[])
    assert ledger.snapshot().calls == 1
    assert not inner.calls


def test_soft_capacity_wait_observes_external_cancellation(monkeypatch):
    cancelled = [False]
    ledger = BudgetLedger(
        HarnessPolicy(duration_mode="soft", max_total_tokens=1000),
        lambda _: 100,
        cancelled=lambda: cancelled[0],
    )
    inner = FakeLLM()
    ledger.reserve_llm_call(
        prompt_tokens=100, requested_max_output_tokens=None, llm_config=inner.config
    )
    monkeypatch.setattr(
        ledger._lock, "wait", lambda _timeout: cancelled.__setitem__(0, True)
    )
    with pytest.raises(TaskCancelled):
        BudgetedLLM(inner, ledger).invoke(prompt=[])
    assert not inner.calls


def test_soft_tool_timeout_is_failure_not_resource_exhaustion(monkeypatch):
    from onyx.agents.v2 import runner

    clock = ManualClock()

    def timeout(**kwargs):
        assert kwargs["timeout"] == 7
        assert not kwargs["context"].cancelled()
        clock.now += 8
        assert kwargs["context"].cancelled()
        raise TimeoutError()

    monkeypatch.setattr(runner, "_execute_tool_with_timeout", timeout)
    model = ScriptedModel(
        [_decision_call("internal_search", {"objective": "q"})],
        after_decide=lambda *_: setattr(clock, "now", 150),
    )
    result = AgentHarness(
        model=model,
        tools=[
            _tool(
                "internal_search", lambda *_: ToolOutput(content="unused"), pinned=True
            )
        ],
        policy=HarnessPolicy(duration_mode="soft", tool_timeout_seconds=7),
        clock=clock,
    ).run("q")
    assert result.outcome == "blocked"
    assert result.receipts[0]["tool_receipt"]["timed_out_may_still_run"]


def test_soft_model_timeout_retains_unknown_usage():
    clock = ManualClock()
    policy = HarnessPolicy(duration_mode="soft")
    ledger = BudgetLedger(policy, lambda _: 20, clock=clock, started_at=0)
    clock.now = 150
    inner = FakeLLM(error=TimeoutError("transport"))
    result = AgentHarness(
        model=OnyxDecisionModel(
            BudgetedLLM(inner, ledger), operation_timeout_seconds=120
        ),
        tools=[],
        policy=policy,
        clock=clock,
        started_at=0,
        usage=ledger.snapshot,
    ).run("q")
    assert result.outcome == "blocked"
    assert result.usage.unpriced_calls == 1
    assert inner.calls[0]["total_timeout_override"] == 120


def test_soft_cancellation_during_model_prevents_completion():
    cancelled = [False]
    model = ScriptedModel(
        [ModelDecision(outcome="completed", answer="late")],
        after_decide=lambda *_: cancelled.__setitem__(0, True),
    )
    result = AgentHarness(
        model=model,
        tools=[],
        policy=HarnessPolicy(duration_mode="soft"),
        cancelled=lambda: cancelled[0],
    ).run("q")
    assert result.outcome == "cancelled"
    assert result.answer == ""


def test_soft_mode_still_enforces_token_budget_after_target():
    clock = ManualClock()
    ledger = BudgetLedger(
        HarnessPolicy(duration_mode="soft", max_total_tokens=1000),
        lambda _: 1000,
        clock=clock,
    )
    clock.now = 500
    inner = FakeLLM()
    with pytest.raises(BudgetExceeded, match="token budget"):
        BudgetedLLM(inner, ledger).invoke(prompt=[])
    assert not inner.calls
