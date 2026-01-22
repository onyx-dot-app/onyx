"""Abstract base class and factory for sandbox operations.

SandboxManager is the abstract interface for sandbox lifecycle management.
Use get_sandbox_manager() to get the appropriate implementation based on SANDBOX_BACKEND.
"""

import threading
from abc import ABC
from abc import abstractmethod
from collections.abc import Generator
from typing import Any

from sqlalchemy.orm import Session

from onyx.server.features.build.configs import SANDBOX_BACKEND
from onyx.server.features.build.configs import SandboxBackend
from onyx.server.features.build.sandbox.models import FilesystemEntry
from onyx.server.features.build.sandbox.models import SandboxInfo
from onyx.server.features.build.sandbox.models import SnapshotInfo
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

    Use get_sandbox_manager() to get the appropriate implementation.
    """

    @abstractmethod
    def provision(
        self,
        session_id: str,
        tenant_id: str,
        file_system_path: str,
        db_session: Session,
        snapshot_id: str | None = None,
    ) -> SandboxInfo:
        """Provision a new sandbox for a session.

        NOTE: This method uses flush() instead of commit(). The caller is
        responsible for committing the transaction when ready.

        Args:
            session_id: Unique identifier for the session
            tenant_id: Tenant identifier for multi-tenant isolation
            file_system_path: Path to the knowledge/source files to link
            db_session: Database session
            snapshot_id: Optional snapshot ID to restore from

        Returns:
            SandboxInfo with the provisioned sandbox details

        Raises:
            ValueError: If max concurrent sandboxes reached
            RuntimeError: If provisioning fails
        """
        ...

    @abstractmethod
    def terminate(self, sandbox_id: str, db_session: Session) -> None:
        """Terminate a sandbox.

        Args:
            sandbox_id: The sandbox ID to terminate
            db_session: Database session
        """
        ...

    @abstractmethod
    def create_snapshot(
        self, sandbox_id: str, db_session: Session
    ) -> SnapshotInfo | None:
        """Create a snapshot of the sandbox's outputs directory.

        Args:
            sandbox_id: The sandbox ID to snapshot
            db_session: Database session

        Returns:
            SnapshotInfo with the created snapshot details, or None if
            snapshots are disabled

        Raises:
            ValueError: If sandbox not found
            RuntimeError: If snapshot creation fails
        """
        ...

    @abstractmethod
    def health_check(self, sandbox_id: str, db_session: Session) -> bool:
        """Check if the sandbox is healthy.

        Args:
            sandbox_id: The sandbox ID to check
            db_session: Database session

        Returns:
            True if sandbox is healthy, False otherwise
        """
        ...

    @abstractmethod
    def send_message(
        self,
        sandbox_id: str,
        message: str,
        db_session: Session,
    ) -> Generator[ACPEvent, None, None]:
        """Send a message to the CLI agent and stream typed ACP events.

        Args:
            sandbox_id: The sandbox ID to send message to
            message: The message content to send
            db_session: Database session

        Yields:
            Typed ACP schema event objects

        Raises:
            ValueError: If sandbox not found
            RuntimeError: If agent communication fails
        """
        ...

    @abstractmethod
    def list_directory(
        self, sandbox_id: str, path: str, db_session: Session
    ) -> list[FilesystemEntry]:
        """List contents of a directory in the sandbox's outputs directory.

        Args:
            sandbox_id: The sandbox ID
            path: Relative path within the outputs directory
            db_session: Database session

        Returns:
            List of FilesystemEntry objects sorted by directory first, then name

        Raises:
            ValueError: If sandbox not found, path traversal attempted,
                       or path is not a directory
        """
        ...

    @abstractmethod
    def read_file(self, sandbox_id: str, path: str, db_session: Session) -> bytes:
        """Read a file from the sandbox's outputs directory.

        Args:
            sandbox_id: The sandbox ID
            path: Relative path within the outputs directory
            db_session: Database session

        Returns:
            File contents as bytes

        Raises:
            ValueError: If sandbox not found, path traversal attempted,
                       or path is not a file
        """
        ...

    @abstractmethod
    def get_sandbox_info(
        self, sandbox_id: str, db_session: Session
    ) -> SandboxInfo | None:
        """Get information about a sandbox.

        Args:
            sandbox_id: The sandbox ID
            db_session: Database session

        Returns:
            SandboxInfo or None if not found
        """
        ...

    @abstractmethod
    def cancel_agent(self, sandbox_id: str) -> None:
        """Cancel the current agent operation.

        Args:
            sandbox_id: The sandbox ID
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
