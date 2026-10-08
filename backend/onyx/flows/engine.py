"""The flow execution engine.

Walks a validated spec in topological order, executes each reachable node, and
reports the outcome. Persistence is behind the ``RunRecorder`` protocol so the
engine can be exercised with nothing but a dict — which is also how the
dry-run path will work when it lands.

Four behaviours are worth stating up front, because they are the ones that
matter when a run goes wrong at 4am:

**A node is recorded before it runs.** ``begin_node`` writes the row, and the
unique key on (run, node, pass, item) is what makes a redelivered Celery
message safe: the second attempt finds a finished row and reuses its output
instead of posting the same message to Slack twice.

**Branches skip, they do not fail.** A node whose predecessors all took the
other branch is SKIPPED. The canvas greys it out, and nobody has to work out
whether grey means broken.

**Expression errors are not retried.** A missing key will still be missing in
two seconds. Only genuinely transient classes get another attempt.

**A parked run holds nothing.** An approval or a long delay parks the run and
returns; whatever resumes it — a person answering, or the clock coming round —
re-queues the run, which walks the graph again from the top and reuses every
row it already wrote. A parked run therefore survives a deploy, a worker crash
and a week of nobody looking at it.

A loop does not change any of that. Its body is walked once per pass by the
same code that walks the whole graph, with the pass number in every row's
key, so a replayed loop replays pass by pass exactly as it first ran.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from onyx.db.enums import FlowErrorClass, FlowNodeKind, FlowNodeRunStatus, FlowRunStatus
from onyx.flows.expressions import ExpressionError, RunContext, resolve
from onyx.flows.models import MAX_FAN_OUT_ITEMS, UNARY_OPERATORS, FlowSpec
from onyx.flows.nodes import (
    NODE_EXECUTORS,
    NODE_REPLAYERS,
    NodeExecutionError,
    NodeOutcome,
    NodeRuntime,
    NodeSuspended,
)
from onyx.flows.nodes.condition import compare
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Wall-clock ceiling for one run. Celery's thread pool silently ignores
# soft_time_limit, so the budget is enforced here or not at all.
DEFAULT_RUN_BUDGET_SECONDS = 15 * 60

# Failures worth another go. Everything else is deterministic: retrying only
# burns the budget and delays the error the author needs to read.
RETRYABLE_ERROR_CLASSES = frozenset(
    {
        FlowErrorClass.HTTP_ERROR,
        FlowErrorClass.TIMEOUT,
        FlowErrorClass.LLM_ERROR,
        FlowErrorClass.NODE_EXCEPTION,
    }
)


class RunBudgetExceeded(Exception):
    """The run used its wall-clock allowance."""


@dataclass(frozen=True)
class RecordedNode:
    """A node row that already exists, from an earlier delivery of this run."""

    status: FlowNodeRunStatus
    output: Any


class RunRecorder(Protocol):
    """Where the engine writes node history.

    ``begin_node`` returns the prior row when one exists, which is the entire
    resume mechanism — the engine does not otherwise know or care that it has
    been restarted.

    A row is named by its node, the loop pass it ran in (``iteration``, 0
    outside a loop) and the fan-out item (``item_index``, 0 without one).
    """

    def begin_node(
        self,
        *,
        node_id: str,
        kind: FlowNodeKind,
        iteration: int,
        item_index: int,
        node_input: dict[str, Any] | None,
    ) -> RecordedNode | None: ...

    def finish_node(
        self,
        *,
        node_id: str,
        iteration: int,
        item_index: int,
        status: FlowNodeRunStatus,
        output: Any,
        attempt: int,
    ) -> None: ...

    def fail_node(
        self,
        *,
        node_id: str,
        iteration: int,
        item_index: int,
        error_class: FlowErrorClass,
        error_detail: str,
        attempt: int,
    ) -> None: ...

    def park_node(
        self,
        *,
        node_id: str,
        iteration: int,
        item_index: int,
        detail: dict[str, Any],
    ) -> None:
        """Note what a node is waiting on, leaving its row open."""
        ...

    def skip_node(
        self, *, node_id: str, kind: FlowNodeKind, iteration: int
    ) -> None: ...


@dataclass
class InMemoryRecorder:
    """A recorder that keeps everything in a list.

    Used by tests and by the engine's own exercising; a dry run will use it
    too, since "execute the graph but persist nothing" is exactly this.
    """

    entries: list[dict[str, Any]] = field(default_factory=list)
    # Keyed (node, pass, item), the same as the unique key on a real row.
    _finished: dict[tuple[str, int, int], RecordedNode] = field(default_factory=dict)

    def begin_node(
        self,
        *,
        node_id: str,
        kind: FlowNodeKind,
        iteration: int,
        item_index: int,
        node_input: dict[str, Any] | None,
    ) -> RecordedNode | None:
        _ = kind, node_input  # part of the protocol; nothing to store here
        return self._finished.get((node_id, iteration, item_index))

    def finish_node(
        self,
        *,
        node_id: str,
        iteration: int,
        item_index: int,
        status: FlowNodeRunStatus,
        output: Any,
        attempt: int,
    ) -> None:
        self._finished[(node_id, iteration, item_index)] = RecordedNode(status, output)
        self.entries.append(
            {
                "node_id": node_id,
                "iteration": iteration,
                "item_index": item_index,
                "status": status,
                "output": output,
                "attempt": attempt,
            }
        )

    def fail_node(
        self,
        *,
        node_id: str,
        iteration: int,
        item_index: int,
        error_class: FlowErrorClass,
        error_detail: str,
        attempt: int,
    ) -> None:
        self.entries.append(
            {
                "node_id": node_id,
                "iteration": iteration,
                "item_index": item_index,
                "status": FlowNodeRunStatus.FAILED,
                "error_class": error_class,
                "error_detail": error_detail,
                "attempt": attempt,
            }
        )

    def park_node(
        self,
        *,
        node_id: str,
        iteration: int,
        item_index: int,
        detail: dict[str, Any],
    ) -> None:
        self.entries.append(
            {
                "node_id": node_id,
                "iteration": iteration,
                "item_index": item_index,
                "status": FlowNodeRunStatus.RUNNING,
                "waiting_for": detail,
            }
        )

    def skip_node(self, *, node_id: str, kind: FlowNodeKind, iteration: int) -> None:
        self.entries.append(
            {
                "node_id": node_id,
                "kind": kind,
                "iteration": iteration,
                "status": FlowNodeRunStatus.SKIPPED,
            }
        )


@dataclass(frozen=True)
class RunResult:
    """What a finished run reports back to its caller."""

    status: FlowRunStatus
    outputs: dict[str, Any]
    error_class: FlowErrorClass | None = None
    error_detail: str | None = None
    failed_node_id: str | None = None
    # Set only for a run parked on a delay: when the sweep should pick it up.
    resume_at: datetime | None = None


def execute_flow(
    *,
    spec: FlowSpec,
    runtime: NodeRuntime,
    recorder: RunRecorder,
    trigger_payload: Any = None,
    budget_seconds: float = DEFAULT_RUN_BUDGET_SECONDS,
) -> RunResult:
    """Run every reachable node and report the outcome.

    The engine never raises for a flow-level failure; it returns a FAILED
    result so the caller has one place to write the run row. Genuine bugs
    still propagate.
    """
    context = RunContext(trigger=trigger_payload, steps={})
    deadline = time.monotonic() + budget_seconds
    runtime.deadline = deadline
    run = _Run(
        spec=spec,
        by_id=spec.node_map(),
        bodies=spec.loop_bodies(),
        runtime=runtime,
        recorder=recorder,
        deadline=deadline,
        budget_seconds=budget_seconds,
    )

    try:
        run.walk(run.top_level(), context, iteration=0)
    except NodeSuspended as exc:
        # Not a failure and not the end: the run keeps its open row at this
        # node, and whatever resumes it — a person answering, or the clock
        # coming round — re-queues the run to start again from the top,
        # replaying everything already recorded.
        logger.info("flow run parked node=%s status=%s", exc.node_id, exc.status.value)
        return RunResult(
            status=exc.status,
            outputs=dict(context.steps),
            resume_at=exc.resume_at,
        )
    except _RunStopped as exc:
        return RunResult(
            status=FlowRunStatus.FAILED,
            outputs=dict(context.steps),
            error_class=exc.error_class,
            error_detail=exc.detail,
            failed_node_id=exc.node_id,
        )

    return RunResult(status=FlowRunStatus.SUCCEEDED, outputs=dict(context.steps))


class _RunStopped(Exception):
    """A step failed for good, or the run's budget ran out.

    Raised out of however many walks are in progress, a loop's pass inside
    the whole flow included, and carries the step that stopped it so the run
    row names the step that broke rather than the loop around it.
    """

    def __init__(
        self, *, error_class: FlowErrorClass, detail: str, node_id: str
    ) -> None:
        super().__init__(detail)
        self.error_class = error_class
        self.detail = detail
        self.node_id = node_id
        # Set on the way out of a loop: which pass the step failed in.
        self.pass_number: int | None = None


@dataclass(frozen=True)
class _Graph:
    """The nodes one walk visits: the whole flow, or one loop's body."""

    order: list[str]
    predecessors: dict[str, set[str]]
    # Run without a predecessor handing them control: the flow's start, or
    # the steps a loop's pass begins at.
    entries: frozenset[str]


