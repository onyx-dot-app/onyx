"""Engine behaviour: traversal, branching, fan-out, retries and resume."""

import time
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from onyx.db.enums import FlowErrorClass, FlowNodeKind, FlowNodeRunStatus, FlowRunStatus
from onyx.flows import engine as engine_module
from onyx.flows.engine import (
    InMemoryRecorder,
    RecordedNode,
    execute_flow,
)
from onyx.flows.models import parse_spec
from onyx.flows.nodes import NodeRuntime
from onyx.flows.nodes.base import NodeExecutionError, NodeOutcome


@pytest.fixture
def runtime() -> NodeRuntime:
    """Transform and condition nodes touch neither dependency."""
    return NodeRuntime(http_client=MagicMock(), llm_provider=MagicMock())


def transform(node_id: str, value: str, **overrides: Any) -> dict:
    node = {"id": node_id, "kind": "TRANSFORM", "fields": {"value": value}}
    node.update(overrides)
    return node


def statuses(recorder: InMemoryRecorder) -> dict[str, Any]:
    return {entry["node_id"]: entry["status"] for entry in recorder.entries}


def test_runs_a_linear_flow_in_order(runtime: NodeRuntime) -> None:
    spec = parse_spec(
        {
            "start": "first",
            "nodes": [
                transform("first", "{{ trigger.name }}", next=["second"]),
                transform("second", "hello {{ steps.first.value }}"),
            ],
        }
    )
    recorder = InMemoryRecorder()

    result = execute_flow(
        spec=spec,
        runtime=runtime,
        recorder=recorder,
        trigger_payload={"name": "ada"},
    )

    assert result.status == FlowRunStatus.SUCCEEDED
    assert result.outputs["second"] == {"value": "hello ada"}
    assert [entry["node_id"] for entry in recorder.entries] == ["first", "second"]


def test_condition_takes_the_true_branch_and_skips_the_other(
    runtime: NodeRuntime,
) -> None:
    spec = parse_spec(
        {
            "start": "check",
            "nodes": [
                {
                    "id": "check",
                    "kind": "CONDITION",
                    "left": "{{ trigger.count }}",
                    "operator": "gt",
                    "right": "5",
                    "on_true": ["big"],
                    "on_false": ["small"],
                },
                transform("big", "big"),
                transform("small", "small"),
            ],
        }
    )
    recorder = InMemoryRecorder()

    result = execute_flow(
        spec=spec, runtime=runtime, recorder=recorder, trigger_payload={"count": 9}
    )

    assert result.status == FlowRunStatus.SUCCEEDED
    assert result.outputs["check"]["matched"] is True
    assert result.outputs["big"] == {"value": "big"}
    assert "small" not in result.outputs
    assert statuses(recorder)["small"] == FlowNodeRunStatus.SKIPPED


def test_condition_compares_across_the_json_text_boundary(
    runtime: NodeRuntime,
) -> None:
    """A webhook delivers "200"; an HTTP node produces 200. Both must match."""
    spec = parse_spec(
        {
            "start": "check",
            "nodes": [
                {
                    "id": "check",
                    "kind": "CONDITION",
                    "left": "{{ trigger.status }}",
                    "operator": "eq",
                    "right": "200",
                    "on_true": ["ok"],
                },
                transform("ok", "ok"),
            ],
        }
    )

    result = execute_flow(
        spec=spec,
        runtime=runtime,
        recorder=InMemoryRecorder(),
        trigger_payload={"status": 200},
    )
    assert result.outputs["check"]["matched"] is True


def test_diamond_runs_the_join_once(runtime: NodeRuntime) -> None:
    spec = parse_spec(
        {
            "start": "split",
            "nodes": [
                transform("split", "x", next=["left", "right"]),
                transform("left", "L", next=["join"]),
                transform("right", "R", next=["join"]),
                transform("join", "{{ steps.left.value }}{{ steps.right.value }}"),
            ],
        }
    )
    recorder = InMemoryRecorder()

    result = execute_flow(spec=spec, runtime=runtime, recorder=recorder)

    assert result.outputs["join"] == {"value": "LR"}
    join_entries = [e for e in recorder.entries if e["node_id"] == "join"]
    assert len(join_entries) == 1


def test_unreachable_nodes_are_never_touched(runtime: NodeRuntime) -> None:
    spec = parse_spec(
        {"start": "a", "nodes": [transform("a", "a"), transform("orphan", "o")]}
    )
    recorder = InMemoryRecorder()

    result = execute_flow(spec=spec, runtime=runtime, recorder=recorder)

    assert "orphan" not in result.outputs
    assert "orphan" not in statuses(recorder)


def test_for_each_runs_once_per_item(runtime: NodeRuntime) -> None:
    spec = parse_spec(
        {
            "start": "each",
            "nodes": [
                transform(
                    "each",
                    "{{ index }}:{{ item.name }}",
                    for_each="{{ trigger.rows }}",
                )
            ],
        }
    )
    recorder = InMemoryRecorder()

    result = execute_flow(
        spec=spec,
        runtime=runtime,
        recorder=recorder,
        trigger_payload={"rows": [{"name": "a"}, {"name": "b"}, {"name": "c"}]},
    )

    assert result.outputs["each"] == [
        {"value": "0:a"},
        {"value": "1:b"},
        {"value": "2:c"},
    ]
    assert [e["item_index"] for e in recorder.entries] == [0, 1, 2]


