"""Sandbox readiness state machine + provisioning, shared between
interactive (``create_session__no_commit``) and headless
(``ensure_sandbox_running``) flows."""

import time
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from enum import Enum
from uuid import UUID

from sqlalchemy.orm import Session as DBSession

from onyx.db.enums import SandboxStatus
from onyx.db.models import Sandbox
from onyx.db.models import User
from onyx.db.users import fetch_user_by_id
from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.build.configs import SANDBOX_IDLE_TIMEOUT_SECONDS
from onyx.server.features.build.configs import SANDBOX_MAX_CONCURRENT_PER_ORG
from onyx.server.features.build.db.build_session import clear_nextjs_ports_for_user
from onyx.server.features.build.db.build_session import (
    mark_user_sessions_idle__no_commit,
)
from onyx.server.features.build.db.sandbox import create_sandbox__no_commit
from onyx.server.features.build.db.sandbox import create_snapshot__no_commit
from onyx.server.features.build.db.sandbox import delete_snapshot__no_commit
from onyx.server.features.build.db.sandbox import ensure_sandbox_pat
from onyx.server.features.build.db.sandbox import get_running_sandbox_count
from onyx.server.features.build.db.sandbox import get_sandbox_by_user_id
from onyx.server.features.build.db.sandbox import get_snapshots_for_session
from onyx.server.features.build.db.sandbox import update_sandbox_status__no_commit
from onyx.server.features.build.sandbox.base import SandboxManager
from onyx.server.features.build.sandbox.models import LLMProviderConfig
from onyx.server.features.build.sandbox.models import SnapshotResult
from onyx.server.features.build.sandbox.snapshot_manager import SnapshotManager
from onyx.server.features.build.session.errors import SandboxProvisioningError
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()


_HEALTHCHECK_TIMEOUT_SECONDS = 5.0


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


class ProvisioningPolicy(str, Enum):
    """How to handle a sandbox already in ``PROVISIONING`` when we arrive.

    - ``POLL``: wait for the concurrent provisioner to finish, then re-enter
      the state machine on the resulting status. Used by headless callers
      (scheduled tasks) that can afford to block.
    - ``FAIL``: raise immediately. Used by interactive callers (web request
      handlers) that hit a wall-clock deadline.
    """

    POLL = "poll"
    FAIL = "fail"


def provision_sandbox(
    db_session: DBSession,
    sandbox_manager: SandboxManager,
    sandbox: Sandbox,
    user: User,
    user_id: UUID,
    tenant_id: str,
    all_llm_configs: list[LLMProviderConfig],
) -> None:
    """Ensure a PAT exists, then provision the pod with every accessible
    provider pre-loaded so per-prompt model overrides can cross providers
    without a pod restart. ``all_llm_configs[0]`` is the default.

    Updates the sandbox row's status to whatever the manager returns.
    Caller is responsible for committing.
    """
    onyx_pat = ensure_sandbox_pat(db_session, sandbox, user)
    sandbox_info = sandbox_manager.provision(
        sandbox_id=sandbox.id,
        user_id=user_id,
        tenant_id=tenant_id,
        llm_config=all_llm_configs[0],
        onyx_pat=onyx_pat,
        all_llm_configs=all_llm_configs,
    )
    update_sandbox_status__no_commit(db_session, sandbox.id, sandbox_info.status)


def _wait_for_provisioning_to_complete(
    db_session: DBSession,
    sandbox: Sandbox,
    wait_seconds: float,
    *,
    poll_interval_seconds: float = 1.0,
) -> Sandbox:
    """Poll a ``PROVISIONING`` sandbox until it transitions or we time out.

    Relies on Postgres' READ COMMITTED isolation: ``session.refresh()``
    issues a fresh SELECT each iteration, so commits from the concurrent
    provisioner become visible.

    Raises:
        SandboxProvisioningError: deadline elapsed before the status
            changed.
    """
    deadline = time.monotonic() + wait_seconds
    started = time.monotonic()
    logger.info(
        "Waiting up to %.1fs for sandbox %s to finish provisioning",
        wait_seconds,
        sandbox.id,
    )
    while True:
        db_session.refresh(sandbox)
        if sandbox.status != SandboxStatus.PROVISIONING:
            logger.info(
                "Sandbox %s left PROVISIONING after %.1fs (now=%s)",
                sandbox.id,
                time.monotonic() - started,
                sandbox.status.value,
            )
            return sandbox
        if time.monotonic() >= deadline:
            raise SandboxProvisioningError(
                f"Sandbox {sandbox.id} still PROVISIONING after {wait_seconds}s"
            )
        time.sleep(poll_interval_seconds)


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


