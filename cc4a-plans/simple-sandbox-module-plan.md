# Simple Sandbox Module Implementation Plan (Filesystem-Based)

## Overview

The Simple Sandbox Module is an internal component of the backend that manages isolated filesystem directories for CLI-based AI agent sessions. Instead of Docker containers, each sandbox is simply a directory on the local filesystem. This provides a lightweight, fast approach suitable for development and single-node deployments.

All code is isolated within `/onyx/server/features/build/` except for SQLAlchemy models which go in `/onyx/db/models.py`.

---

## Issues to Address

1. **Directory Lifecycle Management**: Create, monitor, and cleanup sandbox directories for CLI agent sessions
2. **Directory Structure**: Set up knowledge (read-only copy), outputs (read-write), and instructions (read-only) subdirectories
3. **Snapshot/Restore**: Save directory state to persistent storage and restore on session resumption
4. **CLI Agent Communication**: Run CLI agent as a subprocess and communicate via stdin/stdout or local HTTP
5. **Resource Management**: Track concurrent sandbox count per organization (no CPU/memory isolation)
6. **Multi-Tenant Isolation**: Ensure sandboxes are isolated per-tenant with appropriate access controls via directory permissions

---

## Important Notes

### Key Differences from Docker-Based Approach

| Aspect | Docker-Based | Filesystem-Based |
|--------|--------------|------------------|
| Isolation | Full container isolation | Directory-level separation only |
| Resource limits | CPU/memory enforced | No enforcement (trust-based) |
| Agent execution | HTTP to container port | Subprocess with stdin/stdout |
| Startup time | Seconds (container pull/start) | Milliseconds (mkdir) |
| Complexity | High (Docker SDK, networking) | Low (os/shutil operations) |
| Security | Strong (container boundary) | Weak (process-level only) |

### When to Use This Approach

- Development and testing environments
- Single-node deployments with trusted workloads
- Scenarios where Docker is not available
- Quick prototyping before implementing full container isolation

### Existing Patterns to Follow

Based on codebase exploration:

1. **Feature Structure**: Everything stays in `/onyx/server/features/build/` with a `db/` subdirectory for database operations
2. **Database Models**: SQLAlchemy models go in `/onyx/db/models.py` at the bottom with a comment section
3. **Database Operations**: All DB operations go in `/onyx/server/features/build/db/`
4. **Celery Tasks**: Use `@shared_task` with `TenantAwareTask` base class for background operations
5. **Thread Safety**: Use Singleton pattern with thread locks for the sandbox manager

### Design Decisions

1. **Directory Structure**: Each sandbox is a directory under a configurable base path
   - Path format: `{SANDBOX_BASE_PATH}/{session_id}/`
   - Structure:
     ```
     {session_id}/
     ├── files/              # Symlink to knowledge/source files (read-only)
     ├── outputs/            # Working directory copied from template
     │   ├── web/            # Next.js app for artifact preview
     │   ├── slides/         # Generated slide content
     │   ├── markdown/       # Generated markdown content
     │   └── graphs/         # Generated graph content
     ├── .venv/              # Python virtual environment (copied from template)
     ├── CLAUDE.md           # Agent instructions file
     └── .claude/
         └── skills/         # Agent skills directory
     ```

2. **CLI Agent Protocol**: Subprocess-based communication
   - Agent runs as a subprocess within the sandbox directory
   - Communication via stdin/stdout JSON-lines protocol
   - Alternative: Local HTTP server on random port (for streaming support)

3. **Next.js Dev Server**: Each sandbox runs its own preview server
   - Started on a unique port per sandbox
   - Serves the `outputs/web/` directory
   - Used for previewing generated artifacts (dashboards, visualizations, etc.)
   - Server process tracked alongside agent process

4. **Virtual Environment**: Pre-built venv template for Python dependencies
   - Template copied to each sandbox at `.venv/`
   - Environment variables set to activate venv for agent subprocess
   - Avoids slow pip install on each sandbox creation

5. **Snapshot Storage**: Use existing file store abstraction (`onyx.file_store`)
   - Snapshots stored as tar.gz archives of the `outputs/` directory
   - Path format: `sandbox-snapshots/{tenant_id}/{session_id}/{snapshot_id}.tar.gz`

6. **Process Management**: Use Python's `subprocess` module
   - Track both agent PID and Next.js server PID in database
   - Implement graceful shutdown (SIGTERM then SIGKILL)

---

## Implementation Strategy

### Phase 1: Database Models & Core Infrastructure

#### 1.1 Add Enums to `/onyx/db/enums.py`

```python
class SandboxStatus(str, Enum):
    PROVISIONING = "provisioning"
    RUNNING = "running"
    IDLE = "idle"
    TERMINATED = "terminated"
    FAILED = "failed"
```

#### 1.2 Add Models to `/onyx/db/models.py` (at very bottom with comment)

```python
"""
CLI Agent Sandbox Tables
"""


class Sandbox(Base):
    __tablename__ = "sandbox"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), unique=True, nullable=False)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    directory_path: Mapped[str] = mapped_column(String, nullable=False)
    agent_pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    nextjs_pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    nextjs_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[SandboxStatus] = mapped_column(
        Enum(SandboxStatus, native_enum=False), nullable=False
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_heartbeat: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    terminated_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("ix_sandbox_tenant_status", "tenant_id", "status"),
    )


class SandboxSnapshot(Base):
    __tablename__ = "sandbox_snapshot"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    storage_path: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
```

