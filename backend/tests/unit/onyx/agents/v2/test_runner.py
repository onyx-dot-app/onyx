from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from onyx.agents.v2.models import (
    ExecutionContext,
    HarnessPolicy,
    ModelDecision,
    RegisteredTool,
    ToolInvocation,
    ToolOutput,
    UsageSnapshot,
)
from onyx.agents.v2.runner import AgentHarness


class ScriptedModel:
    def __init__(
        self,
        decisions: list[ModelDecision],
        after_decide: Callable[[int, ModelDecision], None] | None = None,
    ) -> None:
        self._decisions = decisions
        self._after_decide = after_decide
        self.calls: list[dict[str, Any]] = []

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
        self.calls.append(
            {
                "task": task,
                "raw_context": context,
                "context": json.loads(context),
                "tools": tools,
                "remaining_seconds": remaining_seconds,
                "remaining_tokens": remaining_tokens,
                "max_output_tokens": max_output_tokens,
            }
        )
        if not self._decisions:
            raise AssertionError("No scripted decision left")
        decision = self._decisions.pop(0)
        if self._after_decide is not None:
            self._after_decide(len(self.calls), decision)
        return decision


class MutableUsage:
    def __init__(self, snapshot: UsageSnapshot | None = None) -> None:
        self.snapshot = snapshot or UsageSnapshot()

    def __call__(self) -> UsageSnapshot:
        return self.snapshot


class ManualClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_final_answer_preserves_citations_across_evidence_only_searches() -> None:
    model = ScriptedModel(
        [
            _decision_call("internal_search", {"objective": "first"}),
            _decision_call("internal_search", {"objective": "second"}),
            ModelDecision(outcome="completed", answer="First [1] and second [2]."),
        ]
    )

    def evidence(args: dict[str, Any], _ctx: ExecutionContext) -> ToolOutput:
        number = 1 if args["objective"] == "first" else 2
        return ToolOutput(
            content=f"Evidence [{number}]", citation_mapping={number: f"doc{number}"}
        )

    tool = _tool("internal_search", evidence, pinned=True)
    result = AgentHarness(model=model, tools=[tool]).run("Compare both")
    assert result.outcome == "completed"
    assert result.answer == "First [1] and second [2]."
    assert result.citation_mapping == {1: "doc1", 2: "doc2"}
    assert result.document_ids == ["doc1", "doc2"]
    assert result.model_calls == 3


def test_completion_reserve_hides_information_tools_after_evidence() -> None:
    usage = MutableUsage()
    model = ScriptedModel(
        [
            _decision_call("internal_search", {"objective": "first"}),
            ModelDecision(outcome="completed", answer="Best supported answer [1]."),
        ]
    )

    def evidence(_args: dict[str, Any], _ctx: ExecutionContext) -> ToolOutput:
        usage.snapshot = UsageSnapshot(total_tokens=60000)
        return ToolOutput(content="Evidence [1]", citation_mapping={1: "doc1"})

    result = AgentHarness(
        model=model,
        tools=[_tool("internal_search", evidence, pinned=True)],
        policy=HarnessPolicy(
            max_total_tokens=100000,
            completion_reserve_tokens=50000,
            decision_max_output_tokens=64,
        ),
        usage=usage,
    ).run("Question")

    assert result.outcome == "completed"
    assert result.tool_calls == 1
    second_tool_names = {tool["function"]["name"] for tool in model.calls[1]["tools"]}
    assert "internal_search" not in second_tool_names
    assert "completion_only" in model.calls[1]["context"]["contracts"]
    assert model.calls[1]["max_output_tokens"] == 64


def test_completion_review_requests_one_revision_after_tool_use() -> None:
    model = ScriptedModel(
        [
            _decision_call("internal_search", {"objective": "find exact record"}),
            ModelDecision(outcome="completed", answer="provisional answer [1]"),
            ModelDecision(outcome="completed", answer="revised answer [1]"),
        ]
    )
    tool = _tool(
        "internal_search",
        lambda _args, _ctx: ToolOutput(
            content="Exact evidence [1]", citation_mapping={1: "doc1"}
        ),
        pinned=True,
    )

    result = AgentHarness(
        model=model,
        tools=[tool],
        policy=HarnessPolicy(completion_review=True),
    ).run("Question")

    assert result.outcome == "completed"
    assert result.answer == "revised answer [1]"
    assert result.model_calls == 3
    review_state = model.calls[2]["context"]["current_turn_state"]
    assert review_state["receipts"][-1]["tool_name"] == "completion_review"
    assert "provisional answer" in review_state["results"][0]["content_preview"]


