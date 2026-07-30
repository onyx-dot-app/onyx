"""Sandbox readiness state machine: durable reservation, external
reconciliation, and generation-fenced finalization. Shared between the
interactive create/restore flows and headless callers
(``ensure_sandbox_running``).

The lifecycle is split into three parts so no database transaction ever spans
external I/O:

1. **Reserve** (short transaction): lock the user row, commit the sandbox
   identity in ``PROVISIONING`` with an advanced fencing generation, and
   commit the Craft PAT. Once committed, the proxy can resolve the pod's
   owner and credentials from any connection — a bootstrapping pod's egress
   works before the sandbox is ``RUNNING``.
2. **Reconcile** (no transaction): create/reuse the pod and its resources
   idempotently, push sandbox-level managed content.
3. **Finalize** (short transaction): generation-guarded compare-and-set to
   ``RUNNING`` or ``FAILED``. A stale attempt cannot overwrite a newer
   decision.
"""

import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from uuid import UUID

from redis.lock import Lock as RedisLock
from sqlalchemy.orm import Session as DBSession

from onyx.db.enums import SandboxStatus
from onyx.db.models import Sandbox, User
from onyx.db.users import fetch_user_by_id
from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.build.configs import (
    SANDBOX_IDLE_TIMEOUT_SECONDS,
    SANDBOX_MAX_CONCURRENT_PER_ORG,
)
from onyx.server.features.build.db.build_session import (
    clear_nextjs_ports_for_user,
    get_orphan_build_session_ids,
    mark_user_sessions_idle__no_commit,
)
from onyx.server.features.build.db.sandbox import (
    begin_provisioning_attempt__no_commit,
    begin_recovery_attempt_cas__no_commit,
    create_sandbox__no_commit,
    create_snapshot__no_commit,
    delete_snapshot__no_commit,
    ensure_sandbox_pat,
    finalize_provisioning_attempt__no_commit,
    get_running_sandbox_count,
    get_sandbox_by_id,
    get_sandbox_by_user_id,
    get_sandbox_user_map,
    get_snapshots_for_session,
    set_sandbox_mcp_config_hashes__no_commit,
    set_sandbox_skills_hashes__no_commit,
    update_sandbox_status__no_commit,
)
from onyx.server.features.build.sandbox.base import SandboxManager
from onyx.server.features.build.sandbox.models import (
    FileSet,
    SnapshotResult,
)
from onyx.server.features.build.sandbox.snapshot_manager import SnapshotManager
from onyx.server.features.build.sandbox.user_library import (
    USER_LIBRARY_MOUNT_PATH,
    build_user_library_fileset,
)
from onyx.server.features.build.sandbox.util.mcp_config import (
    craft_mcp_fingerprint,
    resolve_craft_mcp_servers,
)
from onyx.server.features.build.session.errors import (
    SandboxProvisioningError,
    SandboxProvisioningInProgressError,
    StaleProvisioningAttemptError,
)
from onyx.server.metrics.craft_sandbox import (
    SandboxProvisionPhase,
    SandboxReadyOutcome,
    observe_sandbox_ready,
    time_provision_phase,
    track_sandbox_provision_in_progress,
)
from onyx.skills.push import (
    SKILLS_MOUNT_PATH,
    build_user_skills_payload,
    compute_skill_runtime_hash,
)
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()


_HEALTHCHECK_TIMEOUT_SECONDS = 5.0

# A committed PROVISIONING attempt older than this is considered dead: every
# bounded wait in the sandbox managers (per-sandbox provisioning lock, pod/
# opencode readiness) completes well within it, so a live attempt cannot still
# be working. A newer reservation may take the generation over.
PROVISIONING_ATTEMPT_STALE_SECONDS = 240.0

# Statuses from which (re-)provisioning a pod is legal.
_REPROVISIONABLE_STATUSES: frozenset[SandboxStatus] = frozenset(
    {
        SandboxStatus.SLEEPING,
        SandboxStatus.TERMINATED,
        SandboxStatus.FAILED,
    }
)


