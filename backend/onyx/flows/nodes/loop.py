"""Loop node: cut a list into batches."""

from __future__ import annotations

from typing import Any

from onyx.db.enums import FlowErrorClass
from onyx.flows.expressions import ExpressionError, RunContext, resolve
from onyx.flows.models import MAX_FAN_OUT_ITEMS, LoopNode
from onyx.flows.nodes.base import NodeExecutionError, NodeOutcome, NodeRuntime


def execute_loop(
    node: LoopNode, context: RunContext, _runtime: NodeRuntime
) -> NodeOutcome:
    """Resolve the list and slice it.

    ``total`` and ``batch_count`` come back alongside the batches because the
    step after a loop is very often "tell somebody how many", and a transform
    node just to call ``len`` would be silly.
    """
    try:
        items = resolve(node.over, context)
    except ExpressionError as exc:
        raise NodeExecutionError(FlowErrorClass.EXPRESSION_ERROR, str(exc)) from exc

    items = _as_list(items)

    batches = [
        items[start : start + node.batch_size]
        for start in range(0, len(items), node.batch_size)
    ]
    return NodeOutcome(
        output={
            "batches": batches,
            "batch_count": len(batches),
            "total": len(items),
        }
    )


def _as_list(items: Any) -> list[Any]:
    """Accept a list, and be forgiving about the two near misses.

    Nothing at all is an empty run rather than an error — an API that returned
    no rows today is not a broken flow. A single object is wrapped, because an
    endpoint that returns a bare object for one result and an array for many
    is common enough that failing on it would just be annoying.
    """
    if items is None:
        return []
    if isinstance(items, list):
        pass
    elif isinstance(items, dict):
        items = [items]
    else:
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
