"""Local filesystem-based sandbox implementation.

This module provides the LocalSandboxManager for development and single-node
deployments that run sandboxes as directories on the local filesystem.

Internal implementation details (agent_client, directory_manager, process_manager)
are in the internal/ subdirectory and should not be used directly.
"""

from onyx.server.features.build.sandbox.local.manager import LocalSandboxManager

__all__ = [
    "LocalSandboxManager",
]
