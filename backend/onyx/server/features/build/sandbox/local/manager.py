"""Filesystem-based sandbox manager for local/dev environments.

LocalSandboxManager manages sandboxes as directories on the local filesystem.
Suitable for development, testing, and single-node deployments.

IMPORTANT: This manager does NOT interface with the database directly.
All database operations should be handled by the caller (SessionManager, Celery tasks, etc.).
"""

import threading
from collections.abc import Generator
from datetime import datetime
from pathlib import Path
from uuid import UUID

from onyx.db.enums import SandboxStatus
from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.build.configs import OPENCODE_DISABLED_TOOLS
from onyx.server.features.build.configs import OUTPUTS_TEMPLATE_PATH
from onyx.server.features.build.configs import SANDBOX_BASE_PATH
from onyx.server.features.build.configs import VENV_TEMPLATE_PATH
from onyx.server.features.build.sandbox.base import SandboxManager
from onyx.server.features.build.sandbox.internal.snapshot_manager import SnapshotManager
from onyx.server.features.build.sandbox.local.internal.agent_client import (
    ACPAgentClient,
)
from onyx.server.features.build.sandbox.local.internal.agent_client import ACPEvent
from onyx.server.features.build.sandbox.local.internal.directory_manager import (
    DirectoryManager,
)
from onyx.server.features.build.sandbox.local.internal.process_manager import (
    ProcessManager,
)
from onyx.server.features.build.sandbox.models import FilesystemEntry
from onyx.server.features.build.sandbox.models import LLMProviderConfig
from onyx.server.features.build.sandbox.models import SandboxInfo
from onyx.server.features.build.sandbox.models import SnapshotResult
from onyx.utils.logger import setup_logger

logger = setup_logger()


