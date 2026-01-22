"""Public interface for sandbox operations.

SandboxManager is the abstract interface for sandbox lifecycle management.
LocalSandboxManager is the filesystem-based implementation for local/dev environments.

Use get_sandbox_manager() to get the appropriate implementation based on SANDBOX_BACKEND.
"""

import subprocess
import threading
from abc import ABC
from abc import abstractmethod
from collections.abc import Generator
from datetime import datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.db.enums import SandboxStatus
from onyx.db.llm import fetch_default_provider
from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.build.configs import OPENCODE_DISABLED_TOOLS
from onyx.server.features.build.configs import OUTPUTS_TEMPLATE_PATH
from onyx.server.features.build.configs import SANDBOX_BACKEND
from onyx.server.features.build.configs import SANDBOX_BASE_PATH
from onyx.server.features.build.configs import SANDBOX_MAX_CONCURRENT_PER_ORG
from onyx.server.features.build.configs import SandboxBackend
from onyx.server.features.build.configs import VENV_TEMPLATE_PATH
from onyx.server.features.build.db.sandbox import allocate_nextjs_port
from onyx.server.features.build.db.sandbox import (
    create_sandbox__no_commit as db_create_sandbox,
)
from onyx.server.features.build.db.sandbox import create_snapshot as db_create_snapshot
from onyx.server.features.build.db.sandbox import get_latest_snapshot_for_session
from onyx.server.features.build.db.sandbox import get_running_sandbox_count_by_tenant
from onyx.server.features.build.db.sandbox import get_sandbox_by_id
from onyx.server.features.build.db.sandbox import update_sandbox_heartbeat
from onyx.server.features.build.db.sandbox import update_sandbox_status__no_commit
from onyx.server.features.build.sandbox.internal.agent_client import ACPAgentClient
from onyx.server.features.build.sandbox.internal.agent_client import ACPEvent
from onyx.server.features.build.sandbox.internal.directory_manager import (
    DirectoryManager,
)
from onyx.server.features.build.sandbox.internal.process_manager import ProcessManager
from onyx.server.features.build.sandbox.internal.snapshot_manager import SnapshotManager
from onyx.server.features.build.sandbox.models import FilesystemEntry
from onyx.server.features.build.sandbox.models import SandboxInfo
from onyx.server.features.build.sandbox.models import SnapshotInfo
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()


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


