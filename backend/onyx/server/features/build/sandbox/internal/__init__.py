"""Shared internal implementation details for sandbox management.

Note: Local-specific components (ACPAgentClient, DirectoryManager, ProcessManager)
have been moved to the local/ subdirectory.
"""

from onyx.server.features.build.sandbox.internal.snapshot_manager import SnapshotManager

__all__ = [
    "SnapshotManager",
]