@dataclass
class _Run:
    """What every walk in one execution of a spec shares."""

    spec: FlowSpec
    by_id: dict[str, Any]
    # Each loop's own steps. They are walked once per pass, never by the
    # walk around the loop.
    bodies: dict[str, list[str]]
    runtime: NodeRuntime
    recorder: RunRecorder
    deadline: float
    budget_seconds: float

    def top_level(self) -> _Graph:
        owned = {node_id for body in self.bodies.values() for node_id in body}
        order = [
            node_id for node_id in _execution_order(self.spec) if node_id not in owned
        ]
        return _Graph(
            order=order,
            predecessors=_predecessor_map(self.spec, order),
            entries=frozenset({self.spec.start}),
        )

    def body_graph(self, repeat: Any) -> _Graph:
        inside = set(self.bodies[repeat.id])
        order = [
            node_id for node_id in _execution_order(self.spec) if node_id in inside
        ]
        return _Graph(
            order=order,
            predecessors=_predecessor_map(self.spec, order),
            entries=frozenset(repeat.body),
        )

    def walk(self, graph: _Graph, context: RunContext, iteration: int) -> None:
        """Run each activated node of ``graph`` once, in topological order."""
        # Successors each node handed control to in this walk. A condition, a
        # switch or an approval narrows this to one branch; everything else
        # passes its whole `next` list.
        handed_to: dict[str, set[str]] = {}

        for node_id in graph.order:
            node = self.by_id[node_id]

            if not _is_activated(node_id, graph.entries, graph.predecessors, handed_to):
                self.skip(node, iteration)
                continue

            if time.monotonic() > self.deadline:
                logger.warning("flow run budget exceeded node=%s", node_id)
                raise _RunStopped(
                    error_class=FlowErrorClass.BUDGET_EXCEEDED,
                    detail=(
                        f"run exceeded its {self.budget_seconds:.0f}s budget "
                        f"at '{node_id}'"
                    ),
                    node_id=node_id,
                )

            try:
                if node.kind is FlowNodeKind.REPEAT:
                    output: Any = self.repeat(node, context, iteration)
                    chosen = list(node.next)
                else:
                    output, chosen = _execute_node(
                        node=node,
                        context=context,
                        runtime=self.runtime,
                        recorder=self.recorder,
                        deadline=self.deadline,
                        iteration=iteration,
                    )
            except RunBudgetExceeded as exc:
                raise _RunStopped(
                    error_class=FlowErrorClass.BUDGET_EXCEEDED,
                    detail=str(exc),
                    node_id=node_id,
                ) from exc
            except NodeExecutionError as exc:
                if node.on_error == "skip":
                    logger.info(
                        "flow node failed but is set to skip node=%s detail=%s",
                        node_id,
                        exc.detail,
                    )
                    context.steps[node_id] = None
                    handed_to[node_id] = set(node.next)
                    continue
                raise _RunStopped(
                    error_class=exc.error_class, detail=exc.detail, node_id=node_id
                ) from exc

            context.steps[node_id] = output
            handed_to[node_id] = set(chosen)

    def skip(self, node: Any, iteration: int) -> None:
        self.recorder.skip_node(node_id=node.id, kind=node.kind, iteration=iteration)
        # A loop that never ran never ran its steps either. Saying so keeps
        # the run view from showing them as merely unvisited.
        for body_id in self.bodies.get(node.id, []):
            self.recorder.skip_node(
                node_id=body_id, kind=self.by_id[body_id].kind, iteration=iteration
            )

    def repeat(self, node: Any, context: RunContext, iteration: int) -> Any:
        """Walk a loop's body pass after pass, until its condition holds.

        The loop's own row stays open while it runs, which is what the run
        view shows as in progress. On a resumed run it is already there, and
        every pass replays from its rows — that is also what puts the last
        pass's outputs back into ``steps`` for whatever follows the loop.
        """
        already = self.recorder.begin_node(
            node_id=node.id,
            kind=node.kind,
            iteration=iteration,
            item_index=0,
            node_input=_describe_input(context),
        )
        finished = already is not None and already.status == FlowNodeRunStatus.SUCCEEDED

        try:
            output = self._passes(node, context)
        except NodeExecutionError as exc:
            if not finished:
                self._fail_loop(node, iteration, exc.error_class, exc.detail)
            raise
        except _RunStopped as exc:
            if not finished:
                self._fail_loop(
                    node,
                    iteration,
                    exc.error_class,
                    f"pass {exc.pass_number} stopped at '{exc.node_id}': {exc.detail}",
                )
            raise

        if not finished:
            self.recorder.finish_node(
                node_id=node.id,
                iteration=iteration,
                item_index=0,
                status=FlowNodeRunStatus.SUCCEEDED,
                output=output,
                attempt=1,
            )
        return output

    def _passes(self, node: Any, context: RunContext) -> dict[str, Any]:
        graph = self.body_graph(node)
        value = _resolve_strict(node.start, context) if node.start is not None else None
        collected: list[Any] = []

        for index in range(node.max_passes):
            # A pass sees its own steps only. Reading last pass's output from
            # a step skipped this time would be reading history as news;
            # what one pass hands the next goes through `carry` instead.
            for body_id in self.bodies[node.id]:
                context.steps.pop(body_id, None)

            pass_context = context.for_item(value, index)
            try:
                self.walk(graph, pass_context, iteration=index)
            except _RunStopped as exc:
                exc.pass_number = index + 1
                raise

            if node.collect is not None:
                _gather(collected, _resolve_lenient(node.collect, pass_context))
            if _loop_satisfied(node, pass_context):
                logger.info("flow loop finished node=%s passes=%d", node.id, index + 1)
                return {"passes": index + 1, "satisfied": True, "results": collected}
            if node.carry is not None:
                value = _resolve_lenient(node.carry, pass_context)

        logger.info(
            "flow loop ran out of passes node=%s passes=%d", node.id, node.max_passes
        )
        if node.fail_when_exhausted:
            raise NodeExecutionError(
                FlowErrorClass.LOOP_EXHAUSTED,
                f"still not {node.operator} after {node.max_passes} passes",
            )
        return {"passes": node.max_passes, "satisfied": False, "results": collected}

    def _fail_loop(
        self,
        node: Any,
        iteration: int,
        error_class: FlowErrorClass,
        detail: str,
    ) -> None:
        self.recorder.fail_node(
            node_id=node.id,
            iteration=iteration,
            item_index=0,
            error_class=error_class,
            error_detail=detail,
            attempt=1,
        )


