"""Filesystem-based sandbox manager for local/dev environments.

LocalSandboxManager manages sandboxes as directories on the local filesystem.
Suitable for development, testing, and single-node deployments.

IMPORTANT: This manager does NOT interface with the database directly.
All database operations should be handled by the caller (SessionManager, Celery tasks, etc.).
"""

import mimetypes
import re
import subprocess
import threading
from collections.abc import Generator
from pathlib import Path
from uuid import UUID

from onyx.db.enums import SandboxStatus
from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.build.configs import DEMO_DATA_PATH
from onyx.server.features.build.configs import OPENCODE_DISABLED_TOOLS
from onyx.server.features.build.configs import OUTPUTS_TEMPLATE_PATH
from onyx.server.features.build.configs import SANDBOX_BASE_PATH
from onyx.server.features.build.configs import VENV_TEMPLATE_PATH
from onyx.server.features.build.sandbox.base import SandboxManager
from onyx.server.features.build.sandbox.local.agent_client import ACPAgentClient
from onyx.server.features.build.sandbox.local.agent_client import ACPEvent
from onyx.server.features.build.sandbox.local.process_manager import ProcessManager
from onyx.server.features.build.sandbox.manager.directory_manager import (
    DirectoryManager,
)
from onyx.server.features.build.sandbox.manager.snapshot_manager import SnapshotManager
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

        # Track Next.js processes - keyed by (sandbox_id, session_id) tuple
        # Used for clean shutdown when sessions are deleted
        self._nextjs_processes: dict[tuple[UUID, UUID], subprocess.Popen[bytes]] = {}

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
                "  python -m onyx.server.features.build.sandbox.util.build_venv_template\n"
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
        llm_config: LLMProviderConfig,
    ) -> SandboxInfo:
        """Provision a new sandbox for a user.

        Creates user-level sandbox structure:
        1. Create sandbox directory with sessions/ subdirectory

        NOTE: This does NOT set up session-specific workspaces or start Next.js.
        Call setup_session_workspace() to create session workspaces.
        Next.js server is started per-session in setup_session_workspace().

        Args:
            sandbox_id: Unique identifier for the sandbox
            user_id: User identifier who owns this sandbox
            tenant_id: Tenant identifier for multi-tenant isolation
            llm_config: LLM provider configuration (stored for default config)

        Returns:
            SandboxInfo with the provisioned sandbox details

        Raises:
            RuntimeError: If provisioning fails
        """
        logger.info(
            f"Starting sandbox provisioning for sandbox {sandbox_id}, "
            f"user {user_id}, tenant {tenant_id}"
        )

        # Create sandbox directory structure (user-level only)
        logger.info(f"Creating sandbox directory structure for sandbox {sandbox_id}")
        sandbox_path = self._directory_manager.create_sandbox_directory(str(sandbox_id))
        logger.debug(f"Sandbox directory created at {sandbox_path}")

        logger.info(
            f"Provisioned sandbox {sandbox_id} at {sandbox_path} (no sessions yet)"
        )

        return SandboxInfo(
            sandbox_id=sandbox_id,
            directory_path=str(self._get_sandbox_path(sandbox_id)),
            status=SandboxStatus.RUNNING,
            last_heartbeat=None,
        )

    def terminate(self, sandbox_id: UUID) -> None:
        """Terminate a sandbox and clean up all resources.

        1. Stop all Next.js processes for this sandbox
        2. Stop all ACP clients for this sandbox (terminates agent subprocesses)
        3. Cleanup sandbox directory

        Args:
            sandbox_id: The sandbox ID to terminate

        Raises:
            RuntimeError: If termination fails
        """
        # Stop all Next.js processes for this sandbox (keyed by (sandbox_id, session_id))
        processes_to_stop = [
            (key, process)
            for key, process in self._nextjs_processes.items()
            if key[0] == sandbox_id
        ]
        for key, process in processes_to_stop:
            session_id = key[1]
            try:
                self._stop_nextjs_process(process, session_id)
                del self._nextjs_processes[key]
            except Exception as e:
                logger.warning(
                    f"Failed to stop Next.js for sandbox {sandbox_id}, "
                    f"session {session_id}: {e}"
                )

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

        # Cleanup directory
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
        nextjs_port: int,
        file_system_path: str | None = None,
        snapshot_path: str | None = None,
        user_name: str | None = None,
        user_role: str | None = None,
        user_work_area: str | None = None,
        user_level: str | None = None,
        use_demo_data: bool = False,
    ) -> None:
        """Set up a session workspace within an existing sandbox.

        Creates per-session directory structure with:
        1. sessions/$session_id/ directory
        2. outputs/ (from snapshot or template)
        3. .venv/ (from template)
        4. AGENTS.md
        5. .agent/skills/
        6. files/ (symlink to demo data OR user's file_system_path)
        7. opencode.json
        8. org_info/ (if demo_data is enabled, the org structure and user identity for the user's demo persona)
        9. attachments/
        10. Start Next.js dev server for this session

        Args:
            sandbox_id: The sandbox ID (must be provisioned)
            session_id: The session ID for this workspace
            llm_config: LLM provider configuration for opencode.json
            file_system_path: Path to user's knowledge/source files
            snapshot_path: Optional storage path to restore outputs from
            user_name: User's name for personalization in AGENTS.md
            user_role: User's role/title for personalization in AGENTS.md
            user_work_area: User's work area for demo persona (e.g., "engineering")
            user_level: User's level for demo persona (e.g., "ic", "manager")
            use_demo_data: If True, symlink files/ to demo data; else to user files

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
            # Setup files symlink - choose between demo data or user files
            if use_demo_data:
                # Demo mode: symlink to demo data directory
                symlink_target = Path(DEMO_DATA_PATH)
                if not symlink_target.exists():
                    logger.warning(
                        f"Demo data directory does not exist: {symlink_target}"
                    )
                logger.info(f"Setting up files symlink to demo data: {symlink_target}")
            elif file_system_path:
                # Normal mode: symlink to user's knowledge files
                symlink_target = Path(file_system_path)
                logger.debug(
                    f"Setting up files symlink to user files: {symlink_target}"
                )
            else:
                raise ValueError("No files symlink target provided")

            self._directory_manager.setup_files_symlink(session_path, symlink_target)
            logger.debug("Files symlink ready")

            # Setup org_info directory with user identity (at session root)
            if user_work_area:
                logger.debug(f"Setting up org_info for {user_work_area}/{user_level}")
                self._directory_manager.setup_org_info(
                    session_path, user_work_area, user_level
                )

            logger.debug("Setting up outputs directory from template")
            self._directory_manager.setup_outputs_directory(session_path)
            logger.debug("Outputs directory ready")

            logger.debug("Setting up skills")
            self._directory_manager.setup_skills(session_path)
            logger.debug("Skills ready")

            # Setup attachments directory
            logger.debug("Setting up attachments directory")
            self._directory_manager.setup_attachments_directory(session_path)
            logger.debug("Attachments directory ready")

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

            # Start Next.js server on pre-allocated port
            web_dir = self._directory_manager.get_web_path(
                sandbox_path, str(session_id)
            )
            logger.info(f"Starting Next.js server at {web_dir} on port {nextjs_port}")

            nextjs_process = self._process_manager.start_nextjs_server(
                web_dir, nextjs_port
            )
            # Store process for clean shutdown on session delete
            self._nextjs_processes[(sandbox_id, session_id)] = nextjs_process
            logger.info("Next.js server started successfully")

            # Setup venv and AGENTS.md
            logger.debug("Setting up virtual environment")
            self._directory_manager.setup_venv(session_path)
            logger.debug("Virtual environment ready")

            logger.debug("Setting up agent instructions (AGENTS.md)")
            self._directory_manager.setup_agent_instructions(
                sandbox_path=session_path,
                provider=llm_config.provider,
                model_name=llm_config.model_name,
                nextjs_port=nextjs_port,
                disabled_tools=OPENCODE_DISABLED_TOOLS,
                user_name=user_name,
                user_role=user_role,
                use_demo_data=use_demo_data,
                include_org_info=use_demo_data,
            )
            logger.debug("Agent instructions ready")

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
        nextjs_port: int | None = None,
    ) -> None:
        """Clean up a session workspace (on session delete).

        1. Stop Next.js dev server if running
        2. Stop ACP client for this session
        3. Remove session directory

        Does NOT terminate the sandbox - other sessions may still be using it.

        Args:
            sandbox_id: The sandbox ID
            session_id: The session ID to clean up
            nextjs_port: Optional port where Next.js server is running (fallback only)
        """
        # Stop Next.js dev server - try stored process first, then fallback to port lookup
        process_key = (sandbox_id, session_id)
        nextjs_process = self._nextjs_processes.pop(process_key, None)
        if nextjs_process is not None:
            self._stop_nextjs_process(nextjs_process, session_id)
        elif nextjs_port is not None:
            # Fallback: find by port (e.g., if server was restarted)
            self._stop_nextjs_server_on_port(nextjs_port, session_id)

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

    def _stop_nextjs_process(
        self, process: subprocess.Popen[bytes], session_id: UUID
    ) -> None:
        """Stop a Next.js dev server process gracefully.

        Args:
            process: The subprocess.Popen object for the Next.js server
            session_id: The session ID (for logging)
        """
        if process.poll() is not None:
            # Process already terminated
            logger.debug(
                f"Next.js server for session {session_id} already terminated "
                f"(exit code: {process.returncode})"
            )
            return

        try:
            logger.info(
                f"Stopping Next.js server (PID {process.pid}) for session {session_id}"
            )
            self._process_manager.terminate_process(process.pid)
            logger.debug(f"Next.js server stopped for session {session_id}")
        except Exception as e:
            logger.warning(
                f"Failed to stop Next.js server for session {session_id}: {e}"
            )

    def _stop_nextjs_server_on_port(self, port: int, session_id: UUID) -> None:
        """Stop Next.js dev server running on a specific port (fallback method).

        Finds the process listening on the port and terminates it gracefully.
        Used when the process object is not available (e.g., after backend restart).

        Args:
            port: The port number where Next.js is running
            session_id: The session ID (for logging)
        """
        # Try lsof first - it's the most reliable cross-platform way
        # Timeout to prevent hanging if system is slow or unresponsive
        LSOF_TIMEOUT_SECONDS = 5.0
        try:
            result = subprocess.run(
                ["lsof", "-ti", f":{port}"],
                capture_output=True,
                text=True,
                timeout=LSOF_TIMEOUT_SECONDS,
            )
            if result.returncode == 0 and result.stdout.strip():
                # lsof can return multiple PIDs - stop all processes on this port
                pids = [
                    int(pid.strip())
                    for pid in result.stdout.strip().split("\n")
                    if pid.strip()
                ]
                if pids:
                    logger.info(
                        f"Found {len(pids)} process(es) on port {port} for session {session_id}, "
                        f"stopping all"
                    )
                    for pid in pids:
                        try:
                            logger.debug(
                                f"Stopping Next.js server (PID {pid}) on port {port} "
                                f"for session {session_id}"
                            )
                            self._process_manager.terminate_process(pid)
                        except Exception as e:
                            logger.warning(
                                f"Failed to stop process {pid} on port {port}: {e}"
                            )
                    return
            else:
                logger.debug(
                    f"No process found on port {port} for session {session_id}"
                )
        except subprocess.TimeoutExpired:
            logger.warning(
                f"lsof timed out after {LSOF_TIMEOUT_SECONDS}s while looking for "
                f"process on port {port} for session {session_id}"
            )
        except FileNotFoundError:
            # lsof not available, try psutil
            try:
                import psutil

                # Use net_connections to find process by port
                # Collect all PIDs on this port (handle multiple processes)
                pids_to_stop = set()
                for conn in psutil.net_connections(kind="inet"):
                    # laddr can be empty tuple for some connection states
                    # Check if it's a tuple with at least 2 elements (host, port)
                    if (
                        conn.laddr
                        and isinstance(conn.laddr, tuple)
                        and len(conn.laddr) >= 2
                        and conn.pid
                    ):
                        if conn.laddr[1] == port:
                            pids_to_stop.add(conn.pid)

                if pids_to_stop:
                    logger.info(
                        f"Found {len(pids_to_stop)} process(es) on port {port} for session {session_id}, "
                        f"stopping all"
                    )
                    for pid in pids_to_stop:
                        try:
                            logger.debug(
                                f"Stopping Next.js server (PID {pid}) on port {port} "
                                f"for session {session_id}"
                            )
                            self._process_manager.terminate_process(pid)
                        except Exception as e:
                            logger.warning(
                                f"Failed to stop process {pid} on port {port}: {e}"
                            )
                    return

                logger.debug(
                    f"No process found on port {port} for session {session_id}"
                )
            except ImportError:
                logger.warning(
                    f"Neither lsof nor psutil available to find process on port {port}"
                )
            except Exception as e:
                logger.warning(f"Failed to find process on port {port}: {e}")
        except Exception as e:
            logger.warning(
                f"Failed to stop Next.js server on port {port} for session {session_id}: {e}"
            )

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

    def session_workspace_exists(
        self,
        sandbox_id: UUID,
        session_id: UUID,
    ) -> bool:
        """Check if a session's workspace directory exists.

        Args:
            sandbox_id: The sandbox ID
            session_id: The session ID to check

        Returns:
            True if the session workspace exists, False otherwise
        """
        session_path = self._get_session_path(sandbox_id, session_id)
        outputs_path = session_path / "outputs"
        return outputs_path.exists()

    def restore_snapshot(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        snapshot_storage_path: str,
        tenant_id: str,
        nextjs_port: int,
    ) -> None:
        """Restore a snapshot into a session's workspace directory and start NextJS.

        Args:
            sandbox_id: The sandbox ID
            session_id: The session ID to restore
            snapshot_storage_path: Path to the snapshot in storage
            tenant_id: Tenant identifier for storage access
            nextjs_port: Port number for the NextJS dev server

        Raises:
            RuntimeError: If snapshot restoration fails
            FileNotFoundError: If snapshot does not exist
        """
        session_path = self._get_session_path(sandbox_id, session_id)

        # Ensure session directory exists
        session_path.mkdir(parents=True, exist_ok=True)

        # Use SnapshotManager to restore
        self._snapshot_manager.restore_snapshot(
            storage_path=snapshot_storage_path,
            target_path=session_path,
        )

        logger.info(f"Restored snapshot for session {session_id}")

        # Start NextJS dev server
        web_dir = session_path / "outputs" / "web"
        if web_dir.exists():
            logger.info(f"Starting Next.js server at {web_dir} on port {nextjs_port}")
            nextjs_process = self._process_manager.start_nextjs_server(
                web_dir, nextjs_port
            )
            # Store process for clean shutdown on session delete
            self._nextjs_processes[(sandbox_id, session_id)] = nextjs_process
            logger.info(
                f"Started NextJS server for session {session_id} on port {nextjs_port}"
            )
        else:
            logger.warning(
                f"Web directory not found at {web_dir}, skipping NextJS startup"
            )

    def health_check(self, sandbox_id: UUID, timeout: float = 60.0) -> bool:
        """Check if the sandbox is healthy (folder exists).

        Args:
            sandbox_id: The sandbox ID to check
            timeout: Health check timeout in seconds

        Returns:
            True if sandbox is healthy, False otherwise
        """
        # assume healthy if no port is specified
        sandbox_path = self._get_sandbox_path(sandbox_id)
        if not sandbox_path.exists():
            return False
        return True

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

    def _sanitize_path(self, path: str) -> str:
        """Sanitize a user-provided path to prevent path traversal attacks.

        Removes '..' components and normalizes the path to prevent attacks like
        'files/../../../../etc/passwd'.

        Args:
            path: User-provided relative path

        Returns:
            Sanitized path string with '..' components removed
        """
        # Parse the path and filter out '..' components
        path_obj = Path(path.lstrip("/"))
        clean_parts = [p for p in path_obj.parts if p != ".."]
        return str(Path(*clean_parts)) if clean_parts else "."

    def _is_path_allowed(self, session_path: Path, target_path: Path) -> bool:
        """Check if target_path is allowed for access.

        Allows paths within session_path OR within the files/ symlink.
        The files/ symlink intentionally points outside session_path to
        provide access to knowledge files.

        Args:
            session_path: The session's root directory
            target_path: The path being accessed

        Returns:
            True if access is allowed, False otherwise
        """
        files_symlink = session_path / "files"

        # Check if path is within the files/ symlink (or is the symlink itself)
        if files_symlink.is_symlink():
            try:
                # Use lexical check (without resolving symlinks)
                # This handles both the symlink itself (returns '.') and paths within it
                target_path.relative_to(files_symlink)
                return True
            except ValueError:
                pass

        # Standard check: path must be within session directory
        try:
            target_path.resolve().relative_to(session_path.resolve())
            return True
        except ValueError:
            return False

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
        # Security: sanitize path to remove path traversal attempts
        clean_path = self._sanitize_path(path)
        target_path = session_path / clean_path

        # Security check
        if not self._is_path_allowed(session_path, target_path):
            raise ValueError("Path traversal not allowed")

        if not target_path.is_dir():
            raise ValueError(f"Not a directory: {path}")

        entries = []
        for item in target_path.iterdir():
            stat = item.stat()
            is_file = item.is_file()
            mime_type = mimetypes.guess_type(str(item))[0] if is_file else None
            entries.append(
                FilesystemEntry(
                    name=item.name,
                    path=str(item.relative_to(session_path)),
                    is_directory=item.is_dir(),
                    size=stat.st_size if is_file else None,
                    mime_type=mime_type,
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
        # Security: sanitize path to remove path traversal attempts
        clean_path = self._sanitize_path(path)
        target_path = session_path / clean_path

        # Security check
        if not self._is_path_allowed(session_path, target_path):
            raise ValueError("Path traversal not allowed")

        if not target_path.is_file():
            raise ValueError(f"Not a file: {path}")

        return target_path.read_bytes()

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
        session_path = self._get_session_path(sandbox_id, session_id)
        attachments_dir = session_path / "attachments"
        attachments_dir.mkdir(parents=True, exist_ok=True)

        # Handle filename collisions by appending a number
        target_path = attachments_dir / filename
        if target_path.exists():
            stem = target_path.stem
            suffix = target_path.suffix
            counter = 1
            while target_path.exists():
                target_path = attachments_dir / f"{stem}_{counter}{suffix}"
                counter += 1
            filename = target_path.name

        target_path.write_bytes(content)
        target_path.chmod(0o644)

        logger.info(
            f"Uploaded file to session {session_id}: attachments/{filename} "
            f"({len(content)} bytes)"
        )

        return f"attachments/{filename}"

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
            ValueError: If path traversal attempted or trying to delete a directory
        """
        session_path = self._get_session_path(sandbox_id, session_id)

        # Security: robust path sanitization (consistent with K8s implementation)
        # Reject paths with traversal patterns, URL-encoded characters, or null bytes
        if re.search(r"\.\.", path) or "%" in path or "\x00" in path:
            raise ValueError("Invalid path: potential path traversal detected")

        # Reject paths with shell metacharacters (consistency with K8s implementation)
        if re.search(r'[;&|`$(){}[\]<>\'"\n\r\\]', path):
            raise ValueError("Invalid path: contains disallowed characters")

        clean_path = path.lstrip("/")

        # Verify path only contains safe characters
        if not re.match(r"^[a-zA-Z0-9_\-./]+$", clean_path):
            raise ValueError("Invalid path: contains disallowed characters")

        file_path = session_path / clean_path

        # Verify path stays within session (defense in depth)
        try:
            file_path.resolve().relative_to(session_path.resolve())
        except ValueError:
            raise ValueError("Path traversal not allowed")

        if not file_path.exists():
            logger.debug(f"File not found for deletion in session {session_id}: {path}")
            return False

        if file_path.is_dir():
            raise ValueError("Cannot delete directory")

        file_path.unlink()
        logger.info(f"Deleted file from session {session_id}: {path}")

        return True

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
        session_path = self._get_session_path(sandbox_id, session_id)
        attachments_path = session_path / "attachments"

        if not attachments_path.exists():
            return 0, 0

        file_count = 0
        total_size = 0
        for item in attachments_path.iterdir():
            if item.is_file():
                file_count += 1
                total_size += item.stat().st_size

        return file_count, total_size

    def get_webapp_url(self, sandbox_id: UUID, port: int) -> str:
        """Get the webapp URL for a session's Next.js server.

        For local backend, returns localhost URL with port.

        Args:
            sandbox_id: The sandbox ID (not used in local backend)
            port: The session's allocated Next.js port

        Returns:
            URL to access the webapp (e.g., http://localhost:3015)
        """
        return f"http://localhost:{port}"

    def sync_files(
        self,
        sandbox_id: UUID,
        user_id: UUID,
        tenant_id: str,
    ) -> bool:
        """No-op for local mode - files are directly accessible via symlink.

        In local mode, the sandbox's files/ directory is a symlink to the
        local persistent document storage, so no sync is needed.

        Args:
            sandbox_id: The sandbox UUID (unused)
            user_id: The user ID (unused)
            tenant_id: The tenant ID (unused)

        Returns:
            True (always succeeds since no sync is needed)
        """
        logger.debug(f"sync_files called for local sandbox {sandbox_id} - no-op")
        return True
