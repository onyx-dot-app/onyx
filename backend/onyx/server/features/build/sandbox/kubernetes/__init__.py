"""Kubernetes-based sandbox implementation.

This module provides the KubernetesSandboxManager for production deployments
that run sandboxes as isolated Kubernetes pods.

Internal implementation details (acp_http_client) are in the internal/
subdirectory and should not be used directly.
"""

from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
    KubernetesSandboxManager,
)

__all__ = [
    "KubernetesSandboxManager",
]
