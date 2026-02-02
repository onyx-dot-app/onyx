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
from uuid import UUID
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
from onyx.db.models import User
from onyx.db.models import UserRole
from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.build.configs import SANDBOX_BASE_PATH
from onyx.server.features.build.db.build_session import allocate_nextjs_port
from onyx.server.features.build.sandbox import get_sandbox_manager
from onyx.server.features.build.sandbox.local import LocalSandboxManager
from onyx.server.features.build.sandbox.local.agent_client import ACPEvent
from onyx.server.features.build.sandbox.models import FilesystemEntry
from onyx.server.features.build.sandbox.models import LLMProviderConfig
from onyx.server.features.build.sandbox.models import SnapshotResult
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR


TEST_TENANT_ID = "public"
TEST_USER_EMAIL = "test_sandbox_user@example.com"


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
def test_user(db_session: Session, tenant_context: None) -> Generator[User, None, None]:
    """Create or get a test user for sandbox tests."""
    from sqlalchemy import select

    # Check if user already exists
    stmt = select(User).where(User.email == TEST_USER_EMAIL)  # type: ignore[arg-type]
    existing_user = db_session.execute(stmt).unique().scalar_one_or_none()

    if existing_user:
        yield existing_user
        return

    # Create new test user with required fields
    user = User(
        id=uuid4(),
        email=TEST_USER_EMAIL,
        hashed_password="test_hashed_password",  # Required NOT NULL field
        role=UserRole.BASIC,  # Required NOT NULL field
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    yield user

    # Cleanup
    existing = db_session.get(User, user.id)
    if existing:
        db_session.delete(existing)
        db_session.commit()


@pytest.fixture
def sandbox_record(
    db_session: Session, tenant_context: None, test_user: User
) -> Generator[Sandbox, None, None]:
    """Create a real Sandbox record in the database and set up sandbox directory."""
    from sqlalchemy import select

    # Check if sandbox already exists for this user (one sandbox per user)
    stmt = select(Sandbox).where(Sandbox.user_id == test_user.id)
    existing_sandbox = db_session.execute(stmt).unique().scalar_one_or_none()

    if existing_sandbox:
        # Clean up existing sandbox directory if it exists
        existing_sandbox_path = Path(SANDBOX_BASE_PATH) / str(existing_sandbox.id)
        if existing_sandbox_path.exists():
            shutil.rmtree(existing_sandbox_path, ignore_errors=True)
        # Delete existing sandbox record
        db_session.delete(existing_sandbox)
        db_session.commit()

    # Create Sandbox with reference to User (new model: one sandbox per user)
    sandbox = Sandbox(
        id=uuid4(),
        user_id=test_user.id,
        status=SandboxStatus.RUNNING,
    )
    db_session.add(sandbox)
    db_session.commit()
    db_session.refresh(sandbox)

    yield sandbox

    # Cleanup - re-fetch in case it was deleted
    existing = db_session.get(Sandbox, sandbox.id)
    if existing:
        db_session.delete(existing)
        db_session.commit()


@pytest.fixture
def build_session_record(
    db_session: Session, tenant_context: None, test_user: User
) -> Generator[BuildSession, None, None]:
    """Create a BuildSession record for testing session-specific operations."""
    build_session = BuildSession(
        id=uuid4(),
        user_id=test_user.id,
        status=BuildSessionStatus.ACTIVE,
    )
    db_session.add(build_session)
    db_session.commit()
    db_session.refresh(build_session)

    yield build_session

    # Cleanup
    existing = db_session.get(BuildSession, build_session.id)
    if existing:
        db_session.delete(existing)
        db_session.commit()


@pytest.fixture
def session_workspace(
    sandbox_manager: LocalSandboxManager,
    sandbox_record: Sandbox,
    build_session_record: BuildSession,
    db_session: Session,
) -> Generator[tuple[Sandbox, UUID], None, None]:
    """Set up a session workspace within the sandbox and return (sandbox, session_id)."""
    session_id = build_session_record.id

    # Use setup_session_workspace to create the session directory structure
    llm_config = LLMProviderConfig(
        provider="openai",
        model_name="gpt-4",
        api_key="test-api-key",
        api_base=None,
    )
    # Allocate port for this test session
    nextjs_port = allocate_nextjs_port(db_session)

    sandbox_manager.provision(
        sandbox_id=sandbox_record.id,
        user_id=sandbox_record.user_id,
        tenant_id=TEST_TENANT_ID,
        llm_config=llm_config,
    )
    sandbox_manager.setup_session_workspace(
        sandbox_id=sandbox_record.id,
        session_id=session_id,
        llm_config=llm_config,
        nextjs_port=nextjs_port,
        file_system_path=SANDBOX_BASE_PATH,
    )

    yield sandbox_record, session_id

    # Cleanup session workspace
    sandbox_manager.cleanup_session_workspace(
        sandbox_id=sandbox_record.id,
        session_id=session_id,
    )

    sandbox_manager.terminate(sandbox_record.id)


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
        session_workspace: tuple[Sandbox, UUID],
        tenant_context: None,
        file_store_initialized: None,
    ) -> None:
        """Test that create_snapshot archives the session's outputs directory.

        Note: Caller is responsible for creating DB record from the SnapshotResult.
        """
        sandbox, session_id = session_workspace
        sandbox_path = Path(SANDBOX_BASE_PATH) / str(sandbox.id)
        outputs_dir = sandbox_path / "sessions" / str(session_id) / "outputs"
        (outputs_dir / "app.py").write_text("print('hello')")

        result = sandbox_manager.create_snapshot(sandbox.id, session_id, TEST_TENANT_ID)

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
        result = sandbox_manager.health_check(sandbox_record.id)

        assert result is False


