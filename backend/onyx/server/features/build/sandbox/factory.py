"""Factory for selecting the SandboxManager implementation.

Lives outside base.py so the abstract interface never references its concrete
subclasses (which all import base).
"""

import threading

from onyx.server.features.build.configs import SANDBOX_BACKEND
from onyx.server.features.build.configs import SandboxBackend
from onyx.server.features.build.sandbox.base import SandboxManager
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Singleton instance cache for the factory
_sandbox_manager_instance: SandboxManager | None = None
_sandbox_manager_lock = threading.Lock()


def get_sandbox_manager() -> SandboxManager:
    """Get the appropriate SandboxManager implementation based on SANDBOX_BACKEND.

    Returns:
        SandboxManager instance:
        - KubernetesSandboxManager for kubernetes backend (production + dev kind)
        - DockerSandboxManager for self-hosted docker-compose
    """
    global _sandbox_manager_instance

    if _sandbox_manager_instance is None:
        with _sandbox_manager_lock:
            if _sandbox_manager_instance is None:
                if SANDBOX_BACKEND == SandboxBackend.KUBERNETES:
                    # Deferred: avoid loading the kubernetes client stack on
                    # docker deployments (and vice versa).
                    from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
                        KubernetesSandboxManager,
                    )

                    _sandbox_manager_instance = KubernetesSandboxManager()
                    logger.info("Using KubernetesSandboxManager for sandbox operations")
                elif SANDBOX_BACKEND == SandboxBackend.DOCKER:
                    from onyx.server.features.build.sandbox.docker.docker_sandbox_manager import (
                        DockerSandboxManager,
                    )

                    _sandbox_manager_instance = DockerSandboxManager()
                    logger.info("Using DockerSandboxManager for sandbox operations")
                else:
                    raise ValueError(f"Unknown sandbox backend: {SANDBOX_BACKEND}")

    return _sandbox_manager_instance
