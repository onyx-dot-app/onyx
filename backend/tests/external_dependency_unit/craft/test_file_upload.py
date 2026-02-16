"""Tests for file upload functionality in build sessions.

Tests the file upload and delete operations for pre-provisioned sessions,
including limit enforcement and SandboxManager delegation.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import TYPE_CHECKING
from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import BuildSessionStatus
from onyx.db.enums import SandboxStatus
from onyx.db.models import BuildSession
from onyx.db.models import Sandbox
from onyx.db.models import User
from onyx.server.features.build.configs import ATTACHMENTS_DIRECTORY
from onyx.server.features.build.configs import MAX_TOTAL_UPLOAD_SIZE_BYTES
from onyx.server.features.build.configs import MAX_UPLOAD_FILES_PER_SESSION
from onyx.server.features.build.session.manager import UploadLimitExceededError

if TYPE_CHECKING:
    from onyx.server.features.build.session.manager import SessionManager


@pytest.fixture(scope="function")
def sandbox(
    db_session: Session, test_user: User, tenant_context: None  # noqa: ARG001
) -> Sandbox:
    """Create a test sandbox for the user (sandboxes are per-user, not per-session)."""
    sandbox = Sandbox(
        id=uuid4(),
        user_id=test_user.id,
        status=SandboxStatus.RUNNING,
    )
    db_session.add(sandbox)
    db_session.commit()
    db_session.refresh(sandbox)
    return sandbox


@pytest.fixture(scope="function")
def build_session_with_user(
    db_session: Session,
    test_user: User,
    sandbox: Sandbox,  # noqa: ARG001
    tenant_context: None,  # noqa: ARG001
) -> BuildSession:
    """Create a test build session for a user who has a sandbox."""
    session = BuildSession(
        id=uuid4(),
        user_id=test_user.id,
        name="Test Build Session",
        status=BuildSessionStatus.ACTIVE,
    )
    db_session.add(session)
    db_session.commit()
    db_session.refresh(session)
    return session


@pytest.fixture(scope="function")
def mock_sandbox_manager() -> MagicMock:
    """Create a mock sandbox manager."""
    return MagicMock()


@pytest.fixture(scope="function")
def session_manager_with_mock(
    db_session: Session, mock_sandbox_manager: MagicMock
) -> Generator["SessionManager", None, None]:
    """Create a SessionManager with mocked sandbox manager."""
    # Import here to avoid module-level initialization issues
    with patch(
        "onyx.server.features.build.session.manager.get_sandbox_manager",
        return_value=mock_sandbox_manager,
    ):
        from onyx.server.features.build.session.manager import SessionManager

        manager = SessionManager(db_session)
        yield manager


class TestFileUpload:
    """Tests for file upload functionality."""

    def test_upload_file_delegates_to_sandbox_manager(
        self,
        test_user: User,
        build_session_with_user: BuildSession,
        sandbox: Sandbox,
        mock_sandbox_manager: MagicMock,
        session_manager_with_mock: "SessionManager",
    ) -> None:
        """Test that uploading a file delegates to the sandbox manager."""
        # Configure mocks
        mock_sandbox_manager.get_upload_stats.return_value = (0, 0)
        mock_sandbox_manager.upload_file.return_value = (
            f"{ATTACHMENTS_DIRECTORY}/test.txt"
        )

        # Upload a file
        content = b"Hello, World!"
        relative_path, size = session_manager_with_mock.upload_file(
            session_id=build_session_with_user.id,
            user_id=test_user.id,
            filename="test.txt",
            content=content,
        )

        # Verify the sandbox manager was called correctly
        mock_sandbox_manager.upload_file.assert_called_once_with(
            sandbox_id=sandbox.id,
            session_id=build_session_with_user.id,
            filename="test.txt",
            content=content,
        )
        assert relative_path == f"{ATTACHMENTS_DIRECTORY}/test.txt"
        assert size == len(content)

    def test_upload_file_returns_correct_path(
        self,
        test_user: User,
        build_session_with_user: BuildSession,
        sandbox: Sandbox,  # noqa: ARG002
        mock_sandbox_manager: MagicMock,
        session_manager_with_mock: "SessionManager",
    ) -> None:
        """Test that upload returns the correct relative path."""
        mock_sandbox_manager.get_upload_stats.return_value = (0, 0)
        mock_sandbox_manager.upload_file.return_value = (
            f"{ATTACHMENTS_DIRECTORY}/document.pdf"
        )

        relative_path, size = session_manager_with_mock.upload_file(
            session_id=build_session_with_user.id,
            user_id=test_user.id,
            filename="document.pdf",
            content=b"PDF content",
        )

        assert relative_path == f"{ATTACHMENTS_DIRECTORY}/document.pdf"
        assert size == 11  # len("PDF content")

    def test_upload_file_session_not_found(
        self,
        test_user: User,
        sandbox: Sandbox,  # noqa: ARG002
        session_manager_with_mock: "SessionManager",
    ) -> None:
        """Test that uploading to a non-existent session raises ValueError."""
        with pytest.raises(ValueError, match="Session not found"):
            session_manager_with_mock.upload_file(
                session_id=uuid4(),  # Non-existent session
                user_id=test_user.id,
                filename="test.txt",
                content=b"content",
            )


class TestFileUploadLimits:
    """Tests for file upload limit enforcement."""

    def test_upload_file_count_limit_enforced(
        self,
        test_user: User,
        build_session_with_user: BuildSession,
        sandbox: Sandbox,  # noqa: ARG002
        mock_sandbox_manager: MagicMock,
        session_manager_with_mock: "SessionManager",
    ) -> None:
        """Test that exceeding the file count limit raises an error."""
        # Mock get_upload_stats to return max files already uploaded
        mock_sandbox_manager.get_upload_stats.return_value = (
            MAX_UPLOAD_FILES_PER_SESSION,
            1000,
        )

        # Try to upload one more file
        with pytest.raises(UploadLimitExceededError, match="Maximum number of files"):
            session_manager_with_mock.upload_file(
                session_id=build_session_with_user.id,
                user_id=test_user.id,
                filename="one_too_many.txt",
                content=b"content",
            )

        # Verify upload_file was NOT called (limit check happens before)
        mock_sandbox_manager.upload_file.assert_not_called()

    def test_upload_total_size_limit_enforced(
        self,
        test_user: User,
        build_session_with_user: BuildSession,
        sandbox: Sandbox,  # noqa: ARG002
        mock_sandbox_manager: MagicMock,
        session_manager_with_mock: "SessionManager",
    ) -> None:
        """Test that exceeding the total size limit raises an error."""
        # Mock get_upload_stats to return almost at the limit
        existing_size = MAX_TOTAL_UPLOAD_SIZE_BYTES - 100  # 100 bytes under limit
        mock_sandbox_manager.get_upload_stats.return_value = (1, existing_size)

        # Try to upload a file that would exceed the limit
        with pytest.raises(UploadLimitExceededError, match="Total upload size limit"):
            session_manager_with_mock.upload_file(
                session_id=build_session_with_user.id,
                user_id=test_user.id,
                filename="over_limit.txt",
                content=b"x" * 200,  # 200 bytes, would exceed by 100
            )

        # Verify upload_file was NOT called (limit check happens before)
        mock_sandbox_manager.upload_file.assert_not_called()

    def test_upload_succeeds_when_under_limits(
        self,
        test_user: User,
        build_session_with_user: BuildSession,
        sandbox: Sandbox,  # noqa: ARG002
        mock_sandbox_manager: MagicMock,
        session_manager_with_mock: "SessionManager",
    ) -> None:
        """Test that upload succeeds when under limits."""
        # Mock get_upload_stats to return well under limits
        mock_sandbox_manager.get_upload_stats.return_value = (5, 1000)
        mock_sandbox_manager.upload_file.return_value = (
            f"{ATTACHMENTS_DIRECTORY}/test.txt"
        )

        relative_path, size = session_manager_with_mock.upload_file(
            session_id=build_session_with_user.id,
            user_id=test_user.id,
            filename="test.txt",
            content=b"content",
        )

        # Verify upload_file was called
        mock_sandbox_manager.upload_file.assert_called_once()
        assert relative_path == f"{ATTACHMENTS_DIRECTORY}/test.txt"


class TestFileDelete:
    """Tests for file delete functionality."""

    def test_delete_file_delegates_to_sandbox_manager(
        self,
        test_user: User,
        build_session_with_user: BuildSession,
        sandbox: Sandbox,
        mock_sandbox_manager: MagicMock,
        session_manager_with_mock: "SessionManager",
    ) -> None:
        """Test that delete file delegates to the sandbox manager."""
        mock_sandbox_manager.delete_file.return_value = True

        result = session_manager_with_mock.delete_file(
            session_id=build_session_with_user.id,
            user_id=test_user.id,
            path=f"{ATTACHMENTS_DIRECTORY}/test.txt",
        )

        assert result is True
        mock_sandbox_manager.delete_file.assert_called_once_with(
            sandbox_id=sandbox.id,
            session_id=build_session_with_user.id,
            path=f"{ATTACHMENTS_DIRECTORY}/test.txt",
        )

    def test_delete_file_returns_false_when_not_found(
        self,
        test_user: User,
        build_session_with_user: BuildSession,
        sandbox: Sandbox,  # noqa: ARG002
        mock_sandbox_manager: MagicMock,
        session_manager_with_mock: "SessionManager",
    ) -> None:
        """Test that delete returns False when file doesn't exist."""
        mock_sandbox_manager.delete_file.return_value = False

        result = session_manager_with_mock.delete_file(
            session_id=build_session_with_user.id,
            user_id=test_user.id,
            path=f"{ATTACHMENTS_DIRECTORY}/nonexistent.txt",
        )

        assert result is False

    def test_delete_file_session_not_found(
        self,
        test_user: User,
        sandbox: Sandbox,  # noqa: ARG002
        session_manager_with_mock: "SessionManager",
    ) -> None:
        """Test that deleting from a non-existent session raises ValueError."""
        with pytest.raises(ValueError, match="Session not found"):
            session_manager_with_mock.delete_file(
                session_id=uuid4(),  # Non-existent session
                user_id=test_user.id,
                path=f"{ATTACHMENTS_DIRECTORY}/test.txt",
            )


