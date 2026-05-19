"""Tests for SandboxManager file-operations public interface.

These are external dependency unit tests that use real DB sessions and filesystem.
Covers terminate, snapshot, health check, list/read directory, send_message, and
delete_file (including path traversal rejection).

Tests for provision are not included as they require the full sandbox environment
with Next.js servers.
"""

from collections.abc import Callable

import pytest

from onyx.server.features.build.sandbox.models import FilesystemEntry
from tests.external_dependency_unit.craft.conftest import SandboxHandle


class TestTerminate:
    """Tests for SandboxManager.terminate()."""

    def test_terminate_cleans_up_resources(
        self,
        running_sandbox: Callable[..., SandboxHandle],
    ) -> None:
        """Test that terminate cleans up sandbox resources.

        Note: Status update is now handled by the caller (SessionManager/tasks),
        not by the SandboxManager itself.
        """
        handle = running_sandbox()
        handle.manager.terminate(handle.sandbox_id)
        # No exception means success - resources cleaned up


class TestCreateSnapshot:
    """Tests for SandboxManager.create_snapshot().

    Snapshot is K8s-only — ``LocalSandboxManager`` raises
    ``NotImplementedError``. The real snapshot tests live in
    ``test_snapshot_restore.py`` (K8s-gated).
    """

    @pytest.mark.skip(
        reason="create_snapshot is not implemented on LocalSandboxManager; "
        "covered by K8s-gated test_snapshot_restore.py"
    )
    def test_create_snapshot_archives_outputs(
        self,
        running_sandbox: Callable[..., SandboxHandle],  # noqa: ARG002
    ) -> None:
        """Test that create_snapshot archives the session's outputs directory."""


class TestHealthCheck:
    """Tests for SandboxManager.health_check()."""

    def test_health_check_returns_true_for_provisioned_sandbox(
        self,
        running_sandbox: Callable[..., SandboxHandle],
    ) -> None:
        """A provisioned sandbox is healthy (directory exists on disk)."""
        handle = running_sandbox()
        assert handle.manager.health_check(handle.sandbox_id) is True

    def test_health_check_returns_false_after_terminate(
        self,
        running_sandbox: Callable[..., SandboxHandle],
    ) -> None:
        """After terminate, health_check returns False (directory removed)."""
        handle = running_sandbox()
        handle.manager.terminate(handle.sandbox_id)
        assert handle.manager.health_check(handle.sandbox_id) is False


class TestListDirectory:
    """Tests for SandboxManager.list_directory()."""

    def test_list_directory_returns_entries(
        self,
        running_sandbox: Callable[..., SandboxHandle],
    ) -> None:
        """Test that list_directory returns filesystem entries."""
        handle = running_sandbox(with_session=True)
        assert handle.session_id is not None
        session_dir = handle.workspace_path / "sessions" / str(handle.session_id)
        (session_dir / "file.txt").write_text("content")
        (session_dir / "subdir").mkdir()

        result = handle.manager.list_directory(
            handle.sandbox_id, handle.session_id, "/"
        )

        assert all(isinstance(e, FilesystemEntry) for e in result)
        entry_names = {e.name for e in result}
        # The two entries this test itself created must be present.
        assert "file.txt" in entry_names
        assert "subdir" in entry_names


class TestReadFile:
    """Tests for SandboxManager.read_file()."""

    def test_read_file_returns_contents(
        self,
        running_sandbox: Callable[..., SandboxHandle],
    ) -> None:
        """Test that read_file returns file contents as bytes."""
        handle = running_sandbox(with_session=True)
        assert handle.session_id is not None
        outputs_dir = (
            handle.workspace_path / "sessions" / str(handle.session_id) / "outputs"
        )
        (outputs_dir / "test.txt").write_bytes(b"Hello, World!")

        result = handle.manager.read_file(
            handle.sandbox_id, handle.session_id, "outputs/test.txt"
        )

        assert result == b"Hello, World!"


class TestDeleteFile:
    """Tests for SandboxManager.delete_file()."""

    def test_delete_file_removes_file(
        self,
        running_sandbox: Callable[..., SandboxHandle],
    ) -> None:
        """Test that delete_file removes a file."""
        handle = running_sandbox(with_session=True)
        assert handle.session_id is not None

        # Upload a file first
        handle.manager.upload_file(
            handle.sandbox_id, handle.session_id, "test.txt", b"content"
        )

        # Delete it
        result = handle.manager.delete_file(
            handle.sandbox_id, handle.session_id, "attachments/test.txt"
        )

        assert result is True

        # Verify file is gone
        file_path = (
            handle.workspace_path
            / "sessions"
            / str(handle.session_id)
            / "attachments"
            / "test.txt"
        )
        assert not file_path.exists()

    def test_delete_file_returns_false_for_missing(
        self,
        running_sandbox: Callable[..., SandboxHandle],
    ) -> None:
        """Test that delete_file returns False for non-existent file."""
        handle = running_sandbox(with_session=True)
        assert handle.session_id is not None

        result = handle.manager.delete_file(
            handle.sandbox_id, handle.session_id, "attachments/nonexistent.txt"
        )

        assert result is False

    def test_delete_file_rejects_path_traversal(
        self,
        running_sandbox: Callable[..., SandboxHandle],
    ) -> None:
        """Test that delete_file rejects path traversal attempts."""
        handle = running_sandbox(with_session=True)
        assert handle.session_id is not None

        with pytest.raises(ValueError, match="path traversal"):
            handle.manager.delete_file(
                handle.sandbox_id, handle.session_id, "../../../etc/passwd"
            )
