"""Picks the sandbox for sessions on the new agent harness.

Only the new harness calls this; opencode sessions keep `get_sandbox_manager`.
Firecracker serves the harness when `SANDBOX_RUNTIME=firecracker` and
`SANDBOX_FC_HARNESS_ENABLED` are both set.
"""

import threading

from onyx.microvm.configs import SANDBOX_FC_HARNESS_ENABLED, SANDBOX_FC_TEMPLATE
from onyx.server.features.build.sandbox.harness_base import HarnessSandbox

_lock = threading.Lock()
_instance: HarnessSandbox | None = None


class HarnessSandboxUnavailableError(Exception):
    """No sandbox backend serves the new harness in this deployment."""


def get_harness_sandbox() -> HarnessSandbox:
    global _instance
    if _instance is not None:
        return _instance
    if not SANDBOX_FC_HARNESS_ENABLED:
        raise HarnessSandboxUnavailableError(
            "Harness sandboxes need SANDBOX_RUNTIME=firecracker and "
            "SANDBOX_FC_HARNESS_ENABLED=true"
        )
    if not SANDBOX_FC_TEMPLATE:
        raise HarnessSandboxUnavailableError(
            "SANDBOX_FC_HARNESS_ENABLED needs SANDBOX_FC_TEMPLATE"
        )
    with _lock:
        if _instance is None:
            # Deferred: the Firecracker client stack loads only when used.
            from onyx.server.features.build.sandbox.firecracker.harness_sandbox import (
                FirecrackerHarnessSandbox,
            )

            _instance = FirecrackerHarnessSandbox(template=SANDBOX_FC_TEMPLATE)
    return _instance