class TestListDirectory:
    """Tests for SandboxManager.list_directory()."""

    def test_list_directory_returns_entries(
        self,
        sandbox_manager: LocalSandboxManager,
        db_session: Session,
        session_workspace: tuple[Sandbox, UUID],
        tenant_context: None,
    ) -> None:
        """Test that list_directory returns filesystem entries."""
        sandbox, session_id = session_workspace
        sandbox_path = Path(SANDBOX_BASE_PATH) / str(sandbox.id)
        outputs_dir = sandbox_path / "sessions" / str(session_id)
        (outputs_dir / "file.txt").write_text("content")
        (outputs_dir / "subdir").mkdir()

        result = sandbox_manager.list_directory(sandbox.id, session_id, "/")
        print(result)

        # .agent, .venv, AGENTS.md, opencode.json, files, outputs, attachments + 2 created files
        assert len(result) == 9
        assert all(isinstance(e, FilesystemEntry) for e in result)


class TestReadFile:
    """Tests for SandboxManager.read_file()."""

    def test_read_file_returns_contents(
        self,
        sandbox_manager: LocalSandboxManager,
        db_session: Session,
        session_workspace: tuple[Sandbox, UUID],
        tenant_context: None,
    ) -> None:
        """Test that read_file returns file contents as bytes."""
        sandbox, session_id = session_workspace
        sandbox_path = Path(SANDBOX_BASE_PATH) / str(sandbox.id)
        outputs_dir = sandbox_path / "sessions" / str(session_id) / "outputs"
        (outputs_dir / "test.txt").write_bytes(b"Hello, World!")

        result = sandbox_manager.read_file(sandbox.id, session_id, "test.txt")

        assert result == b"Hello, World!"


