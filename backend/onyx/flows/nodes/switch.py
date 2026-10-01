"""Switch node: route the run down one of several branches by value."""

from __future__ import annotations

from typing import Any

from onyx.db.enums import FlowErrorClass
from onyx.flows.expressions import ExpressionError, RunContext, resolve
from onyx.flows.models import SwitchNode
from onyx.flows.nodes.base import NodeExecutionError, NodeOutcome, NodeRuntime
from onyx.flows.nodes.condition import compare


def execute_switch(
    node: SwitchNode, context: RunContext, _runtime: NodeRuntime
) -> NodeOutcome:
    """Resolve the value once, then take the first case that equals it.

    Cases after the match are never resolved. That is the ordinary meaning
    of a switch, and it keeps a case that reads a step on another branch from
    failing a run that never needed it.
    """
    value = _resolve(node.value, context)

    for position, case in enumerate(node.cases):
        expected = _resolve(case.equals, context)
        if compare("eq", value, expected):
            return NodeOutcome(
                output={"value": value, "case": position, "equals": expected},
                next_ids=list(case.then),
            )

    return NodeOutcome(
        output={"value": value, "case": None, "equals": None},
        next_ids=list(node.otherwise),
    )


def resume_switch(node: SwitchNode, output: Any) -> NodeOutcome:
    """Rebuild the branch a recorded switch took.

    Read from the case position on the row, never by comparing again: the
    value came from a step that already ran, and re-reading it would be a
    second chance to disagree with history.
    """
    position = output.get("case") if isinstance(output, dict) else None

    if position is None:
        return NodeOutcome(output=output, next_ids=list(node.otherwise))

    # A bool is an int to Python, and `True` is not a case position.
    if (
        isinstance(position, int)
        and not isinstance(position, bool)
        and 0 <= position < len(node.cases)
    ):
        return NodeOutcome(output=output, next_ids=list(node.cases[position].then))

    raise NodeExecutionError(
        FlowErrorClass.NODE_EXCEPTION,
        f"switch step has an unreadable case: {position!r}",
    )


def _resolve(expression: str, context: RunContext) -> Any:
    try:
        return resolve(expression, context)
    except ExpressionError as exc:
        raise NodeExecutionError(FlowErrorClass.EXPRESSION_ERROR, str(exc)) from exc