@dataclass(frozen=True)
class SandboxReservation:
    """Committed identity of a sandbox provisioning attempt. Carries plain
    values only — never a live SQLAlchemy model or session — so external
    reconciliation cannot touch the reservation transaction."""

    sandbox_id: UUID
    tenant_id: str
    generation: int
    # Set only when this reservation authorized external provisioning (the
    # row is committed PROVISIONING at `generation`); None when the sandbox
    # was already RUNNING and only needs a health check.
    onyx_pat: str | None
    requires_provisioning: bool
    sandbox_preexisted: bool


@dataclass(frozen=True)
class ManagedContentPayload:
    """Sandbox-level managed content, prebuilt from database state so the
    external push runs without an open transaction."""

    connectable_apps_section: str
    skills_files: FileSet
    skills_hash: str
    mcp_fingerprint: str
    library_files: FileSet


def snapshot_opencode_history_before_recovery(
    sandbox_manager: SandboxManager,
    sandbox_id: UUID,
    tenant_id: str,
) -> None:
    """Best-effort history capture before terminating an unhealthy sandbox."""
    if not sandbox_manager.supports_opencode_history_persistence:
        return

    try:
        sandbox_manager.create_opencode_history_snapshot(
            sandbox_id,
            tenant_id,
            timeout_seconds=30.0,
        )
    except Exception:
        logger.warning(
            "opencode history snapshot failed during recovery of sandbox %s",
            sandbox_id,
            exc_info=True,
        )


def create_session_snapshot_keep_latest(
    sandbox_manager: SandboxManager,
    db_session: DBSession,
    sandbox_id: UUID,
    session_id: UUID,
    tenant_id: str,
) -> SnapshotResult | None:
    """Create a sandbox archive, record it, and prune snapshots older than it."""
    prior_snapshots = get_snapshots_for_session(db_session, session_id)
    result = sandbox_manager.create_snapshot(
        sandbox_id=sandbox_id,
        session_id=session_id,
        tenant_id=tenant_id,
    )
    if result is None:
        return None

    create_snapshot__no_commit(
        db_session=db_session,
        session_id=session_id,
        storage_path=result.storage_path,
        size_bytes=result.size_bytes,
    )

    snapshot_manager = SnapshotManager(get_default_file_store())
    for old in prior_snapshots:
        try:
            snapshot_manager.delete_snapshot(old.storage_path)
        except Exception as e:
            logger.warning(
                "Skipping prune of snapshot %s; blob delete failed: %s", old.id, e
            )
            continue
        delete_snapshot__no_commit(db_session, old)

    db_session.commit()
    return result


# =============================================================================
# Managed content: build (DB reads) → push (external) → record (short tx)
# =============================================================================


def build_managed_content_payload(
    user: User, db_session: DBSession
) -> ManagedContentPayload:
    """Read-only assembly of the skills/user-library payload and its hashes.
    Callers must close the read transaction before pushing externally."""
    connectable_apps_section, skills_files = build_user_skills_payload(user, db_session)
    return ManagedContentPayload(
        connectable_apps_section=connectable_apps_section,
        skills_files=skills_files,
        skills_hash=compute_skill_runtime_hash(skills_files, connectable_apps_section),
        mcp_fingerprint=craft_mcp_fingerprint(
            resolve_craft_mcp_servers(db_session, user)
        ),
        library_files=build_user_library_fileset(user.id, db_session),
    )


@time_provision_phase(SandboxProvisionPhase.HYDRATE_MANAGED_CONTENT)
def push_managed_content(
    sandbox_manager: SandboxManager,
    sandbox_id: UUID,
    payload: ManagedContentPayload,
) -> bool:
    """Push managed skills + user library into a sandbox. External I/O only —
    no database access. Push failures are logged, never raised.

    Must complete before the sandbox is reported RUNNING: turns dispatch as
    soon as RUNNING is visible, and opencode scans the skills directory once
    per instance, so a turn started mid-push permanently misses managed
    skills.

    Returns whether the skills push fully succeeded (gates recording
    ``skills_hash``).
    """
    skills_hydrated = False
    try:
        result = sandbox_manager.push_to_sandbox(
            sandbox_id=sandbox_id,
            mount_path=SKILLS_MOUNT_PATH,
            files=payload.skills_files,
        )
        skills_hydrated = result.succeeded == result.targets
    except Exception:
        logger.warning("Failed to push skills to sandbox %s", sandbox_id, exc_info=True)
    try:
        sandbox_manager.push_to_sandbox(
            sandbox_id=sandbox_id,
            mount_path=USER_LIBRARY_MOUNT_PATH,
            files=payload.library_files,
        )
    except Exception:
        logger.warning(
            "Failed to push user library to sandbox %s", sandbox_id, exc_info=True
        )
    return skills_hydrated