class LocalSandboxManager(SandboxManager):
    """Filesystem-based sandbox manager for local/dev environments.

    Manages sandboxes as directories on the local filesystem.
    Suitable for development, testing, and single-node deployments.

    Key characteristics:
    - Sandboxes are directories under SANDBOX_BASE_PATH
    - No container isolation (process-level only)
    - Snapshots disabled by default (SANDBOX_BACKEND=local)
    - No automatic cleanup of idle sandboxes

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
        build_dir = Path(
            __file__
        ).parent.parent.resolve()  # /onyx/server/features/build/
        skills_path = (build_dir / "skills").resolve()
        agent_instructions_template_path = (build_dir / "AGENTS.template.md").resolve()

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
        self._acp_clients: dict[str, ACPAgentClient] = (
            {}
        )  # sandbox_id -> ACPAgentClient

        # Track Next.js processes to prevent garbage collection
        self._nextjs_processes: dict[str, subprocess.Popen[bytes]] = (
            {}
        )  # session_id -> Popen

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

    def _get_sandbox_path(self, session_id: str | UUID) -> Path:
        """Get the filesystem path for a sandbox based on session_id.

        Args:
            session_id: The session ID (can be string or UUID)

        Returns:
            Path to the sandbox directory
        """
        return Path(SANDBOX_BASE_PATH) / str(session_id)

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

        1. Check concurrent sandbox limit for tenant
        2. Create sandbox directory structure
        3. Setup files symlink, outputs, venv, AGENTS.md, and skills
        4. If snapshot_id provided and kubernetes backend, restore outputs from snapshot
        5. Start Next.js dev server
        6. Store sandbox record in DB
        7. Return sandbox info (agent not started until first message)
        """
        logger.info(
            f"Starting sandbox provisioning for session {session_id}, "
            f"tenant {tenant_id}"
        )

        session_uuid = UUID(session_id)

        # Check limit (only enforce on cloud deployments)
        if MULTI_TENANT:
            logger.debug(f"Checking concurrent sandbox limit for tenant {tenant_id}")
            running_count = get_running_sandbox_count_by_tenant(db_session, tenant_id)
            logger.debug(
                f"Current running sandboxes: {running_count}, "
                f"max: {SANDBOX_MAX_CONCURRENT_PER_ORG}"
            )
            if running_count >= SANDBOX_MAX_CONCURRENT_PER_ORG:
                raise ValueError(
                    f"Maximum concurrent sandboxes ({SANDBOX_MAX_CONCURRENT_PER_ORG}) "
                    f"reached for tenant"
                )
        else:
            logger.debug(
                f"Skipping sandbox limit check for tenant {tenant_id} "
                "(self-hosted deployment)"
            )

        # Create directory structure
        logger.info(f"Creating sandbox directory structure for session {session_id}")
        sandbox_path = self._directory_manager.create_sandbox_directory(session_id)
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
            if snapshot_id and SANDBOX_BACKEND == SandboxBackend.KUBERNETES:
                logger.debug(f"Restoring from snapshot {snapshot_id}")
                snapshot = get_latest_snapshot_for_session(db_session, session_uuid)
                if snapshot:
                    self._snapshot_manager.restore_snapshot(
                        snapshot.storage_path, sandbox_path
                    )
                    logger.debug("Snapshot restored")
                else:
                    logger.warning(f"Snapshot {snapshot_id} not found, using template")
                    self._directory_manager.setup_outputs_directory(sandbox_path)
            else:
                if snapshot_id and SANDBOX_BACKEND == SandboxBackend.LOCAL:
                    logger.debug(
                        f"Ignoring snapshot {snapshot_id} (local backend - "
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
            logger.debug("Fetching default LLM provider")
            llm_provider = fetch_default_provider(db_session)
            if not llm_provider:
                logger.error("No default LLM provider configured")
                raise RuntimeError(
                    "No default LLM provider configured. "
                    "Please configure an LLM provider in admin settings."
                )
            logger.debug(
                f"Setting up opencode config with provider: {llm_provider.provider}, "
                f"model: {llm_provider.default_model_name}"
            )
            self._directory_manager.setup_opencode_config(
                sandbox_path=sandbox_path,
                provider=llm_provider.provider,
                model_name=llm_provider.default_model_name,
                api_key=llm_provider.api_key,
                api_base=llm_provider.api_base,
                disabled_tools=OPENCODE_DISABLED_TOOLS,
            )
            logger.debug("Opencode config ready")

            # Allocate Next.js port and start server
            nextjs_port = allocate_nextjs_port(db_session)
            web_dir = self._directory_manager.get_web_path(sandbox_path)
            logger.info(f"Starting Next.js server at {web_dir} on port {nextjs_port}")

            nextjs_process = self._process_manager.start_nextjs_server(
                web_dir, nextjs_port
            )
            logger.info("Next.js server started successfully")
            # Store process reference to prevent garbage collection
            self._nextjs_processes[session_id] = nextjs_process

            # Create DB record (uses flush, caller commits)
            logger.debug("Creating sandbox database record")
            sandbox = db_create_sandbox(
                db_session=db_session,
                session_id=session_uuid,
                nextjs_port=nextjs_port,
            )

            update_sandbox_status__no_commit(
                db_session, sandbox.id, SandboxStatus.RUNNING
            )
            logger.debug(f"Sandbox record created with ID {sandbox.id}")

            logger.info(
                f"Provisioned sandbox {sandbox.id} for session {session_id} "
                f"at {sandbox_path}, Next.js on port {nextjs_port}"
            )

            return SandboxInfo(
                id=str(sandbox.id),
                session_id=session_id,
                directory_path=str(self._get_sandbox_path(session_id)),
                status=SandboxStatus.RUNNING,
                created_at=sandbox.created_at,
                last_heartbeat=None,
            )

        except Exception as e:
            # Cleanup on failure
            logger.error(
                f"Sandbox provisioning failed for session {session_id}: {e}",
                exc_info=True,
            )
            logger.info(f"Cleaning up sandbox directory at {sandbox_path}")
            self._directory_manager.cleanup_sandbox_directory(sandbox_path)
            raise

    def terminate(self, sandbox_id: str, db_session: Session) -> None:
        """Terminate a sandbox.

        NOTE: This method uses flush() instead of commit(). The caller is
        responsible for committing the transaction when ready.

        1. Stop ACP client (terminates agent subprocess)
        2. Cleanup sandbox directory (this will handle Next.js process cleanup)
        3. Update DB status to TERMINATED

        Raises:
            ValueError: If sandbox not found
            RuntimeError: If termination fails
        """
        sandbox = get_sandbox_by_id(db_session, UUID(sandbox_id))
        if not sandbox:
            raise ValueError(f"Sandbox {sandbox_id} not found for termination")

        # Stop ACP client (this terminates the opencode subprocess)
        client = self._acp_clients.pop(sandbox_id, None)
        if client:
            try:
                client.stop()
            except Exception as e:
                raise RuntimeError(
                    f"Failed to stop ACP client for sandbox {sandbox_id}: {e}"
                ) from e

        # Clean up Next.js process
        nextjs_proc = self._nextjs_processes.pop(str(sandbox.session_id), None)
        if nextjs_proc:
            self._process_manager.terminate_process(nextjs_proc.pid)

        # Cleanup directory
        sandbox_path = self._get_sandbox_path(sandbox.session_id)
        try:
            self._directory_manager.cleanup_sandbox_directory(sandbox_path)
        except Exception as e:
            raise RuntimeError(
                f"Failed to cleanup sandbox directory {sandbox_path}: {e}"
            ) from e

        # Update status (uses flush, caller commits)
        update_sandbox_status__no_commit(
            db_session, UUID(sandbox_id), SandboxStatus.TERMINATED
        )

        logger.info(f"Terminated sandbox {sandbox_id}")

    def create_snapshot(
        self, sandbox_id: str, db_session: Session
    ) -> SnapshotInfo | None:
        """Create a snapshot of the sandbox's outputs directory.

        Returns None if snapshots are disabled (local backend).
        """
        # Snapshots are disabled for local backend
        if SANDBOX_BACKEND == SandboxBackend.LOCAL:
            logger.debug(
                f"Skipping snapshot creation for sandbox {sandbox_id} "
                "(local backend - snapshots disabled)"
            )
            return None

        sandbox = get_sandbox_by_id(db_session, UUID(sandbox_id))
        if not sandbox:
            raise ValueError(f"Sandbox {sandbox_id} not found")

        sandbox_path = self._get_sandbox_path(sandbox.session_id)
        tenant_id = get_current_tenant_id()
        snapshot_id, storage_path, size_bytes = self._snapshot_manager.create_snapshot(
            sandbox_path,
            str(sandbox.session_id),
            tenant_id,
        )

        snapshot = db_create_snapshot(
            db_session=db_session,
            session_id=sandbox.session_id,
            storage_path=storage_path,
            size_bytes=size_bytes,
        )

        logger.info(
            f"Created snapshot {snapshot.id} for sandbox {sandbox_id}, "
            f"size: {size_bytes} bytes"
        )

        return SnapshotInfo(
            id=str(snapshot.id),
            session_id=str(sandbox.session_id),
            storage_path=storage_path,
            created_at=snapshot.created_at,
            size_bytes=size_bytes,
        )

    def health_check(self, sandbox_id: str, db_session: Session) -> bool:
        """Check if the sandbox is healthy (Next.js server running)."""
        sandbox = get_sandbox_by_id(db_session, UUID(sandbox_id))
        if not sandbox:
            return False

        # Cannot check health if port is not known
        if sandbox.nextjs_port is None:
            return False

        # Check Next.js server is responsive on the sandbox's allocated port
        server_url = f"http://localhost:{sandbox.nextjs_port}"
        if self._process_manager._wait_for_server(server_url, timeout=5.0):
            update_sandbox_heartbeat(db_session, UUID(sandbox_id))
            return True

        return False

    def send_message(
        self,
        sandbox_id: str,
        message: str,
        db_session: Session,
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
        """
        sandbox = get_sandbox_by_id(db_session, UUID(sandbox_id))
        if not sandbox:
            raise ValueError(f"Sandbox {sandbox_id} not found")

        # Get or create ACP client for this sandbox
        client = self._acp_clients.get(sandbox_id)
        if client is None or not client.is_running or client.session_id is None:
            sandbox_path = self._get_sandbox_path(sandbox.session_id)

            # Create and start ACP client
            client = ACPAgentClient(cwd=str(sandbox_path))
            self._acp_clients[sandbox_id] = client

            # Verify session was created
            if client.session_id is None:
                raise RuntimeError(
                    f"Failed to create agent session for sandbox {sandbox_id}"
                )

        # Validate message is not empty
        if not message or not message.strip():
            raise ValueError("Message cannot be empty")

        # Update heartbeat on message send
        update_sandbox_heartbeat(db_session, UUID(sandbox_id))

        for event in client.send_message(message):
            yield event
            # Update heartbeat on activity
            update_sandbox_heartbeat(db_session, UUID(sandbox_id))

    def list_directory(
        self, sandbox_id: str, path: str, db_session: Session
    ) -> list[FilesystemEntry]:
        """List contents of a directory in the sandbox's outputs directory."""
        sandbox = get_sandbox_by_id(db_session, UUID(sandbox_id))
        if not sandbox:
            raise ValueError(f"Sandbox {sandbox_id} not found")

        sandbox_path = self._get_sandbox_path(sandbox.session_id)
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

    def read_file(self, sandbox_id: str, path: str, db_session: Session) -> bytes:
        """Read a file from the sandbox's outputs directory."""
        sandbox = get_sandbox_by_id(db_session, UUID(sandbox_id))
        if not sandbox:
            raise ValueError(f"Sandbox {sandbox_id} not found")

        sandbox_path = self._get_sandbox_path(sandbox.session_id)
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

    def get_sandbox_info(
        self, sandbox_id: str, db_session: Session
    ) -> SandboxInfo | None:
        """Get information about a sandbox."""
        sandbox = get_sandbox_by_id(db_session, UUID(sandbox_id))
        if not sandbox:
            return None

        return SandboxInfo(
            id=str(sandbox.id),
            session_id=str(sandbox.session_id),
            directory_path=str(self._get_sandbox_path(sandbox.session_id)),
            status=sandbox.status,
            created_at=sandbox.created_at,
            last_heartbeat=sandbox.last_heartbeat,
        )

    def cancel_agent(self, sandbox_id: str) -> None:
        """Cancel the current agent operation."""
        client = self._acp_clients.get(sandbox_id)
        if client:
            client.cancel()


# Singleton instance cache for the factory
_sandbox_manager_instance: SandboxManager | None = None
_sandbox_manager_lock = threading.Lock()


def get_sandbox_manager() -> SandboxManager:
    """Get the appropriate SandboxManager implementation based on SANDBOX_BACKEND.

    Returns:
        SandboxManager instance (LocalSandboxManager for local backend,
        future implementations for kubernetes backend)

    Note:
        Currently only LocalSandboxManager is implemented. When kubernetes
        backend is needed, add KubernetesSandboxManager and update this factory.
    """
    global _sandbox_manager_instance

    if _sandbox_manager_instance is None:
        with _sandbox_manager_lock:
            if _sandbox_manager_instance is None:
                if SANDBOX_BACKEND == SandboxBackend.LOCAL:
                    _sandbox_manager_instance = LocalSandboxManager()
                elif SANDBOX_BACKEND == SandboxBackend.KUBERNETES:
                    # For now, use LocalSandboxManager for kubernetes too
                    # TODO: Implement KubernetesSandboxManager when needed
                    logger.warning(
                        "Kubernetes sandbox backend not yet implemented, "
                        "falling back to LocalSandboxManager"
                    )
                    _sandbox_manager_instance = LocalSandboxManager()
                else:
                    raise ValueError(f"Unknown sandbox backend: {SANDBOX_BACKEND}")

    return _sandbox_manager_instance
