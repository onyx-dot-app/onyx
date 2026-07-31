"""Moving live sandboxes onto the current image.

Sandboxes are owned by no controller, so a deploy leaves every running one on the
old image indefinitely. Which ones are behind is derived from what is actually
running, not recorded, so there is nothing to drift and a restart loses nothing.

A restart is only taken while the sandbox is held still: session creation
excluded, no work queued or running, and every prompt slot its sessions use held
across the move. A sandbox that fails any of those just waits for the next pass —
recycling is never urgent enough to interrupt someone, and each pass is bounded
in restarts and in wall clock so a rollout never takes the sweep over.
"""

import time
from collections.abc import Iterator, Sequence
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
from uuid import UUID

from redis.lock import Lock as RedisLock
from sqlalchemy.orm import Session as DBSession

from onyx.db.models import Sandbox
from onyx.redis.tenant_redis_client import TenantRedisClient
from onyx.server.features.build.db.build_session import (
    get_live_session_ids_for_user,
)
from onyx.server.features.build.db.sandbox import get_running_sandboxes
from onyx.server.features.build.sandbox.base import SandboxManager
from onyx.server.features.build.sandbox.models import (
    ImageMoveOutcome,
    SandboxImageTarget,
)
from onyx.server.features.build.session.locks import get_session_creation_lock
from onyx.server.features.build.session.sandbox_busy import sandbox_busy_claim
from onyx.server.features.build.session.sandbox_lifecycle import (
    is_sandbox_idle,
    sandbox_mutation_window,
    sleep_sandbox,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Bounds a rollout to a trickle of restarts per pass. Evaluation is deliberately
# unbounded: skipping is not recycling, so busy sandboxes at the front of a stable
# ordering would otherwise starve the ones behind them.
_MAX_RECYCLES_PER_PASS = 10

# And bounds the pass in wall clock, because the count doesn't: an in-place swap
# waits out a pod restart and a rebuild snapshots first. The idle reaps and
# background snapshots share this tick under one lock, so a rollout must not push
# them behind it — whatever is left is picked up next pass.
_MAX_RECYCLE_SECONDS_PER_PASS = 180.0


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

    # Idle ones are skipped, not recycled: the reaper is about to reclaim them,
    # and one whose reap was refused this pass will be tried again next pass.
    # Restarting it in between costs a user's pod for nothing.
    now = datetime.now(timezone.utc)
    stale = [
        sandbox
        for sandbox in get_running_sandboxes(db_session)
        if sandbox.id in stale_ids and not is_sandbox_idle(sandbox, now)
    ]
    if not stale:
        return

    logger.info("%s sandbox(es) are behind image %s", len(stale), target.digest[:19])

    deadline = time.monotonic() + _MAX_RECYCLE_SECONDS_PER_PASS
    recycled = 0
    for index, sandbox in enumerate(stale):
        out_of_restarts = recycled >= _MAX_RECYCLES_PER_PASS
        if out_of_restarts or time.monotonic() >= deadline:
            logger.info(
                "Recycle pass is out of %s; %s sandbox(es) left for the next one",
                "restarts" if out_of_restarts else "time",
                len(stale) - index,
            )
            break

        # Cheap pre-gate, before any lock: most refusals are a busy sandbox, and
        # skipping one must cost nothing. Re-checked once the sandbox is held.
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
    reacts to what was done rather than choosing a strategy per backend. A backend
    that changed nothing falls through to rebuilding from snapshots; one that
    disturbed the sandbox without finishing is left alone.

    Returns whether the sandbox's pod was restarted, which is what the per-pass
    bound counts.
    """
    # One lock object for both paths, taken by each in turn: the rebuild acquires
    # it itself, so it can only run once the in-place window has released it.
    session_creation_lock = get_session_creation_lock(redis_client, sandbox.user_id)

    outcome = _swap_in_place(
        db_session, sandbox_manager, sandbox, target, session_creation_lock
    )
    if outcome is None:
        return False

    if outcome is ImageMoveOutcome.MOVED:
        logger.info("Recycled sandbox %s in place", sandbox.id)
        return True

    if outcome is ImageMoveOutcome.DISRUPTED:
        logger.warning(
            "Sandbox %s did not come back on %s; leaving it rather than "
            "snapshotting a pod that may be mid-restart",
            sandbox.id,
            target.digest[:19],
        )
        return True

    return _rebuild_sandbox(
        db_session,
        sandbox_manager,
        sandbox,
        target,
        tenant_id,
        session_creation_lock,
    )


def _swap_in_place(
    db_session: DBSession,
    sandbox_manager: SandboxManager,
    sandbox: Sandbox,
    target: SandboxImageTarget,
    session_creation_lock: RedisLock,
) -> ImageMoveOutcome | None:
    """Ask the backend to move the sandbox while it is held still, or ``None``
    if it could not be held."""
    with _sandbox_held_still(
        db_session, sandbox_manager, sandbox, session_creation_lock
    ) as held:
        if not held:
            return None
        try:
            return sandbox_manager.move_to_image(sandbox.id, target)
        except Exception:
            logger.warning(
                "Moving sandbox %s onto %s failed; falling back to rebuilding it",
                sandbox.id,
                target.digest[:19],
                exc_info=True,
            )
            return ImageMoveOutcome.UNSUPPORTED


def _rebuild_sandbox(
    db_session: DBSession,
    sandbox_manager: SandboxManager,
    sandbox: Sandbox,
    target: SandboxImageTarget,
    tenant_id: str,
    session_creation_lock: RedisLock,
) -> bool:
    """Snapshot and sleep, so the user's next request provisions a fresh sandbox.

    The last resort, and the same path the idle reaper uses. Deliberately outside
    the window the in-place swap holds: snapshotting takes minutes, and
    ``sleep_sandbox`` takes the same lock and re-checks eligibility under it
    before the kill anyway.
    """

    def still_worth_rebuilding() -> bool:
        """Minutes have passed: only kill a sandbox still stale and still free."""
        claim = sandbox_busy_claim(db_session, sandbox)
        if claim is not None:
            logger.info(
                "Sandbox %s took on work mid-rebuild: %s", sandbox.id, claim.detail
            )
            return False
        digest = sandbox_manager.get_image_state().movable_digests.get(sandbox.id)
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
        session_creation_lock,
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
def _sandbox_held_still(
    db_session: DBSession,
    sandbox_manager: SandboxManager,
    sandbox: Sandbox,
    session_creation_lock: RedisLock,
) -> Iterator[bool]:
    """Everything that has to hold still for a live sandbox to be restarted,
    yielding whether the caller may proceed.

    ``sandbox_mutation_window`` excludes session creation and re-checks the row
    is RUNNING — creation matters because it execs into the sandbox holding no
    prompt slot, so the barrier below cannot see it. Under that lock the live
    session set cannot grow, which is what makes one read of it enough for both
    the busy check and the slots to hold.
    """
    with sandbox_mutation_window(
        db_session, sandbox, session_creation_lock
    ) as may_mutate:
        if not may_mutate:
            yield False
            return

        session_ids = get_live_session_ids_for_user(sandbox.user_id, db_session)
        claim = sandbox_busy_claim(db_session, sandbox, session_ids=session_ids)
        if claim is not None:
            logger.info(
                "Sandbox %s took on work before the swap: %s", sandbox.id, claim.detail
            )
            yield False
            return

        with _no_prompts_in_flight(sandbox_manager, sandbox.id, session_ids) as held:
            if not held:
                logger.info(
                    "Sandbox %s started a prompt as we moved to recycle it; "
                    "leaving it for the next pass",
                    sandbox.id,
                )
            yield held


@contextmanager
def _no_prompts_in_flight(
    sandbox_manager: SandboxManager,
    sandbox_id: UUID,
    session_ids: Sequence[UUID],
) -> Iterator[bool]:
    """Hold every prompt slot the sandbox's sessions use, yielding whether they
    were all free.

    The same lock the chat path takes, so it is both check and barrier with no
    window between, and a prompt path added later is covered for free. Fails
    *closed*: an unreachable cache cannot tell us a prompt is not running.

    The slots are held, never renewed, so whatever runs inside must finish within
    one lease (``PROMPT_SLOT_LEASE_SECONDS``, which the backends' move timeouts
    stay under).
    """
    with ExitStack() as stack:
        yield all(
            stack.enter_context(
                sandbox_manager.prompt_slot(
                    sandbox_id, session_id, acquire_timeout=0.0, fail_open=False
                )
            ).acquired
            for session_id in session_ids
        )