def record_managed_content_hashes__no_commit(
    db_session: DBSession,
    sandbox_id: UUID,
    payload: ManagedContentPayload,
    skills_hydrated: bool,
) -> None:
    """Stamp the sandbox with the content state that was actually pushed.
    The MCP fingerprint is recorded regardless of the skill push (MCP config
    is written per session), the skills hash only when the push landed."""
    set_sandbox_mcp_config_hashes__no_commit(
        db_session, {sandbox_id: payload.mcp_fingerprint}
    )
    if skills_hydrated:
        set_sandbox_skills_hashes__no_commit(
            db_session, {sandbox_id: payload.skills_hash}
        )


def sync_managed_content(
    db_session: DBSession,
    sandbox_manager: SandboxManager,
    sandbox_id: UUID,
    user: User,
) -> None:
    """Build → push → record for an already-RUNNING sandbox. Commits; callers
    must be at a clean transaction boundary."""
    payload = build_managed_content_payload(user, db_session)
    db_session.commit()
    skills_hydrated = push_managed_content(sandbox_manager, sandbox_id, payload)
    record_managed_content_hashes__no_commit(
        db_session, sandbox_id, payload, skills_hydrated
    )
    db_session.commit()


# =============================================================================
# Reserve → reconcile → finalize
# =============================================================================


class ProvisioningPolicy(str, Enum):
    """How to handle a sandbox already owned by a live ``PROVISIONING``
    attempt when we arrive.

    - ``POLL``: wait for the concurrent provisioner to finish, then re-enter
      the state machine on the resulting status. Used by headless callers
      (scheduled tasks) that can afford to block.
    - ``FAIL``: raise immediately. Used by interactive callers (web request
      handlers) that hit a wall-clock deadline.
    """

    POLL = "poll"
    FAIL = "fail"


def _provisioning_attempt_is_stale(sandbox: Sandbox) -> bool:
    """A committed PROVISIONING row whose attempt can no longer be alive.
    Rows without a start timestamp predate the attempt tracking and are
    always stale."""
    if sandbox.provisioning_started_at is None:
        return True
    age = datetime.now(timezone.utc) - sandbox.provisioning_started_at
    return age.total_seconds() >= PROVISIONING_ATTEMPT_STALE_SECONDS


def _enforce_tenant_concurrency_limit(db_session: DBSession) -> None:
    """No-op on self-hosted. On multi-tenant: raise if creating/waking a
    sandbox would exceed the per-tenant cap."""
    if not MULTI_TENANT:
        return
    running_count = get_running_sandbox_count(db_session)
    if running_count >= SANDBOX_MAX_CONCURRENT_PER_ORG:
        raise ValueError(
            f"Maximum concurrent sandboxes ({SANDBOX_MAX_CONCURRENT_PER_ORG}) reached"
        )