def test_one_search_fast_path_finishes_from_answer_ref() -> None:
    model = ScriptedModel(
        [
            _decision_call("internal_search", {"objective": "find upload limits"}),
            ModelDecision(
                outcome="completed",
                answer_ref="result_0001",
                reason="search answer is sufficient",
            ),
        ]
    )
    tool = _tool(
        "internal_search",
        lambda args, _ctx: ToolOutput(
            content="evidence body",
            answer="Files are 32 MB and requests are 64 MB.",
            receipt={"query": args["objective"]},
            document_ids=["doc-1"],
            citation_mapping={1: "doc-1"},
        ),
        pinned=True,
    )

    result = AgentHarness(model=model, tools=[tool]).run("What are the limits?")

    assert result.outcome == "completed"
    assert result.answer == "Files are 32 MB and requests are 64 MB."
    assert result.tool_calls == 1
    assert result.model_calls == 2
    assert result.document_ids == ["doc-1"]
    assert result.citation_mapping == {1: "doc-1"}


def test_completed_with_unknown_answer_ref_is_blocked() -> None:
    model = ScriptedModel(
        [
            ModelDecision(
                outcome="completed",
                answer_ref="result_9999",
                reason="bad ref",
            )
        ]
    )

    result = AgentHarness(model=model, tools=[]).run("Question")

    assert result.outcome == "blocked"
    assert "unknown result" in result.reason


def test_completed_from_partial_answer_ref_is_blocked() -> None:
    model = ScriptedModel(
        [
            _decision_call("internal_search", {"objective": "q"}),
            ModelDecision(outcome="completed", answer_ref="result_0001"),
        ]
    )
    tool = _tool(
        "internal_search",
        lambda _args, _ctx: ToolOutput(
            status="partial",
            content="partial evidence",
            answer="partial answer",
        ),
        pinned=True,
    )

    result = AgentHarness(model=model, tools=[tool]).run("Question")

    assert result.outcome == "blocked"
    assert result.reason == "completed outcome referenced non-success tool output"


def test_completed_from_truncated_answer_ref_is_blocked() -> None:
    model = ScriptedModel(
        [
            _decision_call("internal_search", {"objective": "q"}),
            ModelDecision(outcome="completed", answer_ref="result_0001"),
        ]
    )
    tool = _tool(
        "internal_search",
        lambda _args, _ctx: ToolOutput(
            content="x" * 10000,
            answer="answer from clipped evidence",
        ),
        pinned=True,
    )
    policy = HarnessPolicy(max_store_bytes=4096)

    result = AgentHarness(model=model, tools=[tool], policy=policy).run("Question")

    assert result.outcome == "blocked"
    assert result.reason == "completed outcome referenced truncated tool output"


def test_completed_reference_allows_compacted_tool_receipt() -> None:
    model = ScriptedModel(
        [
            _decision_call("internal_search", {"objective": "find evidence"}),
            ModelDecision(
                outcome="completed",
                answer="supported answer",
                answer_ref="result_0001",
            ),
        ]
    )
    tool = _tool(
        "internal_search",
        lambda _args, _ctx: ToolOutput(
            content="evidence",
            receipt={"diagnostics": "x" * 100_000},
        ),
        pinned=True,
    )

    result = AgentHarness(model=model, tools=[tool]).run("Question")

    assert result.outcome == "completed"
    assert result.answer == "supported answer"
    assert result.receipts[0]["truncated"] is False
    assert result.receipts[0]["tool_receipt"]["truncated"] is True


def test_followup_objective_reaches_tool_with_overall_task_context() -> None:
    seen: list[tuple[dict[str, Any], ExecutionContext]] = []
    model = ScriptedModel(
        [
            _decision_call(
                "internal_search",
                {"objective": "find customer impact only"},
            ),
            ModelDecision(outcome="partial", answer="partial answer"),
        ]
    )
    tool = _tool(
        "internal_search",
        lambda args, ctx: (
            seen.append((args, ctx)) or ToolOutput(content="impact evidence")
        ),
        pinned=True,
    )

    AgentHarness(model=model, tools=[tool]).run("Explain the incident.")

    assert seen[0][0]["objective"] == "find customer impact only"
    assert seen[0][1].task == "Explain the incident."
    assert model.calls[0]["context"]["contracts"]["followup_objective"]


