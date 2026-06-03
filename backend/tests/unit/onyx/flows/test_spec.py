"""Spec validation: what the editor is allowed to save."""

from typing import Any, TypeVar

import pytest

from onyx.flows.models import (
    INLINE_DELAY_SECONDS,
    MAX_CODE_LENGTH,
    MAX_DELAY_SECONDS,
    MAX_FAN_OUT_ITEMS,
    MAX_PARALLEL_CALLS,
    MAX_PAUSE_SECONDS,
    MAX_SWITCH_CASES,
    ConditionNode,
    DelayNode,
    FilterNode,
    FlowSpec,
    HttpNode,
    MergeNode,
    ParallelNode,
    RetryNode,
    ScheduleNode,
    SpecError,
    SplitNode,
    SwitchNode,
    WebhookNode,
    parse_spec,
)

_Node = TypeVar("_Node")


def only(spec: FlowSpec, kind: type[_Node]) -> _Node:
    """The spec's single node, narrowed. A wrong kind means the test is wrong."""
    node = spec.nodes[0]
    assert isinstance(node, kind), (
        f"expected {kind.__name__}, got {type(node).__name__}"
    )
    return node


def http_node(node_id: str, **overrides: object) -> dict:
    node = {"id": node_id, "kind": "HTTP", "url": "https://example.test/x"}
    node.update(overrides)
    return node


def test_parses_a_linear_flow() -> None:
    spec = parse_spec(
        {
            "start": "fetch",
            "nodes": [
                http_node("fetch", next=["shape"]),
                {
                    "id": "shape",
                    "kind": "TRANSFORM",
                    "fields": {"title": "{{ steps.fetch.body.title }}"},
                },
            ],
        }
    )

    assert [node.id for node in spec.nodes] == ["fetch", "shape"]
    assert spec.reachable_ids() == {"fetch", "shape"}


def test_name_defaults_to_id() -> None:
    spec = parse_spec({"start": "fetch", "nodes": [http_node("fetch")]})
    assert spec.nodes[0].name == "fetch"


def test_rejects_duplicate_ids() -> None:
    with pytest.raises(SpecError, match="duplicate node id: fetch"):
        parse_spec(
            {"start": "fetch", "nodes": [http_node("fetch"), http_node("fetch")]}
        )


def test_rejects_unknown_start() -> None:
    with pytest.raises(SpecError, match="start node 'ghost' is not defined"):
        parse_spec({"start": "ghost", "nodes": [http_node("fetch")]})


def test_rejects_dangling_reference() -> None:
    with pytest.raises(SpecError, match="points at undefined node 'ghost'"):
        parse_spec({"start": "fetch", "nodes": [http_node("fetch", next=["ghost"])]})


def test_rejects_self_reference() -> None:
    with pytest.raises(SpecError, match="points at itself"):
        parse_spec({"start": "fetch", "nodes": [http_node("fetch", next=["fetch"])]})


def test_rejects_cycles() -> None:
    with pytest.raises(SpecError, match="cycle"):
        parse_spec(
            {
                "start": "a",
                "nodes": [http_node("a", next=["b"]), http_node("b", next=["a"])],
            }
        )


def test_rejects_long_cycles() -> None:
    with pytest.raises(SpecError, match="cycle"):
        parse_spec(
            {
                "start": "a",
                "nodes": [
                    http_node("a", next=["b"]),
                    http_node("b", next=["c"]),
                    http_node("c", next=["b"]),
                ],
            }
        )


def test_allows_unreachable_nodes() -> None:
    """The editor creates one every time a node is dropped on the canvas."""
    spec = parse_spec({"start": "a", "nodes": [http_node("a"), http_node("orphan")]})
    assert spec.reachable_ids() == {"a"}


def test_allows_diamond() -> None:
    spec = parse_spec(
        {
            "start": "a",
            "nodes": [
                http_node("a", next=["left", "right"]),
                http_node("left", next=["join"]),
                http_node("right", next=["join"]),
                http_node("join"),
            ],
        }
    )
    assert spec.reachable_ids() == {"a", "left", "right", "join"}


@pytest.mark.parametrize("bad_id", ["Bad", "1leading", "has-dash", "has space", ""])
def test_rejects_malformed_ids(bad_id: str) -> None:
    with pytest.raises(SpecError):
        parse_spec({"start": bad_id, "nodes": [http_node(bad_id)]})