def reserve_sandbox__no_commit(
    db_session: DBSession,
    user: User,
) -> SandboxReservation:
    """Reserve the user's sandbox for use, advancing the provisioning
    generation when external reconciliation is required.

    Must be called with the user's row locked (``fetch_user_by_id(for_update=True)``)
    in the current transaction so concurrent reservers serialize. ``flush``
    only — the caller commits, and MUST commit before any external work.

    Raises:
        SandboxProvisioningInProgressError: a live attempt owns the sandbox.
        ValueError: tenant concurrency cap reached.
    """
    tenant_id = get_current_tenant_id()
    sandbox = get_sandbox_by_user_id(db_session, user.id)
    sandbox_preexisted = sandbox is not None
    requires_provisioning: bool

    if sandbox is None:
        _enforce_tenant_concurrency_limit(db_session)
        sandbox = create_sandbox__no_commit(db_session=db_session, user_id=user.id)
        generation = begin_provisioning_attempt__no_commit(db_session, sandbox)
        requires_provisioning = True
        logger.info(
            "Created sandbox %s for user %s (generation %s)",
            sandbox.id,
            user.id,
            generation,
        )
    elif sandbox.status == SandboxStatus.RUNNING:
        generation = sandbox.provisioning_generation
        requires_provisioning = False
    elif sandbox.status in _REPROVISIONABLE_STATUSES:
        _enforce_tenant_concurrency_limit(db_session)
        previous_status = sandbox.status
        generation = begin_provisioning_attempt__no_commit(db_session, sandbox)
        requires_provisioning = True
        logger.info(
            "Reviving sandbox %s (was %s) for user %s (generation %s)",
            sandbox.id,
            previous_status.value,
            user.id,
            generation,
        )
    elif sandbox.status == SandboxStatus.PROVISIONING:
        if not _provisioning_attempt_is_stale(sandbox):
            raise SandboxProvisioningInProgressError(
                f"Sandbox {sandbox.id} is being provisioned by a live attempt "
                f"(generation {sandbox.provisioning_generation})"
            )
        _enforce_tenant_concurrency_limit(db_session)
        generation = begin_provisioning_attempt__no_commit(db_session, sandbox)
        requires_provisioning = True
        logger.warning(
            "Taking over stale PROVISIONING sandbox %s for user %s (generation %s)",
            sandbox.id,
            user.id,
            generation,
        )
    else:
        raise RuntimeError(
            f"Sandbox {sandbox.id} in unexpected status "
            f"{sandbox.status.value}; refusing to provision"
        )

    # The PAT only matters when a pod is about to be created — the healthy
    # hot path must not pay PAT reads per request.
    onyx_pat: str | None = None
    if requires_provisioning:
        with time_provision_phase(SandboxProvisionPhase.ENSURE_PAT):
            onyx_pat = ensure_sandbox_pat(db_session, sandbox, user)

    return SandboxReservation(
        sandbox_id=sandbox.id,
        tenant_id=tenant_id,
        generation=generation,
        onyx_pat=onyx_pat,
        requires_provisioning=requires_provisioning,
        sandbox_preexisted=sandbox_preexisted,
    )


def _record_provisioning_failure(
    db_session: DBSession,
    sandbox_id: UUID,
    generation: int,
    error: BaseException,
) -> None:
    """Durably mark a failed attempt FAILED (compare-and-set; a stale attempt
    leaves newer state alone). The diagnostic detail lives in this log line,
    keyed by sandbox ID + generation — not in the database. Never raises."""
    try:
        if finalize_provisioning_attempt__no_commit(
            db_session,
            sandbox_id,
            generation,
            SandboxStatus.FAILED,
        ):
            db_session.commit()
            logger.error(
                "Sandbox %s provisioning failed (generation %s): %s",
                sandbox_id,
                generation,
                error,
            )
        else:
            db_session.rollback()
            logger.warning(
                "Sandbox %s provisioning failed but generation %s is "
                "stale; leaving newer state untouched",
                sandbox_id,
                generation,
            )
    except Exception:
        db_session.rollback()
        logger.exception(
            "Failed to record provisioning failure for sandbox %s", sandbox_id
        )


def _get_sandbox_committed(db_session: DBSession, sandbox_id: UUID) -> Sandbox:
    """Fetch the sandbox and close the read transaction. The finalizers write
    via core UPDATEs, which don't touch an already-loaded instance
    (expire_on_commit=False), so refresh to the committed state."""
    sandbox = get_sandbox_by_id(db_session, sandbox_id)
    if sandbox is None:
        raise RuntimeError(f"Sandbox {sandbox_id} disappeared during reconciliation")
    db_session.refresh(sandbox)
    db_session.commit()
    return sandbox