#### 1.3 Create `/onyx/server/features/build/db/__init__.py`

Empty file to make it a package.

#### 1.4 Create `/onyx/server/features/build/db/sandbox.py`

Database operations (isolated within the build feature directory):

```python
from uuid import UUID
from sqlalchemy.orm import Session
from onyx.db.models import Sandbox, SandboxSnapshot
from onyx.db.enums import SandboxStatus

def create_sandbox(
    db_session: Session,
    session_id: UUID,
    tenant_id: str,
    directory_path: str,
) -> Sandbox:
    """Create a new sandbox record."""
    ...

def get_sandbox_by_session_id(db_session: Session, session_id: UUID) -> Sandbox | None:
    """Get sandbox by session ID."""
    ...

def get_sandbox_by_id(db_session: Session, sandbox_id: UUID) -> Sandbox | None:
    """Get sandbox by its ID."""
    ...

def update_sandbox_status(db_session: Session, sandbox_id: UUID, status: SandboxStatus) -> Sandbox:
    """Update sandbox status."""
    ...

def update_sandbox_agent_pid(db_session: Session, sandbox_id: UUID, agent_pid: int) -> Sandbox:
    """Update sandbox agent process PID."""
    ...

def update_sandbox_nextjs(db_session: Session, sandbox_id: UUID, nextjs_pid: int, nextjs_port: int) -> Sandbox:
    """Update sandbox Next.js server process info."""
    ...

def update_sandbox_heartbeat(db_session: Session, sandbox_id: UUID) -> Sandbox:
    """Update sandbox last_heartbeat to now."""
    ...

def get_idle_sandboxes(db_session: Session, idle_threshold_seconds: int) -> list[Sandbox]:
    """Get sandboxes that have been idle longer than threshold."""
    ...

def get_sandboxes_by_tenant(db_session: Session, tenant_id: str) -> list[Sandbox]:
    """Get all sandboxes for a tenant."""
    ...

def get_running_sandbox_count_by_tenant(db_session: Session, tenant_id: str) -> int:
    """Get count of running sandboxes for a tenant (for limit enforcement)."""
    ...

def create_snapshot(
    db_session: Session,
    session_id: UUID,
    tenant_id: str,
    storage_path: str,
    size_bytes: int
) -> SandboxSnapshot:
    """Create a snapshot record."""
    ...

def get_latest_snapshot_for_session(db_session: Session, session_id: UUID) -> SandboxSnapshot | None:
    """Get most recent snapshot for a session."""
    ...

def delete_old_snapshots(db_session: Session, tenant_id: str, retention_days: int) -> int:
    """Delete snapshots older than retention period, return count deleted."""
    ...
```

#### 1.5 Create Alembic Migration

Create migration file in `/alembic/versions/` for the new tables.

---

### Phase 2: Directory & Process Management

#### 2.1 Create `/onyx/server/features/build/sandbox/` Directory Structure

```
build/
├── __init__.py
├── api.py
├── configs.py
├── models.py
├── session_api.py
├── session_manager.py
├── simple_cli_client.py
├── db/
│   ├── __init__.py
│   └── sandbox.py           # Database operations
└── sandbox/                  # NEW: Sandbox module
    ├── manager.py            # SandboxManager class (public interface)
    ├── models.py             # Data classes (SandboxInfo, SnapshotInfo, etc.)
    ├── internal/             # Internal implementation details
    │   ├── directory_manager.py  # Directory creation and cleanup
    │   ├── process_manager.py    # Subprocess lifecycle management
    │   ├── snapshot_manager.py   # Snapshot creation and restoration
    │   └── agent_client.py       # Communication with CLI agent subprocess
    └── tasks/                # Celery tasks
        ├── health_check_task.py
        └── cleanup_task.py
```

#### 2.2 Implement `sandbox/internal/directory_manager.py`

**DirectoryManager class**:

