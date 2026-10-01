"""Transform node: build an object from expressions."""

from __future__ import annotations

from typing import Any

from onyx.flows.expressions import RunContext, resolve
from onyx.flows.models import TransformNode
from onyx.flows.nodes.base import NodeOutcome, NodeRuntime


def execute_transform(
    node: TransformNode, context: RunContext, _runtime: NodeRuntime
) -> NodeOutcome:
    """Evaluate each field and return them as one object.

    Fields are independent — one cannot read another's result — which keeps
    the node order-free and means the editor can show them in any order.
    """
    produced: dict[str, Any] = {
        name: resolve(expression, context) for name, expression in node.fields.items()
    }
    return NodeOutcome(output=produced)