def _resolve_strict(expression: str, context: RunContext) -> Any:
    try:
        return resolve(expression, context)
    except ExpressionError as exc:
        raise NodeExecutionError(FlowErrorClass.EXPRESSION_ERROR, str(exc)) from exc


def _resolve_lenient(expression: str, context: RunContext) -> Any:
    """Resolve, reading a value that is not there as nothing.

    Only for what a loop reads at the end of a pass. An API that drops its
    cursor on the last page instead of sending null is saying "no more", and
    failing the run over it would be reading the answer as an error.
    """
    try:
        return resolve(expression, context)
    except ExpressionError:
        return None


def _loop_satisfied(node: Any, context: RunContext) -> bool:
    left = _resolve_lenient(node.until, context)
    right = (
        None
        if node.operator in UNARY_OPERATORS
        else _resolve_lenient(node.value or "", context)
    )
    return compare(node.operator, left, right)


def _gather(collected: list[Any], value: Any) -> None:
    """Add one pass's ``collect`` to the loop's results.

    Lists are joined and a lone value is added as one item, the same rule a
    merge in append mode follows. Nothing at all adds nothing.
    """
    if value is None:
        return
    if isinstance(value, list):
        collected.extend(value)
    else:
        collected.append(value)
    if len(collected) > MAX_FAN_OUT_ITEMS:
        raise NodeExecutionError(
            FlowErrorClass.INVALID_SPEC,
            f"collected {len(collected)} items, over the {MAX_FAN_OUT_ITEMS} limit",
        )


