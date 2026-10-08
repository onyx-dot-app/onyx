"""Parallel node: call an endpoint once per item, several calls at a time.

The calls run on a small thread pool, and two things about that are easy to
get wrong.

**Every call carries the caller's context.** The SSRF transport reads the
tenant's security settings, and which tenant that is lives in a contextvar. A
bare pool thread starts with an empty context and would quietly apply the
default schema's policy instead of this tenant's.

**Only the calls leave this thread.** A pool thread renders a request, sends
it and shapes the reply; the engine writes the step's history once it
returns. No database session is ever shared between threads.
"""

from __future__ import annotations

import contextvars
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from typing import Any

from onyx.db.enums import FlowErrorClass
from onyx.flows.expressions import ExpressionError, RunContext, resolve
from onyx.flows.models import MAX_FAN_OUT_ITEMS, ParallelNode
from onyx.flows.nodes.base import NodeExecutionError, NodeOutcome, NodeRuntime
from onyx.flows.nodes.http import execute_http
from onyx.utils.logger import setup_logger

logger = setup_logger()


def execute_parallel(
    node: ParallelNode, context: RunContext, runtime: NodeRuntime
) -> NodeOutcome:
    """Send one call per item, keeping ``concurrency`` of them in flight.

    Calls are handed to the pool one at a time as slots free up rather than
    all at once. That is what lets a failure, or the run's budget running
    out, stop the calls nobody has sent yet — a queue of two hundred
    submitted futures would send every one of them regardless.
    """
    items = _as_list(node.over, context)
    if not items:
        return NodeOutcome(output={"results": [], "total": 0})

    results: list[Any] = [None] * len(items)
    failures: dict[int, NodeExecutionError] = {}
    in_flight: dict[Future[NodeOutcome], int] = {}
    sent = 0

    with ThreadPoolExecutor(
        max_workers=min(node.concurrency, len(items)),
        thread_name_prefix="flow-parallel",
    ) as pool:
        while True:
            while (
                sent < len(items)
                and len(in_flight) < node.concurrency
                and not failures
                and not runtime.out_of_time()
            ):
                future = pool.submit(
                    _send,
                    # Copied here, in the caller's thread. A copy taken inside
                    # the pool would be the pool thread's own empty context.
                    contextvars.copy_context(),
                    node,
                    context.for_item(items[sent], sent),
                    runtime,
                )
                in_flight[future] = sent
                sent += 1

            if not in_flight:
                break

            done, _ = wait(list(in_flight), return_when=FIRST_COMPLETED)
            for future in done:
                index = in_flight.pop(future)
                try:
                    results[index] = future.result().output
                except NodeExecutionError as exc:
                    failures[index] = exc
                except Exception as exc:
                    logger.exception(
                        "flow parallel call raised node=%s item=%d", node.id, index
                    )
                    failures[index] = NodeExecutionError(
                        FlowErrorClass.NODE_EXCEPTION, f"{type(exc).__name__}: {exc}"
                    )

    if failures:
        # The lowest index rather than the first to arrive, so the same
        # broken item is reported however the calls happened to race.
        index = min(failures)
        failure = failures[index]
        logger.info(
            "flow parallel node stopped node=%s failed=%d sent=%d of %d",
            node.id,
            len(failures),
            sent,
            len(items),
        )
        raise NodeExecutionError(failure.error_class, f"item {index}: {failure.detail}")

    if sent < len(items):
        raise NodeExecutionError(
            FlowErrorClass.BUDGET_EXCEEDED,
            f"run ran out of time after sending {sent} of {len(items)} calls",
        )

    return NodeOutcome(output={"results": results, "total": len(items)})


def _send(
    snapshot: contextvars.Context,
    node: ParallelNode,
    context: RunContext,
    runtime: NodeRuntime,
) -> NodeOutcome:
    """One call, run inside the caller's context.

    Each call gets its own snapshot because one context cannot be entered by
    two threads at once.
    """
    return snapshot.run(execute_http, node, context, runtime)


def _as_list(expression: str, context: RunContext) -> list[Any]:
    """Resolve ``over``, forgiving the same near misses a loop forgives.

    Nothing at all is no calls rather than an error, and a lone object is one
    call rather than a type error — an endpoint that returns a bare object for
    one result and an array for many is common enough to allow for.
    """
    try:
        items = resolve(expression, context)
    except ExpressionError as exc:
        raise NodeExecutionError(FlowErrorClass.EXPRESSION_ERROR, str(exc)) from exc

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
