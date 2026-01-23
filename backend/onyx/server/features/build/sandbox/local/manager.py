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
from onyx.server.features.build.configs import SANDBOX_BACKEND
from onyx.server.features.build.configs import SANDBOX_BASE_PATH
from onyx.server.features.build.configs import SandboxBackend
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
    - Snapshots disabled by default (SANDBOX_BACKEND=local)
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

        # Track ACP clients in memory
        self._acp_clients: dict[UUID, ACPAgentClient] = (
            {}
        )  # sandbox_id -> ACPAgentClient

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

    def provision(
        self,
        sandbox_id: UUID,
        user_id: UUID,
        tenant_id: str,
        file_system_path: str,
        llm_config: LLMProviderConfig,
        nextjs_port: int | None = None,
        snapshot_path: str | None = None,
    ) -> SandboxInfo:
        """Provision a new sandbox for a session.

        1. Create sandbox directory structure
        2. Setup files symlink, outputs, venv, AGENTS.md, and skills
        3. If snapshot_path provided and kubernetes backend, restore outputs from snapshot
        4. Start Next.js dev server on pre-allocated port
        5. Return sandbox info (agent not started until first message)

        Args:
            sandbox_id: Unique identifier for the sandbox
            user_id: User identifier who owns this sandbox
            tenant_id: Tenant identifier for multi-tenant isolation
            file_system_path: Path to the knowledge/source files to link
            llm_config: LLM provider configuration
            nextjs_port: Pre-allocated port for Next.js server
            snapshot_path: Optional storage path to restore from

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

        # Create directory structure
        logger.info(f"Creating sandbox directory structure for sandbox {sandbox_id}")
        sandbox_path = self._directory_manager.create_sandbox_directory(str(sandbox_id))
        logger.debug(f"Sandbox directory created at {sandbox_path}")

        try:
            # Setup files symlink
            logger.debug(f"Setting up files symlink to {file_system_path}")
            self._directory_manager.setup_files_symlink(
                sandbox_path, Path(file_system_path)
            )
            logger.debug("Files symlink created")

            # Setup outputs (from snapshot or template)
            # NOTE: Snapshot restore is only supported in kubernetes backend
            if snapshot_path and SANDBOX_BACKEND == SandboxBackend.KUBERNETES:
                logger.debug(f"Restoring from snapshot {snapshot_path}")
                self._snapshot_manager.restore_snapshot(snapshot_path, sandbox_path)
                logger.debug("Snapshot restored")
            else:
                if snapshot_path and SANDBOX_BACKEND == SandboxBackend.LOCAL:
                    logger.debug(
                        f"Ignoring snapshot {snapshot_path} (local backend - "
                        "snapshots disabled)"
                    )
                logger.debug("Setting up outputs directory from template")
                self._directory_manager.setup_outputs_directory(sandbox_path)
            logger.debug("Outputs directory ready")

            # Setup venv, AGENTS.md, and skills
            logger.debug("Setting up virtual environment")
            self._directory_manager.setup_venv(sandbox_path)
            logger.debug("Virtual environment ready")

            logger.debug("Setting up agent instructions (AGENTS.md)")
            self._directory_manager.setup_agent_instructions(sandbox_path)
            logger.debug("Agent instructions ready")

            logger.debug("Setting up skills")
            self._directory_manager.setup_skills(sandbox_path)
            logger.debug("Skills ready")

            # Setup user uploads directory
            logger.debug("Setting up user uploads directory")
            self._directory_manager.setup_user_uploads_directory(sandbox_path)
            logger.debug("User uploads directory ready")

            # Setup opencode.json with LLM provider configuration
            logger.debug(
                f"Setting up opencode config with provider: {llm_config.provider}, "
                f"model: {llm_config.model_name}"
            )
            self._directory_manager.setup_opencode_config(
                sandbox_path=sandbox_path,
                provider=llm_config.provider,
                model_name=llm_config.model_name,
                api_key=llm_config.api_key,
                api_base=llm_config.api_base,
                disabled_tools=OPENCODE_DISABLED_TOOLS,
            )
            logger.debug("Opencode config ready")

            # Start Next.js server on pre-allocated port
            web_dir = self._directory_manager.get_web_path(sandbox_path)
            logger.info(f"Starting Next.js server at {web_dir} on port {nextjs_port}")

            self._process_manager.start_nextjs_server(web_dir, nextjs_port)
            logger.info("Next.js server started successfully")

            logger.info(
                f"Provisioned sandbox {sandbox_id} at {sandbox_path}, "
                f"Next.js on port {nextjs_port}"
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
        """Terminate a sandbox and clean up resources.

        1. Stop ACP client (terminates agent subprocess)
        2. Cleanup sandbox directory (this will handle Next.js process cleanup)

        Args:
            sandbox_id: The sandbox ID to terminate

        Raises:
            RuntimeError: If termination fails
        """
        # Stop ACP client (this terminates the opencode subprocess)
        client = self._acp_clients.pop(sandbox_id, None)
        if client:
            try:
                client.stop()
            except Exception as e:
                raise RuntimeError(
                    f"Failed to stop ACP client for sandbox {sandbox_id}: {e}"
                ) from e

        # Cleanup directory (this will handle Next.js process cleanup)
        sandbox_path = self._get_sandbox_path(sandbox_id)
        try:
            self._directory_manager.cleanup_sandbox_directory(sandbox_path)
        except Exception as e:
            raise RuntimeError(
                f"Failed to cleanup sandbox directory {sandbox_path}: {e}"
            ) from e

        logger.info(f"Terminated sandbox {sandbox_id}")

    def create_snapshot(
        self, sandbox_id: UUID, tenant_id: str
    ) -> SnapshotResult | None:
        """Create a snapshot of the sandbox's outputs directory.

        Returns None if snapshots are disabled (local backend).

        Args:
            sandbox_id: The sandbox ID to snapshot
            tenant_id: Tenant identifier for storage path

        Returns:
            SnapshotResult with storage path and size, or None if
            snapshots are disabled for this backend
        """
        # Snapshots are disabled for local backend
        if SANDBOX_BACKEND == SandboxBackend.LOCAL:
            logger.debug(
                f"Skipping snapshot creation for sandbox {sandbox_id} "
                "(local backend - snapshots disabled)"
            )
            return None

        sandbox_path = self._get_sandbox_path(sandbox_id)
        # SnapshotManager expects string sandbox_id
        _, storage_path, size_bytes = self._snapshot_manager.create_snapshot(
            sandbox_path,
            str(sandbox_id),
            tenant_id,
        )

        logger.info(
            f"Created snapshot for sandbox {sandbox_id}, size: {size_bytes} bytes"
        )

        return SnapshotResult(
            storage_path=storage_path,
            size_bytes=size_bytes,
        )

    def health_check(self, sandbox_id: UUID, nextjs_port: int | None = None) -> bool:
        """Check if the sandbox is healthy (Next.js server running).

        Args:
            sandbox_id: The sandbox ID to check
            nextjs_port: The Next.js port to check

        Returns:
            True if sandbox is healthy, False otherwise
        """
        # Cannot check health if port is not known
        if nextjs_port is None:
            return False

        # Check Next.js server is responsive on the sandbox's allocated port
        return self._process_manager._wait_for_server(
            f"http://localhost:{nextjs_port}",
            timeout=5.0,
        )

    def send_message(
        self,
        sandbox_id: UUID,
        message: str,
    ) -> Generator[ACPEvent, None, None]:
        """Send a message to the CLI agent and stream typed ACP events.

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
            sandbox_id: The sandbox ID to send message to
            message: The message content to send

        Yields:
            Typed ACP schema event objects
        """
        # Get or create ACP client for this sandbox
        client = self._acp_clients.get(sandbox_id)
        if client is None or not client.is_running:
            sandbox_path = self._get_sandbox_path(sandbox_id)

            # Create and start ACP client
            client = ACPAgentClient(cwd=str(sandbox_path))
            self._acp_clients[sandbox_id] = client

        for event in client.send_message(message):
            yield event

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
        sandbox_path = self._get_sandbox_path(sandbox_id)
        outputs_path = sandbox_path / "outputs"
        target_path = outputs_path / path.lstrip("/")

        # Security: ensure path is within outputs directory
        try:
            target_path.resolve().relative_to(outputs_path.resolve())
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
                    path=str(item.relative_to(outputs_path)),
                    is_directory=item.is_dir(),
                    size_bytes=stat.st_size if item.is_file() else None,
                    modified_at=datetime.fromtimestamp(stat.st_mtime),
                )
            )

        return sorted(entries, key=lambda e: (not e.is_directory, e.name.lower()))

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
        sandbox_path = self._get_sandbox_path(sandbox_id)
        outputs_path = sandbox_path / "outputs"
        target_path = outputs_path / path.lstrip("/")

        # Security: ensure path is within outputs directory
        try:
            target_path.resolve().relative_to(outputs_path.resolve())
        except ValueError:
            raise ValueError("Path traversal not allowed")

        if not target_path.is_file():
            raise ValueError(f"Not a file: {path}")

        return target_path.read_bytes()