def _execute_node(
    *,
    node: Any,
    context: RunContext,
    runtime: NodeRuntime,
    recorder: RunRecorder,
    deadline: float,
    iteration: int,
) -> tuple[Any, list[str]]:
    """Run one node, fanning out over ``for_each`` when it is set.

    Returns the node's output and the successors it handed control to.
    """
    if node.for_each is None:
        outcome, _ = _run_once(
            node=node,
            context=context,
            runtime=runtime,
            recorder=recorder,
            iteration=iteration,
            item_index=0,
            deadline=deadline,
        )
        return outcome.output, (
            outcome.next_ids if outcome.next_ids is not None else list(node.next)
        )

    try:
        items = resolve(node.for_each, context)
    except ExpressionError as exc:
        raise NodeExecutionError(FlowErrorClass.EXPRESSION_ERROR, str(exc)) from exc

    if not isinstance(items, list):
        raise NodeExecutionError(
            FlowErrorClass.EXPRESSION_ERROR,
            f"'for_each' must resolve to a list, got {type(items).__name__}",
        )
    if len(items) > MAX_FAN_OUT_ITEMS:
        raise NodeExecutionError(
            FlowErrorClass.INVALID_SPEC,
            f"'for_each' produced {len(items)} items, over the "
            f"{MAX_FAN_OUT_ITEMS} limit",
        )

    outputs: list[Any] = []
    # Only an item that ran in this pass is followed by a pause. Items reused
    # from their rows made no call, and sleeping through their pauses again
    # would spend every resumed run's budget waiting on nothing.
    previous_ran = False
    for index, item in enumerate(items):
        if previous_ran and node.pause_seconds > 0:
            _pause_before_item(node, index, deadline)
        outcome, previous_ran = _run_once(
            node=node,
            context=context.for_item(item, index),
            runtime=runtime,
            recorder=recorder,
            iteration=iteration,
            item_index=index,
            deadline=deadline,
        )
        outputs.append(outcome.output)

    return outputs, list(node.next)