def test_for_each_over_an_empty_list_produces_nothing(runtime: NodeRuntime) -> None:
    spec = parse_spec(
        {
            "start": "each",
            "nodes": [transform("each", "{{ item }}", for_each="{{ trigger.rows }}")],
        }
    )

    result = execute_flow(
        spec=spec,
        runtime=runtime,
        recorder=InMemoryRecorder(),
        trigger_payload={"rows": []},
    )

    assert result.status == FlowRunStatus.SUCCEEDED
    assert result.outputs["each"] == []


def test_for_each_rejects_a_non_list(runtime: NodeRuntime) -> None:
    spec = parse_spec(
        {
            "start": "each",
            "nodes": [transform("each", "{{ item }}", for_each="{{ trigger.rows }}")],
        }
    )

    result = execute_flow(
        spec=spec,
        runtime=runtime,
        recorder=InMemoryRecorder(),
        trigger_payload={"rows": "not a list"},
    )

    assert result.status == FlowRunStatus.FAILED
    assert result.error_class == FlowErrorClass.EXPRESSION_ERROR
    assert "must resolve to a list" in (result.error_detail or "")


def test_a_missing_reference_fails_the_run(runtime: NodeRuntime) -> None:
    spec = parse_spec({"start": "a", "nodes": [transform("a", "{{ trigger.nope }}")]})

    result = execute_flow(
        spec=spec,
        runtime=runtime,
        recorder=InMemoryRecorder(),
        trigger_payload={},
    )

    assert result.status == FlowRunStatus.FAILED
    assert result.failed_node_id == "a"
    assert result.error_class == FlowErrorClass.NODE_EXCEPTION


