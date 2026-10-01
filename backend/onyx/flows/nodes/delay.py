"""Delay node: wait, then carry on.

Two ways to wait, picked by how long the wait is.

A short one sleeps where it stands. A long one parks the run: its status
becomes AWAITING_DELAY with a ``resume_at``, the node keeps an open row, and a
sweep re-queues it when it comes due. Nothing is held in between, so "follow up
tomorrow" costs no worker and survives a deploy in the middle of it.

The threshold is fixed rather than configurable because the trade is fixed:
parking costs one sweep tick, so below a minute the park would be slower than
the wait it replaces.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from onyx.db.enums import FlowRunStatus
from onyx.flows.expressions import RunContext
from onyx.flows.models import DelayNode
from onyx.flows.nodes.base import NodeOutcome, NodeRuntime, NodeSuspended
from onyx.utils.logger import setup_logger

logger = setup_logger()


def execute_delay(
    node: DelayNode, _context: RunContext, _runtime: NodeRuntime
) -> NodeOutcome:
    """Sleep for a short wait, or park the run for a long one."""
    if not node.parks_the_run():
        if node.seconds > 0:
            time.sleep(node.seconds)
        return NodeOutcome(output={"waited_seconds": node.seconds, "parked": False})

    resume_at = datetime.now(tz=timezone.utc) + timedelta(seconds=node.seconds)
    logger.info(
        "flow run parking on a delay node=%s until=%s", node.id, resume_at.isoformat()
    )
    raise NodeSuspended(
        node_id=node.id,
        detail={"resume_at": resume_at.isoformat(), "seconds": node.seconds},
        status=FlowRunStatus.AWAITING_DELAY,
        resume_at=resume_at,
    )