def _pause_before_item(node: Any, index: int, deadline: float) -> None:
    """Wait out the node's pause before its next item.

    The budget is checked before sleeping rather than after. A run that
    cannot afford the pause should fail now, not spend the pause and then
    fail anyway.
    """
    if time.monotonic() + node.pause_seconds > deadline:
        raise RunBudgetExceeded(
            f"no time left to pause before item {index} of '{node.id}'"
        )
    logger.info(
        "flow node pausing node=%s before item=%d for %.1fs",
        node.id,
        index,
        node.pause_seconds,
    )
    time.sleep(node.pause_seconds)


def _run_once(
    *,
    node: Any,
    context: RunContext,
    runtime: NodeRuntime,
    recorder: RunRecorder,
    iteration: int,
    item_index: int,
    deadline: float,
) -> tuple[NodeOutcome, bool]:
    """Execute a single node invocation, with resume and retry handling.

    Returns the outcome, and whether the node actually ran rather than
    reusing a row an earlier delivery of the run already finished.
    """
    already = recorder.begin_node(
        node_id=node.id,
        kind=node.kind,
        iteration=iteration,
        item_index=item_index,
        node_input=_describe_input(context),
    )
    if already is not None and already.status == FlowNodeRunStatus.SUCCEEDED:
        logger.info(
            "flow node already completed, reusing output node=%s item=%d",
            node.id,
            item_index,
        )
        replay = NODE_REPLAYERS.get(node.kind)
        if replay is None:
            return NodeOutcome(output=already.output), False
        return replay(node, already.output), False

    executor = NODE_EXECUTORS[node.kind]
    attempts = node.retry.max_attempts
    last_error: NodeExecutionError | None = None

    for attempt in range(1, attempts + 1):
        if time.monotonic() > deadline:
            raise RunBudgetExceeded(f"run ran out of time while executing '{node.id}'")
        try:
            outcome = executor(node, context, runtime)
        except NodeSuspended as exc:
            recorder.park_node(
                node_id=node.id,
                iteration=iteration,
                item_index=item_index,
                detail=exc.detail,
            )
            raise
        except NodeExecutionError as exc:
            last_error = exc
        except Exception as exc:
            last_error = NodeExecutionError(
                FlowErrorClass.NODE_EXCEPTION, f"{type(exc).__name__}: {exc}"
            )
            logger.exception("flow node raised node=%s", node.id)
        else:
            recorder.finish_node(
                node_id=node.id,
                iteration=iteration,
                item_index=item_index,
                status=FlowNodeRunStatus.SUCCEEDED,
                output=outcome.output,
                attempt=attempt,
            )
            return outcome, True

        if attempt >= attempts or last_error.error_class not in RETRYABLE_ERROR_CLASSES:
            break

        pause = node.retry.backoff_seconds * (2 ** (attempt - 1))
        logger.info(
            "flow node retrying node=%s attempt=%d/%d in %.1fs reason=%s",
            node.id,
            attempt,
            attempts,
            pause,
            last_error.detail,
        )
        if time.monotonic() + pause > deadline:
            raise RunBudgetExceeded(f"no time left to retry '{node.id}'")
        time.sleep(pause)

    assert last_error is not None
    recorder.fail_node(
        node_id=node.id,
        iteration=iteration,
        item_index=item_index,
        error_class=last_error.error_class,
        error_detail=last_error.detail,
        attempt=attempts,
    )
    raise last_error