def test_on_error_skip_keeps_the_run_going(
    runtime: NodeRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = parse_spec(
        {
            "start": "flaky",
            "nodes": [
                transform("flaky", "x", next=["after"], on_error="skip"),
                transform("after", "reached"),
            ],
        }
    )
    _always_fail(monkeypatch, FlowErrorClass.HTTP_ERROR, only_node="flaky")

    result = execute_flow(spec=spec, runtime=runtime, recorder=InMemoryRecorder())

    assert result.status == FlowRunStatus.SUCCEEDED
    assert result.outputs["flaky"] is None
    assert result.outputs["after"] == {"value": "reached"}


def test_transient_failures_are_retried(
    runtime: NodeRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _fail_then_succeed(monkeypatch, FlowErrorClass.HTTP_ERROR, failures=2)
    monkeypatch.setattr(engine_module.time, "sleep", lambda _seconds: None)
    spec = parse_spec(
        {
            "start": "flaky",
            "nodes": [
                transform(
                    "flaky", "x", retry={"max_attempts": 3, "backoff_seconds": 0.0}
                )
            ],
        }
    )

    result = execute_flow(spec=spec, runtime=runtime, recorder=InMemoryRecorder())

    assert result.status == FlowRunStatus.SUCCEEDED
    assert calls["count"] == 3


def test_expression_errors_are_not_retried(
    runtime: NodeRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _fail_then_succeed(monkeypatch, FlowErrorClass.EXPRESSION_ERROR, failures=1)
    spec = parse_spec(
        {
            "start": "broken",
            "nodes": [
                transform(
                    "broken", "x", retry={"max_attempts": 3, "backoff_seconds": 0.0}
                )
            ],
        }
    )

    result = execute_flow(spec=spec, runtime=runtime, recorder=InMemoryRecorder())

    assert result.status == FlowRunStatus.FAILED
    assert calls["count"] == 1, "a deterministic failure should not be retried"


def test_a_finished_node_is_not_run_again(runtime: NodeRuntime) -> None:
    """A redelivered Celery message must not repeat a side effect."""
    spec = parse_spec(
        {
            "start": "already",
            "nodes": [
                transform("already", "fresh", next=["after"]),
                transform("after", "{{ steps.already.value }}"),
            ],
        }
    )
    recorder = InMemoryRecorder()
    recorder._finished[("already", 0, 0)] = RecordedNode(
        status=FlowNodeRunStatus.SUCCEEDED, output={"value": "from the first attempt"}
    )

    result = execute_flow(spec=spec, runtime=runtime, recorder=recorder)

    assert result.outputs["already"] == {"value": "from the first attempt"}
    assert result.outputs["after"] == {"value": "from the first attempt"}


def test_run_stops_when_the_budget_is_gone(runtime: NodeRuntime) -> None:
    spec = parse_spec(
        {
            "start": "a",
            "nodes": [transform("a", "a", next=["b"]), transform("b", "b")],
        }
    )

    result = execute_flow(
        spec=spec, runtime=runtime, recorder=InMemoryRecorder(), budget_seconds=-1.0
    )

    assert result.status == FlowRunStatus.FAILED
    assert result.error_class == FlowErrorClass.BUDGET_EXCEEDED
    assert result.failed_node_id == "a"


def _always_fail(
    monkeypatch: pytest.MonkeyPatch, error_class: FlowErrorClass, only_node: str
) -> None:
    """Fail one node; leave the rest of the graph working."""
    real = engine_module.NODE_EXECUTORS[FlowNodeKind.TRANSFORM]

    def boom(node: Any, context: Any, runtime: Any) -> NodeOutcome:
        if node.id == only_node:
            raise NodeExecutionError(error_class, "nope")
        return real(node, context, runtime)

    monkeypatch.setitem(engine_module.NODE_EXECUTORS, FlowNodeKind.TRANSFORM, boom)


def _fail_then_succeed(
    monkeypatch: pytest.MonkeyPatch, error_class: FlowErrorClass, failures: int
) -> dict[str, int]:
    calls = {"count": 0}

    def flaky(_node: Any, _context: Any, _runtime: Any) -> NodeOutcome:
        calls["count"] += 1
        if calls["count"] <= failures:
            raise NodeExecutionError(error_class, "transient")
        return NodeOutcome(output={"value": "recovered"})

    monkeypatch.setitem(engine_module.NODE_EXECUTORS, FlowNodeKind.TRANSFORM, flaky)
    return calls


# ---------------------------------------------------------------------------
# Approvals: parking and resuming
# ---------------------------------------------------------------------------


def gated_spec(**gate_overrides: Any) -> Any:
    gate: dict[str, Any] = {
        "id": "gate",
        "kind": "HUMAN",
        "question": "Ship {{ trigger.tag }}?",
    }
    gate.update(gate_overrides)
    return parse_spec(
        {
            "start": "prepare",
            "nodes": [
                transform("prepare", "{{ trigger.tag }}", next=["gate"]),
                gate,
                transform("ship", "shipped"),
                transform("tell", "told"),
            ],
        }
    )


def approved(comment: str | None = None) -> RecordedNode:
    return RecordedNode(
        status=FlowNodeRunStatus.SUCCEEDED,
        output={"decision": "approve", "comment": comment},
    )


def rejected(comment: str | None = None) -> RecordedNode:
    return RecordedNode(
        status=FlowNodeRunStatus.SUCCEEDED,
        output={"decision": "reject", "comment": comment},
    )


def test_an_approval_parks_the_run_without_touching_what_follows(
    runtime: NodeRuntime,
) -> None:
    spec = gated_spec(on_approve=["ship"], on_reject=["tell"])
    recorder = InMemoryRecorder()

    result = execute_flow(
        spec=spec,
        runtime=runtime,
        recorder=recorder,
        trigger_payload={"tag": "v3"},
    )

    assert result.status == FlowRunStatus.AWAITING_DECISION
    assert result.error_class is None
    assert result.outputs["prepare"] == {"value": "v3"}

    parked = [entry for entry in recorder.entries if "waiting_for" in entry]
    assert parked == [
        {
            "node_id": "gate",
            "iteration": 0,
            "item_index": 0,
            "status": FlowNodeRunStatus.RUNNING,
            "waiting_for": {"question": "Ship v3?", "assignee": None},
        }
    ]
    assert "ship" not in statuses(recorder), "a parked run must not run ahead"
    assert "tell" not in statuses(recorder)


def test_parking_is_not_swallowed_by_on_error_skip(runtime: NodeRuntime) -> None:
    """`on_error: skip` covers failures. Waiting is not a failure."""
    spec = gated_spec(on_approve=["ship"], on_error="skip")

    result = execute_flow(
        spec=spec,
        runtime=runtime,
        recorder=InMemoryRecorder(),
        trigger_payload={"tag": "v3"},
    )

    assert result.status == FlowRunStatus.AWAITING_DECISION


def test_an_approved_run_resumes_down_the_approve_branch(runtime: NodeRuntime) -> None:
    spec = gated_spec(on_approve=["ship"], on_reject=["tell"])
    recorder = InMemoryRecorder()
    recorder._finished[("gate", 0, 0)] = approved()

    result = execute_flow(
        spec=spec,
        runtime=runtime,
        recorder=recorder,
        trigger_payload={"tag": "v3"},
    )

    assert result.status == FlowRunStatus.SUCCEEDED
    assert result.outputs["ship"] == {"value": "shipped"}
    assert "tell" not in result.outputs
    assert statuses(recorder)["tell"] == FlowNodeRunStatus.SKIPPED


def test_a_rejected_run_resumes_down_the_reject_branch(runtime: NodeRuntime) -> None:
    spec = gated_spec(on_approve=["ship"], on_reject=["tell"])
    recorder = InMemoryRecorder()
    recorder._finished[("gate", 0, 0)] = rejected("not this week")

    result = execute_flow(
        spec=spec,
        runtime=runtime,
        recorder=recorder,
        trigger_payload={"tag": "v3"},
    )

    assert result.status == FlowRunStatus.SUCCEEDED
    assert result.outputs["tell"] == {"value": "told"}
    assert statuses(recorder)["ship"] == FlowNodeRunStatus.SKIPPED


def test_rejecting_a_gate_with_no_reject_branch_fails_the_run(
    runtime: NodeRuntime,
) -> None:
    spec = gated_spec(on_approve=["ship"])
    recorder = InMemoryRecorder()
    recorder._finished[("gate", 0, 0)] = rejected("the numbers are wrong")

    result = execute_flow(
        spec=spec,
        runtime=runtime,
        recorder=recorder,
        trigger_payload={"tag": "v3"},
    )

    assert result.status == FlowRunStatus.FAILED
    assert result.error_class == FlowErrorClass.DECISION_REJECTED
    assert result.failed_node_id == "gate"
    assert result.error_detail == "rejected: the numbers are wrong"


def test_a_replayed_condition_keeps_the_branch_it_first_took(
    runtime: NodeRuntime,
) -> None:
    """A resumed run reads the branch off the row, and must not lose it.

    The recorded comparison says the true branch was taken. Reusing the output
    without re-deriving the branch would leave the node handing control to its
    empty `next` list, and everything downstream would be skipped.
    """
    spec = parse_spec(
        {
            "start": "check",
            "nodes": [
                {
                    "id": "check",
                    "kind": "CONDITION",
                    "left": "{{ trigger.count }}",
                    "operator": "gt",
                    "right": "5",
                    "on_true": ["big"],
                    "on_false": ["small"],
                },
                transform("big", "big"),
                transform("small", "small"),
            ],
        }
    )
    recorder = InMemoryRecorder()
    recorder._finished[("check", 0, 0)] = RecordedNode(
        status=FlowNodeRunStatus.SUCCEEDED,
        output={"matched": True, "left": 9, "right": 5},
    )

    result = execute_flow(spec=spec, runtime=runtime, recorder=recorder)

    assert result.outputs["big"] == {"value": "big"}
    assert statuses(recorder)["small"] == FlowNodeRunStatus.SKIPPED


# ---------------------------------------------------------------------------
# Delays: parking on the clock
# ---------------------------------------------------------------------------


def delayed_spec(seconds: float) -> Any:
    return parse_spec(
        {
            "start": "prepare",
            "nodes": [
                transform("prepare", "ready", next=["wait"]),
                {"id": "wait", "kind": "DELAY", "seconds": seconds, "next": ["after"]},
                transform("after", "done"),
            ],
        }
    )


def test_a_long_delay_parks_the_run_with_the_time_it_is_due(
    runtime: NodeRuntime,
) -> None:
    recorder = InMemoryRecorder()

    result = execute_flow(spec=delayed_spec(7200), runtime=runtime, recorder=recorder)

    assert result.status == FlowRunStatus.AWAITING_DELAY
    assert result.error_class is None
    assert result.resume_at is not None
    assert result.resume_at > datetime.now(tz=timezone.utc)
    assert "after" not in statuses(recorder), "a parked run must not run ahead"


def test_a_short_delay_does_not_park_at_all(runtime: NodeRuntime) -> None:
    result = execute_flow(
        spec=delayed_spec(0), runtime=runtime, recorder=InMemoryRecorder()
    )

    assert result.status == FlowRunStatus.SUCCEEDED
    assert result.resume_at is None
    assert result.outputs["after"] == {"value": "done"}


def test_a_resumed_delay_does_not_wait_again(runtime: NodeRuntime) -> None:
    """The row the sweep closed is what stops the replay walking back in."""
    recorder = InMemoryRecorder()
    recorder._finished[("wait", 0, 0)] = RecordedNode(
        status=FlowNodeRunStatus.SUCCEEDED,
        output={"waited_seconds": 7200, "parked": True},
    )

    result = execute_flow(spec=delayed_spec(7200), runtime=runtime, recorder=recorder)

    assert result.status == FlowRunStatus.SUCCEEDED
    assert result.outputs["after"] == {"value": "done"}


def test_parking_on_a_delay_is_not_swallowed_by_on_error_skip(
    runtime: NodeRuntime,
) -> None:
    spec = parse_spec(
        {
            "start": "wait",
            "nodes": [
                {"id": "wait", "kind": "DELAY", "seconds": 7200, "on_error": "skip"}
            ],
        }
    )

    result = execute_flow(spec=spec, runtime=runtime, recorder=InMemoryRecorder())

    assert result.status == FlowRunStatus.AWAITING_DELAY


# ---------------------------------------------------------------------------
# Merging branches back together
# ---------------------------------------------------------------------------


def branching_merge_spec() -> Any:
    """A condition, a step on each side, and a merge below both."""
    return parse_spec(
        {
            "start": "check",
            "nodes": [
                {
                    "id": "check",
                    "kind": "CONDITION",
                    "left": "{{ trigger.count }}",
                    "operator": "gt",
                    "right": "5",
                    "on_true": ["big"],
                    "on_false": ["small"],
                },
                transform("big", "big", next=["both"]),
                transform("small", "small", next=["both"]),
                {"id": "both", "kind": "MERGE", "sources": ["big", "small"]},
            ],
        }
    )


def test_a_merge_below_a_condition_reports_which_branch_arrived(
    runtime: NodeRuntime,
) -> None:
    """The join already worked; seeing what the other side did is the new part."""
    recorder = InMemoryRecorder()

    result = execute_flow(
        spec=branching_merge_spec(),
        runtime=runtime,
        recorder=recorder,
        trigger_payload={"count": 9},
    )

    assert result.status == FlowRunStatus.SUCCEEDED
    assert result.outputs["both"]["values"]["big"] == {"value": "big"}
    assert result.outputs["both"]["present"] == ["big"]
    assert result.outputs["both"]["missing"] == ["small"]
    assert statuses(recorder)["small"] == FlowNodeRunStatus.SKIPPED


def test_a_merge_runs_once_even_though_two_branches_reach_it(
    runtime: NodeRuntime,
) -> None:
    spec = parse_spec(
        {
            "start": "split",
            "nodes": [
                transform("split", "start", next=["left", "right"]),
                transform("left", "L", next=["both"]),
                transform("right", "R", next=["both"]),
                {"id": "both", "kind": "MERGE", "sources": ["left", "right"]},
            ],
        }
    )
    recorder = InMemoryRecorder()

    result = execute_flow(spec=spec, runtime=runtime, recorder=recorder)

    merged = [entry for entry in recorder.entries if entry["node_id"] == "both"]
    assert len(merged) == 1, "a join must not run once per incoming branch"
    assert result.outputs["both"]["present"] == ["left", "right"]


# ---------------------------------------------------------------------------
# Switching between several branches
# ---------------------------------------------------------------------------


def switch_spec() -> Any:
    return parse_spec(
        {
            "start": "route",
            "nodes": [
                {
                    "id": "route",
                    "kind": "SWITCH",
                    "value": "{{ trigger.priority }}",
                    "cases": [
                        {"equals": "high", "then": ["page"]},
                        {"equals": "low", "then": ["queue"]},
                    ],
                    "otherwise": ["triage"],
                },
                transform("page", "paged", next=["done"]),
                transform("queue", "queued", next=["done"]),
                transform("triage", "triaged", next=["done"]),
                transform("done", "done"),
            ],
        }
    )


@pytest.mark.parametrize(
    "priority, taken",
    [("high", "page"), ("low", "queue"), ("whatever", "triage")],
)
def test_a_switch_runs_one_branch_and_skips_the_rest(
    runtime: NodeRuntime, priority: str, taken: str
) -> None:
    recorder = InMemoryRecorder()

    result = execute_flow(
        spec=switch_spec(),
        runtime=runtime,
        recorder=recorder,
        trigger_payload={"priority": priority},
    )

    assert result.status == FlowRunStatus.SUCCEEDED
    ran = {"page", "queue", "triage"} & set(result.outputs)
    assert ran == {taken}
    for branch in {"page", "queue", "triage"} - {taken}:
        assert statuses(recorder)[branch] == FlowNodeRunStatus.SKIPPED
    assert result.outputs["done"] == {"value": "done"}, "the branches rejoin"


def test_a_replayed_switch_keeps_the_branch_it_first_took(
    runtime: NodeRuntime,
) -> None:
    """The row says case 1 was taken, and the trigger now says otherwise.

    Replay follows the row. Without a replayer the node would hand control to
    its empty `next` and skip every branch; re-evaluating would pick the
    wrong one.
    """
    recorder = InMemoryRecorder()
    recorder._finished[("route", 0, 0)] = RecordedNode(
        status=FlowNodeRunStatus.SUCCEEDED,
        output={"value": "low", "case": 1, "equals": "low"},
    )

    result = execute_flow(
        spec=switch_spec(),
        runtime=runtime,
        recorder=recorder,
        trigger_payload={"priority": "high"},
    )

    assert result.outputs["queue"] == {"value": "queued"}
    assert statuses(recorder)["page"] == FlowNodeRunStatus.SKIPPED
    assert statuses(recorder)["triage"] == FlowNodeRunStatus.SKIPPED


# ---------------------------------------------------------------------------
# Parallel calls
# ---------------------------------------------------------------------------


def test_a_parallel_step_stops_sending_when_the_run_budget_runs_out() -> None:
    """The engine hands its deadline to the node, not only checks it between
    nodes — otherwise one step could spend the budget several times over."""
    sent: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(str(request.url))
        time.sleep(0.3)
        return httpx.Response(200, json={})

    spec = parse_spec(
        {
            "start": "lookup",
            "nodes": [
                {
                    "id": "lookup",
                    "kind": "PARALLEL",
                    "url": "https://api.test/users/{{ item }}",
                    "over": "{{ trigger.ids }}",
                    "concurrency": 1,
                }
            ],
        }
    )
    runtime = NodeRuntime(
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        llm_provider=MagicMock(),
    )

    result = execute_flow(
        spec=spec,
        runtime=runtime,
        recorder=InMemoryRecorder(),
        trigger_payload={"ids": [1, 2, 3]},
        budget_seconds=0.2,
    )

    assert result.status == FlowRunStatus.FAILED
    assert result.error_class == FlowErrorClass.BUDGET_EXCEEDED
    assert result.failed_node_id == "lookup"
    assert result.error_detail == "run ran out of time after sending 1 of 3 calls"
    assert sent == ["https://api.test/users/1"]


# ---------------------------------------------------------------------------
# Pausing between fan-out items
# ---------------------------------------------------------------------------


@pytest.fixture
def pauses(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Every sleep the engine asks for, instead of the sleep itself."""
    asked: list[float] = []
    monkeypatch.setattr(engine_module.time, "sleep", asked.append)
    return asked


def paced_spec(pause_seconds: float) -> Any:
    return parse_spec(
        {
            "start": "send",
            "nodes": [
                transform(
                    "send",
                    "{{ item }}",
                    for_each="{{ trigger.batches }}",
                    pause_seconds=pause_seconds,
                )
            ],
        }
    )


def sent(value: Any) -> RecordedNode:
    return RecordedNode(status=FlowNodeRunStatus.SUCCEEDED, output={"value": value})


def test_a_paced_fan_out_waits_between_items_but_not_after_the_last(
    runtime: NodeRuntime, pauses: list[float]
) -> None:
    result = execute_flow(
        spec=paced_spec(2),
        runtime=runtime,
        recorder=InMemoryRecorder(),
        trigger_payload={"batches": ["a", "b", "c"]},
    )

    assert result.status == FlowRunStatus.SUCCEEDED
    assert result.outputs["send"] == [{"value": "a"}, {"value": "b"}, {"value": "c"}]
    assert pauses == [2, 2]


def test_a_replayed_fan_out_does_not_wait_again(
    runtime: NodeRuntime, pauses: list[float]
) -> None:
    """A resumed run replays every finished item. None of them made a call,
    so none of them is owed a pause."""
    recorder = InMemoryRecorder()
    for index, batch in enumerate(["a", "b", "c"]):
        recorder._finished[("send", 0, index)] = sent(batch)

    result = execute_flow(
        spec=paced_spec(30),
        runtime=runtime,
        recorder=recorder,
        trigger_payload={"batches": ["a", "b", "c"]},
    )

    assert result.status == FlowRunStatus.SUCCEEDED
    assert pauses == []


def test_a_fan_out_resumed_midway_waits_only_between_new_items(
    runtime: NodeRuntime, pauses: list[float]
) -> None:
    recorder = InMemoryRecorder()
    recorder._finished[("send", 0, 0)] = sent("a")
    recorder._finished[("send", 0, 1)] = sent("b")

    result = execute_flow(
        spec=paced_spec(2),
        runtime=runtime,
        recorder=recorder,
        trigger_payload={"batches": ["a", "b", "c", "d"]},
    )

    assert result.outputs["send"][2:] == [{"value": "c"}, {"value": "d"}]
    assert pauses == [2], "one pause, between the two items that ran"


def test_a_pause_the_budget_cannot_cover_fails_before_sleeping(
    runtime: NodeRuntime, pauses: list[float]
) -> None:
    result = execute_flow(
        spec=paced_spec(30),
        runtime=runtime,
        recorder=InMemoryRecorder(),
        trigger_payload={"batches": ["a", "b"]},
        budget_seconds=5,
    )

    assert result.status == FlowRunStatus.FAILED
    assert result.error_class == FlowErrorClass.BUDGET_EXCEEDED
    assert result.failed_node_id == "send"
    assert result.error_detail == "no time left to pause before item 1 of 'send'"
    assert pauses == []


# ---------------------------------------------------------------------------
# Loops: running a body pass after pass
# ---------------------------------------------------------------------------

# A cursor chain in the trigger, standing in for a paginated API: each page
# names the next, and the last page has no `next` at all.
PAGES = {"id": 1, "next": {"id": 2, "next": {"id": 3}}}


def loop(**overrides: Any) -> dict[str, Any]:
    node: dict[str, Any] = {
        "id": "pages",
        "kind": "REPEAT",
        "body": ["read"],
        "start": "{{ trigger.page }}",
        "until": "{{ item.next }}",
        "operator": "is_empty",
        "carry": "{{ item.next }}",
        "collect": "{{ steps.read.value }}",
        "next": ["after"],
    }
    node.update(overrides)
    return node


def looped_spec(*body: dict[str, Any], **loop_overrides: Any) -> Any:
    return parse_spec(
        {
            "start": "pages",
            "nodes": [
                loop(**loop_overrides),
                *(body or [transform("read", "{{ item.id }}")]),
                transform("after", "{{ steps.pages.results }}"),
            ],
        }
    )


def rows_of(recorder: InMemoryRecorder, node_id: str, status: Any) -> list[int]:
    """The passes a node has a row of this status for, in order."""
    return [
        entry["iteration"]
        for entry in recorder.entries
        if entry["node_id"] == node_id and entry["status"] == status
    ]


def test_a_loop_follows_a_cursor_until_it_runs_out(runtime: NodeRuntime) -> None:
    recorder = InMemoryRecorder()

    result = execute_flow(
        spec=looped_spec(),
        runtime=runtime,
        recorder=recorder,
        trigger_payload={"page": PAGES},
    )

    assert result.status == FlowRunStatus.SUCCEEDED
    assert result.outputs["pages"] == {
        "passes": 3,
        "satisfied": True,
        "results": [1, 2, 3],
    }
    # What follows the loop runs once, after it, and sees the last pass.
    assert result.outputs["after"] == {"value": [1, 2, 3]}
    assert result.outputs["read"] == {"value": 3}
    assert rows_of(recorder, "read", FlowNodeRunStatus.SUCCEEDED) == [0, 1, 2]
    assert rows_of(recorder, "after", FlowNodeRunStatus.SUCCEEDED) == [0]
    # The walk around the loop leaves the loop's steps to the loop.
    assert rows_of(recorder, "read", FlowNodeRunStatus.SKIPPED) == []


def test_a_cursor_that_is_simply_left_out_counts_as_the_end(
    runtime: NodeRuntime,
) -> None:
    """The last page has no `next` key at all. That is an API saying "no
    more", not an error, so the loop ends instead of failing."""
    result = execute_flow(
        spec=looped_spec(),
        runtime=runtime,
        recorder=InMemoryRecorder(),
        trigger_payload={"page": {"id": 1}},
    )

    assert result.status == FlowRunStatus.SUCCEEDED
    assert result.outputs["pages"]["passes"] == 1


def test_each_pass_knows_its_number(runtime: NodeRuntime) -> None:
    spec = looped_spec(
        transform("read", "{{ index }}"),
        start=None,
        carry=None,
        until="{{ index }}",
        operator="eq",
        value="2",
    )

    result = execute_flow(spec=spec, runtime=runtime, recorder=InMemoryRecorder())

    assert result.outputs["pages"]["results"] == [0, 1, 2]


def test_a_branch_inside_the_loop_is_decided_again_every_pass(
    runtime: NodeRuntime,
) -> None:
    spec = looped_spec(
        {
            "id": "read",
            "kind": "CONDITION",
            "left": "{{ index }}",
            "operator": "eq",
            "right": "1",
            "on_true": ["odd"],
            "on_false": ["even"],
        },
        transform("odd", "odd"),
        transform("even", "even"),
        start=None,
        carry=None,
        collect=None,
        until="{{ index }}",
        operator="eq",
        value="2",
    )
    recorder = InMemoryRecorder()

    execute_flow(spec=spec, runtime=runtime, recorder=recorder)

    assert rows_of(recorder, "even", FlowNodeRunStatus.SUCCEEDED) == [0, 2]
    assert rows_of(recorder, "even", FlowNodeRunStatus.SKIPPED) == [1]
    assert rows_of(recorder, "odd", FlowNodeRunStatus.SUCCEEDED) == [1]
    assert rows_of(recorder, "odd", FlowNodeRunStatus.SKIPPED) == [0, 2]


def test_a_pass_cannot_read_a_step_it_skipped(runtime: NodeRuntime) -> None:
    """`first` only runs on pass 0. If its output lingered, every later pass
    would collect it again as if it had just run."""
    spec = looped_spec(
        {
            "id": "read",
            "kind": "CONDITION",
            "left": "{{ index }}",
            "operator": "eq",
            "right": "0",
            "on_true": ["first"],
        },
        transform("first", "only once"),
        start=None,
        carry=None,
        collect="{{ steps.first.value }}",
        until="{{ index }}",
        operator="eq",
        value="2",
    )

    result = execute_flow(spec=spec, runtime=runtime, recorder=InMemoryRecorder())

    assert result.outputs["pages"]["results"] == ["only once"]


def test_running_out_of_passes_fails_the_run_by_default(
    runtime: NodeRuntime,
) -> None:
    spec = looped_spec(
        transform("read", "{{ index }}"),
        start=None,
        carry=None,
        until="{{ index }}",
        operator="eq",
        value="99",
        max_passes=3,
    )
    recorder = InMemoryRecorder()

    result = execute_flow(spec=spec, runtime=runtime, recorder=recorder)

    assert result.status == FlowRunStatus.FAILED
    assert result.error_class == FlowErrorClass.LOOP_EXHAUSTED
    assert result.failed_node_id == "pages"
    assert result.error_detail == "still not eq after 3 passes"
    assert rows_of(recorder, "pages", FlowNodeRunStatus.FAILED) == [0]
    assert "after" not in result.outputs


def test_running_out_of_passes_can_be_made_to_carry_on(
    runtime: NodeRuntime,
) -> None:
    spec = looped_spec(
        transform("read", "{{ index }}"),
        start=None,
        carry=None,
        until="{{ index }}",
        operator="eq",
        value="99",
        max_passes=3,
        fail_when_exhausted=False,
    )

    result = execute_flow(spec=spec, runtime=runtime, recorder=InMemoryRecorder())

    assert result.status == FlowRunStatus.SUCCEEDED
    assert result.outputs["pages"]["satisfied"] is False
    assert result.outputs["pages"]["passes"] == 3
    assert "after" in result.outputs


def test_a_step_that_fails_inside_the_loop_is_the_one_the_run_names(
    runtime: NodeRuntime,
) -> None:
    """The second page has no `id`. The run names `read`, the step that
    broke, and the loop's own row says which pass it broke in."""
    recorder = InMemoryRecorder()

    result = execute_flow(
        spec=looped_spec(),
        runtime=runtime,
        recorder=recorder,
        trigger_payload={"page": {"id": 1, "next": {"next": {"id": 3}}}},
    )

    assert result.status == FlowRunStatus.FAILED
    assert result.failed_node_id == "read"
    assert result.error_detail == "ExpressionError: 'item' has no 'id' (it has: next)"
    loop_failure = next(
        entry
        for entry in recorder.entries
        if entry["node_id"] == "pages" and entry["status"] == FlowNodeRunStatus.FAILED
    )
    assert loop_failure["error_detail"].startswith("pass 2 stopped at 'read': ")


def test_a_start_that_cannot_be_read_fails_before_any_pass(
    runtime: NodeRuntime,
) -> None:
    """Only what a loop reads after a pass is forgiving. A start that points
    nowhere is a mistake in the flow."""
    recorder = InMemoryRecorder()

    result = execute_flow(
        spec=looped_spec(start="{{ trigger.nope }}"),
        runtime=runtime,
        recorder=recorder,
        trigger_payload={"page": PAGES},
    )

    assert result.status == FlowRunStatus.FAILED
    assert result.error_class == FlowErrorClass.EXPRESSION_ERROR
    assert result.failed_node_id == "pages"
    assert rows_of(recorder, "read", FlowNodeRunStatus.SUCCEEDED) == []


def test_collecting_more_than_the_fan_out_limit_fails_the_loop(
    runtime: NodeRuntime,
) -> None:
    spec = looped_spec(
        transform("read", "{{ index }}"),
        start=None,
        carry=None,
        collect="{{ trigger.rows }}",
        until="{{ index }}",
        operator="eq",
        value="1",
    )

    result = execute_flow(
        spec=spec,
        runtime=runtime,
        recorder=InMemoryRecorder(),
        trigger_payload={"rows": list(range(150))},
    )

    assert result.status == FlowRunStatus.FAILED
    assert result.error_class == FlowErrorClass.INVALID_SPEC
    assert result.failed_node_id == "pages"


def test_a_loop_on_an_untaken_branch_skips_its_steps_too(
    runtime: NodeRuntime,
) -> None:
    spec = parse_spec(
        {
            "start": "check",
            "nodes": [
                {
                    "id": "check",
                    "kind": "CONDITION",
                    "left": "{{ trigger.go }}",
                    "operator": "eq",
                    "right": "yes",
                    "on_true": ["pages"],
                },
                loop(next=[]),
                transform("read", "{{ item.id }}"),
            ],
        }
    )
    recorder = InMemoryRecorder()

    execute_flow(
        spec=spec, runtime=runtime, recorder=recorder, trigger_payload={"go": "no"}
    )

    assert statuses(recorder)["pages"] == FlowNodeRunStatus.SKIPPED
    assert statuses(recorder)["read"] == FlowNodeRunStatus.SKIPPED


def test_a_finished_loop_replays_without_running_its_body_again(
    runtime: NodeRuntime,
) -> None:
    """A redelivered run reuses every pass's rows. Replaying them is also
    what puts the last pass back into `steps` for the step after the loop."""
    recorder = InMemoryRecorder()
    for index, page in enumerate([1, 2, 3]):
        recorder._finished[("read", index, 0)] = RecordedNode(
            status=FlowNodeRunStatus.SUCCEEDED, output={"value": f"page {page}"}
        )
    recorder._finished[("pages", 0, 0)] = RecordedNode(
        status=FlowNodeRunStatus.SUCCEEDED, output={"passes": 3}
    )

    result = execute_flow(
        spec=looped_spec(),
        runtime=runtime,
        recorder=recorder,
        trigger_payload={"page": PAGES},
    )

    assert result.status == FlowRunStatus.SUCCEEDED
    assert result.outputs["read"] == {"value": "page 3"}
    assert [entry["node_id"] for entry in recorder.entries] == ["after"]


def test_a_loop_cut_off_midway_carries_on_from_the_pass_it_reached(
    runtime: NodeRuntime,
) -> None:
    recorder = InMemoryRecorder()
    recorder._finished[("pages", 0, 0)] = RecordedNode(
        status=FlowNodeRunStatus.RUNNING, output=None
    )
    recorder._finished[("read", 0, 0)] = RecordedNode(
        status=FlowNodeRunStatus.SUCCEEDED, output={"value": 1}
    )

    result = execute_flow(
        spec=looped_spec(),
        runtime=runtime,
        recorder=recorder,
        trigger_payload={"page": PAGES},
    )

    assert result.outputs["pages"]["results"] == [1, 2, 3]
    assert rows_of(recorder, "read", FlowNodeRunStatus.SUCCEEDED) == [1, 2]
    assert rows_of(recorder, "pages", FlowNodeRunStatus.SUCCEEDED) == [0]


def test_an_approval_inside_a_loop_parks_each_pass_and_resumes_in_it(
    runtime: NodeRuntime,
) -> None:
    """Two passes, one question each. Every resume replays the passes
    already answered and parks again at the next open question."""
    spec = looped_spec(
        {
            "id": "read",
            "kind": "HUMAN",
            "question": "Send page {{ item.id }}?",
            "on_approve": ["send"],
        },
        transform("send", "sent {{ item.id }}"),
        collect="{{ steps.send.value }}",
    )
    payload = {"page": {"id": 1, "next": {"id": 2}}}

    first = InMemoryRecorder()
    parked = execute_flow(
        spec=spec, runtime=runtime, recorder=first, trigger_payload=payload
    )
    assert parked.status == FlowRunStatus.AWAITING_DECISION
    assert [
        (entry["iteration"], entry["waiting_for"]["question"])
        for entry in first.entries
        if "waiting_for" in entry
    ] == [(0, "Send page 1?")]

    second = InMemoryRecorder()
    second._finished[("read", 0, 0)] = approved()
    parked_again = execute_flow(
        spec=spec, runtime=runtime, recorder=second, trigger_payload=payload
    )
    assert parked_again.status == FlowRunStatus.AWAITING_DECISION
    assert [
        (entry["iteration"], entry["waiting_for"]["question"])
        for entry in second.entries
        if "waiting_for" in entry
    ] == [(1, "Send page 2?")]

    third = InMemoryRecorder()
    third._finished[("read", 0, 0)] = approved()
    third._finished[("read", 1, 0)] = approved()
    finished = execute_flow(
        spec=spec, runtime=runtime, recorder=third, trigger_payload=payload
    )
    assert finished.status == FlowRunStatus.SUCCEEDED
    assert finished.outputs["pages"]["results"] == ["sent 1", "sent 2"]