class TestPathSanitization:
    """Tests for path sanitization in delete operations."""

    def test_delete_file_rejects_path_traversal(
        self,
        test_user: User,
        build_session_with_user: BuildSession,
        sandbox: Sandbox,  # noqa: ARG002
        mock_sandbox_manager: MagicMock,
        session_manager_with_mock: "SessionManager",
    ) -> None:
        """Test that paths with .. are rejected."""
        # Configure mock to raise ValueError (simulating sandbox manager behavior)
        mock_sandbox_manager.delete_file.side_effect = ValueError(
            "Invalid path: potential path traversal detected"
        )

        with pytest.raises(ValueError, match="path traversal"):
            session_manager_with_mock.delete_file(
                session_id=build_session_with_user.id,
                user_id=test_user.id,
                path="../../../etc/passwd",
            )

    def test_delete_file_rejects_url_encoded_traversal(
        self,
        test_user: User,
        build_session_with_user: BuildSession,
        sandbox: Sandbox,  # noqa: ARG002
        mock_sandbox_manager: MagicMock,
        session_manager_with_mock: "SessionManager",
    ) -> None:
        """Test that URL-encoded paths are rejected."""
        mock_sandbox_manager.delete_file.side_effect = ValueError(
            "Invalid path: potential path traversal detected"
        )

        with pytest.raises(ValueError, match="path traversal"):
            session_manager_with_mock.delete_file(
                session_id=build_session_with_user.id,
                user_id=test_user.id,
                path="attachments/%2e%2e/secret.txt",
            )

    def test_delete_file_rejects_shell_metacharacters(
        self,
        test_user: User,
        build_session_with_user: BuildSession,
        sandbox: Sandbox,  # noqa: ARG002
        mock_sandbox_manager: MagicMock,
        session_manager_with_mock: "SessionManager",
    ) -> None:
        """Test that shell metacharacters are rejected."""
        mock_sandbox_manager.delete_file.side_effect = ValueError(
            "Invalid path: contains disallowed characters"
        )

        dangerous_paths = [
            "attachments/file;rm -rf /",
            "attachments/file|cat /etc/passwd",
            "attachments/file`whoami`",
            "attachments/file$(id)",
            "attachments/file'test",
        ]

        for dangerous_path in dangerous_paths:
            with pytest.raises(ValueError, match="disallowed characters"):
                session_manager_with_mock.delete_file(
                    session_id=build_session_with_user.id,
                    user_id=test_user.id,
                    path=dangerous_path,
                )
            # Reset mock for next iteration
            mock_sandbox_manager.delete_file.reset_mock()

    def test_delete_file_rejects_null_bytes(
        self,
        test_user: User,
        build_session_with_user: BuildSession,
        sandbox: Sandbox,  # noqa: ARG002
        mock_sandbox_manager: MagicMock,
        session_manager_with_mock: "SessionManager",
    ) -> None:
        """Test that null bytes in paths are rejected."""
        mock_sandbox_manager.delete_file.side_effect = ValueError(
            "Invalid path: potential path traversal detected"
        )

        with pytest.raises(ValueError, match="path traversal"):
            session_manager_with_mock.delete_file(
                session_id=build_session_with_user.id,
                user_id=test_user.id,
                path="attachments/file.txt\x00.jpg",
            )


