"""Split node: break a piece of text into a list."""

from __future__ import annotations

from typing import Any

from onyx.db.enums import FlowErrorClass
from onyx.flows.expressions import ExpressionError, RunContext, resolve
from onyx.flows.models import MAX_FAN_OUT_ITEMS, SplitNode
from onyx.flows.nodes.base import NodeExecutionError, NodeOutcome, NodeRuntime

# Escapes a single-line field can still express. Kept to the four a
# programmer would try; anything more would be inventing a language.
_ESCAPES = {"\\n": "\n", "\\t": "\t", "\\r": "\r", "\\\\": "\\"}


def execute_split(
    node: SplitNode, context: RunContext, _runtime: NodeRuntime
) -> NodeOutcome:
    """Resolve the value and cut it up."""
    try:
        value = resolve(node.value, context)
    except ExpressionError as exc:
        raise NodeExecutionError(FlowErrorClass.EXPRESSION_ERROR, str(exc)) from exc

    items = _split(node, value)

    if len(items) > MAX_FAN_OUT_ITEMS:
        raise NodeExecutionError(
            FlowErrorClass.INVALID_SPEC,
            f"splitting produced {len(items)} items, over the "
            f"{MAX_FAN_OUT_ITEMS} limit",
        )

    return NodeOutcome(output={"items": items, "total": len(items)})


def _split(node: SplitNode, value: Any) -> list[Any]:
    """Cut ``value`` into pieces, forgiving the shapes that mean "already done".

    Nothing at all splits to nothing rather than failing — a field that was
    not filled in is not a broken flow. A list passes through untouched,
    because it is already what this node is trying to produce and the
    separator has nothing to say about it.
    """
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, bool) or isinstance(value, dict):
        raise NodeExecutionError(
            FlowErrorClass.EXPRESSION_ERROR,
            f"cannot split a {type(value).__name__}",
        )

    pieces = str(value).split(expand_escapes(node.separator))
    if node.trim:
        pieces = [piece.strip() for piece in pieces]
    if node.drop_empty:
        pieces = [piece for piece in pieces if piece != ""]
    return list(pieces)


def expand_escapes(separator: str) -> str:
    """Turn a typed ``\\n`` into a real newline.

    A single-line input cannot carry a newline, and "split on line breaks" is
    half of what anyone wants this for.
    """
    expanded = separator
    for written, real in _ESCAPES.items():
        expanded = expanded.replace(written, real)
    return expanded