def reconcile_sandbox(
    db_session: DBSession,
    sandbox_manager: SandboxManager,
    reservation: SandboxReservation,
    user: User,
) -> tuple[Sandbox, SandboxReadyOutcome]:
    """Converge external state on the committed reservation and finalize.

    The reservation MUST already be committed and ``db_session`` must be at a
    clean transaction boundary; every database touch in here is a short
    transaction that is committed or rolled back before external I/O resumes.

    Raises:
        SandboxProvisioningError: provisioning failed (recorded durably).
        StaleProvisioningAttemptError: a newer generation superseded this
            attempt before it could finalize.
        SandboxProvisioningInProgressError: lost a race to a concurrent
            lifecycle decision while recovering; the caller retries.
    """
    sandbox_id = reservation.sandbox_id
    tenant_id = reservation.tenant_id
    generation = reservation.generation
    onyx_pat = reservation.onyx_pat
    outcome = (
        (
            SandboxReadyOutcome.REVIVED
            if reservation.sandbox_preexisted
            else SandboxReadyOutcome.CREATED
        )
        if reservation.requires_provisioning
        else SandboxReadyOutcome.ALREADY_RUNNING
    )

    if not reservation.requires_provisioning:
        # Claimed RUNNING: verify the pod actually backs it.
        with time_provision_phase(SandboxProvisionPhase.HEALTH_CHECK):
            healthy = sandbox_manager.health_check(
                sandbox_id, timeout=_HEALTHCHECK_TIMEOUT_SECONDS
            )
        if healthy:
            return _get_sandbox_committed(db_session, sandbox_id), outcome

        logger.warning(
            "Sandbox %s marked RUNNING but pod is unhealthy/missing; recovering.",
            sandbox_id,
        )
        # Claim the recovery generation BEFORE any destructive external work:
        # a racing recoverer that loses this CAS must never terminate a
        # runtime the winner is already rebuilding.
        new_generation = begin_recovery_attempt_cas__no_commit(
            db_session, sandbox_id, generation
        )
        db_session.commit()
        if new_generation is None:
            # A concurrent lifecycle decision (reaper, another request) moved
            # the row mid-recovery; let the caller retry through a fresh
            # reservation, which handles every status.
            raise SandboxProvisioningInProgressError(
                f"Sandbox {sandbox_id} state changed during recovery; retry"
            )
        generation = new_generation
        outcome = SandboxReadyOutcome.RECOVERED

        try:
            # A RUNNING reservation skips the PAT read; the re-provision below
            # requires one.
            sandbox = get_sandbox_by_id(db_session, sandbox_id)
            if sandbox is None:
                raise RuntimeError(f"Sandbox {sandbox_id} disappeared during recovery")
            with time_provision_phase(SandboxProvisionPhase.ENSURE_PAT):
                onyx_pat = ensure_sandbox_pat(db_session, sandbox, user)
            db_session.commit()

            snapshot_opencode_history_before_recovery(
                sandbox_manager, sandbox_id, tenant_id
            )
            sandbox_manager.terminate(sandbox_id)
        except Exception as e:
            db_session.rollback()
            _record_provisioning_failure(db_session, sandbox_id, generation, e)
            raise SandboxProvisioningError(
                f"Sandbox {sandbox_id} recovery failed: {e}"
            ) from e

    # External provisioning against the committed identity. provision()
    # returns only once the sandbox is RUNNING; anything else raises.
    try:
        with track_sandbox_provision_in_progress():
            sandbox_manager.provision(
                sandbox_id=sandbox_id,
                user_id=user.id,
                tenant_id=tenant_id,
                onyx_pat=onyx_pat,
                provisioning_generation=generation,
            )
    except Exception as e:
        _record_provisioning_failure(db_session, sandbox_id, generation, e)
        raise SandboxProvisioningError(
            f"Sandbox {sandbox_id} provisioning failed: {e}"
        ) from e

    # Managed content must land before the row reports RUNNING (turns
    # dispatch the moment RUNNING is visible). Any failure here must still
    # finalize the attempt as FAILED — the row cannot be left PROVISIONING
    # until the stale-attempt threshold.
    try:
        payload = build_managed_content_payload(user, db_session)
        db_session.commit()
        skills_hydrated = push_managed_content(sandbox_manager, sandbox_id, payload)

        finalized = finalize_provisioning_attempt__no_commit(
            db_session, sandbox_id, generation, SandboxStatus.RUNNING
        )
        if not finalized:
            db_session.rollback()
            raise StaleProvisioningAttemptError(
                f"Sandbox {sandbox_id} generation {generation} was superseded "
                f"before finalization"
            )
        record_managed_content_hashes__no_commit(
            db_session, sandbox_id, payload, skills_hydrated
        )
        db_session.commit()
    except StaleProvisioningAttemptError:
        raise
    except Exception as e:
        db_session.rollback()
        _record_provisioning_failure(db_session, sandbox_id, generation, e)
        raise SandboxProvisioningError(
            f"Sandbox {sandbox_id} provisioning failed: {e}"
        ) from e

    return _get_sandbox_committed(db_session, sandbox_id), outcome


