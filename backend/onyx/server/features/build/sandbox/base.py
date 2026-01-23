"""Abstract base class and factory for sandbox operations.

SandboxManager is the abstract interface for sandbox lifecycle management.
Use get_sandbox_manager() to get the appropriate implementation based on SANDBOX_BACKEND.

IMPORTANT: SandboxManager implementations must NOT interface with the database directly.
All database operations should be handled by the caller (SessionManager, Celery tasks, etc.).
"""

import threading
from abc import ABC
from abc import abstractmethod
from collections.abc import Generator
from typing import Any
from uuid import UUID

from onyx.server.features.build.configs import SANDBOX_BACKEND
from onyx.server.features.build.configs import SandboxBackend
from onyx.server.features.build.sandbox.models import FilesystemEntry
from onyx.server.features.build.sandbox.models import LLMProviderConfig
from onyx.server.features.build.sandbox.models import SandboxInfo
from onyx.server.features.build.sandbox.models import SnapshotResult
from onyx.utils.logger import setup_logger

logger = setup_logger()

# ACPEvent is a union type defined in both local and kubernetes modules
# Using Any here to avoid circular imports - the actual type checking
# happens in the implementation modules
ACPEvent = Any


class SandboxManager(ABC):
    """Abstract interface for sandbox operations.

    Defines the contract for sandbox lifecycle management including:
    - Provisioning and termination
    - Snapshot creation
    - Health checks
    - Agent communication
    - Filesystem operations

    IMPORTANT: Implementations must NOT interface with the database directly.
    All database operations should be handled by the caller.

    Use get_sandbox_manager() to get the appropriate implementation.
    """

    @abstractmethod
    def provision(
        self,
        sandbox_id: UUID,
        user_id: UUID,
        tenant_id: str,
        file_system_path: str,
        llm_config: LLMProviderConfig,
        nextjs_port: int | None = None,
        snapshot_path: str | None = None,
        user_name: str | None = None,
        user_role: str | None = None,
    ) -> SandboxInfo:
        """Provision a new sandbox for a session.

        Args:
            sandbox_id: Unique identifier for the sandbox
            user_id: User identifier who owns this sandbox
            tenant_id: Tenant identifier for multi-tenant isolation
            file_system_path: Path to the knowledge/source files to link
            llm_config: LLM provider configuration
            nextjs_port: Pre-allocated port for Next.js server (local backend only)
            snapshot_path: Optional storage path to restore from
            user_name: User's name for personalization in AGENTS.md
            user_role: User's role/title for personalization in AGENTS.md

        Returns:
            SandboxInfo with the provisioned sandbox details

        Raises:
            RuntimeError: If provisioning fails
        """
        ...

    @abstractmethod
    def terminate(self, sandbox_id: UUID) -> None:
        """Terminate a sandbox and clean up resources.

        Args:
            sandbox_id: The sandbox ID to terminate
        """
        ...

    @abstractmethod
    def create_snapshot(
        self, sandbox_id: UUID, tenant_id: str
    ) -> SnapshotResult | None:
        """Create a snapshot of the sandbox's outputs directory.

        Args:
            sandbox_id: The sandbox ID to snapshot
            tenant_id: Tenant identifier for storage path

        Returns:
            SnapshotResult with storage path and size, or None if
            snapshots are disabled for this backend

        Raises:
            RuntimeError: If snapshot creation fails
        """
        ...

    @abstractmethod
    def health_check(
        self, sandbox_id: UUID, nextjs_port: int | None, timeout: float = 60.0
    ) -> bool:
        """Check if the sandbox is healthy.

        Args:
            sandbox_id: The sandbox ID to check
            nextjs_port: The Next.js port (for local backend health checks)

        Returns:
            True if sandbox is healthy, False otherwise
        """
        ...

    @abstractmethod
    def send_message(
        self,
        sandbox_id: UUID,
        message: str,
    ) -> Generator[ACPEvent, None, None]:
        """Send a message to the CLI agent and stream typed ACP events.

        Args:
            sandbox_id: The sandbox ID to send message to
            message: The message content to send

        Yields:
            Typed ACP schema event objects

        Raises:
            RuntimeError: If agent communication fails
        """
        ...

    @abstractmethod
    def list_directory(self, sandbox_id: UUID, path: str) -> list[FilesystemEntry]:
        """List contents of a directory in the sandbox's outputs directory.

        Args:
            sandbox_id: The sandbox ID
            path: Relative path within the outputs directory

        Returns:
            List of FilesystemEntry objects sorted by directory first, then name

        Raises:
            ValueError: If path traversal attempted or path is not a directory
        """
        ...

    @abstractmethod
    def read_file(self, sandbox_id: UUID, path: str) -> bytes:
        """Read a file from the sandbox's outputs directory.

        Args:
            sandbox_id: The sandbox ID
            path: Relative path within the outputs directory

        Returns:
            File contents as bytes

        Raises:
            ValueError: If path traversal attempted or path is not a file
        """
        ...


# Singleton instance cache for the factory
_sandbox_manager_instance: SandboxManager | None = None
_sandbox_manager_lock = threading.Lock()


def get_sandbox_manager() -> SandboxManager:
    """Get the appropriate SandboxManager implementation based on SANDBOX_BACKEND.

    Returns:
        SandboxManager instance:
        - LocalSandboxManager for local backend (development)
        - KubernetesSandboxManager for kubernetes backend (production)
    """
    global _sandbox_manager_instance

    if _sandbox_manager_instance is None:
        with _sandbox_manager_lock:
            if _sandbox_manager_instance is None:
                if SANDBOX_BACKEND == SandboxBackend.LOCAL:
                    from onyx.server.features.build.sandbox.local.manager import (
                        LocalSandboxManager,
                    )

                    _sandbox_manager_instance = LocalSandboxManager()
                elif SANDBOX_BACKEND == SandboxBackend.KUBERNETES:
                    from onyx.server.features.build.sandbox.kubernetes.manager import (
                        KubernetesSandboxManager,
                    )

                    _sandbox_manager_instance = KubernetesSandboxManager()
                    logger.info("Using KubernetesSandboxManager for sandbox operations")
                else:
                    raise ValueError(f"Unknown sandbox backend: {SANDBOX_BACKEND}")

    return _sandbox_manager_instance
