"""Tests for SandboxManager public interface.

These are external dependency unit tests that use real DB sessions and filesystem.
Each test covers a single happy path case for the corresponding public function.

Tests for provision are not included as they require the full sandbox environment
with Next.js servers.
"""

import shutil
import tempfile
from collections.abc import Generator
from pathlib import Path
from uuid import uuid4

import pytest
from acp.schema import PromptResponse
from acp.schema import ToolCallStart
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.enums import BuildSessionStatus
from onyx.db.enums import SandboxStatus
from onyx.db.models import BuildSession
from onyx.db.models import Sandbox
from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.build.configs import SANDBOX_BASE_PATH
from onyx.server.features.build.sandbox import get_sandbox_manager
from onyx.server.features.build.sandbox.local import LocalSandboxManager
from onyx.server.features.build.sandbox.local.agent_client import ACPEvent
from onyx.server.features.build.sandbox.models import FilesystemEntry
from onyx.server.features.build.sandbox.models import SnapshotResult
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR


TEST_TENANT_ID = "public"


@pytest.fixture(scope="function")
def db_session() -> Generator[Session, None, None]:
    """Create a database session for testing."""
    SqlEngine.init_engine(pool_size=10, max_overflow=5)
    with get_session_with_current_tenant() as session:
        yield session


@pytest.fixture(scope="function")
def tenant_context() -> Generator[None, None, None]:
    """Set up tenant context for testing."""
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(TEST_TENANT_ID)
    try:
        yield
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


@pytest.fixture
def sandbox_manager() -> LocalSandboxManager:
    """Get the SandboxManager instance via factory function."""
    manager = get_sandbox_manager()
    assert isinstance(manager, LocalSandboxManager)
    return manager


@pytest.fixture
def temp_sandbox_dir() -> Generator[Path, None, None]:
    """Create a temporary directory structure for sandbox testing."""
    temp_dir = Path(tempfile.mkdtemp(prefix="sandbox_test_"))
    outputs_dir = temp_dir / "outputs"
    outputs_dir.mkdir()

    yield temp_dir

    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def actual_sandbox_path(sandbox_record: Sandbox) -> Path:
    """Get the actual sandbox path where the manager expects it."""
    return Path(SANDBOX_BASE_PATH) / str(sandbox_record.id)


@pytest.fixture
def sandbox_record(
    db_session: Session, tenant_context: None
) -> Generator[Sandbox, None, None]:
    """Create a real Sandbox record in the database and set up sandbox directory."""
    # Create BuildSession first (required foreign key)
    build_session = BuildSession(
        id=uuid4(),
        status=BuildSessionStatus.ACTIVE,
    )
    db_session.add(build_session)
    db_session.flush()  # Flush to get the ID without committing

    # Create Sandbox with reference to BuildSession
    sandbox = Sandbox(
        id=uuid4(),
        session_id=build_session.id,
        status=SandboxStatus.RUNNING,
    )
    db_session.add(sandbox)
    db_session.commit()
    db_session.refresh(sandbox)

    # Create sandbox directory at the expected location
    # The manager uses _get_sandbox_path() which returns SANDBOX_BASE_PATH / sandbox_id
    expected_sandbox_path = Path(SANDBOX_BASE_PATH) / str(sandbox.id)
    expected_sandbox_path.mkdir(parents=True, exist_ok=True)

    # Ensure outputs directory exists at the expected path
    expected_outputs = expected_sandbox_path / "outputs"
    expected_outputs.mkdir(parents=True, exist_ok=True)

    yield sandbox

    # Cleanup sandbox directory
    if expected_sandbox_path.exists():
        shutil.rmtree(expected_sandbox_path, ignore_errors=True)

    # Cleanup - re-fetch in case it was deleted
    existing = db_session.get(Sandbox, sandbox.id)
    if existing:
        db_session.delete(existing)
        db_session.commit()

    # Cleanup BuildSession (cascade should handle it, but be explicit)
    existing_session = db_session.get(BuildSession, build_session.id)
    if existing_session:
        db_session.delete(existing_session)
        db_session.commit()