def test_condition_requires_right_for_binary_operator() -> None:
    with pytest.raises(SpecError, match="needs a 'right' value"):
        parse_spec(
            {
                "start": "check",
                "nodes": [
                    {
                        "id": "check",
                        "kind": "CONDITION",
                        "left": "{{ trigger.x }}",
                        "operator": "eq",
                    }
                ],
            }
        )


def test_condition_allows_unary_operator_without_right() -> None:
    spec = parse_spec(
        {
            "start": "check",
            "nodes": [
                {
                    "id": "check",
                    "kind": "CONDITION",
                    "left": "{{ trigger.x }}",
                    "operator": "is_empty",
                }
            ],
        }
    )
    node = spec.nodes[0]
    assert isinstance(node, ConditionNode)
    assert node.right is None


def test_condition_cannot_fan_out() -> None:
    with pytest.raises(SpecError, match="cannot use 'for_each'"):
        parse_spec(
            {
                "start": "check",
                "nodes": [
                    {
                        "id": "check",
                        "kind": "CONDITION",
                        "left": "{{ item }}",
                        "operator": "is_empty",
                        "for_each": "{{ trigger.rows }}",
                    }
                ],
            }
        )


def test_rejects_duplicate_ai_output_fields() -> None:
    with pytest.raises(SpecError, match="duplicate output field names: team"):
        parse_spec(
            {
                "start": "think",
                "nodes": [
                    {
                        "id": "think",
                        "kind": "AI",
                        "prompt": "who owns this?",
                        "output_fields": [
                            {"name": "team", "type": "text"},
                            {"name": "team", "type": "text"},
                        ],
                    }
                ],
            }
        )


def test_rejects_unknown_fields() -> None:
    with pytest.raises(SpecError):
        parse_spec({"start": "a", "nodes": [http_node("a", surprise=1)]})


def test_an_approval_reaches_both_of_its_branches() -> None:
    spec = parse_spec(
        {
            "start": "gate",
            "nodes": [
                {
                    "id": "gate",
                    "kind": "HUMAN",
                    "question": "send it?",
                    "on_approve": ["send"],
                    "on_reject": ["log"],
                },
                http_node("send"),
                {"id": "log", "kind": "TRANSFORM", "fields": {"why": "declined"}},
            ],
        }
    )

    assert spec.nodes[0].successors() == ["send", "log"]
    assert spec.reachable_ids() == {"gate", "send", "log"}


def test_rejects_an_approval_that_fans_out() -> None:
    with pytest.raises(SpecError, match="ask once, then fan out"):
        parse_spec(
            {
                "start": "gate",
                "nodes": [
                    {
                        "id": "gate",
                        "kind": "HUMAN",
                        "question": "send it?",
                        "for_each": "{{ trigger.rows }}",
                    }
                ],
            }
        )


def test_rejects_an_empty_snippet() -> None:
    with pytest.raises(SpecError, match="code: must not be empty"):
        parse_spec(
            {"start": "run", "nodes": [{"id": "run", "kind": "CODE", "code": ""}]}
        )


def test_rejects_a_snippet_longer_than_the_limit() -> None:
    long_snippet = "x = 1\n" * MAX_CODE_LENGTH
    with pytest.raises(SpecError):
        parse_spec(
            {
                "start": "run",
                "nodes": [{"id": "run", "kind": "CODE", "code": long_snippet}],
            }
        )


def test_a_loop_batch_must_fit_the_fan_out_limit() -> None:
    with pytest.raises(SpecError):
        parse_spec(
            {
                "start": "chunk",
                "nodes": [
                    {
                        "id": "chunk",
                        "kind": "LOOP",
                        "over": "{{ trigger.rows }}",
                        "batch_size": MAX_FAN_OUT_ITEMS + 1,
                    }
                ],
            }
        )


def test_a_retry_cannot_wait_longer_than_one_step_is_allowed() -> None:
    with pytest.raises(SpecError, match="over the 600s limit"):
        parse_spec(
            {
                "start": "poll",
                "nodes": [
                    {
                        "id": "poll",
                        "kind": "RETRY",
                        "url": "https://example.test/jobs/1",
                        "value": "done",
                        "max_checks": 40,
                        "interval_seconds": 30,
                    }
                ],
            }
        )


def test_a_retry_with_a_binary_operator_needs_something_to_compare() -> None:
    with pytest.raises(SpecError, match="needs a 'value'"):
        parse_spec(
            {
                "start": "poll",
                "nodes": [
                    {
                        "id": "poll",
                        "kind": "RETRY",
                        "url": "https://example.test/jobs/1",
                        "operator": "eq",
                    }
                ],
            }
        )


