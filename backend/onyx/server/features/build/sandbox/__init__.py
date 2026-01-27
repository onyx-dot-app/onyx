"""
Sandbox module for CLI agent filesystem-based isolation.

This module provides lightweight sandbox management for CLI-based AI agent sessions.
Each sandbox is a directory on the local filesystem or a Kubernetes pod.

Usage:
    from onyx.server.features.build.sandbox import get_sandbox_manager

    # Get the appropriate sandbox manager based on SANDBOX_BACKEND config
    sandbox_manager = get_sandbox_manager()

    # Use the sandbox manager
    sandbox_info = sandbox_manager.provision(...)

Module structure:
    - base.py: SandboxManager ABC and get_sandbox_manager() factory
    - models.py: Shared Pydantic models
    - local/: Local filesystem-based implementation for development
    - kubernetes/: Kubernetes pod-based implementation for production
    - internal/: Shared internal utilities (snapshot manager)
"""

from onyx.server.features.build.sandbox.base import get_sandbox_manager
from onyx.server.features.build.sandbox.base import SandboxManager
from onyx.server.features.build.sandbox.local.local_sandbox_manager import (
    LocalSandboxManager,
)
from onyx.server.features.build.sandbox.models import FilesystemEntry
from onyx.server.features.build.sandbox.models import SandboxInfo
from onyx.server.features.build.sandbox.models import SnapshotInfo

__all__ = [
    # Factory function (preferred)
    "get_sandbox_manager",
    # Interface
    "SandboxManager",
    # Implementations
    "LocalSandboxManager",
    # Models
    "SandboxInfo",
    "SnapshotInfo",
    "FilesystemEntry",
]
