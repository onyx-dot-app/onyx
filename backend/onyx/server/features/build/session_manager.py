import threading
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from pathlib import Path

from onyx.server.features.build.simple_cli_client import Sandbox
from onyx.server.features.build.simple_cli_client import SimpleCLIClient
from onyx.utils.logger import setup_logger

logger = setup_logger()


@dataclass
class BuildSession:
    """Represents an active build session."""

    session_id: str
    sandbox: Sandbox | None = None
    status: str = "idle"  # idle, running, completed, failed
    created_at: datetime = field(default_factory=datetime.utcnow)
    task: str | None = None
    user_id: str | None = None
    tenant_id: str | None = None


class BuildSessionManager:
    """
    Thread-safe manager for build sessions.

    Tracks active sessions and their associated sandboxes.
    """

    _instance: "BuildSessionManager | None" = None
    _lock = threading.Lock()

    def __new__(cls) -> "BuildSessionManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialize()
        return cls._instance

    def _initialize(self) -> None:
        self._sessions: dict[str, BuildSession] = {}
        self._sessions_lock = threading.Lock()
        self._client = SimpleCLIClient()

    @property
    def client(self) -> SimpleCLIClient:
        return self._client

    def create_session(
        self,
        task: str,
        user_id: str | None = None,
        tenant_id: str | None = None,
    ) -> str:
        """Create a new build session and return the session ID."""
        session_id = f"build-{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # Create the sandbox immediately so files are accessible
        sandbox = self._client.create_sandbox(session_id)

        session = BuildSession(
            session_id=session_id,
            sandbox=sandbox,
            task=task,
            user_id=user_id,
            tenant_id=tenant_id,
            status="idle",
        )

        with self._sessions_lock:
            self._sessions[session_id] = session

        logger.info(f"Created build session: {session_id}")
        return session_id

    def get_session(self, session_id: str) -> BuildSession | None:
        """Get a session by ID."""
        with self._sessions_lock:
            return self._sessions.get(session_id)

    def update_session(
        self,
        session_id: str,
        sandbox: Sandbox | None = None,
        status: str | None = None,
    ) -> None:
        """Update session state."""
        with self._sessions_lock:
            session = self._sessions.get(session_id)
            if session:
                if sandbox is not None:
                    session.sandbox = sandbox
                if status is not None:
                    session.status = status

    def delete_session(self, session_id: str) -> bool:
        """
        Delete a session and cleanup its sandbox.

        Returns True if session was found and deleted.
        """
        with self._sessions_lock:
            session = self._sessions.pop(session_id, None)

        if session is None:
            return False

        # Cleanup sandbox if it exists
        if session.sandbox is not None:
            try:
                SimpleCLIClient.cleanup_sandbox(session.sandbox)
                logger.info(f"Cleaned up sandbox for session: {session_id}")
            except Exception as e:
                logger.error(f"Error cleaning up sandbox for session {session_id}: {e}")

        logger.info(f"Deleted build session: {session_id}")
        return True

    def get_sandbox_path(self, session_id: str) -> Path | None:
        """Get the sandbox path for a session."""
        session = self.get_session(session_id)
        if session and session.sandbox:
            return session.sandbox.path
        return None

    def list_sessions(self) -> list[BuildSession]:
        """List all active sessions."""
        with self._sessions_lock:
            return list(self._sessions.values())


# Global session manager instance
def get_session_manager() -> BuildSessionManager:
    """Get the singleton session manager instance."""
    return BuildSessionManager()