def ensure_sandbox_ready(
    db_session: DBSession,
    sandbox_manager: SandboxManager,
    user_id: UUID,
    all_llm_configs: list[LLMProviderConfig],
    *,
    policy: ProvisioningPolicy,
    provisioning_wait_seconds: float = 30.0,
    user: User | None = None,
) -> Sandbox:
    """Return a ``RUNNING`` sandbox for ``user_id``, creating, waking, or
    recovering as needed.

    Branches by current sandbox status:
    - No sandbox row: create + provision.
    - ``RUNNING`` + pod healthy: return as-is (hot path; no extra writes).
    - ``RUNNING`` + pod missing/unhealthy: terminate, mark TERMINATED,
      re-provision.
    - ``SLEEPING`` / ``TERMINATED`` / ``FAILED``: re-provision in place.
    - ``PROVISIONING``: depends on ``policy`` —
        - ``POLL``: wait up to ``provisioning_wait_seconds`` then re-enter
          the state machine on the new status (raises
          ``SandboxProvisioningError`` on timeout).
        - ``FAIL``: raise ``RuntimeError`` immediately so the caller can
          return a fast error to the user.

    Honors ``SANDBOX_MAX_CONCURRENT_PER_ORG`` when ``MULTI_TENANT`` for any
    path that newly counts toward the running limit (create + revive).
    Caller is responsible for committing.

    Raises:
        SandboxProvisioningError: Sandbox still ``PROVISIONING`` after the
            wait window (POLL only).
        ValueError: Concurrency cap reached, or user not found.
        RuntimeError: Pod provisioning failed, or sandbox is mid-provision
            under FAIL policy.
    """
    sandbox = get_sandbox_by_user_id(db_session, user_id)
    tenant_id = get_current_tenant_id()

    # Resolve PROVISIONING upfront so the rest of the state machine sees a
    # stable status (or knows there isn't one).
    if sandbox is not None and sandbox.status == SandboxStatus.PROVISIONING:
        if policy == ProvisioningPolicy.FAIL:
            raise RuntimeError(
                f"Sandbox {sandbox.id} has status PROVISIONING and is being "
                f"created by another request"
            )
        sandbox = _wait_for_provisioning_to_complete(
            db_session, sandbox, provisioning_wait_seconds
        )

    # Hot path: pod is up; nothing else to do.
    if sandbox is not None and sandbox.status == SandboxStatus.RUNNING:
        if sandbox_manager.health_check(
            sandbox.id, timeout=_HEALTHCHECK_TIMEOUT_SECONDS
        ):
            return sandbox
        logger.warning(
            "Sandbox %s marked RUNNING but pod is unhealthy/missing; recovering.",
            sandbox.id,
        )
        snapshot_opencode_history_before_recovery(
            sandbox_manager, sandbox.id, tenant_id
        )
        sandbox_manager.terminate(sandbox.id)
        update_sandbox_status__no_commit(
            db_session, sandbox.id, SandboxStatus.TERMINATED
        )
        # Fall through into the re-provision path below.

    if sandbox is not None and sandbox.status not in {
        SandboxStatus.SLEEPING,
        SandboxStatus.TERMINATED,
        SandboxStatus.FAILED,
    }:
        raise RuntimeError(
            f"Sandbox {sandbox.id} in unexpected status "
            f"{sandbox.status.value}; refusing to provision"
        )

    # Everything below provisions a pod, which adds to the per-tenant cap.
    _enforce_tenant_concurrency_limit(db_session)

    if user is None:
        user = fetch_user_by_id(db_session, user_id)
        if user is None:
            raise ValueError(f"User {user_id} not found")

    if sandbox is None:
        sandbox = create_sandbox__no_commit(db_session=db_session, user_id=user_id)
        logger.info("Created sandbox %s for user %s", sandbox.id, user_id)
    else:
        logger.info(
            "Reviving sandbox %s (status=%s) for user %s",
            sandbox.id,
            sandbox.status.value,
            user_id,
        )

    provision_sandbox(
        db_session,
        sandbox_manager,
        sandbox,
        user,
        user_id,
        tenant_id,
        all_llm_configs,
    )
    return sandbox


def is_sandbox_idle(sandbox: Sandbox, now: datetime) -> bool:
    """Idle = no heartbeat for the timeout (NULL heartbeat falls back to
    created_at so legacy/edge-case rows don't sit RUNNING forever)."""
    reference = sandbox.last_heartbeat or sandbox.created_at
    return reference < now - timedelta(seconds=SANDBOX_IDLE_TIMEOUT_SECONDS)


def sleep_sandbox(
    db_session: DBSession,
    sandbox_manager: SandboxManager,
    sandbox: Sandbox,
    tenant_id: str,
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

    session_ids = sandbox_manager.list_session_workspaces(sandbox_id)

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
        logger.warning(
            "Sandbox %s pod is unreachable; "
            "terminating despite snapshot failure (cannot recover "
            "its workspace, won't pin it RUNNING forever)",
            sandbox_id,
        )

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