def _describe_input(context: RunContext) -> dict[str, Any] | None:
    """The slice of context the run inspector shows beside a node.

    Only what the node can actually see: the whole ``steps`` dict would repeat
    the entire run on every row.
    """
    described: dict[str, Any] = {}
    if context.item is not None:
        described["item"] = context.item
    if context.index is not None:
        described["index"] = context.index
    return described or None


def _execution_order(spec: FlowSpec) -> list[str]:
    """Reachable nodes in topological order.

    Kahn's algorithm over the reachable subgraph, seeded in declaration order
    so a flow with independent branches runs the same way every time. The spec
    validator has already ruled out cycles, so this cannot stall.
    """
    reachable = spec.reachable_ids()
    by_id = spec.node_map()

    indegree: dict[str, int] = dict.fromkeys(reachable, 0)
    for node_id in reachable:
        for target in by_id[node_id].successors():
            if target in reachable:
                indegree[target] += 1

    declaration_order = [node.id for node in spec.nodes if node.id in reachable]
    ready = deque(node_id for node_id in declaration_order if indegree[node_id] == 0)

    order: list[str] = []
    while ready:
        node_id = ready.popleft()
        order.append(node_id)
        for target in by_id[node_id].successors():
            if target not in reachable:
                continue
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)

    return order


def _predecessor_map(spec: FlowSpec, order: list[str]) -> dict[str, set[str]]:
    included = set(order)
    predecessors: dict[str, set[str]] = defaultdict(set)
    by_id = spec.node_map()
    for node_id in order:
        for target in by_id[node_id].successors():
            if target in included:
                predecessors[target].add(node_id)
    return predecessors


def _is_activated(
    node_id: str,
    entries: frozenset[str],
    predecessors: dict[str, set[str]],
    handed_to: dict[str, set[str]],
) -> bool:
    """Whether any predecessor actually chose this node.

    An entry node — the start, or where a loop's pass begins — is always
    activated. Everything else needs a predecessor that ran *and* named it,
    which is how a condition's untaken branch ends up skipped rather than
    merely unvisited.
    """
    if node_id in entries:
        return True
    return any(
        node_id in handed_to.get(parent, set())
        for parent in predecessors.get(node_id, set())
    )
