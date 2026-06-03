"""Node executors, keyed by kind.

The engine looks a node's handler up here and calls it. Adding a kind means
adding a spec model, a handler, and one line in this table.

``NODE_REPLAYERS`` is the second, smaller table. A node the engine meets again
on a resumed run is not executed a second time — its recorded output is
reused. For most kinds that is the whole story, but a kind that picks a branch
also has to say which way it went, and that is what a replayer does.
"""

from __future__ import annotations

from onyx.db.enums import FlowNodeKind
from onyx.flows.nodes.ai import execute_ai
from onyx.flows.nodes.base import (
    NodeExecutionError,
    NodeExecutor,
    NodeOutcome,
    NodeReplayer,
    NodeRuntime,
    NodeSuspended,
)
from onyx.flows.nodes.code import execute_code
from onyx.flows.nodes.condition import execute_condition, resume_condition
from onyx.flows.nodes.delay import execute_delay
from onyx.flows.nodes.filter import execute_filter
from onyx.flows.nodes.http import build_http_client, execute_http
from onyx.flows.nodes.human import execute_human, resume_human
from onyx.flows.nodes.loop import execute_loop
from onyx.flows.nodes.merge import execute_merge
from onyx.flows.nodes.parallel import execute_parallel
from onyx.flows.nodes.retry import execute_retry
from onyx.flows.nodes.schedule import execute_schedule
from onyx.flows.nodes.split import execute_split
from onyx.flows.nodes.switch import execute_switch, resume_switch
from onyx.flows.nodes.transform import execute_transform
from onyx.flows.nodes.webhook import execute_webhook

NODE_EXECUTORS: dict[FlowNodeKind, NodeExecutor] = {
    FlowNodeKind.HTTP: execute_http,
    FlowNodeKind.TRANSFORM: execute_transform,
    FlowNodeKind.CONDITION: execute_condition,
    FlowNodeKind.AI: execute_ai,
    FlowNodeKind.HUMAN: execute_human,
    FlowNodeKind.CODE: execute_code,
    FlowNodeKind.LOOP: execute_loop,
    FlowNodeKind.RETRY: execute_retry,
    FlowNodeKind.WEBHOOK: execute_webhook,
    FlowNodeKind.DELAY: execute_delay,
    FlowNodeKind.FILTER: execute_filter,
    FlowNodeKind.SCHEDULE: execute_schedule,
    FlowNodeKind.MERGE: execute_merge,
    FlowNodeKind.SPLIT: execute_split,
    FlowNodeKind.PARALLEL: execute_parallel,
    FlowNodeKind.SWITCH: execute_switch,
}

NODE_REPLAYERS: dict[FlowNodeKind, NodeReplayer] = {
    FlowNodeKind.CONDITION: resume_condition,
    FlowNodeKind.HUMAN: resume_human,
    FlowNodeKind.SWITCH: resume_switch,
}

__all__ = [
    "NODE_EXECUTORS",
    "NODE_REPLAYERS",
    "NodeExecutionError",
    "NodeExecutor",
    "NodeOutcome",
    "NodeReplayer",
    "NodeRuntime",
    "NodeSuspended",
    "build_http_client",
]