```python
import shutil
from pathlib import Path

class DirectoryManager:
    """Manages sandbox directory creation and cleanup."""

    def __init__(
        self,
        base_path: Path,
        outputs_template_path: Path,
        venv_template_path: Path,
        skills_path: Path,
        claude_template_path: Path,
    ) -> None:
        self._base_path = base_path
        self._outputs_template_path = outputs_template_path
        self._venv_template_path = venv_template_path
        self._skills_path = skills_path
        self._claude_template_path = claude_template_path

    def create_sandbox_directory(self, session_id: str) -> Path:
        """
        Create sandbox directory structure:
        {base_path}/{session_id}/
        ├── files/              # Symlink to knowledge/source files
        ├── outputs/            # Working directory from template
        │   ├── web/            # Next.js app
        │   ├── slides/
        │   ├── markdown/
        │   └── graphs/
        ├── .venv/              # Python virtual environment
        ├── CLAUDE.md           # Agent instructions
        └── .claude/
            └── skills/         # Agent skills
        """
        sandbox_path = self._base_path / session_id
        sandbox_path.mkdir(parents=True, exist_ok=True)
        return sandbox_path

    def setup_files_symlink(
        self,
        sandbox_path: Path,
        file_system_path: Path,
    ) -> None:
        """Create symlink to knowledge/source files."""
        files_link = sandbox_path / "files"
        if not files_link.exists():
            files_link.symlink_to(file_system_path, target_is_directory=True)

    def setup_outputs_directory(self, sandbox_path: Path) -> None:
        """Copy outputs template and create additional directories."""
        output_dir = sandbox_path / "outputs"
        if not output_dir.exists():
            shutil.copytree(self._outputs_template_path, output_dir, symlinks=True)

        # Create additional output directories for generated content
        (output_dir / "slides").mkdir(parents=True, exist_ok=True)
        (output_dir / "markdown").mkdir(parents=True, exist_ok=True)
        (output_dir / "graphs").mkdir(parents=True, exist_ok=True)

    def setup_venv(self, sandbox_path: Path) -> Path:
        """Copy virtual environment template."""
        venv_path = sandbox_path / ".venv"
        if not venv_path.exists() and self._venv_template_path.exists():
            shutil.copytree(self._venv_template_path, venv_path, symlinks=True)
        return venv_path

    def setup_claude_md(self, sandbox_path: Path) -> None:
        """Copy CLAUDE.md instructions template."""
        claude_md_path = sandbox_path / "CLAUDE.md"
        if not claude_md_path.exists():
            shutil.copy(self._claude_template_path, claude_md_path)

    def setup_skills(self, sandbox_path: Path) -> None:
        """Copy skills directory to .claude/skills."""
        skills_dest = sandbox_path / ".claude" / "skills"
        if self._skills_path.exists() and not skills_dest.exists():
            skills_dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(self._skills_path, skills_dest)

    def cleanup_sandbox_directory(self, sandbox_path: Path) -> None:
        """Remove sandbox directory and all contents."""
        if sandbox_path.exists():
            shutil.rmtree(sandbox_path)

    def get_outputs_path(self, sandbox_path: Path) -> Path:
        """Return path to outputs directory."""
        return sandbox_path / "outputs"

    def get_web_path(self, sandbox_path: Path) -> Path:
        """Return path to Next.js web directory."""
        return sandbox_path / "outputs" / "web"

    def get_venv_path(self, sandbox_path: Path) -> Path:
        """Return path to virtual environment."""
        return sandbox_path / ".venv"

    def directory_exists(self, sandbox_path: Path) -> bool:
        """Check if sandbox directory exists."""
        return sandbox_path.exists() and sandbox_path.is_dir()
```

#### 2.3 Implement `sandbox/internal/process_manager.py`

**ProcessManager class**:

```python
import os
import shutil
import signal
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

class ProcessManager:
    """Manages CLI agent and Next.js server subprocess lifecycle."""

    def build_venv_env(self, venv_path: Path) -> dict[str, str]:
        """
        Build environment variables dict with the virtual environment activated.
        """
        env = os.environ.copy()
        venv_bin = str(venv_path / "bin")
        env["PATH"] = f"{venv_bin}:{env.get('PATH', '')}"
        env["VIRTUAL_ENV"] = str(venv_path)
        # Unset PYTHONHOME if set (can interfere with venv)
        env.pop("PYTHONHOME", None)
        return env

    def start_agent_process(
        self,
        sandbox_path: Path,
        agent_command: list[str],
        venv_path: Path | None = None,
        env_vars: dict[str, str] | None = None,
    ) -> subprocess.Popen:
        """
        Start CLI agent as subprocess.

        Working directory is set to sandbox root.
        Virtual environment is activated if provided.
        """
        env = self.build_venv_env(venv_path) if venv_path else os.environ.copy()
        if env_vars:
            env.update(env_vars)

        process = subprocess.Popen(
            agent_command,
            cwd=sandbox_path,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return process

    def start_nextjs_server(
        self,
        web_dir: Path,
        port: int,
        timeout: float = 60.0,
    ) -> subprocess.Popen:
        """
        Start Next.js dev server.

        1. Clear .next cache to avoid stale paths from template
        2. Start npm run dev on specified port
        3. Wait for server to be ready

        Returns the subprocess.Popen object.
        Raises RuntimeError if server fails to start within timeout.
        """
        # Clear Next.js cache to avoid stale paths from template
        next_cache = web_dir / ".next"
        if next_cache.exists():
            shutil.rmtree(next_cache)

        process = subprocess.Popen(
            ["npm", "run", "dev", "--", "-p", str(port)],
            cwd=web_dir,
        )

        # Wait for server to be ready
        server_url = f"http://localhost:{port}"
        if not self._wait_for_server(server_url, timeout=timeout):
            # Check if process died
            if process.poll() is not None:
                raise RuntimeError(f"Next.js server process died with code {process.returncode}")
            raise RuntimeError(f"Next.js server failed to start within {timeout} seconds")

        return process

    def _wait_for_server(
        self,
        url: str,
        timeout: float = 30.0,
        poll_interval: float = 0.5,
    ) -> bool:
        """Wait for a server to become available by polling."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                with urllib.request.urlopen(url, timeout=2) as response:
                    if response.status == 200:
                        return True
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
                pass
            time.sleep(poll_interval)
        return False

    def is_process_running(self, pid: int) -> bool:
        """Check if process with given PID is still running."""
        try:
            os.kill(pid, 0)  # Signal 0 just checks if process exists
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True  # Process exists but we can't signal it

    def terminate_process(self, pid: int, timeout: float = 5.0) -> bool:
        """
        Gracefully terminate process.

        1. Send SIGTERM
        2. Wait up to timeout seconds
        3. If still running, send SIGKILL

        Returns True if process was terminated, False if it wasn't running.
        """
        if not self.is_process_running(pid):
            return False

        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return False

        # Wait for graceful shutdown
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not self.is_process_running(pid):
                return True
            time.sleep(0.1)

        # Force kill if still running
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

        return True

    def get_process_info(self, pid: int) -> dict | None:
        """Get information about a running process."""
        if not self.is_process_running(pid):
            return None

        try:
            import psutil
            proc = psutil.Process(pid)
            return {
                "pid": pid,
                "status": proc.status(),
                "cpu_percent": proc.cpu_percent(),
                "memory_mb": proc.memory_info().rss / 1024 / 1024,
                "create_time": proc.create_time(),
            }
        except Exception:
            return {"pid": pid, "status": "unknown"}
```