class TestSendMessage:
    """Tests for SandboxManager.send_message()."""

    def test_send_message_streams_events(
        self,
        sandbox_manager: LocalSandboxManager,
        db_session: Session,
        session_workspace: tuple[Sandbox, UUID],
        tenant_context: None,
    ) -> None:
        """Test that send_message streams ACPEvent objects and ends with PromptResponse.

        Note: Heartbeat update is now handled by the caller (SessionManager),
        not by the SandboxManager itself.
        """
        sandbox, session_id = session_workspace

        events: list[ACPEvent] = []
        for event in sandbox_manager.send_message(
            sandbox.id, session_id, "What is 2 + 2?"
        ):
            events.append(event)

        # Should have received at least one event
        assert len(events) > 0

        # Last event should be PromptResponse (success) or contain results
        last_event = events[-1]
        assert isinstance(last_event, PromptResponse)

    def test_send_message_write_file(
        self,
        sandbox_manager: LocalSandboxManager,
        db_session: Session,
        session_workspace: tuple[Sandbox, UUID],
        tenant_context: None,
    ) -> None:
        """Test that send_message can write files and emits edit tool calls."""
        sandbox, session_id = session_workspace
        sandbox_path = Path(SANDBOX_BASE_PATH) / str(sandbox.id)
        session_path = sandbox_path / "sessions" / str(session_id)

        events: list[ACPEvent] = []
        for event in sandbox_manager.send_message(
            sandbox.id,
            session_id,
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

        # Verify the file was actually created (agent writes relative to session root)
        created_file = session_path / "hello.txt"
        assert created_file.exists(), f"Expected file {created_file} to be created"
        assert "Hello" in created_file.read_text()

    def test_send_message_read_file(
        self,
        sandbox_manager: LocalSandboxManager,
        db_session: Session,
        session_workspace: tuple[Sandbox, UUID],
        tenant_context: None,
    ) -> None:
        """Test that send_message can read files and emits read tool calls."""
        sandbox, session_id = session_workspace
        sandbox_path = Path(SANDBOX_BASE_PATH) / str(sandbox.id)
        session_path = sandbox_path / "sessions" / str(session_id)

        # Create a file for the agent to read (at session root, where agent has access)
        test_file = session_path / "secret.txt"
        test_file.write_text("The secret code is 12345")

        events: list[ACPEvent] = []
        for event in sandbox_manager.send_message(
            sandbox.id,
            session_id,
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


class TestUploadFile:
    """Tests for SandboxManager.upload_file()."""

    def test_upload_file_creates_file(
        self,
        sandbox_manager: LocalSandboxManager,
        db_session: Session,
        session_workspace: tuple[Sandbox, UUID],
        tenant_context: None,
    ) -> None:
        """Test that upload_file creates a file in the attachments directory."""
        sandbox, session_id = session_workspace
        content = b"Hello, World!"

        result = sandbox_manager.upload_file(
            sandbox.id, session_id, "test.txt", content
        )

        assert result == "attachments/test.txt"

        # Verify file exists
        sandbox_path = Path(SANDBOX_BASE_PATH) / str(sandbox.id)
        file_path = (
            sandbox_path / "sessions" / str(session_id) / "attachments" / "test.txt"
        )
        assert file_path.exists()
        assert file_path.read_bytes() == content

    def test_upload_file_handles_collision(
        self,
        sandbox_manager: LocalSandboxManager,
        db_session: Session,
        session_workspace: tuple[Sandbox, UUID],
        tenant_context: None,
    ) -> None:
        """Test that upload_file renames files on collision."""
        sandbox, session_id = session_workspace

        # Upload first file
        sandbox_manager.upload_file(sandbox.id, session_id, "test.txt", b"first")

        # Upload second file with same name
        result = sandbox_manager.upload_file(
            sandbox.id, session_id, "test.txt", b"second"
        )

        assert result == "attachments/test_1.txt"


class TestDeleteFile:
    """Tests for SandboxManager.delete_file()."""

    def test_delete_file_removes_file(
        self,
        sandbox_manager: LocalSandboxManager,
        db_session: Session,
        session_workspace: tuple[Sandbox, UUID],
        tenant_context: None,
    ) -> None:
        """Test that delete_file removes a file."""
        sandbox, session_id = session_workspace

        # Upload a file first
        sandbox_manager.upload_file(sandbox.id, session_id, "test.txt", b"content")

        # Delete it
        result = sandbox_manager.delete_file(
            sandbox.id, session_id, "attachments/test.txt"
        )

        assert result is True

        # Verify file is gone
        sandbox_path = Path(SANDBOX_BASE_PATH) / str(sandbox.id)
        file_path = (
            sandbox_path / "sessions" / str(session_id) / "attachments" / "test.txt"
        )
        assert not file_path.exists()

    def test_delete_file_returns_false_for_missing(
        self,
        sandbox_manager: LocalSandboxManager,
        db_session: Session,
        session_workspace: tuple[Sandbox, UUID],
        tenant_context: None,
    ) -> None:
        """Test that delete_file returns False for non-existent file."""
        sandbox, session_id = session_workspace

        result = sandbox_manager.delete_file(
            sandbox.id, session_id, "attachments/nonexistent.txt"
        )

        assert result is False

    def test_delete_file_rejects_path_traversal(
        self,
        sandbox_manager: LocalSandboxManager,
        db_session: Session,
        session_workspace: tuple[Sandbox, UUID],
        tenant_context: None,
    ) -> None:
        """Test that delete_file rejects path traversal attempts."""
        sandbox, session_id = session_workspace

        with pytest.raises(ValueError, match="path traversal"):
            sandbox_manager.delete_file(sandbox.id, session_id, "../../../etc/passwd")


class TestGetUploadStats:
    """Tests for SandboxManager.get_upload_stats()."""

    def test_get_upload_stats_empty(
        self,
        sandbox_manager: LocalSandboxManager,
        db_session: Session,
        session_workspace: tuple[Sandbox, UUID],
        tenant_context: None,
    ) -> None:
        """Test get_upload_stats returns zeros for empty directory."""
        sandbox, session_id = session_workspace

        file_count, total_size = sandbox_manager.get_upload_stats(
            sandbox.id, session_id
        )

        assert file_count == 0
        assert total_size == 0

    def test_get_upload_stats_with_files(
        self,
        sandbox_manager: LocalSandboxManager,
        db_session: Session,
        session_workspace: tuple[Sandbox, UUID],
        tenant_context: None,
    ) -> None:
        """Test get_upload_stats returns correct count and size."""
        sandbox, session_id = session_workspace

        # Upload some files
        sandbox_manager.upload_file(
            sandbox.id, session_id, "file1.txt", b"hello"
        )  # 5 bytes
        sandbox_manager.upload_file(
            sandbox.id, session_id, "file2.txt", b"world!"
        )  # 6 bytes

        file_count, total_size = sandbox_manager.get_upload_stats(
            sandbox.id, session_id
        )

        assert file_count == 2
        assert total_size == 11  # 5 + 6