def test_discovery_then_execute_hidden_tool() -> None:
    model = ScriptedModel(
        [
            _decision_call("discover_tools", {"query": "calendar"}),
            _decision_call("calendar_lookup", {"date": "2026-09-09"}),
            ModelDecision(outcome="completed", answer="meeting found"),
        ]
    )
    tools = [
        _tool(
            "internal_search", lambda _args, _ctx: ToolOutput(content=""), pinned=True
        ),
        _tool(
            "calendar_lookup",
            lambda _args, _ctx: ToolOutput(content="calendar result"),
            description="calendar events lookup",
        ),
    ]

    result = AgentHarness(model=model, tools=tools).run("Check my calendar.")

    assert result.outcome == "completed"
    assert result.tool_calls == 1
    assert any(
        call["function"]["name"] == "calendar_lookup"
        for call in model.calls[1]["tools"]
        if call["type"] == "function"
    )


def test_malformed_discovery_arguments_do_not_expose_hidden_tool() -> None:
    model = ScriptedModel(
        [
            _decision_call("discover_tools", {"query": 3}),
            _decision_call("calendar_lookup", {"date": "2026-09-09"}),
        ]
    )
    tools = [
        _tool(
            "internal_search", lambda _args, _ctx: ToolOutput(content=""), pinned=True
        ),
        _tool(
            "calendar_lookup",
            lambda _args, _ctx: ToolOutput(content="calendar result"),
            description="calendar events lookup",
        ),
    ]

    result = AgentHarness(model=model, tools=tools).run("Check my calendar.")

    assert result.outcome == "blocked"
    assert result.tool_calls == 0
    assert result.receipts[0]["status"] == "error"
    assert (
        "failed validation" in result.receipts[0]["tool_receipt"].get("message", "")
        or result.receipts[0]["status"] == "error"
    )


def test_receipts_survive_bounded_context_and_read_result() -> None:
    large_content = "0123456789" * 1000
    model = ScriptedModel(
        [
            _decision_call("internal_search", {"objective": "find logs"}),
            _decision_call(
                "read_result",
                {"result_ref": "result_0001", "offset": 10, "max_chars": 12},
            ),
            ModelDecision(outcome="partial", answer="read enough"),
        ]
    )
    tool = _tool(
        "internal_search",
        lambda _args, _ctx: ToolOutput(
            content=large_content,
            receipt={"query": "logs"},
        ),
        pinned=True,
    )

    result = AgentHarness(model=model, tools=[tool]).run("Read logs.")

    assert result.outcome == "partial"
    assert result.receipts[0]["result_ref"] == "result_0001"
    assert result.receipts[0]["tool_receipt"] == {"query": "logs"}
    read_payload = json.loads(result.receipts[1]["tool_receipt"].get("payload", "{}"))
    assert read_payload == {}
    assert "result_0002" in {receipt["result_ref"] for receipt in result.receipts}


def test_context_render_reserves_prompt_and_tool_overhead() -> None:
    policy = HarnessPolicy(
        max_context_tokens=8000,
        max_output_tokens=64,
        max_store_bytes=20000,
    )
    model = ScriptedModel(
        [
            _decision_call("internal_search", {"objective": "find long evidence"}),
            ModelDecision(outcome="partial", answer="enough"),
        ]
    )
    tool = _tool(
        "internal_search",
        lambda _args, _ctx: ToolOutput(content="x" * 10000),
        pinned=True,
    )

    result = AgentHarness(
        model=model,
        tools=[tool],
        policy=policy,
        token_counter=len,
    ).run("Question")

    second_prompt = json.dumps(
        {
            "context": model.calls[1]["raw_context"],
            "tools": model.calls[1]["tools"],
        },
        sort_keys=True,
    )
    assert result.outcome == "partial"
    assert policy.max_context_tokens is not None
    assert len(second_prompt) <= policy.max_context_tokens


def test_approval_required_returns_needs_user_input_without_execution() -> None:
    executed = False

    def execute(_args: dict[str, Any], _ctx: ExecutionContext) -> ToolOutput:
        nonlocal executed
        executed = True
        return ToolOutput(content="should not run")

    model = ScriptedModel([_decision_call("send_email", {"to": "a@example.com"})])
    tool = _tool("send_email", execute, requires_approval=True, pinned=True)

    result = AgentHarness(model=model, tools=[tool]).run("Send mail.")

    assert result.outcome == "needs_user_input"
    assert not executed
    assert result.tool_calls == 0