**Configuration** (add to `build/configs.py`):
```python
# These already exist in configs.py - ensure they're defined:
SANDBOX_BASE_PATH = os.environ.get("SANDBOX_BASE_PATH", "/tmp/onyx-sandboxes")
OUTPUTS_TEMPLATE_PATH = os.environ.get("OUTPUTS_TEMPLATE_PATH", "/templates/outputs")
VENV_TEMPLATE_PATH = os.environ.get("VENV_TEMPLATE_PATH", "/templates/venv")
PERSISTENT_DOCUMENT_STORAGE_PATH = os.environ.get("PERSISTENT_DOCUMENT_STORAGE_PATH", "/data/documents")

# New configs for sandbox module:
SANDBOX_AGENT_COMMAND = os.environ.get("SANDBOX_AGENT_COMMAND", "claude-code").split()
SANDBOX_IDLE_TIMEOUT_SECONDS = int(os.environ.get("SANDBOX_IDLE_TIMEOUT_SECONDS", "900"))
SANDBOX_MAX_CONCURRENT_PER_ORG = int(os.environ.get("SANDBOX_MAX_CONCURRENT_PER_ORG", "10"))
SANDBOX_SNAPSHOTS_BUCKET = os.environ.get("SANDBOX_SNAPSHOTS_BUCKET", "sandbox-snapshots")
SANDBOX_NEXTJS_PORT_START = int(os.environ.get("SANDBOX_NEXTJS_PORT_START", "3010"))
SANDBOX_NEXTJS_PORT_END = int(os.environ.get("SANDBOX_NEXTJS_PORT_END", "3100"))
```

---

### Phase 3: Snapshot Management

#### 3.1 Implement `sandbox/internal/snapshot_manager.py`

**SnapshotManager class**:

```python
import tarfile
import tempfile
from pathlib import Path
from uuid import uuid4

class SnapshotManager:
    """Manages sandbox snapshot creation and restoration."""

    def __init__(self, file_store) -> None:
        self._file_store = file_store

    def create_snapshot(
        self,
        sandbox_path: Path,
        session_id: str,
        tenant_id: str,
    ) -> tuple[str, str, int]:
        """
        Create a snapshot of the outputs directory.

        Returns: (snapshot_id, storage_path, size_bytes)
        """
        snapshot_id = str(uuid4())
        outputs_path = sandbox_path / "outputs"

        # Create tar.gz in temp location
        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
            tmp_path = tmp.name

        with tarfile.open(tmp_path, "w:gz") as tar:
            tar.add(outputs_path, arcname="outputs")

        # Get size
        size_bytes = Path(tmp_path).stat().st_size

        # Upload to file store
        storage_path = f"sandbox-snapshots/{tenant_id}/{session_id}/{snapshot_id}.tar.gz"
        with open(tmp_path, "rb") as f:
            self._file_store.save_file(storage_path, f.read())

        # Cleanup temp file
        Path(tmp_path).unlink()

        return snapshot_id, storage_path, size_bytes

    def restore_snapshot(
        self,
        storage_path: str,
        target_path: Path,
    ) -> None:
        """
        Restore a snapshot to target directory.

        Extracts outputs/ from snapshot into target_path.
        """
        # Download from file store
        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
            tmp_path = tmp.name
            data = self._file_store.read_file(storage_path)
            tmp.write(data)

        # Extract
        with tarfile.open(tmp_path, "r:gz") as tar:
            tar.extractall(target_path)

        # Cleanup temp file
        Path(tmp_path).unlink()

    def delete_snapshot(self, storage_path: str) -> None:
        """Delete snapshot from file store."""
        self._file_store.delete_file(storage_path)
```

---

### Phase 4: Agent Communication

#### 4.1 Implement `sandbox/internal/agent_client.py`

**AgentClient class** (subprocess stdin/stdout based):

