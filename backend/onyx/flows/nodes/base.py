"""Shared plumbing for node executors.

Every node kind is a plain function taking (node, context, runtime) and
returning a ``NodeOutcome``. Keeping them functions rather than classes means
a test can call one directly with a hand-built context, which is most of why
the engine stays easy to reason about.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from onyx.db.enums import FlowErrorClass
from onyx.flows.expressions import RunContext
from onyx.llm.interfaces import LLM


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


@dataclass(frozen=True)
class NodeOutcome:
    """What a node produced and where control goes next.

    ``next_ids`` is None for every node that just follows its declared
    successors; only a condition overrides it.
    """

    output: Any
    next_ids: list[str] | None = None


@dataclass
class NodeRuntime:
    """Resources shared across the nodes of one run.

    Both dependencies are injected rather than imported at the call site so a
    test can pass a transport-mocked client and a stub model without touching
    global state or reaching the network.
    """

    http_client: httpx.Client
    llm_provider: Callable[[], LLM]

    _llm: LLM | None = None

    def llm(self) -> LLM:
        """The run's model, created on first use.

        A flow with no AI node never builds one, which keeps a purely
        mechanical flow independent of LLM configuration.
        """
        if self._llm is None:
            self._llm = self.llm_provider()
        return self._llm


class NodeExecutor(Protocol):
    # Positional-only: a handler that ignores one of these names it `_runtime`
    # and stays conformant.
    def __call__(
        self, node: Any, context: RunContext, runtime: NodeRuntime, /
    ) -> NodeOutcome: ...