@pytest.fixture
def file_store_initialized() -> Generator[None, None, None]:
    """Initialize file store for snapshot tests."""
    get_default_file_store().initialize()
    yield


class TestTerminate:
    """Tests for SandboxManager.terminate()."""

    def test_terminate_cleans_up_resources(
        self,
        sandbox_manager: LocalSandboxManager,
        db_session: Session,
        sandbox_record: Sandbox,
        temp_sandbox_dir: Path,
        tenant_context: None,
    ) -> None:
        """Test that terminate cleans up sandbox resources.

        Note: Status update is now handled by the caller (SessionManager/tasks),
        not by the SandboxManager itself.
        """
        sandbox_manager.terminate(sandbox_record.id)
        # No exception means success - resources cleaned up


class TestCreateSnapshot:
    """Tests for SandboxManager.create_snapshot()."""

    def test_create_snapshot_archives_outputs(
        self,
        sandbox_manager: LocalSandboxManager,
        db_session: Session,
        sandbox_record: Sandbox,
        actual_sandbox_path: Path,
        tenant_context: None,
        file_store_initialized: None,
    ) -> None:
        """Test that create_snapshot archives the outputs directory.

        Note: Caller is responsible for creating DB record from the SnapshotResult.
        """
        outputs_dir = actual_sandbox_path / "outputs"
        (outputs_dir / "app.py").write_text("print('hello')")

        result = sandbox_manager.create_snapshot(sandbox_record.id, TEST_TENANT_ID)

        assert isinstance(result, SnapshotResult)
        assert result.size_bytes > 0
        assert result.storage_path is not None


class TestHealthCheck:
    """Tests for SandboxManager.health_check()."""

    def test_health_check_returns_false_when_no_processes(
        self,
        sandbox_manager: LocalSandboxManager,
        db_session: Session,
        sandbox_record: Sandbox,
        tenant_context: None,
    ) -> None:
        """Test that health_check returns False when no processes are running.

        Note: nextjs_port is now passed by the caller instead of being fetched from DB.
        """
        result = sandbox_manager.health_check(sandbox_record.id, nextjs_port=None)

        assert result is False


class TestListDirectory:
    """Tests for SandboxManager.list_directory()."""

    def test_list_directory_returns_entries(
        self,
        sandbox_manager: LocalSandboxManager,
        db_session: Session,
        sandbox_record: Sandbox,
        actual_sandbox_path: Path,
        tenant_context: None,
    ) -> None:
        """Test that list_directory returns filesystem entries."""
        outputs_dir = actual_sandbox_path / "outputs"
        (outputs_dir / "file.txt").write_text("content")
        (outputs_dir / "subdir").mkdir()

        result = sandbox_manager.list_directory(sandbox_record.id, "/")

        assert len(result) == 2
        assert all(isinstance(e, FilesystemEntry) for e in result)
        assert result[0].name == "subdir"  # directories first
        assert result[0].is_directory is True
        assert result[1].name == "file.txt"
        assert result[1].is_directory is False


class TestReadFile:
    """Tests for SandboxManager.read_file()."""

    def test_read_file_returns_contents(
        self,
        sandbox_manager: LocalSandboxManager,
        db_session: Session,
        sandbox_record: Sandbox,
        actual_sandbox_path: Path,
        tenant_context: None,
    ) -> None:
        """Test that read_file returns file contents as bytes."""
        outputs_dir = actual_sandbox_path / "outputs"
        (outputs_dir / "test.txt").write_bytes(b"Hello, World!")

        result = sandbox_manager.read_file(sandbox_record.id, "test.txt")

        assert result == b"Hello, World!"


class TestCancelAgent:
    """Tests for SandboxManager.cancel_agent()."""

    def test_cancel_agent_no_client_is_noop(
        self,
        sandbox_manager: LocalSandboxManager,
    ) -> None:
        """Test that cancel_agent is a no-op when no client exists."""
        fake_sandbox_id = uuid4()
        sandbox_manager._acp_clients.pop(fake_sandbox_id, None)

        sandbox_manager.cancel_agent(fake_sandbox_id)

        # No exception means success


