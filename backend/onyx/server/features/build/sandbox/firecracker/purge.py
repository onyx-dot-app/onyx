"""Delete hooks for Firecracker harness sandboxes.

Onyx calls these after a Craft session, a user or a tenant is deleted. They
do nothing unless harness sandboxes run on Firecracker
(`SANDBOX_RUNTIME=firecracker` and `SANDBOX_FC_TEMPLATE`), and they never
raise: a failure is logged. The heavy client stack loads only when enabled.

- Session: its save archive, its directory on the running VM and its exec
  records. Its published artifacts stay.
- Sandbox (user or tenant delete): the VM is stopped (the node agent removes
  its disk), and every save archive, artifact and record of the sandbox goes.
- Chat retention: each saved session that retention no longer keeps is
  purged as on session delete.
"""

import random
import time
from datetime import datetime, timedelta, timezone
from uuid import UUID

from onyx.microvm.configs import FIRECRACKER_ENABLED, SANDBOX_FC_TEMPLATE
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import start_thread_with_context
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()


HARNESS_PURGE_ENABLED = FIRECRACKER_ENABLED and bool(SANDBOX_FC_TEMPLATE)


def purge_harness_session(
    sandbox_id: UUID, session_id: UUID, *, retention: bool = False
) -> None:
    if not HARNESS_PURGE_ENABLED:
        return
    try:
        from onyx.server.features.build.sandbox.harness_factory import (
            get_firecracker_sandbox,
        )

        get_firecracker_sandbox().purge_session(
            tenant_id=get_current_tenant_id(),
            sandbox_id=sandbox_id,
            session_id=session_id,
            retention=retention,
        )
    except Exception:
        logger.exception(
            "sandbox_fc_session_purge_failed sandbox=%s session=%s",
            sandbox_id,
            session_id,
        )


def purge_harness_sandboxes(targets: dict[UUID, list[UUID]]) -> None:
    """`targets`: sandbox ID -> session IDs to purge with it (older saves
    that the saved-session index may not name)."""
    if not HARNESS_PURGE_ENABLED or not targets:
        return
    tenant_id = get_current_tenant_id()
    try:
        from onyx.server.features.build.sandbox.harness_factory import (
            get_firecracker_sandbox,
        )

        sandbox = get_firecracker_sandbox()
    except Exception:
        logger.exception("sandbox_fc_sandbox_purge_failed: no harness sandbox")
        return
    for sandbox_id, session_ids in targets.items():
        try:
            sandbox.purge_sandbox(
                tenant_id=tenant_id, sandbox_id=sandbox_id, session_ids=session_ids
            )
        except Exception:
            logger.exception("sandbox_fc_sandbox_purge_failed sandbox=%s", sandbox_id)


def purge_expired_harness_sessions(
    retention_days: float, limit: int, deadline: float
) -> None:
    """Purge at most `limit` saved sessions whose chat session is gone or
    whose build session had no activity in `retention_days`, until
    `deadline` (monotonic). The next run takes the rest. Run after the
    retention deletes commit."""
    if not HARNESS_PURGE_ENABLED:
        return
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=retention_days)
    # The scan gets half the time, so the purges always get the rest.
    scan_deadline = time.monotonic() + (deadline - time.monotonic()) / 2
    try:
        from onyx.cache.factory import get_cache_backend
        from onyx.db.engine.sql_engine import get_session_with_current_tenant
        from onyx.server.features.build.db.sandbox import (
            get_all_sandbox_ids,
            get_retained_session_ids,
        )
        from onyx.server.features.build.sandbox.firecracker.harness_state import (
            SAVED_SESSIONS_PREFIX,
            clear_retention_mark,
            get_ids,
        )
        from onyx.server.features.build.sandbox.firecracker.session_saves import (
            session_save_lock,
        )

        tenant_cache = get_cache_backend(tenant_id=get_current_tenant_id())
        expired: list[tuple[UUID, UUID]] = []
        with get_session_with_current_tenant() as db_session:
            for sandbox_id in get_all_sandbox_ids(db_session):
                if time.monotonic() >= scan_deadline:
                    break
                saved = [
                    UUID(i)
                    for i in get_ids(tenant_cache, SAVED_SESSIONS_PREFIX, sandbox_id)
                ]
                kept = get_retained_session_ids(db_session, saved, cutoff)
                expired += [(sandbox_id, s) for s in saved if s not in kept]
    except Exception:
        logger.exception("sandbox_fc_retention_purge_failed")
        return
    # Random order: saves whose purge keeps failing cannot block the rest.
    random.shuffle(expired)
    for sandbox_id, session_id in expired[:limit]:
        if time.monotonic() >= deadline:
            return
        # A session used again since the scan keeps its save.
        try:
            with get_session_with_current_tenant() as db_session:
                if get_retained_session_ids(db_session, [session_id], cutoff):
                    continue
        except Exception:
            logger.exception("sandbox_fc_retention_check_failed session=%s", session_id)
            continue
        purge_harness_session(sandbox_id, session_id, retention=True)
        # Unlike a delete, the session can be opened again: let it save new
        # work. Only with no save in flight, which could bring back the
        # purged files; otherwise the mark expires on its own.
        try:
            with session_save_lock(tenant_cache, session_id) as no_save_runs:
                if no_save_runs:
                    clear_retention_mark(tenant_cache, session_id)
        except Exception:
            logger.exception(
                "sandbox_fc_purge_mark_clear_failed session=%s", session_id
            )


def purge_harness_sandboxes_in_background(targets: dict[UUID, list[UUID]]) -> None:
    """For sync callers that may run on an event loop: a purge can wait a
    minute for the sandbox lock and the VM stop."""
    if not HARNESS_PURGE_ENABLED or not targets:
        return
    start_thread_with_context(
        target=purge_harness_sandboxes,
        name="fc-sandbox-purge",
        daemon=True,
        args=(targets,),
    )
