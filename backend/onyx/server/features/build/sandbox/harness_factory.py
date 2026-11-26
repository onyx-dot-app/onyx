"""Picks the sandbox for sessions on the new agent harness.

Only the new harness calls this; opencode sessions keep `get_sandbox_manager`
(pod or Docker, chosen by `SANDBOX_BACKEND`). The harness gets:
- Firecracker with `SANDBOX_RUNTIME=firecracker`, or with `auto` and no
  container backend.
- The container backend (`SANDBOX_CONTAINER_HARNESS=true`) with `pod`, or
  with `auto` and `SANDBOX_BACKEND=docker` (Compose never uses Firecracker).
- Both with `auto` on Kubernetes and the container backend on: each sandbox
  gets one backend (`harness_selection`).
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
    CONTAINER_HARNESS_ENABLED,
    SANDBOX_BACKEND,
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
    from onyx.server.features.build.sandbox.harness_selection import (
        SelectingHarnessSandbox,
    )

logger = setup_logger()

_lock = threading.Lock()
_instance: "FirecrackerHarnessSandbox | None" = None
_container_instance: "ContainerHarnessSandbox | None" = None
_selecting_instance: "SelectingHarnessSandbox | None" = None
_eviction_error_logged = False


class HarnessSandboxUnavailableError(Exception):
    """No sandbox backend serves the new harness in this deployment."""


def _firecracker_sandbox() -> "FirecrackerHarnessSandbox":
    global _instance
    if not HARNESS_SANDBOX_ENABLED:
        raise HarnessSandboxUnavailableError(
            "Harness sandboxes need SANDBOX_RUNTIME=firecracker or auto, and SANDBOX_FC_TEMPLATE"
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
    if not CONTAINER_HARNESS_ENABLED:
        raise HarnessSandboxUnavailableError(
            "Container harness sandboxes need SANDBOX_CONTAINER_HARNESS=true "
            "and SANDBOX_RUNTIME=auto or pod"
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


def _selecting_sandbox() -> "SelectingHarnessSandbox":
    global _selecting_instance
    firecracker = _firecracker_sandbox()
    container = get_container_harness_sandbox()
    with _lock:
        if _selecting_instance is None:
            from onyx.microvm.availability import firecracker_available
            from onyx.server.features.build.sandbox.harness_selection import (
                SelectingHarnessSandbox,
            )

            _selecting_instance = SelectingHarnessSandbox(
                firecracker=firecracker,
                container=container,
                firecracker_available=firecracker_available,
            )
    return _selecting_instance


def get_harness_sandbox() -> HarnessSandbox:
    """The harness sandbox of this deployment. Raises
    HarnessSandboxUnavailableError when no backend is on."""
    if HARNESS_SANDBOX_ENABLED and CONTAINER_HARNESS_ENABLED:
        return _selecting_sandbox()
    if CONTAINER_HARNESS_ENABLED:
        return get_container_harness_sandbox()
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
