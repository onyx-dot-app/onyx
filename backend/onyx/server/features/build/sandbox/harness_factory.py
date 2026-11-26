"""Picks the sandbox for sessions on the new agent harness.

Only the new harness calls this; opencode sessions keep `get_sandbox_manager`
(pod or Docker, chosen by `SANDBOX_BACKEND`). The harness gets Firecracker
sandboxes with `SANDBOX_RUNTIME=firecracker`. The container backend
(`get_container_harness_sandbox`, `SANDBOX_CONTAINER_HARNESS=true`) is built
but not yet selected for harness calls.
"""

import threading
from typing import TYPE_CHECKING

from onyx.microvm.configs import HARNESS_SANDBOX_ENABLED, SANDBOX_FC_TEMPLATE
from onyx.microvm.lifecycle import (
    NoCheckpointSupport,
    SandboxActivityProbe,
    SandboxCheckpointer,
    UnknownActivity,
)
from onyx.server.features.build.configs import (
    SANDBOX_BACKEND,
    SANDBOX_CONTAINER_HARNESS,
    SandboxBackend,
)
from onyx.server.features.build.sandbox.harness_base import HarnessSandbox
from onyx.utils.logger import setup_logger

if TYPE_CHECKING:
    from onyx.server.features.build.sandbox.container.harness_sandbox import (
        ContainerHarnessSandbox,
    )
    from onyx.server.features.build.sandbox.firecracker.harness_sandbox import (
        FirecrackerHarnessSandbox,
    )

logger = setup_logger()

_lock = threading.Lock()
_instance: "FirecrackerHarnessSandbox | None" = None
_container_instance: "ContainerHarnessSandbox | None" = None
_eviction_error_logged = False


class HarnessSandboxUnavailableError(Exception):
    """No sandbox backend serves the new harness in this deployment."""


def _firecracker_sandbox() -> "FirecrackerHarnessSandbox":
    global _instance
    if not HARNESS_SANDBOX_ENABLED:
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


def get_container_harness_sandbox() -> "ContainerHarnessSandbox":
    """The container backend: pods with SANDBOX_BACKEND=kubernetes, Docker
    containers with SANDBOX_BACKEND=docker."""
    global _container_instance
    if not SANDBOX_CONTAINER_HARNESS:
        raise HarnessSandboxUnavailableError(
            "Container harness sandboxes need SANDBOX_CONTAINER_HARNESS=true"
        )
    with _lock:
        if _container_instance is None:
            # Deferred: the Docker or Kubernetes client loads only when used.
            from onyx.server.features.build.sandbox.container.harness_sandbox import (
                ContainerHarnessSandbox,
            )
            from onyx.server.features.build.sandbox.container.runtime import (
                ContainerRuntime,
            )
            from onyx.server.features.build.sandbox.container.transfer import (
                default_file_store_archives,
            )

            runtime: ContainerRuntime
            if SANDBOX_BACKEND is SandboxBackend.DOCKER:
                from onyx.server.features.build.sandbox.container.docker_runtime import (
                    DockerRuntime,
                )

                runtime = DockerRuntime()
            else:
                from onyx.server.features.build.sandbox.container.pod_runtime import (
                    PodRuntime,
                )

                runtime = PodRuntime()
            _container_instance = ContainerHarnessSandbox(
                runtime=runtime, archives=default_file_store_archives()
            )
    return _container_instance


def get_harness_sandbox() -> HarnessSandbox:
    return _firecracker_sandbox()


def get_firecracker_sandbox() -> "FirecrackerHarnessSandbox":
    """The Firecracker sandbox itself, for the smoke script. Node reports
    use `get_eviction_policy`, which turns eviction off on a configuration
    error instead of raising."""
    return _firecracker_sandbox()


def get_eviction_policy() -> tuple[SandboxCheckpointer, SandboxActivityProbe]:
    """The node-report idle evictor's save and busy checks. Firecracker VMs
    serve only the harness: without harness sandboxes no VM is stopped
    automatically. A configuration error (for example the file store) turns
    eviction off; it never fails the node report."""
    global _eviction_error_logged
    try:
        return _firecracker_sandbox().eviction_policy()
    except HarnessSandboxUnavailableError:
        return NoCheckpointSupport(), UnknownActivity()
    except Exception:
        if not _eviction_error_logged:
            _eviction_error_logged = True
            logger.exception("sandbox_fc_eviction_policy_failed; idle eviction is off")
        return NoCheckpointSupport(), UnknownActivity()