def test_a_retry_checking_for_presence_needs_no_value() -> None:
    spec = parse_spec(
        {
            "start": "poll",
            "nodes": [
                {
                    "id": "poll",
                    "kind": "RETRY",
                    "url": "https://example.test/jobs/1",
                    "until_path": "result",
                    "operator": "is_not_empty",
                }
            ],
        }
    )

    assert only(spec, RetryNode).value is None


def test_rejects_a_webhook_with_no_url() -> None:
    with pytest.raises(SpecError, match="url: must not be empty"):
        parse_spec({"start": "w", "nodes": [{"id": "w", "kind": "WEBHOOK", "url": ""}]})


def test_a_webhook_delivers_whatever_shape_you_give_it() -> None:
    """The payload is arbitrary JSON, not a flat map of strings."""
    spec = parse_spec(
        {
            "start": "w",
            "nodes": [
                {
                    "id": "w",
                    "kind": "WEBHOOK",
                    "url": "https://hooks.example.test/x",
                    "payload": {
                        "text": "{{ steps.ai.summary }}",
                        "blocks": [{"type": "section", "n": 1}],
                    },
                }
            ],
        }
    )

    assert only(spec, WebhookNode).payload["blocks"][0]["type"] == "section"


def test_rejects_a_delay_that_fans_out() -> None:
    with pytest.raises(SpecError, match="wait once, then fan out"):
        parse_spec(
            {
                "start": "wait",
                "nodes": [
                    {
                        "id": "wait",
                        "kind": "DELAY",
                        "seconds": 30,
                        "for_each": "{{ trigger.rows }}",
                    }
                ],
            }
        )


def test_a_delay_longer_than_a_month_is_refused() -> None:
    with pytest.raises(SpecError):
        parse_spec(
            {
                "start": "wait",
                "nodes": [
                    {"id": "wait", "kind": "DELAY", "seconds": MAX_DELAY_SECONDS + 1}
                ],
            }
        )


def test_the_delay_threshold_decides_sleeping_from_parking() -> None:
    def delay(seconds: float) -> DelayNode:
        spec = parse_spec(
            {"start": "w", "nodes": [{"id": "w", "kind": "DELAY", "seconds": seconds}]}
        )
        return only(spec, DelayNode)

    assert delay(INLINE_DELAY_SECONDS).parks_the_run() is False
    assert delay(INLINE_DELAY_SECONDS + 1).parks_the_run() is True


def test_a_filter_needs_something_to_compare_unless_the_operator_does_not() -> None:
    with pytest.raises(SpecError, match="needs a 'right' value"):
        parse_spec(
            {
                "start": "keep",
                "nodes": [
                    {
                        "id": "keep",
                        "kind": "FILTER",
                        "over": "{{ trigger.rows }}",
                        "left": "{{ item.state }}",
                        "operator": "eq",
                    }
                ],
            }
        )


def test_a_filter_testing_for_presence_needs_no_comparison_value() -> None:
    spec = parse_spec(
        {
            "start": "keep",
            "nodes": [
                {
                    "id": "keep",
                    "kind": "FILTER",
                    "over": "{{ trigger.rows }}",
                    "left": "{{ item.note }}",
                    "operator": "is_not_empty",
                }
            ],
        }
    )

    assert only(spec, FilterNode).right is None


def merged_spec(*extra: dict[str, Any], **merge_overrides: Any) -> dict[str, Any]:
    """Two steps in a chain and a merge below them, plus anything else given."""
    merge: dict[str, Any] = {
        "id": "both",
        "kind": "MERGE",
        "sources": ["left", "right"],
    }
    merge.update(merge_overrides)
    return {
        "start": "left",
        "nodes": [
            {
                "id": "left",
                "kind": "TRANSFORM",
                "fields": {"a": "1"},
                "next": ["right"],
            },
            {
                "id": "right",
                "kind": "TRANSFORM",
                "fields": {"b": "2"},
                "next": ["both"],
            },
            merge,
            *extra,
        ],
    }


def test_a_merge_accepts_any_ancestor_not_only_the_step_before_it() -> None:
    """`left` reaches the merge through `right`, which is still an ancestor."""
    spec = parse_spec(merged_spec())

    merge = spec.node_map()["both"]
    assert isinstance(merge, MergeNode)
    assert merge.sources == ["left", "right"]