@time_provision_phase(SandboxProvisionPhase.PROVISIONING_WAIT)
def _wait_for_provisioning_to_complete(
    db_session: DBSession,
    user_id: UUID,
    deadline: float,
    *,
    poll_interval_seconds: float = 1.0,
) -> None:
    """Poll a ``PROVISIONING`` sandbox with short-lived reads until it
    transitions, its attempt goes stale, or the deadline passes. No
    transaction (or connection) is held while sleeping.

    Raises:
        SandboxProvisioningError: deadline elapsed before the status changed.
    """
    started = time.monotonic()
    while True:
        sandbox = get_sandbox_by_user_id(db_session, user_id)
        still_provisioning = (
            sandbox is not None
            and sandbox.status == SandboxStatus.PROVISIONING
            and not _provisioning_attempt_is_stale(sandbox)
        )
        db_session.rollback()
        if not still_provisioning:
            logger.info(
                "Sandbox for user %s left live-PROVISIONING after %.1fs",
                user_id,
                time.monotonic() - started,
            )
            return
        if time.monotonic() >= deadline:
            raise SandboxProvisioningError(
                f"Sandbox for user {user_id} still PROVISIONING after "
                f"{time.monotonic() - started:.1f}s"
            )
        time.sleep(poll_interval_seconds)


def ensure_sandbox_ready(
    db_session: DBSession,
    sandbox_manager: SandboxManager,
    user_id: UUID,
    *,
    policy: ProvisioningPolicy,
    provisioning_wait_seconds: float = 30.0,
) -> tuple[Sandbox, SandboxReadyOutcome]:
    """Return the RUNNING sandbox for ``user_id`` (and how it got there),
    creating, waking, or recovering it as needed via reserve → reconcile →
    finalize.

    ``db_session`` must be at a clean transaction boundary; this function
    commits its own short transactions and leaves no transaction open across
    external work.

    Branches by current sandbox status:
    - No sandbox row: reserve + provision.
    - ``RUNNING`` + pod healthy: return as-is (hot path).
    - ``RUNNING`` + pod missing/unhealthy: recover (terminate, new
      generation, re-provision).
    - ``SLEEPING`` / ``TERMINATED`` / ``FAILED``: new generation +
      re-provision.
    - ``PROVISIONING`` (live attempt): ``POLL`` waits up to
      ``provisioning_wait_seconds`` then re-enters; ``FAIL`` raises
      immediately. A stale attempt is taken over by either policy.

    Raises:
        SandboxProvisioningInProgressError: live concurrent attempt (FAIL
            policy, or still contended after waiting).
        SandboxProvisioningError: provisioning failed or wait timed out.
        ValueError: concurrency cap reached, or user not found.
    """
    started_at = time.monotonic()
    outcome = SandboxReadyOutcome.FAILED
    try:
        deadline = started_at + provisioning_wait_seconds
        while True:
            try:
                user = fetch_user_by_id(db_session, user_id, for_update=True)
                if user is None:
                    raise ValueError(f"User {user_id} not found")
                reservation = reserve_sandbox__no_commit(db_session, user)
                db_session.commit()
            except SandboxProvisioningInProgressError:
                db_session.rollback()
                if policy == ProvisioningPolicy.FAIL:
                    raise
                _wait_for_provisioning_to_complete(db_session, user_id, deadline)
                continue
            except BaseException:
                db_session.rollback()
                raise
            break

        sandbox, outcome = reconcile_sandbox(
            db_session, sandbox_manager, reservation, user
        )
        return sandbox, outcome
    finally:
        observe_sandbox_ready(outcome, time.monotonic() - started_at)


def is_sandbox_idle(sandbox: Sandbox, now: datetime) -> bool:
    """Idle = no heartbeat for the timeout (NULL heartbeat falls back to
    created_at so legacy/edge-case rows don't sit RUNNING forever)."""
    reference = sandbox.last_heartbeat or sandbox.created_at
    return reference < now - timedelta(seconds=SANDBOX_IDLE_TIMEOUT_SECONDS)


