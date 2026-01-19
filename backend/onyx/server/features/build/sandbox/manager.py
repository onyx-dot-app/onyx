"""Public interface for sandbox operations.

SandboxManager is the main entry point for sandbox lifecycle management.
It orchestrates internal managers for directory, process, snapshot, and agent communication.
"""

import subprocess
import threading
from collections.abc import Generator
from datetime import datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.db.enums import SandboxStatus
from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.build.configs import OUTPUTS_TEMPLATE_PATH
from onyx.server.features.build.configs import SANDBOX_BASE_PATH
from onyx.server.features.build.configs import SANDBOX_MAX_CONCURRENT_PER_ORG
from onyx.server.features.build.configs import SANDBOX_NEXTJS_PORT_END
from onyx.server.features.build.configs import SANDBOX_NEXTJS_PORT_START
from onyx.server.features.build.configs import VENV_TEMPLATE_PATH
from onyx.server.features.build.db.sandbox import create_sandbox as db_create_sandbox
from onyx.server.features.build.db.sandbox import create_snapshot as db_create_snapshot
from onyx.server.features.build.db.sandbox import get_latest_snapshot_for_session
from onyx.server.features.build.db.sandbox import get_running_sandbox_count_by_tenant
from onyx.server.features.build.db.sandbox import get_sandbox_by_id
from onyx.server.features.build.db.sandbox import update_sandbox_agent_pid
from onyx.server.features.build.db.sandbox import update_sandbox_heartbeat
from onyx.server.features.build.db.sandbox import update_sandbox_nextjs
from onyx.server.features.build.db.sandbox import update_sandbox_status
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

logger = setup_logger()


