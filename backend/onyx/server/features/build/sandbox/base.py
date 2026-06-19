"""Abstract base class for sandbox operations.

SandboxManager is the abstract interface for sandbox lifecycle management.
Use sandbox.factory.get_sandbox_manager() to get the implementation for SANDBOX_BACKEND.

IMPORTANT: SandboxManager implementations must NOT interface with the database directly.
All database operations should be handled by the caller (SessionManager, Celery tasks, etc.).

Architecture Note (User-Shared Sandbox Model):
- One sandbox (container/pod) is shared across all of a user's sessions
- provision() creates the user's sandbox
- setup_session_workspace() creates per-session workspace within the sandbox
- cleanup_session_workspace() removes session workspace on session delete
- terminate() destroys the entire sandbox (all sessions)
"""

import time
from abc import ABC
from abc import abstractmethod
from collections.abc import Callable
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

from onyx.server.features.build.sandbox.event_schema import AgentMessageChunk
from onyx.server.features.build.sandbox.event_schema import AgentPlanUpdate
from onyx.server.features.build.sandbox.event_schema import AgentThoughtChunk
from onyx.server.features.build.sandbox.event_schema import CurrentModeUpdate
from onyx.server.features.build.sandbox.event_schema import Error
from onyx.server.features.build.sandbox.event_schema import PromptResponse
from onyx.server.features.build.sandbox.event_schema import ToolCallProgress
from onyx.server.features.build.sandbox.event_schema import ToolCallStart
from onyx.server.features.build.sandbox.models import FatalWriteError
from onyx.server.features.build.sandbox.models import FileSet
from onyx.server.features.build.sandbox.models import FilesystemEntry
from onyx.server.features.build.sandbox.models import LLMProviderConfig
from onyx.server.features.build.sandbox.models import PushFailure
from onyx.server.features.build.sandbox.models import PushResult
from onyx.server.features.build.sandbox.models import RetriableWriteError
from onyx.server.features.build.sandbox.models import SandboxInfo
from onyx.server.features.build.sandbox.models import SnapshotResult
from onyx.server.features.build.sandbox.serve_transport import _ServeMixin
from onyx.server.features.build.sandbox.sse import SSEKeepalive
from onyx.utils.logger import setup_logger

logger = setup_logger()


# In-sandbox paths shared by every backend implementation. Kept in sync with
# the SESSIONS_ROOT constants the individual managers define (those exist
# separately because the K8s manager emits exec scripts and the Docker
# manager mounts via the named volume — both happen to land at the same
# in-container path). The daemon's sandbox_daemon/snapshot.py also has its
# own copy because it can't import from this package at runtime.
BUN_CACHE_DIR = "/workspace/sessions/.bun-cache"
BUN_IMAGE_CACHE_DIR = "/home/sandbox/.bun/install/cache"

# Internal sandbox-event protocol — the type contract between the agent
# harness and everything downstream (session manager, SSE encoder,
# persistence, frontend). Schema lives in :mod:`event_schema`.
SandboxEvent = (
    AgentMessageChunk
    | AgentThoughtChunk
    | ToolCallStart
    | ToolCallProgress
    | AgentPlanUpdate
    | CurrentModeUpdate
    | PromptResponse
    | Error
    | SSEKeepalive
)


