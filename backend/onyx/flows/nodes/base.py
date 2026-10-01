"""Shared plumbing for node executors.

Every node kind is a plain function taking (node, context, runtime) and
returning a ``NodeOutcome``. Keeping them functions rather than classes means
a test can call one directly with a hand-built context, which is most of why
the engine stays easy to reason about.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

import httpx

from onyx.db.enums import FlowErrorClass, FlowRunStatus
from onyx.flows.expressions import RunContext
from onyx.llm.interfaces import LLM
from onyx.tools.tool_implementations.python.code_interpreter_client import (
    CodeInterpreterClient,
    ExecuteResponse,
    FileInput,
)


class NodeExecutionError(Exception):
    """A node failed in a way worth recording on its run row.

    ``error_class`` lands in ``flow_node_run.error_class`` and feeds triage
    queries, so it must come from the closed vocabulary rather than being
    invented at the call site.
    """

    def __init__(self, error_class: FlowErrorClass, detail: str) -> None:
        super().__init__(detail)
        self.error_class = error_class
        self.detail = detail


class NodeSuspended(Exception):
    """A node is waiting, so the run parks instead of finishing.

    Not a failure, and deliberately not a subclass of ``NodeExecutionError``:
    ``on_error`` and the retry policy must both leave it alone. The engine
    catches it, returns the status the node asked for, and the node keeps its
    open row until whatever it is waiting for arrives.

    Two things do the waiting. An approval waits on a person and carries no
    ``resume_at``; a long delay waits on the clock and carries one, which the
    sweep reads to know when the run is due.
    """

    def __init__(
        self,
        *,
        node_id: str,
        detail: dict[str, Any],
        status: FlowRunStatus = FlowRunStatus.AWAITING_DECISION,
        resume_at: datetime | None = None,
    ) -> None:
        super().__init__(f"run parked at '{node_id}' as {status.value}")
        self.node_id = node_id
        # Merged into the node row's input, which is what the run view shows
        # beside the step. Rendered by then, so a reader sees real values
        # rather than `{{ }}`.
        self.detail = detail
        self.status = status
        self.resume_at = resume_at


@dataclass(frozen=True)
class NodeOutcome:
    """What a node produced and where control goes next.

    ``next_ids`` is None for every node that just follows its declared
    successors; the branching kinds set it to the path they chose.
    """

    output: Any
    next_ids: list[str] | None = None


class CodeRunner(Protocol):
    """The slice of the code interpreter client a flow needs.

    Narrow on purpose: a test substitutes a dozen-line fake, and nothing in
    the flow package can reach for session or file management by accident.
    """

    def execute(
        self,
        code: str,
        stdin: str | None = None,
        timeout_ms: int = 30000,
        files: list[FileInput] | None = None,
    ) -> ExecuteResponse: ...

    def close(self) -> None: ...


def build_code_runner() -> CodeRunner:
    """The real sandbox client.

    Raises if the service is not configured, which the code node turns into a
    readable error rather than a stack trace.
    """
    return CodeInterpreterClient()


@dataclass
class NodeRuntime:
    """Resources shared across the nodes of one run.

    Every dependency is injected rather than imported at the call site so a
    test can pass a transport-mocked client, a stub model and a fake sandbox
    without touching global state or reaching the network.

    The model and the sandbox are built on first use. A flow made of HTTP
    nodes never constructs either, which keeps a purely mechanical flow
    working on a deployment that has configured neither.
    """

    http_client: httpx.Client
    llm_provider: Callable[[], LLM]
    code_runner_provider: Callable[[], CodeRunner] = build_code_runner
    # Signs what the flow's webhook nodes send. None leaves deliveries
    # unsigned, which the webhook node warns about rather than refusing —
    # a flow written before the secret existed should still deliver.
    webhook_signing_secret: str | None = None
    # Monotonic time the run has to finish by, set by the engine. The engine
    # checks it between nodes; a node that does many things in one step reads
    # it too, so it stops starting new work instead of overrunning the budget.
    deadline: float | None = None

    _llm: LLM | None = None
    _code_runner: CodeRunner | None = None

    def llm(self) -> LLM:
        """The run's model, created on first use."""
        if self._llm is None:
            self._llm = self.llm_provider()
        return self._llm

    def code_runner(self) -> CodeRunner:
        """The run's sandbox client, created on first use."""
        if self._code_runner is None:
            self._code_runner = self.code_runner_provider()
        return self._code_runner

    def out_of_time(self) -> bool:
        """Whether the run's budget is spent. Never true without a deadline."""
        return self.deadline is not None and time.monotonic() > self.deadline

    def close(self) -> None:
        """Release what the run opened. Safe to call twice."""
        self.http_client.close()
        if self._code_runner is not None:
            self._code_runner.close()
            self._code_runner = None


class NodeExecutor(Protocol):
    # Positional-only: a handler that ignores one of these names it `_runtime`
    # and stays conformant.
    def __call__(
        self, node: Any, context: RunContext, runtime: NodeRuntime, /
    ) -> NodeOutcome: ...


class NodeReplayer(Protocol):
    """Rebuilds the outcome of a node execution already on record.

    Only kinds that choose a branch need one: a plain node's successors are
    the same whatever it produced, while a condition, a switch or an approval
    has to read its own recorded output to know which way the run went. Without this
    a resumed run would take the empty ``next`` list and skip everything
    downstream of the branch it actually chose.
    """

    def __call__(self, node: Any, output: Any, /) -> NodeOutcome: ...