class SandboxManager:
    """Public interface for sandbox operations.

    Orchestrates internal managers for directory lifecycle, processes,
    snapshots, and agent communication.

    This is a singleton class - use SandboxManager() to get the instance.
    """

    _instance: "SandboxManager | None" = None
    _lock = threading.Lock()

    def __new__(cls) -> "SandboxManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialize()
        return cls._instance

    def _initialize(self) -> None:
        """Initialize managers."""
        # Paths for templates
        build_dir = Path(__file__).parent.parent  # /onyx/server/features/build/
        skills_path = build_dir / "skills"
        agent_instructions_template_path = build_dir / "AGENT.template.md"

        self._directory_manager = DirectoryManager(
            base_path=Path(SANDBOX_BASE_PATH),
            outputs_template_path=Path(OUTPUTS_TEMPLATE_PATH),
            venv_template_path=Path(VENV_TEMPLATE_PATH),
            skills_path=skills_path,
            agent_instructions_template_path=agent_instructions_template_path,
        )
        self._process_manager = ProcessManager()
        self._snapshot_manager = SnapshotManager(get_default_file_store())

        # Track ACP clients and Next.js processes in memory
        self._acp_clients: dict[str, ACPAgentClient] = (
            {}
        )  # sandbox_id -> ACPAgentClient
        self._nextjs_processes: dict[str, subprocess.Popen[bytes]] = {}

        # Port allocation tracking
        self._allocated_ports: set[int] = set()
        self._port_lock = threading.Lock()

    def _allocate_port(self) -> int:
        """Allocate an available port for Next.js server."""
        with self._port_lock:
            for port in range(SANDBOX_NEXTJS_PORT_START, SANDBOX_NEXTJS_PORT_END):
                if port not in self._allocated_ports:
                    self._allocated_ports.add(port)
                    return port

            raise RuntimeError("No available ports for Next.js server")

    def _release_port(self, port: int) -> None:
        """Release an allocated port."""
        with self._port_lock:
            self._allocated_ports.discard(port)

    def provision(
        self,
        session_id: str,
        tenant_id: str,
        file_system_path: str,
        db_session: Session,
        snapshot_id: str | None = None,
    ) -> SandboxInfo:
        """Provision a new sandbox for a session.

        1. Check concurrent sandbox limit for tenant
        2. Create sandbox directory structure
        3. Setup files symlink, outputs, venv, AGENT.md, and skills
        4. If snapshot_id provided, restore outputs from snapshot
        5. Start Next.js dev server
        6. Store sandbox record in DB
        7. Return sandbox info (agent not started until first message)

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
        session_uuid = UUID(session_id)

        # Check limit
        running_count = get_running_sandbox_count_by_tenant(db_session, tenant_id)
        if running_count >= SANDBOX_MAX_CONCURRENT_PER_ORG:
            raise ValueError(
                f"Maximum concurrent sandboxes ({SANDBOX_MAX_CONCURRENT_PER_ORG}) "
                f"reached for tenant"
            )

        # Create directory structure
        sandbox_path = self._directory_manager.create_sandbox_directory(session_id)

        try:
            # Setup files symlink
            self._directory_manager.setup_files_symlink(
                sandbox_path, Path(file_system_path)
            )

            # Setup outputs (from snapshot or template)
            if snapshot_id:
                snapshot = get_latest_snapshot_for_session(db_session, session_uuid)
                if snapshot:
                    self._snapshot_manager.restore_snapshot(
                        snapshot.storage_path, sandbox_path
                    )
                else:
                    self._directory_manager.setup_outputs_directory(sandbox_path)
            else:
                self._directory_manager.setup_outputs_directory(sandbox_path)

            # Setup venv, AGENT.md, and skills
            self._directory_manager.setup_venv(sandbox_path)
            self._directory_manager.setup_agent_instructions(sandbox_path)
            self._directory_manager.setup_skills(sandbox_path)

            # Allocate port and start Next.js server
            nextjs_port = self._allocate_port()
            web_dir = self._directory_manager.get_web_path(sandbox_path)

            try:
                nextjs_process = self._process_manager.start_nextjs_server(
                    web_dir, nextjs_port
                )
            except RuntimeError:
                self._release_port(nextjs_port)
                raise

            # Create DB record
            sandbox = db_create_sandbox(
                db_session=db_session,
                session_id=session_uuid,
                tenant_id=tenant_id,
                directory_path=str(sandbox_path),
            )

            # Update with Next.js info
            update_sandbox_nextjs(
                db_session, sandbox.id, nextjs_process.pid, nextjs_port
            )
            update_sandbox_status(db_session, sandbox.id, SandboxStatus.RUNNING)

            # Track process
            self._nextjs_processes[str(sandbox.id)] = nextjs_process

            logger.info(
                f"Provisioned sandbox {sandbox.id} for session {session_id} "
                f"at {sandbox_path}, Next.js on port {nextjs_port}"
            )

            return SandboxInfo(
                id=str(sandbox.id),
                session_id=session_id,
                directory_path=str(sandbox_path),
                agent_pid=None,
                nextjs_pid=nextjs_process.pid,
                nextjs_port=nextjs_port,
                status=SandboxStatus.RUNNING,
                created_at=sandbox.created_at,
                last_heartbeat=None,
            )

        except Exception:
            # Cleanup on failure
            self._directory_manager.cleanup_sandbox_directory(sandbox_path)
            raise

    def terminate(self, sandbox_id: str, db_session: Session) -> None:
        """Terminate a sandbox.

        1. Stop ACP client (terminates agent subprocess)
        2. Terminate Next.js server
        3. Release allocated port
        4. Cleanup sandbox directory
        5. Update DB status to TERMINATED

        Args:
            sandbox_id: The sandbox ID to terminate
            db_session: Database session
        """
        sandbox = get_sandbox_by_id(db_session, UUID(sandbox_id))
        if not sandbox:
            logger.warning(f"Sandbox {sandbox_id} not found for termination")
            return

        # Stop ACP client (this terminates the opencode subprocess)
        client = self._acp_clients.pop(sandbox_id, None)
        if client:
            try:
                client.stop()
            except Exception as e:
                logger.warning(
                    f"Error stopping ACP client for sandbox {sandbox_id}: {e}"
                )

        # Terminate Next.js server
        if sandbox.nextjs_pid:
            self._process_manager.terminate_process(sandbox.nextjs_pid)
        self._nextjs_processes.pop(sandbox_id, None)

        # Release port
        if sandbox.nextjs_port:
            self._release_port(sandbox.nextjs_port)

        # Cleanup directory
        self._directory_manager.cleanup_sandbox_directory(Path(sandbox.directory_path))

        # Update status
        update_sandbox_status(db_session, UUID(sandbox_id), SandboxStatus.TERMINATED)

        logger.info(f"Terminated sandbox {sandbox_id}")

    def create_snapshot(self, sandbox_id: str, db_session: Session) -> SnapshotInfo:
        """Create a snapshot of the sandbox's outputs directory.

        Args:
            sandbox_id: The sandbox ID to snapshot
            db_session: Database session

        Returns:
            SnapshotInfo with the created snapshot details

        Raises:
            ValueError: If sandbox not found
            RuntimeError: If snapshot creation fails
        """
        sandbox = get_sandbox_by_id(db_session, UUID(sandbox_id))
        if not sandbox:
            raise ValueError(f"Sandbox {sandbox_id} not found")

        snapshot_id, storage_path, size_bytes = self._snapshot_manager.create_snapshot(
            Path(sandbox.directory_path),
            str(sandbox.session_id),
            sandbox.tenant_id,
        )

        snapshot = db_create_snapshot(
            db_session=db_session,
            session_id=sandbox.session_id,
            tenant_id=sandbox.tenant_id,
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
        """Check if the sandbox is healthy (Next.js server running).

        Args:
            sandbox_id: The sandbox ID to check
            db_session: Database session

        Returns:
            True if sandbox is healthy, False otherwise
        """
        sandbox = get_sandbox_by_id(db_session, UUID(sandbox_id))
        if not sandbox:
            return False

        # Check Next.js server is running
        if sandbox.nextjs_pid and not self._process_manager.is_process_running(
            sandbox.nextjs_pid
        ):
            return False

        # Check agent process is running (if started)
        if sandbox.agent_pid and not self._process_manager.is_process_running(
            sandbox.agent_pid
        ):
            return False

        # Check Next.js server is responsive
        if sandbox.nextjs_port:
            if self._process_manager._wait_for_server(
                f"http://localhost:{sandbox.nextjs_port}",
                timeout=5.0,
            ):
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
        sandbox = get_sandbox_by_id(db_session, UUID(sandbox_id))
        if not sandbox:
            raise ValueError(f"Sandbox {sandbox_id} not found")

        # Get or create ACP client for this sandbox
        client = self._acp_clients.get(sandbox_id)
        if client is None or not client.is_running:
            sandbox_path = Path(sandbox.directory_path)

            # Create and start ACP client
            client = ACPAgentClient(cwd=str(sandbox_path))
            self._acp_clients[sandbox_id] = client

            # Track the agent PID (from the opencode subprocess)
            if client._process:
                update_sandbox_agent_pid(db_session, sandbox.id, client._process.pid)

        # Update heartbeat on message send
        update_sandbox_heartbeat(db_session, UUID(sandbox_id))

        for event in client.send_message(message):
            yield event
            # Update heartbeat on activity
            update_sandbox_heartbeat(db_session, UUID(sandbox_id))

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
        sandbox = get_sandbox_by_id(db_session, UUID(sandbox_id))
        if not sandbox:
            raise ValueError(f"Sandbox {sandbox_id} not found")

        outputs_path = Path(sandbox.directory_path) / "outputs"
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
        sandbox = get_sandbox_by_id(db_session, UUID(sandbox_id))
        if not sandbox:
            raise ValueError(f"Sandbox {sandbox_id} not found")

        outputs_path = Path(sandbox.directory_path) / "outputs"
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
        """Get information about a sandbox.

        Args:
            sandbox_id: The sandbox ID
            db_session: Database session

        Returns:
            SandboxInfo or None if not found
        """
        sandbox = get_sandbox_by_id(db_session, UUID(sandbox_id))
        if not sandbox:
            return None

        return SandboxInfo(
            id=str(sandbox.id),
            session_id=str(sandbox.session_id),
            directory_path=sandbox.directory_path,
            agent_pid=sandbox.agent_pid,
            nextjs_pid=sandbox.nextjs_pid,
            nextjs_port=sandbox.nextjs_port,
            status=sandbox.status,
            created_at=sandbox.created_at,
            last_heartbeat=sandbox.last_heartbeat,
        )

    def cancel_agent(self, sandbox_id: str) -> None:
        """Cancel the current agent operation.

        Args:
            sandbox_id: The sandbox ID
        """
        client = self._acp_clients.get(sandbox_id)
        if client:
            client.cancel()
