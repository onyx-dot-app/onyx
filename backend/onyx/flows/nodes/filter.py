"""Filter node: keep the items of a list that match a comparison."""

from __future__ import annotations

from typing import Any

from onyx.db.enums import FlowErrorClass
from onyx.flows.expressions import ExpressionError, RunContext, resolve
from onyx.flows.models import MAX_FAN_OUT_ITEMS, UNARY_OPERATORS, FilterNode
from onyx.flows.nodes.base import NodeExecutionError, NodeOutcome, NodeRuntime
from onyx.flows.nodes.condition import compare


def execute_filter(
    node: FilterNode, context: RunContext, _runtime: NodeRuntime
) -> NodeOutcome:
    """Test every element and return the ones that passed.

    ``dropped`` comes back alongside the survivors because "it did nothing"
    and "everything was filtered out" look identical downstream otherwise,
    and those are very different bugs.
    """
    items = _as_list(_resolve(node.over, context))
    expected = (
        None
        if node.operator in UNARY_OPERATORS
        else _resolve(node.right or "", context)
    )

    kept = [
        item
        for index, item in enumerate(items)
        if compare(
            node.operator,
            _resolve(node.left, context.for_item(item, index)),
            expected,
        )
    ]

    return NodeOutcome(
        output={
            "items": kept,
            "kept": len(kept),
            "dropped": len(items) - len(kept),
            "total": len(items),
        }
    )


def _resolve(expression: str, context: RunContext) -> Any:
    try:
        return resolve(expression, context)
    except ExpressionError as exc:
        raise NodeExecutionError(FlowErrorClass.EXPRESSION_ERROR, str(exc)) from exc


def _as_list(items: Any) -> list[Any]:
    """Accept a list, and be forgiving about the same near misses a loop is.

    Nothing at all filters to nothing rather than failing — an API that
    returned no rows today is not a broken flow — and a lone object is
    wrapped, because an endpoint that returns a bare object for one result
    and an array for many is common enough that failing on it would just be
    annoying.
    """
    if items is None:
        return []
    if isinstance(items, dict):
        items = [items]
    elif not isinstance(items, list):
        raise NodeExecutionError(
            FlowErrorClass.EXPRESSION_ERROR,
            f"'over' must resolve to a list, got {type(items).__name__}",
        )

    if len(items) > MAX_FAN_OUT_ITEMS:
        raise NodeExecutionError(
            FlowErrorClass.INVALID_SPEC,
            f"'over' produced {len(items)} items, over the {MAX_FAN_OUT_ITEMS} limit",
        )
    return items
