"""Spec validation: what the editor is allowed to save."""

import pytest

from onyx.flows.models import (
    MAX_CODE_LENGTH,
    MAX_FAN_OUT_ITEMS,
    ConditionNode,
    SpecError,
    parse_spec,
)


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