class TestFilenameCollision:
    """Tests for filename collision handling."""

    def test_upload_returns_collision_handled_path(
        self,
        test_user: User,
        build_session_with_user: BuildSession,
        sandbox: Sandbox,  # noqa: ARG002
        mock_sandbox_manager: MagicMock,
        session_manager_with_mock: "SessionManager",
    ) -> None:
        """Test that sandbox manager can return a renamed path for collisions."""
        # Simulate sandbox manager handling collision by returning renamed path
        mock_sandbox_manager.get_upload_stats.return_value = (1, 100)  # 1 existing file
        mock_sandbox_manager.upload_file.return_value = (
            f"{ATTACHMENTS_DIRECTORY}/document_1.pdf"
        )

        relative_path, size = session_manager_with_mock.upload_file(
            session_id=build_session_with_user.id,
            user_id=test_user.id,
            filename="document.pdf",
            content=b"PDF content",
        )

        # Verify the collision-handled path is returned
        assert relative_path == f"{ATTACHMENTS_DIRECTORY}/document_1.pdf"


class TestGetUploadStats:
    """Tests for get_upload_stats functionality."""

    def test_get_upload_stats_delegates_to_sandbox_manager(
        self,
        test_user: User,
        build_session_with_user: BuildSession,
        sandbox: Sandbox,
        mock_sandbox_manager: MagicMock,
        session_manager_with_mock: "SessionManager",
    ) -> None:
        """Test that get_upload_stats delegates to the sandbox manager."""
        mock_sandbox_manager.get_upload_stats.return_value = (3, 1500)

        file_count, total_size = session_manager_with_mock.get_upload_stats(
            session_id=build_session_with_user.id,
            user_id=test_user.id,
        )

        # Verify the sandbox manager was called correctly
        mock_sandbox_manager.get_upload_stats.assert_called_once_with(
            sandbox_id=sandbox.id,
            session_id=build_session_with_user.id,
        )
        assert file_count == 3
        assert total_size == 1500

    def test_get_upload_stats_session_not_found(
        self,
        test_user: User,
        sandbox: Sandbox,  # noqa: ARG002
        session_manager_with_mock: "SessionManager",
    ) -> None:
        """Test that getting stats for non-existent session raises ValueError."""
        with pytest.raises(ValueError, match="Session not found"):
            session_manager_with_mock.get_upload_stats(
                session_id=uuid4(),  # Non-existent session
                user_id=test_user.id,
            )