```python
import json
import subprocess
from typing import Generator
from pathlib import Path

class AgentClient:
    """Handles communication with CLI agent subprocess."""

    def send_message(
        self,
        process: subprocess.Popen,
        message: str,
        conversation_history: list[dict] | None = None,
    ) -> Generator[dict, None, None]:
        """
        Send message to agent and stream response.

        Protocol:
        - Write JSON request to stdin (newline-terminated)
        - Read JSON-lines responses from stdout
        - Each line is a StreamPacket
        """
        request = {
            "type": "message",
            "content": message,
            "history": conversation_history or [],
        }

        # Send request
        process.stdin.write(json.dumps(request) + "\n")
        process.stdin.flush()

        # Stream response
        for line in process.stdout:
            line = line.strip()
            if not line:
                continue

            try:
                packet = json.loads(line)
                yield packet

                # Check for end of response
                if packet.get("type") == "done":
                    break
            except json.JSONDecodeError:
                # Log and continue
                continue

    def health_check(self, process: subprocess.Popen) -> bool:
        """
        Check if agent is responsive.

        Send a ping request and wait for pong response.
        """
        try:
            request = {"type": "ping"}
            process.stdin.write(json.dumps(request) + "\n")
            process.stdin.flush()

            # Read with timeout
            import select
            if select.select([process.stdout], [], [], 5.0)[0]:
                response = process.stdout.readline()
                data = json.loads(response)
                return data.get("type") == "pong"
            return False
        except Exception:
            return False
```

**Alternative: HTTP-based AgentClient** (for better streaming support):

```python
import httpx
from typing import Generator

class HttpAgentClient:
    """HTTP-based communication with CLI agent."""

    def send_message(
        self,
        agent_port: int,
        message: str,
        conversation_history: list[dict] | None = None,
    ) -> Generator[dict, None, None]:
        """
        Send message to agent HTTP server and stream response.
        """
        url = f"http://127.0.0.1:{agent_port}/message"
        payload = {
            "content": message,
            "history": conversation_history or [],
        }

        with httpx.stream("POST", url, json=payload, timeout=300.0) as response:
            for line in response.iter_lines():
                if line:
                    yield json.loads(line)

    def health_check(self, agent_port: int) -> bool:
        """Check agent health via HTTP endpoint."""
        try:
            response = httpx.get(
                f"http://127.0.0.1:{agent_port}/health",
                timeout=5.0
            )
            return response.status_code == 200
        except Exception:
            return False
```

---

### Phase 5: Public Interface

#### 5.1 Implement `sandbox/models.py`

Data classes for module communication:

```python
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from onyx.db.enums import SandboxStatus

@dataclass
class SandboxInfo:
    id: str
    session_id: str
    directory_path: str
    agent_pid: int | None
    nextjs_pid: int | None
    nextjs_port: int | None
    status: SandboxStatus
    created_at: datetime
    last_heartbeat: datetime | None

@dataclass
class SnapshotInfo:
    id: str
    session_id: str
    storage_path: str
    created_at: datetime
    size_bytes: int

@dataclass
class FilesystemEntry:
    name: str
    path: str
    is_directory: bool
    size_bytes: int | None
    modified_at: datetime | None
```

#### 5.2 Implement `sandbox/manager.py` - SandboxManager Class