class SandboxManager(_ServeMixin, ABC):
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
        ├── managed/skills/            # Pushed skills, symlinked per session
        └── sessions/
            ├── $session_id_1/         # Per-session workspace
            │   ├── outputs/           # Agent output for this session
            │   │   └── web/           # Next.js app
            │   ├── venv/              # Python virtual environment
            │   ├── .opencode/skills   # Symlink → managed/skills
            │   ├── AGENTS.md          # Agent instructions
            │   └── attachments/
            └── $session_id_2/
                └── ...

    Serve-transport plumbing lives in :class:`_ServeMixin` (composed via
    MRO); subclasses implement :meth:`_load_serve_connection_info` plus
    the abstract methods below.

    IMPORTANT: Implementations must NOT interface with the database directly.
    All database operations should be handled by the caller.

    Use get_sandbox_manager() to get the appropriate implementation.
    """

    supports_opencode_history_persistence: bool = False

    @abstractmethod
    def provision(
        self,
        sandbox_id: UUID,
        user_id: UUID,
        tenant_id: str,
        llm_config: LLMProviderConfig,
        onyx_pat: str | None = None,
        *,
        all_llm_configs: list[LLMProviderConfig] | None = None,
    ) -> SandboxInfo:
        """Provision a new sandbox for a user.

        ``all_llm_configs``: the full set of LLM providers the user has
        configured. K8s pre-loads each into opencode-serve's startup config
        so per-prompt model overrides can cross providers without restarting
        the pod. Defaults to ``[llm_config]`` (single-provider, back-compat).

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
        """Terminate a sandbox and clean up all resources. Destroys every
        session workspace; for one session use ``cleanup_session_workspace``.

        Implementations MUST call ``self._close_all_sandbox_buses(sandbox_id)``
        before destroying the backend so late subscribes can't race a fresh
        bus in.
        """
        ...

    @abstractmethod
    def setup_session_workspace(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        llm_config: LLMProviderConfig,
        nextjs_port: int | None,
        skills_section: str,
        user_name: str | None = None,
    ) -> None:
        """Set up a session workspace within an existing sandbox.

        Creates the per-session directory structure:
        - sessions/$session_id/outputs/
        - sessions/$session_id/venv/
        - sessions/$session_id/.opencode/skills (symlink → managed skills dir)
        - sessions/$session_id/AGENTS.md
        - sessions/$session_id/attachments/

        Args:
            sandbox_id: The sandbox ID (must be provisioned)
            session_id: The session ID for this workspace
            llm_config: LLM provider configuration (passed to AGENTS.md rendering)
            nextjs_port: Port for the Next.js dev server, or None for headless.
            skills_section: Pre-rendered ``{{AVAILABLE_SKILLS_SECTION}}`` for AGENTS.md.
            user_name: User's name for personalization in AGENTS.md

        Raises:
            RuntimeError: If workspace setup fails
        """
        ...

    @abstractmethod
    def cleanup_session_workspace(
        self,
        sandbox_id: UUID,
        session_id: UUID,
    ) -> None:
        """Clean up a session workspace on session delete: stop the
        Next.js dev server and remove ``sessions/$session_id/``. Does NOT
        terminate the sandbox.

        Implementations MUST call ``self._close_session_buses(sandbox_id,
        session_id)`` — otherwise the per-session ``PodEventBus`` (reader
        thread + httpx connection) leaks until api_server restarts.
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

        Does NOT include: venv, skills, AGENTS.md, files symlink
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
        nextjs_port: int | None,
        llm_config: LLMProviderConfig,
        skills_section: str,
    ) -> None:
        """Restore a session workspace from a snapshot.

        For Kubernetes: Downloads and extracts the snapshot, regenerates config files.
        For Local: No-op since workspaces persist on disk (no snapshots).

        Args:
            sandbox_id: The sandbox ID
            session_id: The session ID to restore
            snapshot_storage_path: Path to the snapshot in storage
            nextjs_port: Port number for the NextJS dev server, or None to
                skip starting it (e.g. headless scheduled-task fires).
            llm_config: LLM provider configuration (used to regenerate AGENTS.md)

        Raises:
            RuntimeError: If snapshot restoration fails
        """
        ...

    def create_opencode_history_snapshot(
        self,
        sandbox_id: UUID,
        tenant_id: str,
        timeout_seconds: float = 300.0,
    ) -> bool:
        """Snapshot sandbox-global opencode history if this backend supports it.

        Returns False when opencode has not created any data yet. By default,
        an empty live store leaves any existing durable archive untouched so idle
        and recovery snapshots do not discard the last known history.
        Callers must gate on ``supports_opencode_history_persistence`` before
        invoking this optional capability.
        """
        _ = sandbox_id, tenant_id, timeout_seconds
        raise NotImplementedError(
            f"{type(self).__name__} does not support opencode history snapshots"
        )

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
    def list_session_workspaces(self, sandbox_id: UUID) -> list[UUID]:
        """List session workspace IDs under a sandbox's sessions/ directory.

        Used by idle cleanup to discover which sessions need snapshotting before
        the sandbox is terminated. Implementations should filter out non-UUID
        directory names.

        Args:
            sandbox_id: The sandbox ID

        Returns:
            List of session UUIDs found under sessions/. Returns an empty list
            if the sandbox is not running, has no sessions, or the backend does
            not support cleanup (e.g. local).
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

    def send_message(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        message: str,
        *,
        opencode_session_id: str | None = None,
        agent_provider: str | None = None,
        agent_model: str | None = None,
        on_opencode_session_resolved: Callable[[str], None] | None = None,
        should_interrupt: Callable[[], bool] | None = None,
    ) -> Generator[SandboxEvent, None, None]:
        """Stream typed sandbox events for one user message via
        opencode-serve.

        - ``opencode_session_id``: persistent serve session id; pass
          ``BuildSession.opencode_session_id`` or ``None`` to mint.
        - ``agent_provider`` / ``agent_model``: per-prompt model override;
          either ``None`` falls back to the loaded default.
        - ``on_opencode_session_resolved``: invoked with the resolved id
          when it differs from the caller's. Caller persists it so later
          turns don't orphan a fresh session each time.
        """
        yield from self._send_message_via_serve(
            sandbox_id,
            session_id,
            message,
            opencode_session_id,
            agent_provider,
            agent_model,
            on_opencode_session_resolved=on_opencode_session_resolved,
            should_interrupt=should_interrupt,
        )

    def send_subagent_message(
        self,
        sandbox_id: UUID,
        parent_session_id: UUID,
        subagent_opencode_session_id: str,
        message: str,
        agent_provider: str | None = None,
        agent_model: str | None = None,
    ) -> Generator[SandboxEvent, None, None]:
        """Stream a follow-up turn against an existing subagent (child)
        opencode session that was spawned under ``parent_session_id``.

        The child session shares the parent's session directory. Pass the
        parent session's ``agent_provider``/``agent_model`` so the follow-up
        uses the same model as the parent rather than the child session's own
        default.
        """
        yield from self.send_subagent_message_via_serve(
            sandbox_id,
            parent_session_id,
            subagent_opencode_session_id,
            message,
            agent_provider=agent_provider,
            agent_model=agent_model,
        )

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