class TestSendMessage:
    """Tests for SandboxManager.send_message()."""

    def test_send_message_streams_events(
        self,
        sandbox_manager: LocalSandboxManager,
        db_session: Session,
        sandbox_record: Sandbox,
        temp_sandbox_dir: Path,
        tenant_context: None,
    ) -> None:
        """Test that send_message streams ACPEvent objects and ends with PromptResponse.

        Note: Heartbeat update is now handled by the caller (SessionManager),
        not by the SandboxManager itself.
        """
        sandbox_id = sandbox_record.id

        events: list[ACPEvent] = []
        for event in sandbox_manager.send_message(sandbox_id, "What is 2 + 2?"):
            events.append(event)

        # Should have received at least one event
        assert len(events) > 0

        # Last event should be PromptResponse (success) or contain results
        last_event = events[-1]
        assert isinstance(last_event, PromptResponse)

        # Cleanup: stop the ACP client
        sandbox_manager.cancel_agent(sandbox_id)
        client = sandbox_manager._acp_clients.pop(sandbox_id, None)
        if client:
            client.stop()

    def test_send_message_write_file(
        self,
        sandbox_manager: LocalSandboxManager,
        db_session: Session,
        sandbox_record: Sandbox,
        actual_sandbox_path: Path,
        tenant_context: None,
    ) -> None:
        """Test that send_message can write files and emits edit tool calls."""
        sandbox_id = sandbox_record.id

        events: list[ACPEvent] = []
        for event in sandbox_manager.send_message(
            sandbox_id,
            "Create a file called hello.txt with the content 'Hello, World!'",
        ):
            events.append(event)

        # Should have at least one ToolCallStart with kind='edit'
        tool_calls = [e for e in events if isinstance(e, ToolCallStart)]
        edit_tool_calls = [tc for tc in tool_calls if tc.kind == "edit"]
        assert len(edit_tool_calls) >= 1, (
            f"Expected at least one edit tool call, got {len(edit_tool_calls)}. "
            f"Tool calls: {[(tc.title, tc.kind) for tc in tool_calls]}"
        )

        # Last event should be PromptResponse
        last_event = events[-1]
        assert isinstance(last_event, PromptResponse)

        # Verify the file was actually created (agent writes relative to sandbox root)
        created_file = actual_sandbox_path / "hello.txt"
        assert created_file.exists(), f"Expected file {created_file} to be created"
        assert "Hello" in created_file.read_text()

        # Cleanup
        sandbox_manager.cancel_agent(sandbox_id)
        client = sandbox_manager._acp_clients.pop(sandbox_id, None)
        if client:
            client.stop()

    def test_send_message_read_file(
        self,
        sandbox_manager: LocalSandboxManager,
        db_session: Session,
        sandbox_record: Sandbox,
        actual_sandbox_path: Path,
        tenant_context: None,
    ) -> None:
        """Test that send_message can read files and emits read tool calls."""
        sandbox_id = sandbox_record.id

        # Create a file for the agent to read (at sandbox root, where agent has access)
        test_file = actual_sandbox_path / "secret.txt"
        test_file.write_text("The secret code is 12345")

        events: list[ACPEvent] = []
        for event in sandbox_manager.send_message(
            sandbox_id,
            "Read the file secret.txt and tell me what the secret code is",
        ):
            events.append(event)

        # Should have at least one ToolCallStart with kind='read'
        tool_calls = [e for e in events if isinstance(e, ToolCallStart)]
        read_tool_calls = [tc for tc in tool_calls if tc.kind == "read"]
        assert len(read_tool_calls) >= 1, (
            f"Expected at least one read tool call, got {len(read_tool_calls)}. "
            f"Tool calls: {[(tc.title, tc.kind) for tc in tool_calls]}"
        )

        # Last event should be PromptResponse
        last_event = events[-1]
        assert isinstance(last_event, PromptResponse)

        # Cleanup
        sandbox_manager.cancel_agent(sandbox_id)
        client = sandbox_manager._acp_clients.pop(sandbox_id, None)
        if client:
            client.stop()