```python
from typing import Generator
from pathlib import Path
from onyx.server.features.build.sandbox.internal.directory_manager import DirectoryManager
from onyx.server.features.build.sandbox.internal.process_manager import ProcessManager
from onyx.server.features.build.sandbox.internal.snapshot_manager import SnapshotManager
from onyx.server.features.build.sandbox.internal.agent_client import AgentClient
from onyx.server.features.build.sandbox.models import SandboxInfo, SnapshotInfo, FilesystemEntry


class SandboxManager:
    """
    Public interface for sandbox operations.
    Orchestrates internal managers for directory lifecycle, processes, snapshots, and agent communication.
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
        from pathlib import Path
        from onyx.server.features.build.configs import (
            SANDBOX_BASE_PATH,
            OUTPUTS_TEMPLATE_PATH,
            VENV_TEMPLATE_PATH,
        )
        from onyx.file_store.file_store import get_default_file_store

        # Paths for templates
        build_dir = Path(__file__).parent.parent  # /onyx/server/features/build/
        skills_path = build_dir / "skills"
        claude_template_path = build_dir / "CLAUDE.template.md"

        self._directory_manager = DirectoryManager(
            base_path=Path(SANDBOX_BASE_PATH),
            outputs_template_path=Path(OUTPUTS_TEMPLATE_PATH),
            venv_template_path=Path(VENV_TEMPLATE_PATH),
            skills_path=skills_path,
            claude_template_path=claude_template_path,
        )
        self._process_manager = ProcessManager()
        self._snapshot_manager = SnapshotManager(get_default_file_store())
        self._agent_client = AgentClient()

        # Track processes in memory: sandbox_id -> (agent_process, nextjs_process)
        self._agent_processes: dict[str, subprocess.Popen] = {}
        self._nextjs_processes: dict[str, subprocess.Popen] = {}

        # Port allocation tracking
        self._allocated_ports: set[int] = set()

    def _allocate_port(self) -> int:
        """Allocate an available port for Next.js server."""
        from onyx.server.features.build.configs import (
            SANDBOX_NEXTJS_PORT_START,
            SANDBOX_NEXTJS_PORT_END,
        )

        for port in range(SANDBOX_NEXTJS_PORT_START, SANDBOX_NEXTJS_PORT_END):
            if port not in self._allocated_ports:
                self._allocated_ports.add(port)
                return port

        raise RuntimeError("No available ports for Next.js server")

    def _release_port(self, port: int) -> None:
        """Release an allocated port."""
        self._allocated_ports.discard(port)

    def provision(
        self,
        session_id: str,
        tenant_id: str,
        file_system_path: str,
        snapshot_id: str | None = None,
        db_session: Session,
    ) -> SandboxInfo:
        """
        Provision a new sandbox for a session.

        1. Check concurrent sandbox limit for tenant
        2. Create sandbox directory structure
        3. Setup files symlink, outputs, venv, CLAUDE.md, and skills
        4. If snapshot_id provided, restore outputs from snapshot
        5. Start Next.js dev server
        6. Store sandbox record in DB
        7. Return sandbox info (agent not started until first message)
        """
        from pathlib import Path
        from onyx.server.features.build.db.sandbox import (
            create_sandbox,
            get_running_sandbox_count_by_tenant,
            get_latest_snapshot_for_session,
            update_sandbox_nextjs,
            update_sandbox_status,
        )
        from onyx.server.features.build.configs import SANDBOX_MAX_CONCURRENT_PER_ORG

        # Check limit
        running_count = get_running_sandbox_count_by_tenant(db_session, tenant_id)
        if running_count >= SANDBOX_MAX_CONCURRENT_PER_ORG:
            raise ValueError(f"Maximum concurrent sandboxes ({SANDBOX_MAX_CONCURRENT_PER_ORG}) reached for tenant")

        # Create directory structure
        sandbox_path = self._directory_manager.create_sandbox_directory(session_id)

        # Setup files symlink
        self._directory_manager.setup_files_symlink(sandbox_path, Path(file_system_path))

        # Setup outputs (from snapshot or template)
        if snapshot_id:
            snapshot = get_latest_snapshot_for_session(db_session, session_id)
            if snapshot:
                self._snapshot_manager.restore_snapshot(snapshot.storage_path, sandbox_path)
        else:
            self._directory_manager.setup_outputs_directory(sandbox_path)

        # Setup venv, CLAUDE.md, and skills
        self._directory_manager.setup_venv(sandbox_path)
        self._directory_manager.setup_claude_md(sandbox_path)
        self._directory_manager.setup_skills(sandbox_path)

        # Allocate port and start Next.js server
        nextjs_port = self._allocate_port()
        web_dir = self._directory_manager.get_web_path(sandbox_path)

        try:
            nextjs_process = self._process_manager.start_nextjs_server(web_dir, nextjs_port)
        except RuntimeError:
            self._release_port(nextjs_port)
            self._directory_manager.cleanup_sandbox_directory(sandbox_path)
            raise

        # Create DB record
        sandbox = create_sandbox(
            db_session=db_session,
            session_id=session_id,
            tenant_id=tenant_id,
            directory_path=str(sandbox_path),
        )

        # Update with Next.js info
        update_sandbox_nextjs(db_session, sandbox.id, nextjs_process.pid, nextjs_port)
        update_sandbox_status(db_session, sandbox.id, SandboxStatus.RUNNING)

        # Track process
        self._nextjs_processes[str(sandbox.id)] = nextjs_process

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

    def terminate(self, sandbox_id: str, db_session: Session) -> None:
        """
        Terminate a sandbox.

        1. Terminate agent process (if running)
        2. Terminate Next.js server
        3. Release allocated port
        4. Cleanup sandbox directory
        5. Update DB status to TERMINATED
        """
        from pathlib import Path
        from onyx.server.features.build.db.sandbox import get_sandbox_by_id, update_sandbox_status

        sandbox = get_sandbox_by_id(db_session, sandbox_id)
        if not sandbox:
            return

        # Terminate agent process
        if sandbox.agent_pid:
            self._process_manager.terminate_process(sandbox.agent_pid)
        self._agent_processes.pop(sandbox_id, None)

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
        update_sandbox_status(db_session, sandbox_id, SandboxStatus.TERMINATED)

    def create_snapshot(self, sandbox_id: str, db_session: Session) -> SnapshotInfo:
        """Create a snapshot of the sandbox's outputs directory."""
        from onyx.server.features.build.db.sandbox import get_sandbox_by_id, create_snapshot

        sandbox = get_sandbox_by_id(db_session, sandbox_id)
        if not sandbox:
            raise ValueError(f"Sandbox {sandbox_id} not found")

        snapshot_id, storage_path, size_bytes = self._snapshot_manager.create_snapshot(
            Path(sandbox.directory_path),
            str(sandbox.session_id),
            sandbox.tenant_id,
        )

        snapshot = create_snapshot(
            db_session=db_session,
            session_id=sandbox.session_id,
            tenant_id=sandbox.tenant_id,
            storage_path=storage_path,
            size_bytes=size_bytes,
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
        from onyx.server.features.build.db.sandbox import get_sandbox_by_id, update_sandbox_heartbeat

        sandbox = get_sandbox_by_id(db_session, sandbox_id)
        if not sandbox:
            return False

        # Check Next.js server is running
        if sandbox.nextjs_pid and not self._process_manager.is_process_running(sandbox.nextjs_pid):
            return False

        # Check agent process is running (if started)
        if sandbox.agent_pid and not self._process_manager.is_process_running(sandbox.agent_pid):
            return False

        # Check Next.js server is responsive
        if sandbox.nextjs_port:
            if self._process_manager._wait_for_server(
                f"http://localhost:{sandbox.nextjs_port}",
                timeout=5.0
            ):
                update_sandbox_heartbeat(db_session, sandbox_id)
                return True

        return False

    def send_message(
        self,
        sandbox_id: str,
        message: str,
        conversation_history: list[dict] | None = None,
        db_session: Session,
    ) -> Generator[dict, None, None]:
        """Send a message to the CLI agent and stream the response."""
        from pathlib import Path
        from onyx.server.features.build.db.sandbox import (
            get_sandbox_by_id,
            update_sandbox_heartbeat,
            update_sandbox_agent_pid,
        )
        from onyx.server.features.build.configs import SANDBOX_AGENT_COMMAND

        sandbox = get_sandbox_by_id(db_session, sandbox_id)
        if not sandbox:
            raise ValueError(f"Sandbox {sandbox_id} not found")

        # Start agent process if not already running
        process = self._agent_processes.get(sandbox_id)
        if not process or process.poll() is not None:
            sandbox_path = Path(sandbox.directory_path)
            venv_path = self._directory_manager.get_venv_path(sandbox_path)

            process = self._process_manager.start_agent_process(
                sandbox_path=sandbox_path,
                agent_command=SANDBOX_AGENT_COMMAND,
                venv_path=venv_path if venv_path.exists() else None,
            )
            self._agent_processes[sandbox_id] = process
            update_sandbox_agent_pid(db_session, sandbox.id, process.pid)

        # Update heartbeat on message send
        update_sandbox_heartbeat(db_session, sandbox_id)

        for packet in self._agent_client.send_message(process, message, conversation_history):
            yield packet
            # Update heartbeat on activity
            update_sandbox_heartbeat(db_session, sandbox_id)

    def list_directory(self, sandbox_id: str, path: str, db_session: Session) -> list[FilesystemEntry]:
        """List contents of a directory in the sandbox's outputs directory."""
        from onyx.server.features.build.db.sandbox import get_sandbox_by_id

        sandbox = get_sandbox_by_id(db_session, sandbox_id)
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
            entries.append(FilesystemEntry(
                name=item.name,
                path=str(item.relative_to(outputs_path)),
                is_directory=item.is_dir(),
                size_bytes=stat.st_size if item.is_file() else None,
                modified_at=datetime.fromtimestamp(stat.st_mtime),
            ))

        return sorted(entries, key=lambda e: (not e.is_directory, e.name.lower()))

    def read_file(self, sandbox_id: str, path: str, db_session: Session) -> bytes:
        """Read a file from the sandbox's outputs directory."""
        from onyx.server.features.build.db.sandbox import get_sandbox_by_id

        sandbox = get_sandbox_by_id(db_session, sandbox_id)
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
```

