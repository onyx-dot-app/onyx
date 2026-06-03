"""Engine behaviour: traversal, branching, fan-out, retries and resume."""

from typing import Any
from unittest.mock import MagicMock

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
    recorder._finished[("already", 0)] = RecordedNode(
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