def list_snapshotable_session_workspaces(
    db_session: DBSession,
    sandbox_manager: SandboxManager,
    sandbox: Sandbox,
    session_creation_lock: RedisLock,
) -> list[UUID]:
    """List snapshotable workspaces while session creation is excluded."""
    if not session_creation_lock.owned():
        raise RuntimeError(
            f"Session creation lock is not owned for sandbox user {sandbox.user_id}"
        )

    workspace_session_ids = sandbox_manager.list_session_workspaces(sandbox.id)
    orphan_session_ids = get_orphan_build_session_ids(
        workspace_session_ids,
        sandbox.user_id,
        db_session,
    )

    existing_session_ids: list[UUID] = []
    for session_id in workspace_session_ids:
        if session_id not in orphan_session_ids:
            existing_session_ids.append(session_id)
            continue

        logger.warning(
            "Removing orphan workspace for session %s from sandbox %s",
            session_id,
            sandbox.id,
        )
        try:
            sandbox_manager.cleanup_session_workspace(sandbox.id, session_id)
        except Exception:
            logger.warning(
                "Failed to remove orphan workspace for session %s from sandbox %s; "
                "skipping it",
                session_id,
                sandbox.id,
                exc_info=True,
            )

    return existing_session_ids


def sleep_sandbox(
    db_session: DBSession,
    sandbox_manager: SandboxManager,
    sandbox: Sandbox,
    tenant_id: str,
    session_creation_lock: RedisLock,
) -> None:
    """Snapshot an idle ``RUNNING`` sandbox, terminate its pod, and mark it
    ``SLEEPING``. Commits on success; on abort the sandbox stays ``RUNNING``.

    Invariant: snapshot before terminate, fail-closed — a snapshot failure on
    a reachable pod aborts the reap so the next sweep retries, while an
    unreachable pod is terminated anyway (its workspace is unrecoverable;
    never pin it RUNNING forever). Idleness is re-checked right before the
    kill since snapshotting can take minutes.
    """
    sandbox_id = sandbox.id

    # Chat history lives outside session workspaces; capture it before the
    # pod dies.
    if sandbox_manager.supports_opencode_history_persistence:
        try:
            sandbox_manager.create_opencode_history_snapshot(sandbox_id, tenant_id)
        except Exception as e:
            if sandbox_manager.health_check(
                sandbox_id, timeout=_HEALTHCHECK_TIMEOUT_SECONDS
            ):
                logger.error(
                    "opencode history snapshot failed for sandbox "
                    "%s; leaving it RUNNING: %s",
                    sandbox_id,
                    e,
                )
                return
            logger.warning(
                "Sandbox %s pod unreachable; sleeping "
                "without a fresh opencode history snapshot: %s",
                sandbox_id,
                e,
            )

    if not session_creation_lock.acquire(blocking=False):
        logger.info(
            "Skipping idle sandbox %s while a session is being created",
            sandbox_id,
        )
        return
    try:
        session_ids = list_snapshotable_session_workspaces(
            db_session,
            sandbox_manager,
            sandbox,
            session_creation_lock,
        )
    finally:
        if session_creation_lock.owned():
            session_creation_lock.release()

    snapshot_failed = False
    for session_id in session_ids:
        try:
            snapshot_start = time.monotonic()
            snapshot_result = create_session_snapshot_keep_latest(
                sandbox_manager=sandbox_manager,
                db_session=db_session,
                sandbox_id=sandbox_id,
                session_id=session_id,
                tenant_id=tenant_id,
            )
            snapshot_elapsed = time.monotonic() - snapshot_start
            if snapshot_result:
                logger.info(
                    "Snapshot created for session %s: %.1f MiB in %.1fs",
                    session_id,
                    snapshot_result.size_bytes / 1_048_576,
                    snapshot_elapsed,
                )
        except Exception as e:
            snapshot_failed = True
            logger.warning(
                "Failed to create snapshot for session %s: %s", session_id, e
            )
            db_session.rollback()

    logger.info("Putting sandbox %s to sleep", sandbox_id)

    # Fail-closed: terminating with an unsnapshotted workspace loses it
    # (restore falls back to a fresh template). Keep the sandbox RUNNING to
    # retry next cycle — unless the pod is unreachable, where snapshots can
    # never succeed and the workspace is already gone, so don't pin it
    # RUNNING forever.
    pod_unreachable = False
    if snapshot_failed:
        if sandbox_manager.health_check(
            sandbox_id, timeout=_HEALTHCHECK_TIMEOUT_SECONDS
        ):
            logger.error(
                "Snapshot failed for sandbox %s; "
                "leaving it RUNNING to retry next cycle",
                sandbox_id,
            )
            return
        pod_unreachable = True
        logger.warning(
            "Sandbox %s pod is unreachable; "
            "terminating despite snapshot failure (cannot recover "
            "its workspace, won't pin it RUNNING forever)",
            sandbox_id,
        )

    # Do not block session creation during snapshots. Reacquire its lock before
    # the final check so a workspace cannot appear between the rescan and kill.
    if not session_creation_lock.acquire(blocking=False):
        logger.info(
            "Sandbox %s has a session creation in progress; skipping reap",
            sandbox_id,
        )
        return
    try:
        if not pod_unreachable:
            current_session_ids = list_snapshotable_session_workspaces(
                db_session,
                sandbox_manager,
                sandbox,
                session_creation_lock,
            )
            new_session_ids = set(current_session_ids) - set(session_ids)
            if new_session_ids:
                logger.info(
                    "Sandbox %s gained %s session workspace(s) during snapshot; "
                    "skipping reap",
                    sandbox_id,
                    len(new_session_ids),
                )
                return

        # Snapshotting above can take minutes; re-check idleness right before
        # the kill.
        db_session.refresh(sandbox)
        if sandbox.status != SandboxStatus.RUNNING or not is_sandbox_idle(
            sandbox, datetime.now(timezone.utc)
        ):
            logger.info("Sandbox %s went active mid-sweep; skipping reap", sandbox_id)
            return

        # Terminate the pod (but keep the sandbox record).
        sandbox_manager.terminate(sandbox_id)

        # Ports are no longer in use once the pod is gone.
        cleared = clear_nextjs_ports_for_user(db_session, sandbox.user_id)
        logger.debug(
            "Cleared %s nextjs_port allocations for user %s", cleared, sandbox.user_id
        )

        idled = mark_user_sessions_idle__no_commit(db_session, sandbox.user_id)
        logger.debug("Marked %s sessions as IDLE for user %s", idled, sandbox.user_id)

        update_sandbox_status__no_commit(db_session, sandbox_id, SandboxStatus.SLEEPING)
        db_session.commit()
        logger.info("Sandbox %s is now sleeping", sandbox_id)
    finally:
        if session_creation_lock.owned():
            session_creation_lock.release()