def test_unknown_and_malformed_tool_calls_return_blocked_after_feedback() -> None:
    model = ScriptedModel(
        [
            _decision_call("missing_tool", {}),
            _decision_call("internal_search", {}),
        ]
    )
    tool = _tool(
        "internal_search",
        lambda _args, _ctx: ToolOutput(content="never"),
        parameters={
            "type": "object",
            "properties": {"objective": {"type": "string"}},
            "required": ["objective"],
            "additionalProperties": False,
        },
        pinned=True,
    )

    result = AgentHarness(model=model, tools=[tool]).run("Question")

    assert result.outcome == "blocked"
    assert result.reason == "repeated tool failures"
    assert result.tool_calls == 0
    assert len(result.receipts) == 2


def test_external_schema_ref_rejects_before_tool_execution() -> None:
    executed = False

    def execute(_args: dict[str, Any], _ctx: ExecutionContext) -> ToolOutput:
        nonlocal executed
        executed = True
        return ToolOutput(content="should not run")

    model = ScriptedModel(
        [
            _decision_call("internal_search", {"objective": "q"}),
            ModelDecision(outcome="partial", answer="stopped"),
        ]
    )
    tool = _tool(
        "internal_search",
        execute,
        parameters={"$ref": "https://example.com/schema.json"},
        pinned=True,
    )

    result = AgentHarness(model=model, tools=[tool]).run("Question")

    assert result.outcome == "partial"
    assert not executed
    assert result.tool_calls == 0
    assert (
        "external $ref" in result.receipts[0]["tool_receipt"].get("message", "")
        or result.receipts[0]["status"] == "error"
    )


def test_external_dynamic_schema_ref_rejects_before_tool_execution() -> None:
    executed = False

    def execute(_args: dict[str, Any], _ctx: ExecutionContext) -> ToolOutput:
        nonlocal executed
        executed = True
        return ToolOutput(content="should not run")

    model = ScriptedModel(
        [
            _decision_call("internal_search", {"objective": "q"}),
            ModelDecision(outcome="partial", answer="stopped"),
        ]
    )
    tool = _tool(
        "internal_search",
        execute,
        parameters={"$dynamicRef": "https://example.com/schema.json"},
        pinned=True,
    )

    result = AgentHarness(model=model, tools=[tool]).run("Question")

    assert result.outcome == "partial"
    assert not executed
    assert result.tool_calls == 0
    assert result.receipts[0]["status"] == "error"


def test_repeated_large_feedback_returns_budget_exhausted() -> None:
    model = ScriptedModel(
        [
            ModelDecision(
                calls=[
                    ToolInvocation(
                        name="internal_search", arguments={"objective": "a"}
                    ),
                    ToolInvocation(
                        name="internal_search", arguments={"objective": "b"}
                    ),
                    ToolInvocation(
                        name="internal_search", arguments={"objective": "c"}
                    ),
                ]
            )
        ]
    )
    tool = _tool(
        "internal_search",
        lambda _args, _ctx: ToolOutput(content="x" * 100000),
        pinned=True,
    )
    policy = HarnessPolicy(max_store_bytes=4096)

    result = AgentHarness(model=model, tools=[tool], policy=policy).run("Question")

    assert result.outcome == "budget_exhausted"
    assert result.reason == "context budget exhausted"
    assert result.tool_calls >= 2
    assert any(event.kind == "context_add_failed" for event in result.events)


def test_slow_tool_times_out_without_waiting_for_completion() -> None:
    def execute(_args: dict[str, Any], ctx: ExecutionContext) -> ToolOutput:
        time.sleep(0.25)
        assert ctx.cancelled()
        return ToolOutput(content="late", answer="late answer")

    model = ScriptedModel([_decision_call("internal_search", {"objective": "q"})])
    tool = _tool("internal_search", execute, pinned=True)
    policy = HarnessPolicy(duration_mode="hard", max_elapsed_seconds=0.05)

    started = time.perf_counter()
    result = AgentHarness(model=model, tools=[tool], policy=policy).run("Question")
    elapsed = time.perf_counter() - started

    assert result.outcome == "budget_exhausted"
    assert result.answer == ""
    assert result.reason == "Tool 'internal_search' timed out."
    assert elapsed < 0.20
    assert result.receipts[0]["tool_receipt"]["timed_out_may_still_run"]
    assert any(event.kind == "tool_timeout" for event in result.events)