def test_rejects_a_merge_of_a_step_that_does_not_lead_to_it() -> None:
    """The common slip: naming the sources and forgetting to wire them."""
    stray = {"id": "stray", "kind": "TRANSFORM", "fields": {"c": "3"}}

    with pytest.raises(SpecError, match="does not lead to it"):
        parse_spec(merged_spec(stray, sources=["left", "stray"]))


def test_rejects_a_merge_of_an_undefined_step() -> None:
    with pytest.raises(SpecError, match="merges undefined node 'ghost'"):
        parse_spec(merged_spec(sources=["left", "ghost"]))


def test_rejects_a_merge_that_fans_out() -> None:
    with pytest.raises(SpecError, match="merge first, then fan out"):
        parse_spec(merged_spec(for_each="{{ trigger.rows }}"))


def test_rejects_a_schedule_that_fans_out() -> None:
    with pytest.raises(SpecError, match="wait once, then fan out"):
        parse_spec(
            {
                "start": "at_nine",
                "nodes": [
                    {
                        "id": "at_nine",
                        "kind": "SCHEDULE",
                        "cron": "0 9 * * *",
                        "for_each": "{{ trigger.rows }}",
                    }
                ],
            }
        )


def test_a_schedule_keeps_the_cron_it_was_given() -> None:
    spec = parse_spec(
        {
            "start": "at_nine",
            "nodes": [{"id": "at_nine", "kind": "SCHEDULE", "cron": "0 9 * * 1-5"}],
        }
    )

    assert only(spec, ScheduleNode).cron == "0 9 * * 1-5"


def test_a_split_keeps_the_separator_it_was_given() -> None:
    spec = parse_spec(
        {
            "start": "cut",
            "nodes": [
                {
                    "id": "cut",
                    "kind": "SPLIT",
                    "value": "{{ trigger.tags }}",
                    "separator": " | ",
                }
            ],
        }
    )

    assert only(spec, SplitNode).separator == " | "


def test_rejects_a_split_with_nothing_to_split_on() -> None:
    with pytest.raises(SpecError, match="separator: must not be empty"):
        parse_spec(
            {
                "start": "cut",
                "nodes": [
                    {
                        "id": "cut",
                        "kind": "SPLIT",
                        "value": "{{ trigger.tags }}",
                        "separator": "",
                    }
                ],
            }
        )


def test_a_split_may_fan_out_because_splitting_per_item_makes_sense() -> None:
    """Each row carrying its own tag string is the ordinary case."""
    spec = parse_spec(
        {
            "start": "cut",
            "nodes": [
                {
                    "id": "cut",
                    "kind": "SPLIT",
                    "value": "{{ item.tags }}",
                    "for_each": "{{ trigger.rows }}",
                }
            ],
        }
    )

    assert only(spec, SplitNode).for_each == "{{ trigger.rows }}"


def switch_spec(**switch_overrides: Any) -> dict[str, Any]:
    switch: dict[str, Any] = {
        "id": "route",
        "kind": "SWITCH",
        "value": "{{ trigger.priority }}",
        "cases": [
            {"equals": "high", "then": ["page"]},
            {"equals": "low", "then": ["queue"]},
        ],
        "otherwise": ["triage"],
    }
    switch.update(switch_overrides)
    return {
        "start": "route",
        "nodes": [
            switch,
            http_node("page"),
            http_node("queue"),
            http_node("triage"),
        ],
    }


def test_a_switch_reaches_every_case_and_its_otherwise() -> None:
    spec = parse_spec(switch_spec())

    assert spec.reachable_ids() == {"route", "page", "queue", "triage"}
    assert only(spec, SwitchNode).successors() == ["page", "queue", "triage"]


def test_rejects_a_switch_case_pointing_at_nothing() -> None:
    with pytest.raises(SpecError, match="points at undefined node 'nowhere'"):
        parse_spec(
            switch_spec(cases=[{"equals": "high", "then": ["nowhere"]}]),
        )


def test_rejects_a_cycle_through_a_switch_case() -> None:
    raw = switch_spec()
    raw["nodes"][1]["next"] = ["route"]

    with pytest.raises(SpecError, match="cycle"):
        parse_spec(raw)


def test_rejects_a_case_that_could_never_match() -> None:
    """The first match wins, so the second copy is dead — whitespace and all."""
    with pytest.raises(SpecError, match="case 'high' appears twice"):
        parse_spec(
            switch_spec(
                cases=[
                    {"equals": "high", "then": ["page"]},
                    {"equals": " high ", "then": ["queue"]},
                ]
            )
        )


