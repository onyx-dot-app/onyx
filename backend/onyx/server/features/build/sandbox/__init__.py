"""
Sandbox module for CLI agent filesystem-based isolation.

This module provides lightweight sandbox management for CLI-based AI agent sessions.
Each sandbox is a directory on the local filesystem rather than a Docker container.
"""

from onyx.server.features.build.sandbox.manager import SandboxManager
from onyx.server.features.build.sandbox.models import FilesystemEntry
from onyx.server.features.build.sandbox.models import SandboxInfo
from onyx.server.features.build.sandbox.models import SnapshotInfo

__all__ = [
    "SandboxManager",
    "SandboxInfo",
    "SnapshotInfo",
    "FilesystemEntry",
]
