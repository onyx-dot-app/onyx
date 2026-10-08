"""Merge node: bring the output of several earlier steps back together."""

from __future__ import annotations

from typing import Any

from onyx.db.enums import FlowErrorClass
from onyx.flows.expressions import RunContext
from onyx.flows.models import MAX_FAN_OUT_ITEMS, MergeNode
from onyx.flows.nodes.base import NodeExecutionError, NodeOutcome, NodeRuntime

# A source that produced nothing. Kept distinct from a source that produced
# `None`, because "the branch was skipped" and "the step returned null" are
# different answers to the question the merge exists to ask.
_ABSENT = object()


def execute_merge(
    node: MergeNode, context: RunContext, _runtime: NodeRuntime
) -> NodeOutcome:
    """Combine what the named steps produced.

    ``present`` and ``missing`` come back alongside the data because after a
    condition that is the whole question — which branch got here — and reading
    it off the shape of the values would mean guessing.
    """
    collected = {source: context.steps.get(source, _ABSENT) for source in node.sources}
    present = [source for source, value in collected.items() if value is not _ABSENT]
    missing = [source for source, value in collected.items() if value is _ABSENT]

    if node.mode == "append":
        return NodeOutcome(output=_append(node, collected, present, missing))

    return NodeOutcome(
        output={
            "values": {
                source: (None if value is _ABSENT else value)
                for source, value in collected.items()
            },
            "present": present,
            "missing": missing,
        }
    )


def _append(
    node: MergeNode,
    collected: dict[str, Any],
    present: list[str],
    missing: list[str],
) -> dict[str, Any]:
    """Join the sources' lists into one.

    A source that produced a single value is appended as one item rather than
    rejected: a step that returns a bare object when there is one result and
    an array when there are many is common, and failing on it would only
    force a transform node in between.
    """
    items: list[Any] = []
    for source in node.sources:
        value = collected[source]
        if value is _ABSENT or value is None:
            continue
        if isinstance(value, list):
            items.extend(value)
        else:
            items.append(value)

    if len(items) > MAX_FAN_OUT_ITEMS:
        raise NodeExecutionError(
            FlowErrorClass.INVALID_SPEC,
            f"merging produced {len(items)} items, over the {MAX_FAN_OUT_ITEMS} limit",
        )

    return {
        "items": items,
        "total": len(items),
        "present": present,
        "missing": missing,
    }
