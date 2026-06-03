"""Condition node: compare two values and pick a branch."""

from __future__ import annotations

from typing import Any

from onyx.db.enums import FlowErrorClass
from onyx.flows.expressions import RunContext, resolve
from onyx.flows.models import UNARY_OPERATORS, ConditionNode
from onyx.flows.nodes.base import NodeExecutionError, NodeOutcome, NodeRuntime


def execute_condition(
    node: ConditionNode, context: RunContext, _runtime: NodeRuntime
) -> NodeOutcome:
    """Resolve both operands, compare, and hand control to one branch.

    The output records the operands alongside the verdict. That costs a few
    bytes per run and saves the "but why did it go left?" conversation every
    single time.
    """
    left = resolve(node.left, context)
    right = (
        None if node.operator in UNARY_OPERATORS else resolve(node.right or "", context)
    )

    matched = _compare(node.operator, left, right)
    branch = node.on_true if matched else node.on_false

    return NodeOutcome(
        output={"matched": matched, "left": left, "right": right},
        next_ids=list(branch),
    )


def _compare(operator: str, left: Any, right: Any) -> bool:
    if operator == "eq":
        return _loosely_equal(left, right)
    if operator == "ne":
        return not _loosely_equal(left, right)
    if operator in ("gt", "gte", "lt", "lte"):
        return _compare_ordered(operator, left, right)
    if operator == "contains":
        return _contains(left, right)
    if operator == "not_contains":
        return not _contains(left, right)
    if operator == "is_empty":
        return _is_empty(left)
    if operator == "is_not_empty":
        return not _is_empty(left)
    raise NodeExecutionError(
        FlowErrorClass.NODE_EXCEPTION, f"unknown operator '{operator}'"
    )


def _loosely_equal(left: Any, right: Any) -> bool:
    """Equality that survives the JSON/text boundary.

    A webhook delivers ``"200"`` where an HTTP node produces ``200``, and
    nobody editing a flow wants to think about which side is which. Numbers
    compare numerically when both sides look numeric; otherwise fall back to
    exact equality, then to a text comparison.
    """
    if isinstance(left, bool) or isinstance(right, bool):
        return _as_bool(left) == _as_bool(right)
    left_number, right_number = _as_number(left), _as_number(right)
    if left_number is not None and right_number is not None:
        return left_number == right_number
    if left == right:
        return True
    if left is None or right is None:
        return False
    if isinstance(left, (str, int, float)) and isinstance(right, (str, int, float)):
        return str(left) == str(right)
    return False


def _compare_ordered(operator: str, left: Any, right: Any) -> bool:
    left_number, right_number = _as_number(left), _as_number(right)
    if left_number is None or right_number is None:
        # Text still has a useful ordering; anything else genuinely has none.
        if isinstance(left, str) and isinstance(right, str):
            left_number, right_number = None, None
        else:
            raise NodeExecutionError(
                FlowErrorClass.NODE_EXCEPTION,
                f"cannot order-compare {type(left).__name__} with "
                f"{type(right).__name__}",
            )
    first: Any = left if left_number is None else left_number
    second: Any = right if right_number is None else right_number

    if operator == "gt":
        return bool(first > second)
    if operator == "gte":
        return bool(first >= second)
    if operator == "lt":
        return bool(first < second)
    return bool(first <= second)


def _contains(haystack: Any, needle: Any) -> bool:
    if haystack is None:
        return False
    if isinstance(haystack, (list, tuple)):
        return any(_loosely_equal(element, needle) for element in haystack)
    if isinstance(haystack, dict):
        return needle in haystack
    return str(needle) in str(haystack)


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (str, list, tuple, dict)):
        return len(value) == 0
    return False


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    return bool(value)