class LocalSandboxManager(SandboxManager):
    """Filesystem-based sandbox manager for local/dev environments.

    Manages sandboxes as directories on the local filesystem.
    Suitable for development, testing, and single-node deployments.

    Key characteristics:
    - Sandboxes are directories under SANDBOX_BASE_PATH
    - No container isolation (process-level only)
    - No automatic cleanup of idle sandboxes

    IMPORTANT: This manager does NOT interface with the database directly.
    All database operations should be handled by the caller.

    This is a singleton class - use get_sandbox_manager() to get the instance.
    """

    _instance: "LocalSandboxManager | None" = None
    _lock = threading.Lock()

    def __new__(cls) -> "LocalSandboxManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialize()
        return cls._instance

    def _initialize(self) -> None:
        """Initialize managers."""
        # Paths for templates
        build_dir = Path(__file__).parent.parent.parent  # /onyx/server/features/build/
        skills_path = build_dir / "skills"
        agent_instructions_template_path = build_dir / "AGENTS.template.md"

        self._directory_manager = DirectoryManager(
            base_path=Path(SANDBOX_BASE_PATH),
            outputs_template_path=Path(OUTPUTS_TEMPLATE_PATH),
            venv_template_path=Path(VENV_TEMPLATE_PATH),
            skills_path=skills_path,
            agent_instructions_template_path=agent_instructions_template_path,
        )
        self._process_manager = ProcessManager()
        self._snapshot_manager = SnapshotManager(get_default_file_store())

        # Track ACP clients in memory - keyed by (sandbox_id, session_id) tuple
        # Each session within a sandbox has its own ACP client
        self._acp_clients: dict[tuple[UUID, UUID], ACPAgentClient] = {}

        # Validate templates exist (raises RuntimeError if missing)
        self._validate_templates()

    def _validate_templates(self) -> None:
        """Validate that sandbox templates exist.

        Raises RuntimeError if templates are missing.
        Templates are required for sandbox functionality.

        Raises:
            RuntimeError: If outputs or venv templates are missing
        """
        outputs_path = Path(OUTPUTS_TEMPLATE_PATH)
        venv_path = Path(VENV_TEMPLATE_PATH)

        missing_templates: list[str] = []

        if not outputs_path.exists():
            missing_templates.append(f"Outputs template not found at {outputs_path}")

        if not venv_path.exists():
            missing_templates.append(f"Venv template not found at {venv_path}")

        if missing_templates:
            error_msg = (
                "Sandbox templates are missing. "
                "Please build templates using:\n"
                "  python -m onyx.server.features.build.sandbox.build_templates\n"
                "Or use Docker image built with Dockerfile.sandbox-templates.\n\n"
                "Missing templates:\n"
            )
            error_msg += "\n".join(f"  - {template}" for template in missing_templates)
            raise RuntimeError(error_msg)

        logger.debug(f"Outputs template found at {outputs_path}")
        logger.debug(f"Venv template found at {venv_path}")

    def _get_sandbox_path(self, sandbox_id: str | UUID) -> Path:
        """Get the filesystem path for a sandbox based on sandbox_id.

        Args:
            sandbox_id: The sandbox ID (can be string or UUID)

        Returns:
            Path to the sandbox directory
        """
        return Path(SANDBOX_BASE_PATH) / str(sandbox_id)

    def _get_session_path(self, sandbox_id: str | UUID, session_id: str | UUID) -> Path:
        """Get the filesystem path for a session workspace.

        Args:
            sandbox_id: The sandbox ID
            session_id: The session ID

        Returns:
            Path to the session workspace directory (sessions/$session_id/)
        """
        return self._get_sandbox_path(sandbox_id) / "sessions" / str(session_id)

    def provision(
        self,
        sandbox_id: UUID,
        user_id: UUID,
        tenant_id: str,
        file_system_path: str,
        llm_config: LLMProviderConfig,
        nextjs_port: int | None = None,
    ) -> SandboxInfo:
        """Provision a new sandbox for a user.

        Creates user-level sandbox structure:
        1. Create sandbox directory with sessions/ subdirectory
        2. Setup files symlink to knowledge/source files

        NOTE: This does NOT set up session-specific workspaces or start Next.js.
        Call setup_session_workspace() to create session workspaces.
        Next.js server is started per-session in setup_session_workspace().

        Args:
            sandbox_id: Unique identifier for the sandbox
            user_id: User identifier who owns this sandbox
            tenant_id: Tenant identifier for multi-tenant isolation
            file_system_path: Path to the knowledge/source files to link
            llm_config: LLM provider configuration (stored for default config)
            nextjs_port: Pre-allocated port for Next.js server (stored for later use)

        Returns:
            SandboxInfo with the provisioned sandbox details

        Raises:
            RuntimeError: If provisioning fails
        """
        logger.info(
            f"Starting sandbox provisioning for sandbox {sandbox_id}, "
            f"user {user_id}, tenant {tenant_id}"
        )

        if nextjs_port is None:
            raise RuntimeError(
                "nextjs_port must be provided for local sandbox provisioning"
            )

        # Create sandbox directory structure (user-level only)
        logger.info(f"Creating sandbox directory structure for sandbox {sandbox_id}")
        sandbox_path = self._directory_manager.create_sandbox_directory(str(sandbox_id))
        logger.debug(f"Sandbox directory created at {sandbox_path}")

        try:
            # Setup files symlink (shared across all sessions)
            logger.debug(f"Setting up files symlink to {file_system_path}")
            self._directory_manager.setup_files_symlink(
                sandbox_path, Path(file_system_path)
            )
            logger.debug("Files symlink created")

            logger.info(
                f"Provisioned sandbox {sandbox_id} at {sandbox_path} "
                f"(no sessions yet, Next.js port reserved: {nextjs_port})"
            )

            return SandboxInfo(
                sandbox_id=sandbox_id,
                directory_path=str(self._get_sandbox_path(sandbox_id)),
                status=SandboxStatus.RUNNING,
                last_heartbeat=None,
                nextjs_port=nextjs_port,
            )

        except Exception as e:
            # Cleanup on failure
            logger.error(
                f"Sandbox provisioning failed for sandbox {sandbox_id}: {e}",
                exc_info=True,
            )
            logger.info(f"Cleaning up sandbox directory at {sandbox_path}")
            self._directory_manager.cleanup_sandbox_directory(sandbox_path)
            raise

    def terminate(self, sandbox_id: UUID) -> None:
        """Terminate a sandbox and clean up all resources.

        1. Stop all ACP clients for this sandbox (terminates agent subprocesses)
        2. Cleanup sandbox directory (this will handle Next.js process cleanup)

        Args:
            sandbox_id: The sandbox ID to terminate

        Raises:
            RuntimeError: If termination fails
        """
        # Stop all ACP clients for this sandbox (keyed by (sandbox_id, session_id))
        clients_to_stop = [
            (key, client)
            for key, client in self._acp_clients.items()
            if key[0] == sandbox_id
        ]
        for key, client in clients_to_stop:
            try:
                client.stop()
                del self._acp_clients[key]
            except Exception as e:
                logger.warning(
                    f"Failed to stop ACP client for sandbox {sandbox_id}, "
                    f"session {key[1]}: {e}"
                )

        # Cleanup directory (this will handle Next.js process cleanup)
        sandbox_path = self._get_sandbox_path(sandbox_id)
        try:
            self._directory_manager.cleanup_sandbox_directory(sandbox_path)
        except Exception as e:
            raise RuntimeError(
                f"Failed to cleanup sandbox directory {sandbox_path}: {e}"
            ) from e

        logger.info(f"Terminated sandbox {sandbox_id}")

    def setup_session_workspace(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        llm_config: LLMProviderConfig,
        snapshot_path: str | None = None,
    ) -> None:
        """Set up a session workspace within an existing sandbox.

        Creates per-session directory structure with:
        1. sessions/$session_id/ directory
        2. outputs/ (from snapshot or template)
        3. .venv/ (from template)
        4. AGENTS.md
        5. .agent/skills/
        6. files/ (symlink to sandbox-level files/)
        7. opencode.json
        8. user_uploaded_files/
        9. Start Next.js dev server for this session

        Args:
            sandbox_id: The sandbox ID (must be provisioned)
            session_id: The session ID for this workspace
            llm_config: LLM provider configuration for opencode.json
            snapshot_path: Optional storage path to restore outputs from

        Raises:
            RuntimeError: If workspace setup fails
        """
        sandbox_path = self._get_sandbox_path(sandbox_id)

        if not self._directory_manager.directory_exists(sandbox_path):
            raise RuntimeError(
                f"Sandbox {sandbox_id} not provisioned - provision() first"
            )

        logger.info(
            f"Setting up session workspace for session {session_id} "
            f"in sandbox {sandbox_id}"
        )

        # Create session directory
        session_path = self._directory_manager.create_session_directory(
            sandbox_path, str(session_id)
        )
        logger.debug(f"Session directory created at {session_path}")

        try:
            logger.debug("Setting up outputs directory from template")
            self._directory_manager.setup_outputs_directory(session_path)
            logger.debug("Outputs directory ready")

            # Setup venv, AGENTS.md, and skills
            logger.debug("Setting up virtual environment")
            self._directory_manager.setup_venv(session_path)
            logger.debug("Virtual environment ready")

            logger.debug("Setting up agent instructions (AGENTS.md)")
            self._directory_manager.setup_agent_instructions(session_path)
            logger.debug("Agent instructions ready")

            logger.debug("Setting up skills")
            self._directory_manager.setup_skills(session_path)
            logger.debug("Skills ready")

            # Setup user uploads directory
            logger.debug("Setting up user uploads directory")
            self._directory_manager.setup_user_uploads_directory(session_path)
            logger.debug("User uploads directory ready")

            # Setup files symlink within session workspace
            logger.debug("Setting up files symlink in session workspace")
            self._directory_manager.setup_session_files_symlink(
                sandbox_path, session_path
            )
            logger.debug("Files symlink ready")

            # Setup opencode.json with LLM provider configuration
            logger.debug(
                f"Setting up opencode config with provider: {llm_config.provider}, "
                f"model: {llm_config.model_name}"
            )
            self._directory_manager.setup_opencode_config(
                sandbox_path=session_path,
                provider=llm_config.provider,
                model_name=llm_config.model_name,
                api_key=llm_config.api_key,
                api_base=llm_config.api_base,
                disabled_tools=OPENCODE_DISABLED_TOOLS,
            )
            logger.debug("Opencode config ready")

            # Start Next.js server for this session
            web_dir = session_path / "outputs" / "web"
            if web_dir.exists():
                # Note: For now, we'll share the sandbox's Next.js port
                # Future: Each session could have its own port
                logger.debug(
                    f"Session workspace {session_id} ready "
                    f"(Next.js served from sandbox port)"
                )

            logger.info(f"Set up session workspace {session_id} at {session_path}")

        except Exception as e:
            # Cleanup on failure
            logger.error(
                f"Session workspace setup failed for session {session_id}: {e}",
                exc_info=True,
            )
            logger.info(f"Cleaning up session directory at {session_path}")
            self._directory_manager.cleanup_session_directory(
                sandbox_path, str(session_id)
            )
            raise RuntimeError(
                f"Failed to set up session workspace {session_id}: {e}"
            ) from e

    def cleanup_session_workspace(
        self,
        sandbox_id: UUID,
        session_id: UUID,
    ) -> None:
        """Clean up a session workspace (on session delete).

        1. Stop ACP client for this session
        2. Remove session directory

        Does NOT terminate the sandbox - other sessions may still be using it.

        Args:
            sandbox_id: The sandbox ID
            session_id: The session ID to clean up
        """
        # Stop ACP client for this session
        client_key = (sandbox_id, session_id)
        client = self._acp_clients.pop(client_key, None)
        if client:
            try:
                client.stop()
                logger.debug(f"Stopped ACP client for session {session_id}")
            except Exception as e:
                logger.warning(
                    f"Failed to stop ACP client for session {session_id}: {e}"
                )

        # Cleanup session directory
        sandbox_path = self._get_sandbox_path(sandbox_id)
        self._directory_manager.cleanup_session_directory(sandbox_path, str(session_id))
        logger.info(f"Cleaned up session workspace {session_id}")

    def create_snapshot(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        tenant_id: str,
    ) -> SnapshotResult | None:
        """Create a snapshot of a session's outputs directory.

        Returns None if snapshots are disabled (local backend).

        Args:
            sandbox_id: The sandbox ID
            session_id: The session ID to snapshot
            tenant_id: Tenant identifier for storage path

        Returns:
            SnapshotResult with storage path and size, or None if
            snapshots are disabled for this backend
        """
        session_path = self._get_session_path(sandbox_id, session_id)
        # SnapshotManager expects string session_id for storage path
        _, storage_path, size_bytes = self._snapshot_manager.create_snapshot(
            session_path,
            str(session_id),
            tenant_id,
        )

        logger.info(
            f"Created snapshot for session {session_id}, size: {size_bytes} bytes"
        )

        return SnapshotResult(
            storage_path=storage_path,
            size_bytes=size_bytes,
        )

    def health_check(
        self, sandbox_id: UUID, nextjs_port: int | None, timeout: float = 60.0
    ) -> bool:
        """Check if the sandbox is healthy (Next.js server running).

        Args:
            sandbox_id: The sandbox ID to check
            nextjs_port: The Next.js port to check
            timeout: Health check timeout in seconds

        Returns:
            True if sandbox is healthy, False otherwise
        """
        # assume healthy if no port is specified
        if not nextjs_port:
            return True

        # Check Next.js server is responsive on the sandbox's allocated port
        return self._process_manager._wait_for_server(
            f"http://localhost:{nextjs_port}",
            timeout=timeout,
        )

    def send_message(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        message: str,
    ) -> Generator[ACPEvent, None, None]:
        """Send a message to the CLI agent and stream typed ACP events.

        The agent runs in the session-specific workspace:
        sessions/$session_id/

        Yields ACPEvent objects:
        - AgentMessageChunk: Text/image content from agent
        - AgentThoughtChunk: Agent's internal reasoning
        - ToolCallStart: Tool invocation started
        - ToolCallProgress: Tool execution progress/result
        - AgentPlanUpdate: Agent's execution plan
        - CurrentModeUpdate: Agent mode change
        - PromptResponse: Agent finished (has stop_reason)
        - Error: An error occurred

        Args:
            sandbox_id: The sandbox ID
            session_id: The session ID (determines workspace directory)
            message: The message content to send

        Yields:
            Typed ACP schema event objects
        """
        # Get or create ACP client for this session
        client_key = (sandbox_id, session_id)
        client = self._acp_clients.get(client_key)
        if client is None or not client.is_running:
            session_path = self._get_session_path(sandbox_id, session_id)

            # Create and start ACP client for this session
            client = ACPAgentClient(cwd=str(session_path))
            self._acp_clients[client_key] = client

        for event in client.send_message(message):
            yield event

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
        session_path = self._get_session_path(sandbox_id, session_id)
        target_path = session_path / path.lstrip("/")

        # Security: ensure path is within outputs directory
        try:
            target_path.resolve().relative_to(session_path.resolve())
        except ValueError:
            raise ValueError("Path traversal not allowed")

        if not target_path.is_dir():
            raise ValueError(f"Not a directory: {path}")

        entries = []
        for item in target_path.iterdir():
            stat = item.stat()
            entries.append(
                FilesystemEntry(
                    name=item.name,
                    path=str(item.relative_to(session_path)),
                    is_directory=item.is_dir(),
                    size_bytes=stat.st_size if item.is_file() else None,
                    modified_at=datetime.fromtimestamp(stat.st_mtime),
                )
            )

        return sorted(entries, key=lambda e: (not e.is_directory, e.name.lower()))

    def read_file(self, sandbox_id: UUID, session_id: UUID, path: str) -> bytes:
        """Read a file from the session's outputs directory.

        Args:
            sandbox_id: The sandbox ID
            session_id: The session ID
            path: Relative path within sessions/$session_id/outputs/

        Returns:
            File contents as bytes

        Raises:
            ValueError: If path traversal attempted or path is not a file
        """
        session_path = self._get_session_path(sandbox_id, session_id)
        outputs_path = session_path / "outputs"
        target_path = outputs_path / path.lstrip("/")

        # Security: ensure path is within outputs directory
        try:
            target_path.resolve().relative_to(outputs_path.resolve())
        except ValueError:
            raise ValueError("Path traversal not allowed")

        if not target_path.is_file():
            raise ValueError(f"Not a file: {path}")

        return target_path.read_bytes()
