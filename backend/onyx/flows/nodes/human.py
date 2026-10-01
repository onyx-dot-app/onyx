"""Human node: park the run until somebody approves or rejects.

Two halves that never run in the same pass of the engine:

``execute_human`` is reached the first time the run walks this node. It
renders the question and raises ``NodeSuspended``, which parks the run.

``resume_human`` is reached on every later pass. By then the decision is on
the node's row, so the engine short-circuits the executor entirely and asks
this instead which branch the answer chose. That is also why nothing is held
in memory between the two: a run can sit parked for a week across any number
of worker restarts and still resume correctly.
"""

from __future__ import annotations

from typing import Any

from onyx.db.enums import FlowErrorClass
from onyx.flows.expressions import ExpressionError, RunContext, render_text
from onyx.flows.models import DECISION_APPROVE, DECISION_REJECT, HumanNode
from onyx.flows.nodes.base import (
    NodeExecutionError,
    NodeOutcome,
    NodeRuntime,
    NodeSuspended,
)


def execute_human(
    node: HumanNode, context: RunContext, _runtime: NodeRuntime
) -> NodeOutcome:
    """Render the question and park the run.

    Always raises. Returning an outcome would mean the flow carried on past an
    approval nobody gave, so there is no path through here that continues.
    """
    try:
        question = render_text(node.question, context)
    except ExpressionError as exc:
        raise NodeExecutionError(FlowErrorClass.EXPRESSION_ERROR, str(exc)) from exc

    raise NodeSuspended(
        node_id=node.id,
        detail={"question": question, "assignee": node.assignee},
    )


def resume_human(node: HumanNode, output: Any) -> NodeOutcome:
    """Turn a recorded decision into the branch the run should take."""
    decision = output.get("decision") if isinstance(output, dict) else None

    if decision == DECISION_APPROVE:
        return NodeOutcome(output=output, next_ids=list(node.on_approve))

    if decision == DECISION_REJECT:
        if node.on_reject:
            return NodeOutcome(output=output, next_ids=list(node.on_reject))
        # No reject branch means this node was a gate, so a "no" is the end of
        # the run and should read like one.
        raise NodeExecutionError(
            FlowErrorClass.DECISION_REJECTED,
            _rejection_detail(output),
        )

    raise NodeExecutionError(
        FlowErrorClass.NODE_EXCEPTION,
        f"approval step has an unreadable decision: {decision!r}",
    )


def _rejection_detail(output: Any) -> str:
    """The message the run list shows, with the reviewer's comment if given."""
    comment = output.get("comment") if isinstance(output, dict) else None
    if comment:
        return f"rejected: {comment}"
    return "rejected"
