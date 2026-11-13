"""Delete hooks for Firecracker harness sandboxes.

Onyx calls these after a Craft session, a user or a tenant is deleted. They
do nothing unless harness sandboxes run on Firecracker
(`SANDBOX_RUNTIME=firecracker` and `SANDBOX_FC_TEMPLATE`), and they never
raise: a failure is logged. The heavy client stack loads only when enabled.

- Session: its save archive, its directory on the running VM and its exec
  records. Its published artifacts stay.
- Sandbox (user or tenant delete): the VM is stopped (the node agent removes
  its disk), and every save archive, artifact and record of the sandbox goes.
"""

from uuid import UUID

from onyx.microvm.configs import FIRECRACKER_ENABLED, SANDBOX_FC_TEMPLATE
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import start_thread_with_context
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()


HARNESS_PURGE_ENABLED = FIRECRACKER_ENABLED and bool(SANDBOX_FC_TEMPLATE)


def purge_harness_session(sandbox_id: UUID, session_id: UUID) -> None:
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
        )
    except Exception:
        logger.exception(
            "sandbox_fc_session_purge_failed sandbox=%s session=%s",
            sandbox_id,
            session_id,
        )


def purge_harness_sandboxes(sandbox_ids: list[UUID]) -> None:
    if not HARNESS_PURGE_ENABLED or not sandbox_ids:
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
    for sandbox_id in sandbox_ids:
        try:
            sandbox.purge_sandbox(tenant_id=tenant_id, sandbox_id=sandbox_id)
        except Exception:
            logger.exception("sandbox_fc_sandbox_purge_failed sandbox=%s", sandbox_id)


def purge_harness_sandboxes_in_background(sandbox_ids: list[UUID]) -> None:
    """For sync callers that may run on an event loop: a purge can wait a
    minute for the sandbox lock and the VM stop."""
    if not HARNESS_PURGE_ENABLED or not sandbox_ids:
        return
    start_thread_with_context(
        target=purge_harness_sandboxes,
        name="fc-sandbox-purge",
        daemon=True,
        args=(sandbox_ids,),
    )
