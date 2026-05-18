"""Tests for SandboxManager file-operations public interface.

These are external dependency unit tests that use real DB sessions and filesystem.
Covers terminate, snapshot, health check, list/read directory, send_message, and
delete_file (including path traversal rejection).

Tests for provision are not included as they require the full sandbox environment
with Next.js servers.
"""

from collections.abc import Callable

import pytest
from acp.schema import PromptResponse
from acp.schema import ToolCallStart

from onyx.server.features.build.sandbox.local.agent_client import ACPEvent
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
            handle.sandbox_id, handle.session_id, "test.txt"
        )

        assert result == b"Hello, World!"


class TestSendMessage:
    """Tests for SandboxManager.send_message()."""

    def test_send_message_streams_events(
        self,
        running_sandbox: Callable[..., SandboxHandle],
    ) -> None:
        """Test that send_message streams ACPEvent objects and ends with PromptResponse.

        Note: Heartbeat update is now handled by the caller (SessionManager),
        not by the SandboxManager itself.
        """
        handle = running_sandbox(with_session=True)
        assert handle.session_id is not None

        events: list[ACPEvent] = []
        for event in handle.manager.send_message(
            handle.sandbox_id, handle.session_id, "What is 2 + 2?"
        ):
            events.append(event)

        # Should have received at least one event
        assert len(events) > 0

        # Last event should be PromptResponse (success) or contain results
        last_event = events[-1]
        assert isinstance(last_event, PromptResponse)

    def test_send_message_write_file(
        self,
        running_sandbox: Callable[..., SandboxHandle],
    ) -> None:
        """Test that send_message can write files and emits edit tool calls."""
        handle = running_sandbox(with_session=True)
        assert handle.session_id is not None
        session_path = handle.workspace_path / "sessions" / str(handle.session_id)

        events: list[ACPEvent] = []
        for event in handle.manager.send_message(
            handle.sandbox_id,
            handle.session_id,
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
        running_sandbox: Callable[..., SandboxHandle],
    ) -> None:
        """Test that send_message can read files and emits read tool calls."""
        handle = running_sandbox(with_session=True)
        assert handle.session_id is not None
        session_path = handle.workspace_path / "sessions" / str(handle.session_id)

        # Create a file for the agent to read (at session root, where agent has access)
        test_file = session_path / "secret.txt"
        test_file.write_text("The secret code is 12345")

        events: list[ACPEvent] = []
        for event in handle.manager.send_message(
            handle.sandbox_id,
            handle.session_id,
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