def refresh_mcp_config_hashes_for_users(
    user_ids: set[UUID], db_session: DBSession
) -> None:
    """Stamp each affected user's running sandbox with the current craft MCP
    fingerprint so live sessions detect the change and reload on their next turn.
    Unlike the skill push this touches only ``mcp_config_hash`` — no skill-file
    push. Deliberately unlocked (the skill push locks ``skills_hash``): two
    concurrent MCP changes for the same user could interleave and leave a
    momentarily stale ``mcp_config_hash``, but that self-heals — the reload
    resolves the MCP set live, and the next change re-stamps — so a brief
    bookkeeping skew never yields a wrong runtime.

    Best-effort: callers invoke this AFTER their own change has committed, so a
    failure here must neither surface to the caller nor roll their change back —
    it is swallowed and the session is left clean. Commits its own writes."""
    if not user_ids:
        return
    try:
        sandbox_map = get_sandbox_user_map(list(user_ids), db_session)
        if not sandbox_map:
            return
        hashes = {
            sandbox_id: craft_mcp_fingerprint(
                resolve_craft_mcp_servers(db_session, user)
            )
            for sandbox_id, user in sandbox_map.items()
        }
        set_sandbox_mcp_config_hashes__no_commit(db_session, hashes)
        db_session.commit()
    except Exception:
        logger.warning(
            "Failed to refresh MCP config hashes for users %s", user_ids, exc_info=True
        )
        db_session.rollback()
