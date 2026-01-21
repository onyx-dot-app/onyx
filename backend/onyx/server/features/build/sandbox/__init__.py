"""
Sandbox module for CLI agent filesystem-based isolation.

This module provides lightweight sandbox management for CLI-based AI agent sessions.
Each sandbox is a directory on the local filesystem rather than a Docker container.

Usage:
    from onyx.server.features.build.sandbox import get_sandbox_manager

    # Get the appropriate sandbox manager based on SANDBOX_BACKEND config
    sandbox_manager = get_sandbox_manager()

    # Use the sandbox manager
    sandbox_info = sandbox_manager.provision(...)
"""

from onyx.server.features.build.sandbox.manager import get_sandbox_manager
from onyx.server.features.build.sandbox.manager import LocalSandboxManager
from onyx.server.features.build.sandbox.manager import SandboxManager
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
