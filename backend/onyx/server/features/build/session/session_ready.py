"""Bringing a session's runtime up, for whoever needs it.

Provisioning the sandbox and rebuilding the session workspace are one operation:
an opencode instance caches the config of the directory it is created for, so a
turn that touches a session while its workspace is still being written stays
pinned to a config that did not exist yet, for the life of the pod. Both the
restore endpoint and the interactive-turn runner come through here, under the
user's session-creation lock, so the two cannot interleave.
"""

from uuid import UUID

from sqlalchemy.orm import Session as DBSession

from onyx.db.enums import BuildSessionStatus
from onyx.db.external_app import get_connectable_apps_for_user
from onyx.db.models import BuildSession, Sandbox, User
from onyx.server.features.build.db.build_session import (
    reserve_nextjs_port__no_commit,
    session_runtime_stale,
)
from onyx.server.features.build.db.sandbox import (
    get_latest_snapshot_for_session,
    get_sandbox_by_user_id,
    update_sandbox_heartbeat,
)
from onyx.server.features.build.sandbox.base import SandboxManager
from onyx.server.features.build.sandbox.util.agent_instructions import (
    build_connectable_apps_list,
)
from onyx.server.features.build.sandbox.util.mcp_config import (
    resolve_craft_mcp_servers,
)
from onyx.server.features.build.session.manager import (
    SessionManager,
    mark_opencode_dispose_pending,
)
from onyx.server.features.build.session.sandbox_lifecycle import (
    ProvisioningPolicy,
    SandboxReadyOutcome,
    ensure_sandbox_ready,
    sync_managed_content,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


def session_runtime_intact(
    session: BuildSession | None, sandbox: Sandbox | None
) -> bool:
    """Whether the recorded state says this session can be prompted right now.

    Database-only: this is the per-turn fast path, and confirming a workspace
    costs an exec into the pod.
    """
    return (
        session is not None
        and sandbox is not None
        and session.status == BuildSessionStatus.ACTIVE
        and sandbox.status.is_active()
    )


def ensure_session_ready(
    db_session: DBSession,
    sandbox_manager: SandboxManager,
    session: BuildSession,
    user: User,
) -> Sandbox:
    """Return the user's RUNNING sandbox with ``session``'s workspace in place.

    Provisions or wakes the sandbox — a claimed-RUNNING pod is health-checked
    and recovered inside ``ensure_sandbox_ready``, so no caller can skip that
    verification — rebuilds the workspace from its latest snapshot (or a fresh
    template) when the pod does not have it, and leaves the session ACTIVE. A
    failed rebuild discards the partial workspace so a later attempt does not
    mistake it for a restored one.

    The caller must already hold the user's session-creation lock: this
    provisions and writes into the sandbox, so it must not interleave with a
    reap, a second restore, or another turn doing the same thing.
    """
    session_id = session.id
    session_manager = SessionManager(db_session)

    # Validate the model configuration before any external work; the commit
    # closes the read transaction without expiring loaded instances.
    llm_config = session_manager.build_llm_configs(user)
    db_session.commit()

    sandbox, outcome = ensure_sandbox_ready(
        db_session,
        sandbox_manager,
        user.id,
        policy=ProvisioningPolicy.FAIL,
    )

    if sandbox_manager.session_workspace_exists(sandbox.id, session_id):
        session.status = BuildSessionStatus.ACTIVE
        if session_runtime_stale(session, sandbox):
            session_manager.reload_session_skills(session_id, user)
        else:
            update_sandbox_heartbeat(db_session, sandbox.id)
            db_session.commit()
        return sandbox

    if not session.nextjs_port:
        reserve_nextjs_port__no_commit(db_session, session)
        db_session.commit()

    if outcome == SandboxReadyOutcome.ALREADY_RUNNING:
        # A reused pod may be missing content pushed since it last synced;
        # fresh provisioning already pushed managed content.
        sync_managed_content(db_session, sandbox_manager, sandbox.id, user)

    snapshot = get_latest_snapshot_for_session(db_session, session_id)
    connectable_apps_section = build_connectable_apps_list(
        get_connectable_apps_for_user(db_session, user)
    )
    mcp_servers = resolve_craft_mcp_servers(db_session, user)
    nextjs_port = session.nextjs_port
    sandbox_skills_hash = sandbox.skills_hash
    sandbox_mcp_config_hash = sandbox.mcp_config_hash
    db_session.commit()

    # A reused pod may already hold an opencode instance for this session's
    # directory — instances outlive the workspace and stay pinned to the config
    # they saw at creation. The rebuild writes an opencode.json that already
    # matches what the next turn's reconcile expects, so reconcile would
    # short-circuit without disposing; claim the dispose up front instead
    # (a no-op on a freshly provisioned pod).
    mark_opencode_dispose_pending(session_id)

    try:
        if snapshot:
            sandbox_manager.restore_snapshot(
                sandbox_id=sandbox.id,
                session_id=session_id,
                snapshot_storage_path=snapshot.storage_path,
                nextjs_port=nextjs_port,
                llm_config=llm_config,
                connectable_apps_section=connectable_apps_section,
                mcp_servers=mcp_servers,
            )
        else:
            sandbox_manager.setup_session_workspace(
                sandbox_id=sandbox.id,
                session_id=session_id,
                llm_config=llm_config,
                nextjs_port=nextjs_port,
                connectable_apps_section=connectable_apps_section,
                mcp_servers=mcp_servers,
            )
    except Exception:
        if snapshot:
            # Release the port the restore reserved but never bound.
            db_session.rollback()
            session.nextjs_port = None
            db_session.commit()
        _discard_partial_workspace(db_session, sandbox_manager, user.id, session_id)
        raise

    session.status = BuildSessionStatus.ACTIVE
    session.skills_hash = sandbox_skills_hash
    session.mcp_config_hash = sandbox_mcp_config_hash
    db_session.commit()
    return sandbox


def _discard_partial_workspace(
    db_session: DBSession,
    sandbox_manager: SandboxManager,
    user_id: UUID,
    session_id: UUID,
) -> None:
    """Best-effort: drop a half-written workspace so ``session_workspace_exists``
    doesn't later report it as restored. Sandbox-level failures are already
    recorded durably by the state machine."""
    try:
        db_session.rollback()
        current = get_sandbox_by_user_id(db_session, user_id)
        db_session.rollback()
        if current is not None and current.status.is_active():
            sandbox_manager.cleanup_session_workspace(current.id, session_id)
            logger.info(
                "Cleaned up partial workspace for session %s after failed restore",
                session_id,
            )
    except Exception:
        logger.warning("Failed to clean up after restore failure", exc_info=True)
