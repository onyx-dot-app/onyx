"""Picks the sandbox for sessions on the new agent harness.

Only the new harness calls this; opencode sessions keep `get_sandbox_manager`
(pod or Docker, chosen by `SANDBOX_BACKEND`). The harness gets Firecracker
sandboxes with `SANDBOX_RUNTIME=firecracker`.
"""

import threading
from typing import TYPE_CHECKING

from onyx.microvm.configs import FIRECRACKER_ENABLED, SANDBOX_FC_TEMPLATE
from onyx.microvm.lifecycle import (
    NoCheckpointSupport,
    SandboxActivityProbe,
    SandboxCheckpointer,
    UnknownActivity,
)
from onyx.server.features.build.sandbox.harness_base import HarnessSandbox

if TYPE_CHECKING:
    from onyx.server.features.build.sandbox.firecracker.harness_sandbox import (
        FirecrackerHarnessSandbox,
    )

_lock = threading.Lock()
_instance: "FirecrackerHarnessSandbox | None" = None


class HarnessSandboxUnavailableError(Exception):
    """No sandbox backend serves the new harness in this deployment."""


def _firecracker_sandbox() -> "FirecrackerHarnessSandbox":
    global _instance
    if not FIRECRACKER_ENABLED or not SANDBOX_FC_TEMPLATE:
        raise HarnessSandboxUnavailableError(
            "Harness sandboxes need SANDBOX_RUNTIME=firecracker and SANDBOX_FC_TEMPLATE"
        )
    with _lock:
        if _instance is None:
            # Deferred: the Firecracker client stack loads only when used.
            from onyx.server.features.build.sandbox.firecracker.harness_sandbox import (
                FirecrackerHarnessSandbox,
            )
            from onyx.server.features.build.sandbox.firecracker.session_saves import (
                default_archive_store,
            )

            _instance = FirecrackerHarnessSandbox(
                template=SANDBOX_FC_TEMPLATE, archive_store=default_archive_store()
            )
    return _instance


def get_harness_sandbox() -> HarnessSandbox:
    return _firecracker_sandbox()


def get_eviction_policy() -> tuple[SandboxCheckpointer, SandboxActivityProbe]:
    """The node-report idle evictor's save and busy checks. Firecracker VMs
    serve only the harness: without harness sandboxes no VM is stopped
    automatically."""
    try:
        return _firecracker_sandbox().eviction_policy()
    except HarnessSandboxUnavailableError:
        return NoCheckpointSupport(), UnknownActivity()
