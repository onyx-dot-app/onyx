"""Expression resolution: the one syntax a flow author has to learn."""

import pytest

from onyx.flows.expressions import (
    ExpressionError,
    RunContext,
    referenced_node_ids,
    render_text,
    resolve,
    resolve_structure,
    walk_path,
)


@pytest.fixture
def context() -> RunContext:
    return RunContext(
        trigger={"email": "ada@example.test", "tags": ["alpha", "beta"]},
        steps={
            "fetch": {
                "status": 200,
                "ok": True,
                "body": {
                    "items": [{"id": 1, "title": "one"}, {"id": 2, "title": "two"}]
                },
            },
            "empty": {"value": None},
        },
    )


def test_lone_expression_keeps_its_type(context: RunContext) -> None:
    assert resolve("{{ steps.fetch.status }}", context) == 200
    assert isinstance(resolve("{{ steps.fetch.status }}", context), int)
    assert resolve("{{ steps.fetch.body.items }}", context) == [
        {"id": 1, "title": "one"},
        {"id": 2, "title": "two"},
    ]


def test_mixed_text_interpolates(context: RunContext) -> None:
    assert (
        render_text("status={{ steps.fetch.status }} ok={{ steps.fetch.ok }}", context)
        == "status=200 ok=true"
    )


def test_booleans_render_as_json_not_python(context: RunContext) -> None:
    assert render_text("{{ steps.fetch.ok }}!", context) == "true!"


def test_none_renders_as_empty_string(context: RunContext) -> None:
    assert render_text("[{{ steps.empty.value }}]", context) == "[]"


def test_containers_render_as_json(context: RunContext) -> None:
    assert render_text("{{ trigger.tags }}", context) == '["alpha", "beta"]'


def test_negative_index(context: RunContext) -> None:
    assert resolve("{{ steps.fetch.body.items[-1].title }}", context) == "two"


def test_quoted_key_for_awkward_names() -> None:
    context = RunContext(trigger={"content-type": "application/json"})
    assert resolve("{{ trigger['content-type'] }}", context) == "application/json"


def test_item_and_index_bind_during_fan_out(context: RunContext) -> None:
    bound = context.for_item({"id": 9}, 4)
    assert render_text("{{ index }}:{{ item.id }}", bound) == "4:9"


def test_for_item_does_not_mutate_the_parent(context: RunContext) -> None:
    context.for_item({"id": 1}, 0)
    assert context.item is None
    assert context.index is None


def test_resolve_structure_walks_keys_and_values(context: RunContext) -> None:
    resolved = resolve_structure(
        {
            "to": "{{ trigger.email }}",
            "code": "{{ steps.fetch.status }}",
            "nested": ["{{ trigger.tags[0] }}", 7],
        },
        context,
    )
    assert resolved == {"to": "ada@example.test", "code": 200, "nested": ["alpha", 7]}


def test_walk_path_reads_an_arbitrary_payload() -> None:
    body = {"data": {"rows": [{"name": "first"}]}}
    assert walk_path(body, "data.rows[0].name") == "first"
    assert walk_path(body, "") is body


@pytest.mark.parametrize(
    "expression, fragment",
    [
        ("{{ steps.missing.x }}", "'steps' has no 'missing'"),
        ("{{ steps.fetch.nope }}", "'steps.fetch' has no 'nope'"),
        ("{{ steps.fetch.status.deeper }}", "is a number"),
        ("{{ nowhere.x }}", "unknown root 'nowhere'"),
        ("{{ steps.fetch.body.items[9] }}", "out of range"),
        ("{{ }}", "empty expression"),
    ],
)
def test_errors_name_the_hop_that_failed(
    context: RunContext, expression: str, fragment: str
) -> None:
    with pytest.raises(ExpressionError, match=fragment):
        resolve(expression, context)


def test_referenced_node_ids_finds_upstream_reads() -> None:
    found = referenced_node_ids(
        {"a": "{{ steps.fetch.x }}", "b": ["{{ steps.other.y }}", "{{ trigger.z }}"]}
    )
    assert found == {"fetch", "other"}


def test_text_without_expressions_passes_through(context: RunContext) -> None:
    assert resolve("plain text", context) == "plain text"
