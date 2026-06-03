"""Sandbox lifecycle: provisioning, the readiness state machine, and
hydration helpers shared between interactive and headless flows."""

import time
from enum import Enum
from uuid import UUID

from sqlalchemy.orm import Session as DBSession

from onyx.db.enums import SandboxStatus
from onyx.db.models import Sandbox
from onyx.db.models import User
from onyx.db.users import fetch_user_by_id
from onyx.server.features.build.configs import SANDBOX_MAX_CONCURRENT_PER_ORG
from onyx.server.features.build.db.sandbox import create_sandbox__no_commit
from onyx.server.features.build.db.sandbox import ensure_sandbox_pat
from onyx.server.features.build.db.sandbox import get_running_sandbox_count_by_tenant
from onyx.server.features.build.db.sandbox import get_sandbox_by_user_id
from onyx.server.features.build.db.sandbox import update_sandbox_status__no_commit
from onyx.server.features.build.sandbox.base import SandboxManager
from onyx.server.features.build.sandbox.models import FileSet
from onyx.server.features.build.sandbox.models import LLMProviderConfig
from onyx.server.features.build.sandbox.user_library import hydrate_user_library
from onyx.server.features.build.session.errors import SandboxProvisioningError
from onyx.skills.push import hydrate_sandbox_skills
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()


# Statuses that mean "the pod is dead; we need to re-provision in place."
_REVIVE_STATUSES = frozenset(
    {SandboxStatus.SLEEPING, SandboxStatus.TERMINATED, SandboxStatus.FAILED}
)

_HEALTHCHECK_TIMEOUT_SECONDS = 5.0


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


# =============================================================================
# Hydration (best-effort)
# =============================================================================


def hydrate_skills(
    db_session: DBSession,
    sandbox_id: UUID,
    user: User,
    files: FileSet | None = None,
) -> None:
    """Push the user's skills into a sandbox. Best-effort: failures are
    logged, never raised."""
    try:
        hydrate_sandbox_skills(sandbox_id, user, db_session, files=files)
    except Exception:
        logger.warning("Failed to push skills to sandbox %s", sandbox_id, exc_info=True)


def hydrate_user_library_into_sandbox(
    db_session: DBSession, sandbox_id: UUID, user_id: UUID
) -> None:
    """Push the user's library into a sandbox. Best-effort."""
    try:
        hydrate_user_library(sandbox_id, user_id, db_session)
    except Exception:
        logger.warning(
            "Failed to push user library to sandbox %s", sandbox_id, exc_info=True
        )


# =============================================================================
# Provisioning
# =============================================================================


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


def _enforce_tenant_concurrency_limit(db_session: DBSession, tenant_id: str) -> None:
    """No-op on self-hosted. On multi-tenant: raise if creating/waking a
    sandbox would exceed the per-tenant cap."""
    if not MULTI_TENANT:
        return
    running_count = get_running_sandbox_count_by_tenant(db_session, tenant_id)
    if running_count >= SANDBOX_MAX_CONCURRENT_PER_ORG:
        raise ValueError(
            f"Maximum concurrent sandboxes ({SANDBOX_MAX_CONCURRENT_PER_ORG}) reached"
        )


def _is_pod_healthy(sandbox_manager: SandboxManager, sandbox_id: UUID) -> bool:
    return sandbox_manager.health_check(
        sandbox_id, timeout=_HEALTHCHECK_TIMEOUT_SECONDS
    )


def _terminate_and_mark(
    db_session: DBSession,
    sandbox_manager: SandboxManager,
    sandbox: Sandbox,
) -> None:
    """Kill the pod and mark the row TERMINATED. Used when the DB says the
    sandbox is healthy but the pod is missing or unresponsive."""
    sandbox_manager.terminate(sandbox.id)
    update_sandbox_status__no_commit(db_session, sandbox.id, SandboxStatus.TERMINATED)


# =============================================================================
# State machine
# =============================================================================


def ensure_sandbox_ready(
    db_session: DBSession,
    sandbox_manager: SandboxManager,
    user_id: UUID,
    all_llm_configs: list[LLMProviderConfig],
    *,
    policy: ProvisioningPolicy,
    provisioning_wait_seconds: float = 30.0,
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
        if _is_pod_healthy(sandbox_manager, sandbox.id):
            return sandbox
        logger.warning(
            "Sandbox %s marked RUNNING but pod is unhealthy/missing; recovering.",
            sandbox.id,
        )
        _terminate_and_mark(db_session, sandbox_manager, sandbox)
        # Fall through into the re-provision path below.

    # Everything below provisions a pod, which adds to the per-tenant cap.
    tenant_id = get_current_tenant_id()
    _enforce_tenant_concurrency_limit(db_session, tenant_id)

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


# =============================================================================
# Misc
# =============================================================================


def terminate_user_sandbox(
    db_session: DBSession, sandbox_manager: SandboxManager, user_id: UUID
) -> bool:
    """Tear down the user's sandbox (all sessions). Used for "start fresh".

    Returns True if the user had a sandbox (even if already TERMINATED), or
    False if the user had no sandbox row at all.
    """
    sandbox = get_sandbox_by_user_id(db_session, user_id)
    if sandbox is None:
        return False

    if sandbox.status == SandboxStatus.TERMINATED:
        logger.info("Sandbox %s already terminated", sandbox.id)
        return True

    try:
        sandbox_manager.terminate(sandbox.id)
        logger.info("Terminated sandbox %s for user %s", sandbox.id, user_id)
        update_sandbox_status__no_commit(
            db_session, sandbox.id, SandboxStatus.TERMINATED
        )
        db_session.flush()
        return True
    except Exception as e:
        logger.error("Failed to terminate sandbox %s: %s", sandbox.id, e)
        raise RuntimeError(f"Failed to terminate sandbox: {e}") from e