def test_rejects_a_blank_case() -> None:
    with pytest.raises(SpecError, match="equals: must not be empty"):
        parse_spec(switch_spec(cases=[{"equals": "  ", "then": ["page"]}]))


def test_rejects_a_switch_with_no_cases() -> None:
    with pytest.raises(SpecError, match="cases"):
        parse_spec(switch_spec(cases=[]))


def test_rejects_a_switch_with_more_cases_than_the_limit() -> None:
    cases = [{"equals": f"v{n}"} for n in range(MAX_SWITCH_CASES + 1)]

    with pytest.raises(SpecError, match="cases"):
        parse_spec(switch_spec(cases=cases))


def test_rejects_a_switch_that_fans_out() -> None:
    with pytest.raises(SpecError, match="a switch cannot use 'for_each'"):
        parse_spec(switch_spec(for_each="{{ trigger.rows }}"))


def test_a_switch_may_leave_a_case_and_otherwise_unwired() -> None:
    """An empty branch ends there, the same as a condition's."""
    spec = parse_spec(
        {
            "start": "route",
            "nodes": [
                {
                    "id": "route",
                    "kind": "SWITCH",
                    "value": "{{ trigger.priority }}",
                    "cases": [{"equals": "high"}],
                }
            ],
        }
    )

    switch = only(spec, SwitchNode)
    assert switch.cases[0].then == []
    assert switch.otherwise == []


def parallel_node(**overrides: Any) -> dict[str, Any]:
    node: dict[str, Any] = {
        "id": "lookup",
        "kind": "PARALLEL",
        "url": "https://example.test/users/{{ item }}",
        "over": "{{ trigger.ids }}",
    }
    node.update(overrides)
    return node


def test_a_parallel_step_takes_every_http_field() -> None:
    spec = parse_spec(
        {
            "start": "lookup",
            "nodes": [
                parallel_node(
                    method="POST",
                    body={"id": "{{ item }}"},
                    result_path="data",
                    fail_on_error_status=False,
                    concurrency=3,
                )
            ],
        }
    )

    node = only(spec, ParallelNode)
    assert node.method == "POST"
    assert node.body == {"id": "{{ item }}"}
    assert node.result_path == "data"
    assert node.concurrency == 3


def test_rejects_a_parallel_step_over_the_concurrency_cap() -> None:
    with pytest.raises(SpecError, match="concurrency"):
        parse_spec(
            {
                "start": "lookup",
                "nodes": [parallel_node(concurrency=MAX_PARALLEL_CALLS + 1)],
            }
        )


def test_rejects_a_parallel_step_with_nothing_to_go_over() -> None:
    with pytest.raises(SpecError, match="over: must not be empty"):
        parse_spec({"start": "lookup", "nodes": [parallel_node(over=" ")]})


def test_rejects_a_parallel_step_that_also_fans_out() -> None:
    with pytest.raises(SpecError, match="a parallel step cannot use 'for_each'"):
        parse_spec(
            {
                "start": "lookup",
                "nodes": [parallel_node(for_each="{{ trigger.groups }}")],
            }
        )


def test_a_pause_needs_items_to_pause_between() -> None:
    """On a step that runs once a pause would do nothing, so it is refused."""
    with pytest.raises(SpecError, match="only applies between the items"):
        parse_spec({"start": "send", "nodes": [http_node("send", pause_seconds=5)]})


def test_a_paced_fan_out_keeps_its_pause() -> None:
    spec = parse_spec(
        {
            "start": "send",
            "nodes": [
                http_node("send", for_each="{{ trigger.batches }}", pause_seconds=2.5)
            ],
        }
    )

    assert only(spec, HttpNode).pause_seconds == 2.5


def test_a_pause_longer_than_a_minute_is_refused() -> None:
    with pytest.raises(SpecError, match="pause_seconds"):
        parse_spec(
            {
                "start": "send",
                "nodes": [
                    http_node(
                        "send",
                        for_each="{{ trigger.batches }}",
                        pause_seconds=MAX_PAUSE_SECONDS + 1,
                    )
                ],
            }
        )


def test_a_spec_saved_before_pauses_existed_runs_unpaced() -> None:
    """Stored specs are kept as they were sent, so most have no pause."""
    spec = parse_spec(
        {
            "start": "send",
            "nodes": [http_node("send", for_each="{{ trigger.batches }}")],
        }
    )

    assert only(spec, HttpNode).pause_seconds == 0