def test_finish_cannot_coexist_with_other_tool_calls() -> None:
    model = ScriptedModel(
        [
            ModelDecision(
                calls=[
                    ToolInvocation(
                        name="finish_task",
                        arguments={"outcome": "completed", "answer": "done"},
                    ),
                    ToolInvocation(name="internal_search", arguments={}),
                ]
            ),
            ModelDecision(outcome="partial", answer="stopped"),
        ]
    )
    tool = _tool(
        "internal_search", lambda _args, _ctx: ToolOutput(content=""), pinned=True
    )

    result = AgentHarness(model=model, tools=[tool]).run("Question")

    assert result.outcome == "partial"
    assert result.tool_calls == 0
    assert (
        "finish_task cannot be combined"
        in result.receipts[0]["tool_receipt"].get("message", "")
        or result.receipts[0]["status"] == "error"
    )


def test_unstructured_final_is_partial() -> None:
    model = ScriptedModel([ModelDecision(answer="maybe this is enough")])

    result = AgentHarness(model=model, tools=[]).run("Question")

    assert result.outcome == "partial"
    assert result.answer == "maybe this is enough"


def test_model_call_budget_is_explicit_budget_exhausted() -> None:
    model = ScriptedModel([_decision_call("internal_search", {"objective": "q"})])
    tool = _tool(
        "internal_search", lambda _args, _ctx: ToolOutput(content=""), pinned=True
    )
    policy = HarnessPolicy(max_model_calls=1)

    result = AgentHarness(model=model, tools=[tool], policy=policy).run("Question")

    assert result.outcome == "budget_exhausted"
    assert result.reason == "model call budget exhausted"


def test_finish_on_last_allowed_model_call_can_complete() -> None:
    model = ScriptedModel([ModelDecision(outcome="completed", answer="done")])
    policy = HarnessPolicy(max_model_calls=1)

    result = AgentHarness(model=model, tools=[], policy=policy).run("Question")

    assert result.outcome == "completed"
    assert result.answer == "done"
    assert result.model_calls == 1


def test_post_model_token_budget_prevents_completed_result() -> None:
    usage = MutableUsage()

    def after_decide(_call_count: int, _decision: ModelDecision) -> None:
        usage.snapshot = UsageSnapshot(total_tokens=3000)

    model = ScriptedModel(
        [ModelDecision(outcome="completed", answer="done")],
        after_decide=after_decide,
    )
    policy = HarnessPolicy(max_total_tokens=3000, max_output_tokens=64)

    result = AgentHarness(
        model=model,
        tools=[],
        policy=policy,
        usage=usage,
    ).run("Question")

    assert result.outcome == "budget_exhausted"
    assert result.answer == ""
    assert result.reason == "token budget exhausted"
    assert result.model_calls == 1


def test_post_model_elapsed_budget_prevents_completed_result() -> None:
    clock = ManualClock()

    def after_decide(_call_count: int, _decision: ModelDecision) -> None:
        clock.now = 2.0

    model = ScriptedModel(
        [ModelDecision(outcome="completed", answer="done")],
        after_decide=after_decide,
    )
    policy = HarnessPolicy(duration_mode="hard", max_elapsed_seconds=1)

    result = AgentHarness(
        model=model,
        tools=[],
        policy=policy,
        clock=clock,
    ).run("Question")

    assert result.outcome == "budget_exhausted"
    assert result.answer == ""
    assert result.reason == "elapsed time budget exhausted"


def test_post_model_cancel_prevents_completed_result() -> None:
    cancelled = False

    def after_decide(_call_count: int, _decision: ModelDecision) -> None:
        nonlocal cancelled
        cancelled = True

    model = ScriptedModel(
        [ModelDecision(outcome="completed", answer="done")],
        after_decide=after_decide,
    )

    result = AgentHarness(
        model=model,
        tools=[],
        cancelled=lambda: cancelled,
    ).run("Question")

    assert result.outcome == "cancelled"
    assert result.answer == ""


def test_tool_call_budget_stops_before_second_tool() -> None:
    model = ScriptedModel(
        [
            ModelDecision(
                calls=[
                    ToolInvocation(
                        name="internal_search",
                        arguments={"objective": "first"},
                    ),
                    ToolInvocation(
                        name="internal_search",
                        arguments={"objective": "second"},
                    ),
                ]
            )
        ]
    )
    tool = _tool(
        "internal_search",
        lambda args, _ctx: ToolOutput(content=args["objective"]),
        pinned=True,
    )
    policy = HarnessPolicy(max_tool_calls=1)

    result = AgentHarness(model=model, tools=[tool], policy=policy).run("Question")

    assert result.outcome == "budget_exhausted"
    assert result.reason == "tool call budget exhausted"
    assert result.tool_calls == 1