---

### Phase 6: Background Tasks (Celery)

#### 6.1 Add Constants to `/onyx/configs/constants.py`

```python
# In OnyxCeleryQueues
SANDBOX = "sandbox"

# In OnyxCeleryTask
CHECK_SANDBOX_HEALTH = "check_sandbox_health"
CLEANUP_IDLE_SANDBOXES = "cleanup_idle_sandboxes"
CLEANUP_OLD_SNAPSHOTS = "cleanup_old_snapshots"
```

#### 6.2 Create `/onyx/server/features/build/sandbox/tasks/`

**`tasks/__init__.py`**: Empty file

**`tasks/health_check_task.py`**:
```python
from celery import shared_task
from onyx.background.celery.apps.app_base import task_logger, TenantAwareTask

@shared_task(name="check_sandbox_health", base=TenantAwareTask)
def check_sandbox_health_task(tenant_id: str) -> None:
    """
    1. Get all running sandboxes for tenant
    2. Check health of each (Next.js server running + responsive)
    3. Mark failed sandboxes as FAILED status
    """
    from onyx.db.engine import get_session_with_tenant
    from onyx.server.features.build.db.sandbox import get_sandboxes_by_tenant, update_sandbox_status
    from onyx.server.features.build.sandbox.manager import SandboxManager
    from onyx.db.enums import SandboxStatus

    sandbox_manager = SandboxManager()

    with get_session_with_tenant(tenant_id) as db_session:
        sandboxes = get_sandboxes_by_tenant(db_session, tenant_id)

        for sandbox in sandboxes:
            if sandbox.status not in (SandboxStatus.RUNNING, SandboxStatus.IDLE):
                continue

            if not sandbox_manager.health_check(str(sandbox.id), db_session):
                task_logger.warning(f"Sandbox {sandbox.id} failed health check (Next.js server unresponsive)")
                update_sandbox_status(db_session, sandbox.id, SandboxStatus.FAILED)
```

