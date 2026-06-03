"""Schedule node: wait until the next time a cron expression comes round.

The sibling of the delay node, and it parks the run the same way and at the
same threshold. The difference is only in how the moment is worked out: a
delay is told how long to wait, a schedule is told when to stop waiting.

Cron is read in UTC, matching the schedule triggers, so there is one answer to
"what does 9 mean" across the product rather than two.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from onyx.db.enums import FlowErrorClass, FlowRunStatus
from onyx.error_handling.exceptions import OnyxError
from onyx.flows.expressions import RunContext
from onyx.flows.models import INLINE_DELAY_SECONDS, ScheduleNode
from onyx.flows.nodes.base import (
    NodeExecutionError,
    NodeOutcome,
    NodeRuntime,
    NodeSuspended,
)
from onyx.server.features.build.scheduled_tasks.schedule import compute_next_run_at
from onyx.utils.logger import setup_logger

logger = setup_logger()


def execute_schedule(
    node: ScheduleNode, _context: RunContext, _runtime: NodeRuntime
) -> NodeOutcome:
    """Work out the next occurrence, then sleep or park until it arrives."""
    now = datetime.now(tz=timezone.utc)
    try:
        due_at = compute_next_run_at(node.cron, now)
    except (ValueError, OnyxError) as exc:
        # The spec rejects an unusable cron on save, so reaching here means
        # the expression stopped having a future fire after it was stored.
        raise NodeExecutionError(
            FlowErrorClass.INVALID_SPEC,
            f"schedule '{node.cron}' has no next occurrence: {exc}",
        ) from exc

    seconds = max(0.0, (due_at - now).total_seconds())

    if seconds <= INLINE_DELAY_SECONDS:
        # Close enough that parking would cost more than the wait, the same
        # trade a short delay makes.
        if seconds > 0:
            time.sleep(seconds)
        return NodeOutcome(output={"waited_seconds": seconds, "parked": False})

    logger.info(
        "flow run parking on a schedule node=%s cron=%s until=%s",
        node.id,
        node.cron,
        due_at.isoformat(),
    )
    raise NodeSuspended(
        node_id=node.id,
        detail={
            "resume_at": due_at.isoformat(),
            "cron": node.cron,
            "seconds": seconds,
        },
        status=FlowRunStatus.AWAITING_DELAY,
        resume_at=due_at,
    )
