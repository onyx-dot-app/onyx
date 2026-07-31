"""Moving live sandboxes onto the current image.

Sandboxes are owned by no controller, so a deploy leaves every running one on the
old image indefinitely. Which ones are behind is derived from what is actually
running, not recorded, so there is nothing to drift and a restart loses nothing.

Two moments protect a chat: a sandbox with work queued or running is skipped, and
the prompt slots for its sessions are held across the move so one starting in
between is caught rather than interrupted. A busy sandbox just waits for the next
pass — recycling is never urgent enough to interrupt someone.
"""

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager

from redis.lock import Lock as RedisLock
from sqlalchemy.orm import Session as DBSession

from onyx.db.models import Sandbox
from onyx.redis.tenant_redis_client import TenantRedisClient
from onyx.server.features.build.db.build_session import (
    get_active_session_ids_for_user,
)
from onyx.server.features.build.db.sandbox import get_running_sandboxes
from onyx.server.features.build.sandbox.base import SandboxManager
from onyx.server.features.build.sandbox.models import (
    ImageMoveOutcome,
    SandboxImageTarget,
)
from onyx.server.features.build.session.locks import get_session_creation_lock
from onyx.server.features.build.session.sandbox_busy import sandbox_busy_claim
from onyx.server.features.build.session.sandbox_lifecycle import sleep_sandbox
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Bounds a rollout to a trickle of restarts per pass. Evaluation is deliberately
# unbounded: skipping is not recycling, so busy sandboxes at the front of a stable
# ordering would otherwise starve the ones behind them.
_MAX_RECYCLES_PER_PASS = 10


def recycle_sandboxes_on_stale_images(
    db_session: DBSession,
    sandbox_manager: SandboxManager,
    redis_client: TenantRedisClient,
    tenant_id: str,
) -> None:
    """Move as many sandboxes onto the current image as is safe right now.

    Safe on any cadence and from any process: everything is recomputed from live
    state, so a dropped, duplicated, or half-finished pass costs only time.
    """
    state = sandbox_manager.get_image_state()
    target = state.target
    stale_ids = state.stale_sandbox_ids()
    if target is None or not stale_ids:
        return

    stale = [
        sandbox
        for sandbox in get_running_sandboxes(db_session)
        if sandbox.id in stale_ids
    ]
    if not stale:
        return

    logger.info("%s sandbox(es) are behind image %s", len(stale), target.digest[:19])

    recycled = 0
    for sandbox in stale:
        if recycled >= _MAX_RECYCLES_PER_PASS:
            logger.info(
                "Reached the per-pass recycle limit; %s sandbox(es) left for the "
                "next pass",
                len(stale) - recycled,
            )
            break

        claim = sandbox_busy_claim(db_session, sandbox)
        if claim is not None:
            logger.info(
                "Leaving sandbox %s on the old image: %s", sandbox.id, claim.detail
            )
            continue

        if _recycle_sandbox(
            db_session, sandbox_manager, redis_client, sandbox, target, tenant_id
        ):
            recycled += 1


def _recycle_sandbox(
    db_session: DBSession,
    sandbox_manager: SandboxManager,
    redis_client: TenantRedisClient,
    sandbox: Sandbox,
    target: SandboxImageTarget,
    tenant_id: str,
) -> bool:
    """Ask the backend to move the sandbox, and finish whatever it started.

    Backends preserve different amounts — Kubernetes swaps the image under a live
    pod, compose replaces the container but keeps the workspace volume — so this
    reacts to what was done rather than choosing a strategy per backend. Anything
    the backend cannot do falls through to rebuilding from snapshots.
    """
    outcome = ImageMoveOutcome.UNSUPPORTED
    try:
        with _no_prompts_in_flight(db_session, sandbox_manager, sandbox) as held:
            if not held:
                logger.info(
                    "Sandbox %s started a prompt as we moved to recycle it; "
                    "leaving it for the next pass",
                    sandbox.id,
                )
                return False
            outcome = sandbox_manager.move_to_image(sandbox.id, target)
    except Exception:
        logger.warning(
            "Moving sandbox %s onto %s failed; falling back to rebuilding it",
            sandbox.id,
            target.digest[:19],
            exc_info=True,
        )
        outcome = ImageMoveOutcome.UNSUPPORTED

    if outcome is ImageMoveOutcome.MOVED:
        logger.info("Recycled sandbox %s in place", sandbox.id)
        return True

    return _rebuild_sandbox(
        db_session, sandbox_manager, redis_client, sandbox, target, tenant_id
    )


def _rebuild_sandbox(
    db_session: DBSession,
    sandbox_manager: SandboxManager,
    redis_client: TenantRedisClient,
    sandbox: Sandbox,
    target: SandboxImageTarget,
    tenant_id: str,
) -> bool:
    """Snapshot and sleep, so the user's next request provisions a fresh sandbox.

    The last resort, and the same path the idle reaper uses. Deliberately outside
    the prompt barrier: snapshotting takes minutes, and ``sleep_sandbox``
    re-checks eligibility under its own lock before the kill anyway.
    """
    lock: RedisLock = get_session_creation_lock(redis_client, sandbox.user_id)

    def still_worth_rebuilding() -> bool:
        """Minutes have passed: only kill a sandbox still stale and still free."""
        claim = sandbox_busy_claim(db_session, sandbox)
        if claim is not None:
            logger.info(
                "Sandbox %s took on work mid-rebuild: %s", sandbox.id, claim.detail
            )
            return False
        digest = sandbox_manager.get_image_state().live_digests.get(sandbox.id)
        if digest is None or digest == target.digest:
            logger.info(
                "Sandbox %s is no longer behind; skipping the rebuild", sandbox.id
            )
            return False
        return True

    slept = sleep_sandbox(
        db_session,
        sandbox_manager,
        sandbox,
        tenant_id,
        lock,
        still_eligible=still_worth_rebuilding,
    )
    if slept:
        logger.info(
            "Sandbox %s slept; its next request will provision on %s",
            sandbox.id,
            target.digest[:19],
        )
    return slept


@contextmanager
def _no_prompts_in_flight(
    db_session: DBSession,
    sandbox_manager: SandboxManager,
    sandbox: Sandbox,
) -> Iterator[bool]:
    """Hold every prompt slot the sandbox's sessions use, yielding whether they
    were all free.

    The same lock the chat path takes, so it is both check and barrier with no
    window between, and a prompt path added later is covered for free. Fails
    *closed*: an unreachable cache cannot tell us a prompt is not running.
    """
    session_ids = get_active_session_ids_for_user(sandbox.user_id, db_session)
    with ExitStack() as stack:
        yield all(
            stack.enter_context(
                sandbox_manager.prompt_slot(
                    sandbox.id, session_id, acquire_timeout=0.0, fail_open=False
                )
            ).acquired
            for session_id in session_ids
        )
