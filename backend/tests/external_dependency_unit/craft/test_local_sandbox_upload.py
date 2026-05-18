"""Tests for SandboxManager upload-related public interface.

These are external dependency unit tests that use real DB sessions and filesystem.
"""

import shutil
import tempfile
from collections.abc import Generator
from pathlib import Path
from uuid import UUID
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

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
from tests.external_dependency_unit.constants import TEST_TENANT_ID
from tests.external_dependency_unit.craft._test_helpers import default_llm_config

TEST_USER_EMAIL = "test_sandbox_user@example.com"


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
def test_user(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[User, None, None]:
    """Create or get a test user for sandbox tests."""
    # Check if user already exists
    stmt = select(User).where(
        User.email == TEST_USER_EMAIL  # ty: ignore[invalid-argument-type]
    )
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
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    test_user: User,
) -> Generator[Sandbox, None, None]:
    """Create a real Sandbox record in the database and set up sandbox directory."""
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
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    test_user: User,
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
    llm_config = default_llm_config()
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
        skills_section="No skills available.",
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


class TestUploadFile:
    """Tests for SandboxManager.upload_file()."""

    def test_upload_file_creates_file(
        self,
        sandbox_manager: LocalSandboxManager,
        db_session: Session,  # noqa: ARG002
        session_workspace: tuple[Sandbox, UUID],
        tenant_context: None,  # noqa: ARG002
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
        db_session: Session,  # noqa: ARG002
        session_workspace: tuple[Sandbox, UUID],
        tenant_context: None,  # noqa: ARG002
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

    def test_upload_first_file_injects_agents_md_attachments_section(
        self,
        sandbox_manager: LocalSandboxManager,
        db_session: Session,  # noqa: ARG002
        session_workspace: tuple[Sandbox, UUID],
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """First upload injects the attachments section into AGENTS.md;
        subsequent uploads don't duplicate it.

        Pins ``_ensure_agents_md_attachments_section`` (Cluster O — manager
        side-effect on AGENTS.md). Observable via the session's AGENTS.md
        file content before and after the first upload.
        """
        sandbox, session_id = session_workspace
        sandbox_path = Path(SANDBOX_BASE_PATH) / str(sandbox.id)
        agents_md = sandbox_path / "sessions" / str(session_id) / "AGENTS.md"
        assert agents_md.exists(), (
            "precondition: setup_session_workspace must write AGENTS.md"
        )

        section_marker = "## Attachments (PRIORITY)"
        before = agents_md.read_text()
        assert section_marker not in before, (
            "precondition: AGENTS.md should not yet contain the attachments section"
        )

        sandbox_manager.upload_file(sandbox.id, session_id, "first.txt", b"hello")
        after_first = agents_md.read_text()
        assert section_marker in after_first, (
            "first upload must inject the attachments section into AGENTS.md"
        )

        # Second upload must NOT duplicate the section.
        sandbox_manager.upload_file(sandbox.id, session_id, "second.txt", b"world")
        after_second = agents_md.read_text()
        assert after_second.count(section_marker) == 1, (
            "second upload should not duplicate the attachments section; "
            f"got {after_second.count(section_marker)} occurrences"
        )


class TestGetUploadStats:
    """Tests for SandboxManager.get_upload_stats()."""

    def test_get_upload_stats_empty(
        self,
        sandbox_manager: LocalSandboxManager,
        db_session: Session,  # noqa: ARG002
        session_workspace: tuple[Sandbox, UUID],
        tenant_context: None,  # noqa: ARG002
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
        db_session: Session,  # noqa: ARG002
        session_workspace: tuple[Sandbox, UUID],
        tenant_context: None,  # noqa: ARG002
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
