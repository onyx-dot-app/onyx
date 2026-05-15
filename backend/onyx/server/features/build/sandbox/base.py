"""Abstract base class and factory for sandbox operations.

SandboxManager is the abstract interface for sandbox lifecycle management.
Use get_sandbox_manager() to get the appropriate implementation based on SANDBOX_BACKEND.

IMPORTANT: SandboxManager implementations must NOT interface with the database directly.
All database operations should be handled by the caller (SessionManager, Celery tasks, etc.).

Architecture Note (User-Shared Sandbox Model):
- One sandbox (container/pod) is shared across all of a user's sessions
- provision() creates the user's sandbox
- setup_session_workspace() creates per-session workspace within the sandbox
- cleanup_session_workspace() removes session workspace on session delete
- terminate() destroys the entire sandbox (all sessions)
"""

import threading
import time
from abc import ABC
from abc import abstractmethod
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from uuid import UUID

from onyx.server.features.build.configs import SANDBOX_BACKEND
from onyx.server.features.build.configs import SandboxBackend
from onyx.server.features.build.sandbox.models import FatalWriteError
from onyx.server.features.build.sandbox.models import FileSet
from onyx.server.features.build.sandbox.models import FilesystemEntry
from onyx.server.features.build.sandbox.models import LLMProviderConfig
from onyx.server.features.build.sandbox.models import PushFailure
from onyx.server.features.build.sandbox.models import PushResult
from onyx.server.features.build.sandbox.models import RetriableWriteError
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
    - Provisioning and termination (user-level)
    - Session workspace setup and cleanup (session-level)
    - Snapshot creation (session-level)
    - Health checks
    - Agent communication (session-level)
    - Filesystem operations (session-level)

    Directory Structure:
        $SANDBOX_ROOT/
        └── sessions/
            ├── $session_id_1/         # Per-session workspace
            │   ├── outputs/           # Agent output for this session
            │   │   └── web/           # Next.js app
            │   ├── venv/              # Python virtual environment
            │   ├── skills/            # Opencode skills
            │   ├── AGENTS.md          # Agent instructions
            │   ├── opencode.json      # LLM config
            │   └── attachments/
            └── $session_id_2/
                └── ...

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
        llm_config: LLMProviderConfig,
        onyx_pat: str | None = None,
    ) -> SandboxInfo:
        """Provision a new sandbox for a user.

        Creates the sandbox container/directory with:
        - sessions/ directory for per-session workspaces

        NOTE: This does NOT set up session-specific workspaces.
        Call setup_session_workspace() after provisioning to create a session workspace.

        Args:
            sandbox_id: Unique identifier for the sandbox
            user_id: User identifier who owns this sandbox
            tenant_id: Tenant identifier for multi-tenant isolation
            llm_config: LLM provider configuration (for default config)
            onyx_pat: Raw PAT token to inject as ONYX_PAT env var in the sandbox

        Returns:
            SandboxInfo with the provisioned sandbox details

        Raises:
            RuntimeError: If provisioning fails
        """
        ...

    @abstractmethod
    def terminate(self, sandbox_id: UUID) -> None:
        """Terminate a sandbox and clean up all resources.

        Destroys the entire sandbox including all session workspaces.
        Use cleanup_session_workspace() to remove individual sessions.

        Args:
            sandbox_id: The sandbox ID to terminate
        """
        ...

    @abstractmethod
    def setup_session_workspace(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        llm_config: LLMProviderConfig,
        nextjs_port: int | None,
        snapshot_path: str | None = None,
        user_name: str | None = None,
        user_role: str | None = None,
        user_work_area: str | None = None,
        user_level: str | None = None,
    ) -> None:
        """Set up a session workspace within an existing sandbox.

        Creates the per-session directory structure:
        - sessions/$session_id/outputs/ (from snapshot or template)
        - sessions/$session_id/venv/
        - sessions/$session_id/skills/
        - sessions/$session_id/AGENTS.md
        - sessions/$session_id/opencode.json
        - sessions/$session_id/attachments/
        - sessions/$session_id/org_info/ (if user_work_area provided)

        Args:
            sandbox_id: The sandbox ID (must be provisioned)
            session_id: The session ID for this workspace
            llm_config: LLM provider configuration for opencode.json
            snapshot_path: Optional storage path to restore outputs from
            user_name: User's name for personalization in AGENTS.md
            user_role: User's role/title for personalization in AGENTS.md
            user_work_area: User's work area for persona (e.g., "engineering")
            user_level: User's level for persona (e.g., "ic", "manager")

        Raises:
            RuntimeError: If workspace setup fails
        """
        ...

    @abstractmethod
    def cleanup_session_workspace(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        nextjs_port: int | None = None,
    ) -> None:
        """Clean up a session workspace (on session delete).

        1. Stop the Next.js dev server if running on nextjs_port
        2. Remove the session directory: sessions/$session_id/

        Does NOT terminate the sandbox - other sessions may still be using it.

        Args:
            sandbox_id: The sandbox ID
            session_id: The session ID to clean up
            nextjs_port: Optional port where Next.js server is running
        """
        ...

    @abstractmethod
    def create_snapshot(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        tenant_id: str,
    ) -> SnapshotResult | None:
        """Create a snapshot of a session's outputs and attachments directories.

        Captures session-specific user data:
        - sessions/$session_id/outputs/ (generated artifacts, web apps)
        - sessions/$session_id/attachments/ (user uploaded files)

        Does NOT include: venv, skills, AGENTS.md, opencode.json, files symlink
        (these are regenerated during restore)

        Args:
            sandbox_id: The sandbox ID
            session_id: The session ID to snapshot
            tenant_id: Tenant identifier for storage path

        Returns:
            SnapshotResult with storage path and size, or None if:
            - Snapshots are disabled for this backend
            - No outputs directory exists (nothing to snapshot)

        Raises:
            RuntimeError: If snapshot creation fails
        """
        ...

    @abstractmethod
    def restore_snapshot(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        snapshot_storage_path: str,
        tenant_id: str,
        nextjs_port: int | None,
        llm_config: LLMProviderConfig,
    ) -> None:
        """Restore a session workspace from a snapshot.

        For Kubernetes: Downloads and extracts the snapshot, regenerates config files.
        For Local: No-op since workspaces persist on disk (no snapshots).

        Args:
            sandbox_id: The sandbox ID
            session_id: The session ID to restore
            snapshot_storage_path: Path to the snapshot in storage
            tenant_id: Tenant identifier for storage access
            nextjs_port: Port number for the NextJS dev server, or None to
                skip starting it (e.g. headless scheduled-task fires).
            llm_config: LLM provider configuration for opencode.json

        Raises:
            RuntimeError: If snapshot restoration fails
        """
        ...

    @abstractmethod
    def session_workspace_exists(
        self,
        sandbox_id: UUID,
        session_id: UUID,
    ) -> bool:
        """Check if a session's workspace directory exists in the sandbox.

        Used to determine if we need to restore from snapshot.
        Checks for sessions/$session_id/outputs/ directory.

        Args:
            sandbox_id: The sandbox ID
            session_id: The session ID to check

        Returns:
            True if the session workspace exists, False otherwise
        """
        ...

    @abstractmethod
    def health_check(self, sandbox_id: UUID, timeout: float = 60.0) -> bool:
        """Check if the sandbox is healthy.

        Args:
            sandbox_id: The sandbox ID to check

        Returns:
            True if sandbox is healthy, False otherwise
        """
        ...

    @abstractmethod
    def send_message(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        message: str,
    ) -> Generator[ACPEvent, None, None]:
        """Send a message to the CLI agent and stream typed ACP events.

        The agent runs in the session-specific workspace:
        sessions/$session_id/

        Args:
            sandbox_id: The sandbox ID
            session_id: The session ID (determines workspace directory)
            message: The message content to send

        Yields:
            Typed ACP schema event objects

        Raises:
            RuntimeError: If agent communication fails
        """
        ...

    @abstractmethod
    def list_directory(
        self, sandbox_id: UUID, session_id: UUID, path: str
    ) -> list[FilesystemEntry]:
        """List contents of a directory in the session's outputs directory.

        Args:
            sandbox_id: The sandbox ID
            session_id: The session ID
            path: Relative path within sessions/$session_id/outputs/

        Returns:
            List of FilesystemEntry objects sorted by directory first, then name

        Raises:
            ValueError: If path traversal attempted or path is not a directory
        """
        ...

    @abstractmethod
    def read_file(self, sandbox_id: UUID, session_id: UUID, path: str) -> bytes:
        """Read a file from the session's workspace.

        Args:
            sandbox_id: The sandbox ID
            session_id: The session ID
            path: Relative path within sessions/$session_id/

        Returns:
            File contents as bytes

        Raises:
            ValueError: If path traversal attempted or path is not a file
        """
        ...

    @abstractmethod
    def upload_file(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        filename: str,
        content: bytes,
    ) -> str:
        """Upload a file to the session's attachments directory.

        Args:
            sandbox_id: The sandbox ID
            session_id: The session ID
            filename: Sanitized filename
            content: File content as bytes

        Returns:
            Relative path where file was saved (e.g., "attachments/doc.pdf")

        Raises:
            RuntimeError: If upload fails
        """
        ...

    @abstractmethod
    def delete_file(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        path: str,
    ) -> bool:
        """Delete a file from the session's workspace.

        Args:
            sandbox_id: The sandbox ID
            session_id: The session ID
            path: Relative path to the file (e.g., "attachments/doc.pdf")

        Returns:
            True if file was deleted, False if not found

        Raises:
            ValueError: If path traversal attempted
        """
        ...

    @abstractmethod
    def write_sandbox_file(
        self,
        sandbox_id: UUID,
        path: str,
        content: str,
    ) -> None:
        """Write a text file to the sandbox workspace root.

        Creates parent directories as needed. Sessions symlink to the
        sandbox-root skills directory, so writes here are visible to
        all sessions.

        Args:
            sandbox_id: The sandbox ID
            path: Relative path (e.g., "skills/company-search/SKILL.md").
                Must not contain ".." or start with "/".
            content: UTF-8 text content to write

        Raises:
            RuntimeError: If write fails
            ValueError: If path is invalid
        """
        ...

    @abstractmethod
    def get_upload_stats(
        self,
        sandbox_id: UUID,
        session_id: UUID,
    ) -> tuple[int, int]:
        """Get current file count and total size for a session's attachments.

        Args:
            sandbox_id: The sandbox ID
            session_id: The session ID

        Returns:
            Tuple of (file_count, total_size_bytes)
        """
        ...

    @abstractmethod
    def write_files_to_sandbox(
        self,
        *,
        sandbox_id: UUID,
        mount_path: str,
        files: FileSet,
    ) -> None:
        """Write files atomically to a sandbox. Raise RetriableWriteError for
        transients, FatalWriteError for permanent failures."""
        ...

    def push_to_sandbox(
        self,
        *,
        sandbox_id: UUID,
        mount_path: str,
        files: FileSet,
        timeout_s: float = 30.0,
    ) -> PushResult:
        """Push files to a single sandbox with retry."""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                self.write_files_to_sandbox(
                    sandbox_id=sandbox_id,
                    mount_path=mount_path,
                    files=files,
                )
                return PushResult(targets=1, succeeded=1, failures=[])
            except FatalWriteError as e:
                return PushResult(
                    targets=1,
                    succeeded=0,
                    failures=[
                        PushFailure(
                            sandbox_id=sandbox_id,
                            reason="write_error",
                            detail=str(e),
                        )
                    ],
                )
            except RetriableWriteError:
                if attempt < max_retries - 1:
                    time.sleep(min(2**attempt, timeout_s / max_retries))
                    continue
                return PushResult(
                    targets=1,
                    succeeded=0,
                    failures=[
                        PushFailure(
                            sandbox_id=sandbox_id,
                            reason="timeout",
                            detail=f"Failed after {max_retries} retries",
                        )
                    ],
                )
            except Exception as e:
                logger.warning(
                    "Unexpected error pushing to sandbox %s: %s",
                    sandbox_id,
                    e,
                )
                return PushResult(
                    targets=1,
                    succeeded=0,
                    failures=[
                        PushFailure(
                            sandbox_id=sandbox_id,
                            reason="write_error",
                            detail=str(e),
                        )
                    ],
                )
        raise AssertionError("unreachable: all retries should return")

    def push_to_sandboxes(
        self,
        *,
        mount_path: str,
        sandbox_files: dict[UUID, FileSet],
        timeout_s: float = 30.0,
    ) -> PushResult:
        """Push files to multiple sandboxes in parallel.

        Caller owns user→sandbox resolution (via DB). This method only handles
        parallelism and result aggregation over push_to_sandbox.
        """
        if not sandbox_files:
            return PushResult(targets=0, succeeded=0, failures=[])

        all_failures: list[PushFailure] = []
        pushed = 0

        def _push_one(sandbox_id: UUID) -> PushResult:
            return self.push_to_sandbox(
                sandbox_id=sandbox_id,
                mount_path=mount_path,
                files=sandbox_files[sandbox_id],
                timeout_s=timeout_s,
            )

        with ThreadPoolExecutor(max_workers=min(len(sandbox_files), 10)) as pool:
            for result in pool.map(_push_one, sandbox_files):
                pushed += result.succeeded
                all_failures.extend(result.failures)

        if all_failures:
            logger.warning(
                "push_to_sandboxes: %d/%d targets failed for mount_path=%s",
                len(all_failures),
                len(sandbox_files),
                mount_path,
            )

        return PushResult(
            targets=len(sandbox_files),
            succeeded=pushed,
            failures=all_failures,
        )

    @abstractmethod
    def get_webapp_url(self, sandbox_id: UUID, port: int) -> str:
        """Get the webapp URL for a session's Next.js server.

        Returns the appropriate URL based on the backend:
        - Local: Returns localhost URL with port
        - Kubernetes: Returns internal cluster service URL

        Args:
            sandbox_id: The sandbox ID
            port: The session's allocated Next.js port

        Returns:
            URL to access the webapp
        """
        ...

    @abstractmethod
    def generate_pptx_preview(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        pptx_path: str,
        cache_dir: str,
    ) -> tuple[list[str], bool]:
        """Convert PPTX to slide JPEG images for preview, with caching.

        Checks if cache_dir already has slides. If the PPTX is newer than the
        cached images (or no cache exists), runs soffice -> pdftoppm pipeline.

        Args:
            sandbox_id: The sandbox ID
            session_id: The session ID
            pptx_path: Relative path to the PPTX file within the session workspace
            cache_dir: Relative path for the cache directory
                       (e.g., "outputs/.pptx-preview/abc123")

        Returns:
            Tuple of (slide_paths, cached) where slide_paths is a list of
            relative paths to slide JPEG images (within session workspace)
            and cached indicates whether the result was served from cache.

        Raises:
            ValueError: If file not found or conversion fails
        """
        ...

    def ensure_nextjs_running(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        nextjs_port: int,
    ) -> None:
        """Ensure the Next.js server is running for a session.

        Default is a no-op — only meaningful for local backends that manage
        process lifecycles directly (e.g., LocalSandboxManager).

        Args:
            sandbox_id: The sandbox ID
            session_id: The session ID
            nextjs_port: The port the Next.js server should be listening on
        """


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
                    from onyx.server.features.build.sandbox.local.local_sandbox_manager import (
                        LocalSandboxManager,
                    )

                    _sandbox_manager_instance = LocalSandboxManager()
                elif SANDBOX_BACKEND == SandboxBackend.KUBERNETES:
                    from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
                        KubernetesSandboxManager,
                    )

                    _sandbox_manager_instance = KubernetesSandboxManager()
                    logger.info("Using KubernetesSandboxManager for sandbox operations")
                else:
                    raise ValueError(f"Unknown sandbox backend: {SANDBOX_BACKEND}")

    return _sandbox_manager_instance
