"""Retry node: keep calling until the answer is the one you are waiting for.

Worth being precise about what this retries, because the word is overloaded
here. Every node has a ``retry`` policy, and that one fires when a step
*raised* — a timeout, a refused connection, a 500. This node fires when a step
*succeeded and said "not yet"*.

That is the long-job-behind-an-API shape: you POST some work, you get a job id
back, and then you sit there asking whether it is done. Without this you would
need a cycle in the graph, and a spec is acyclic on purpose.

The two layers compose rather than overlap. A transient error still propagates
out of here and is handled by the node's retry policy; only an unsatisfied
condition is handled in this loop.
"""

from __future__ import annotations

import time
from typing import Any

from onyx.db.enums import FlowErrorClass
from onyx.flows.expressions import ExpressionError, RunContext, render_text, walk_path
from onyx.flows.models import UNARY_OPERATORS, RetryNode
from onyx.flows.nodes.base import NodeExecutionError, NodeOutcome, NodeRuntime
from onyx.flows.nodes.condition import compare
from onyx.flows.nodes.http import execute_http
from onyx.utils.logger import setup_logger

logger = setup_logger()


def execute_retry(
    node: RetryNode, context: RunContext, runtime: NodeRuntime
) -> NodeOutcome:
    """Call the endpoint until the check passes or the checks run out.

    The last response is returned whatever happened, so a flow that gave up
    can still read what the endpoint was saying at the end. ``satisfied`` says
    which of the two it was.
    """
    expected = _expected_value(node, context)
    last: Any = None

    for check in range(1, node.max_checks + 1):
        last = execute_http(node, context, runtime).output

        if _satisfied(node, last, expected):
            logger.info(
                "flow retry node satisfied node=%s check=%d/%d",
                node.id,
                check,
                node.max_checks,
            )
            return NodeOutcome(
                output={"result": last, "checks": check, "satisfied": True}
            )

        # No sleep after the final check: nobody is waiting on that answer.
        if check < node.max_checks and node.interval_seconds > 0:
            time.sleep(node.interval_seconds)

    logger.info(
        "flow retry node gave up node=%s after %d checks", node.id, node.max_checks
    )
    if node.fail_when_exhausted:
        raise NodeExecutionError(
            FlowErrorClass.RETRY_EXHAUSTED,
            f"still not {node.operator} after {node.max_checks} checks over "
            f"{node.max_checks * node.interval_seconds:.0f}s",
        )

    return NodeOutcome(
        output={"result": last, "checks": node.max_checks, "satisfied": False}
    )


def _expected_value(node: RetryNode, context: RunContext) -> Any:
    """The value to compare against, with its expressions resolved once.

    Resolved before the loop rather than inside it: the context does not
    change between checks, so re-rendering it every few seconds would only be
    a way to get a different answer on check seven.
    """
    if node.operator in UNARY_OPERATORS or node.value is None:
        return None
    try:
        return render_text(node.value, context)
    except ExpressionError as exc:
        raise NodeExecutionError(FlowErrorClass.EXPRESSION_ERROR, str(exc)) from exc


def _satisfied(node: RetryNode, output: Any, expected: Any) -> bool:
    """Whether this attempt's response is what the node is waiting for.

    A path that is not there yet counts as "not yet" rather than as an error.
    An endpoint that omits `state` until the job starts is answering the
    question, and failing the run over it would be reading it wrong.
    """
    found = _read_path(node, output)
    if found is _MISSING:
        return False
    return compare(node.operator, found, expected)


class _Missing:
    """Distinguishes "the path is not there" from "the value is None"."""


_MISSING = _Missing()


def _read_path(node: RetryNode, output: Any) -> Any:
    body = output.get("body") if isinstance(output, dict) else output
    if not node.until_path:
        return body
    try:
        return walk_path(body, node.until_path, root_name="body")
    except ExpressionError:
        return _MISSING