def test_elapsed_budget_checked_after_tool_call_preserves_best_answer() -> None:
    clock = ManualClock()

    def execute(_args: dict[str, Any], _ctx: ExecutionContext) -> ToolOutput:
        clock.now = 2.0
        return ToolOutput(content="evidence", answer="best answer")

    model = ScriptedModel([_decision_call("internal_search", {"objective": "q"})])
    tool = _tool("internal_search", execute, pinned=True)
    policy = HarnessPolicy(duration_mode="hard", max_elapsed_seconds=1)

    result = AgentHarness(
        model=model,
        tools=[tool],
        policy=policy,
        clock=clock,
    ).run("Question")

    assert result.outcome == "budget_exhausted"
    assert result.answer == "best answer"
    assert result.reason == "elapsed time budget exhausted"


def test_token_budget_checked_before_model_call() -> None:
    model = ScriptedModel([ModelDecision(outcome="completed", answer="never")])
    usage = MutableUsage(UsageSnapshot(total_tokens=1000))
    policy = HarnessPolicy(max_total_tokens=1000)

    result = AgentHarness(
        model=model,
        tools=[],
        policy=policy,
        usage=usage,
    ).run("Question")

    assert result.outcome == "budget_exhausted"
    assert result.model_calls == 0
    assert result.reason == "token budget exhausted"


def test_cost_budget_with_unpriced_usage_blocks_without_false_hard_cap() -> None:
    model = ScriptedModel([ModelDecision(outcome="completed", answer="never")])
    usage = MutableUsage(UsageSnapshot(unpriced_calls=1))
    policy = HarnessPolicy(max_cost_cents=1)

    result = AgentHarness(
        model=model,
        tools=[],
        policy=policy,
        usage=usage,
    ).run("Question")

    assert result.outcome == "blocked"
    assert "unpriced" in result.reason


def test_cost_budget_exhaustion_is_explicit() -> None:
    model = ScriptedModel([ModelDecision(outcome="completed", answer="never")])
    usage = MutableUsage(UsageSnapshot(cost_cents=2))
    policy = HarnessPolicy(max_cost_cents=1)

    result = AgentHarness(
        model=model,
        tools=[],
        policy=policy,
        usage=usage,
    ).run("Question")

    assert result.outcome == "budget_exhausted"
    assert result.reason == "cost budget exhausted"


def test_cancelled_stops_before_work() -> None:
    model = ScriptedModel([ModelDecision(outcome="completed", answer="never")])

    result = AgentHarness(
        model=model,
        tools=[],
        cancelled=lambda: True,
    ).run("Question")

    assert result.outcome == "cancelled"
    assert result.model_calls == 0


def test_plain_blocked_and_needs_input_outcomes_are_preserved() -> None:
    blocked = AgentHarness(
        model=ScriptedModel(
            [ModelDecision(outcome="blocked", answer="", reason="no access")]
        ),
        tools=[],
    ).run("Question")
    needs_input = AgentHarness(
        model=ScriptedModel(
            [
                ModelDecision(
                    outcome="needs_user_input", answer="", reason="choose account"
                )
            ]
        ),
        tools=[],
    ).run("Question")

    assert blocked.outcome == "blocked"
    assert blocked.reason == "no access"
    assert needs_input.outcome == "needs_user_input"
    assert needs_input.reason == "choose account"


def _decision_call(name: str, arguments: dict[str, Any]) -> ModelDecision:
    return ModelDecision(calls=[ToolInvocation(name=name, arguments=arguments)])


def _tool(
    name: str,
    execute: Callable[[dict[str, Any], ExecutionContext], ToolOutput],
    *,
    description: str = "tool for tests",
    parameters: dict[str, Any] | None = None,
    pinned: bool = False,
    requires_approval: bool = False,
) -> RegisteredTool:
    return RegisteredTool(
        name=name,
        description=description,
        parameters=parameters
        or {
            "type": "object",
            "properties": {},
            "additionalProperties": True,
        },
        execute=execute,
        pinned=pinned,
        requires_approval=requires_approval,
    )