**`tasks/cleanup_task.py`**:
```python
from celery import shared_task
from onyx.background.celery.apps.app_base import task_logger, TenantAwareTask

@shared_task(name="cleanup_idle_sandboxes", base=TenantAwareTask)
def cleanup_idle_sandboxes_task(tenant_id: str) -> None:
    """
    1. Get sandboxes idle longer than SANDBOX_IDLE_TIMEOUT_SECONDS
    2. Create snapshot for each
    3. Terminate sandbox
    """
    from onyx.db.engine import get_session_with_tenant
    from onyx.server.features.build.db.sandbox import get_idle_sandboxes
    from onyx.server.features.build.sandbox.manager import SandboxManager
    from onyx.server.features.build.configs import SANDBOX_IDLE_TIMEOUT_SECONDS

    sandbox_manager = SandboxManager()

    with get_session_with_tenant(tenant_id) as db_session:
        idle_sandboxes = get_idle_sandboxes(db_session, SANDBOX_IDLE_TIMEOUT_SECONDS)

        for sandbox in idle_sandboxes:
            task_logger.info(f"Cleaning up idle sandbox {sandbox.id}")
            try:
                # Create snapshot before terminating
                sandbox_manager.create_snapshot(str(sandbox.id), db_session)
            except Exception as e:
                task_logger.warning(f"Failed to create snapshot for sandbox {sandbox.id}: {e}")

            sandbox_manager.terminate(str(sandbox.id), db_session)

@shared_task(name="cleanup_old_snapshots", base=TenantAwareTask)
def cleanup_old_snapshots_task(tenant_id: str) -> None:
    """Delete snapshots older than retention period."""
    from onyx.db.engine import get_session_with_tenant
    from onyx.server.features.build.db.sandbox import delete_old_snapshots

    RETENTION_DAYS = 30

    with get_session_with_tenant(tenant_id) as db_session:
        deleted_count = delete_old_snapshots(db_session, tenant_id, RETENTION_DAYS)
        if deleted_count > 0:
            task_logger.info(f"Deleted {deleted_count} old snapshots for tenant {tenant_id}")
```

#### 6.3 Add to Beat Schedule

In `/onyx/background/celery/tasks/beat_schedule.py`:
```python
# Check sandbox health every 30 seconds
{
    "name": "check-sandbox-health",
    "task": OnyxCeleryTask.CHECK_SANDBOX_HEALTH,
    "schedule": timedelta(seconds=30),
}

# Cleanup idle sandboxes every minute
{
    "name": "cleanup-idle-sandboxes",
    "task": OnyxCeleryTask.CLEANUP_IDLE_SANDBOXES,
    "schedule": timedelta(minutes=1),
}

# Cleanup old snapshots daily
{
    "name": "cleanup-old-snapshots",
    "task": OnyxCeleryTask.CLEANUP_OLD_SNAPSHOTS,
    "schedule": timedelta(hours=24),
}
```

---

## File Structure Summary

```
backend/
├── onyx/
│   ├── db/
│   │   ├── enums.py                    # + SandboxStatus
│   │   └── models.py                   # + Sandbox, SandboxSnapshot (at bottom with comment)
│   ├── server/features/
│   │   └── build/                      # Everything isolated here
│   │       ├── __init__.py
│   │       ├── api.py
│   │       ├── configs.py              # + Sandbox configuration
│   │       ├── models.py
│   │       ├── session_api.py
│   │       ├── session_manager.py
│   │       ├── simple_cli_client.py
│   │       ├── db/                     # NEW: Database operations
│   │       │   ├── __init__.py
│   │       │   └── sandbox.py
│   │       └── sandbox/                # NEW: Sandbox module
│   │           ├── manager.py          # SandboxManager class (public interface)
│   │           ├── models.py           # Data classes
│   │           ├── internal/           # Internal implementation
│   │           │   ├── directory_manager.py
│   │           │   ├── process_manager.py
│   │           │   ├── snapshot_manager.py
│   │           │   └── agent_client.py
│   │           └── tasks/              # Celery tasks
│   │               ├── health_check_task.py
│   │               └── cleanup_task.py
│   ├── configs/
│   │   └── constants.py                # + Celery queue/task constants
│   └── background/celery/tasks/
│       └── beat_schedule.py            # + Sandbox task schedules
└── alembic/versions/
    └── xxx_add_sandbox_tables.py       # NEW: Migration
```

---

## Dependencies

Add to `requirements.txt`:
```
psutil>=5.9.0    # Process monitoring (optional, for detailed process info)
```

Note: No Docker SDK needed for the simple filesystem-based approach.

---

## Security Considerations

Since this approach lacks container isolation:

1. **Directory Permissions**: Set appropriate file permissions on sandbox directories
2. **Path Traversal**: Validate all file paths to prevent escape from outputs directory
3. **Process Isolation**: Agent runs as subprocess with same user permissions as backend
4. **No Resource Limits**: Cannot enforce CPU/memory limits without containers
5. **Recommended Use**: Development, testing, or trusted single-tenant deployments only

---

## Migration Path to Docker-Based

When ready to upgrade to full container isolation:

1. Keep the same `SandboxManager` public interface
2. Swap internal implementations:
   - `DirectoryManager` → `ContainerManager` (Docker SDK)
   - `ProcessManager` → container lifecycle via Docker API
   - `AgentClient` → HTTP to container IP:port
3. Database models remain the same (just different values in `directory_path` vs `container_id`)
4. Celery tasks remain the same

---

## Open Items for Follow-up

1. **CLI Agent Protocol**: Define exact stdin/stdout JSON-lines protocol for subprocess communication
2. **Knowledge Volume Setup**: Decide between copy vs symlink for knowledge files
3. **Frontend Integration**: Need frontend plan for VM Explorer and artifact rendering
4. **Production Hardening**: When to migrate to Docker-based approach
5. **Testing Strategy**: Integration tests for sandbox lifecycle
