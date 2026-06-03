"""Node executors, keyed by kind.

The engine looks a node's handler up here and calls it. Adding a kind means
adding a spec model, a handler, and one line in this table.
"""

from __future__ import annotations

from onyx.db.enums import FlowNodeKind
from onyx.flows.nodes.ai import execute_ai
from onyx.flows.nodes.base import (
    NodeExecutionError,
    NodeExecutor,
    NodeOutcome,
    NodeRuntime,
)
from onyx.flows.nodes.condition import execute_condition
from onyx.flows.nodes.http import build_http_client, execute_http
from onyx.flows.nodes.transform import execute_transform

NODE_EXECUTORS: dict[FlowNodeKind, NodeExecutor] = {
    FlowNodeKind.HTTP: execute_http,
    FlowNodeKind.TRANSFORM: execute_transform,
    FlowNodeKind.CONDITION: execute_condition,
    FlowNodeKind.AI: execute_ai,
}

__all__ = [
    "NODE_EXECUTORS",
    "NodeExecutionError",
    "NodeExecutor",
    "NodeOutcome",
    "NodeRuntime",
    "build_http_client",
]
