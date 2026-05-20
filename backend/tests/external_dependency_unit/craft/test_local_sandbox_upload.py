"""Tests for SandboxManager upload-related public interface.

These are external dependency unit tests that use real DB sessions and filesystem.
"""

from collections.abc import Callable

from tests.external_dependency_unit.craft.conftest import SandboxHandle


class TestUploadFile:
    """Tests for SandboxManager.upload_file()."""

    def test_upload_file_creates_file(
        self,
        running_sandbox: Callable[..., SandboxHandle],
    ) -> None:
        """Test that upload_file creates a file in the attachments directory."""
        handle = running_sandbox(with_session=True)
        assert handle.session_id is not None
        content = b"Hello, World!"

        result = handle.manager.upload_file(
            handle.sandbox_id, handle.session_id, "test.txt", content
        )

        assert result == "attachments/test.txt"

        # Verify file exists
        file_path = (
            handle.workspace_path
            / "sessions"
            / str(handle.session_id)
            / "attachments"
            / "test.txt"
        )
        assert file_path.exists()
        assert file_path.read_bytes() == content

    def test_upload_file_handles_collision(
        self,
        running_sandbox: Callable[..., SandboxHandle],
    ) -> None:
        """Test that upload_file renames files on collision."""
        handle = running_sandbox(with_session=True)
        assert handle.session_id is not None

        # Upload first file
        handle.manager.upload_file(
            handle.sandbox_id, handle.session_id, "test.txt", b"first"
        )

        # Upload second file with same name
        result = handle.manager.upload_file(
            handle.sandbox_id, handle.session_id, "test.txt", b"second"
        )

        assert result == "attachments/test_1.txt"

    def test_upload_first_file_injects_agents_md_attachments_section(
        self,
        running_sandbox: Callable[..., SandboxHandle],
    ) -> None:
        """First upload injects the attachments section into AGENTS.md;
        subsequent uploads don't duplicate it.

        Pins ``_ensure_agents_md_attachments_section`` (manager side-effect
        on AGENTS.md). Observable via the session's AGENTS.md file content
        before and after the first upload.
        """
        handle = running_sandbox(with_session=True)
        assert handle.session_id is not None
        agents_md = (
            handle.workspace_path / "sessions" / str(handle.session_id) / "AGENTS.md"
        )
        assert agents_md.exists(), (
            "precondition: setup_session_workspace must write AGENTS.md"
        )

        section_marker = "## Attachments (PRIORITY)"
        before = agents_md.read_text()
        assert section_marker not in before, (
            "precondition: AGENTS.md should not yet contain the attachments section"
        )

        handle.manager.upload_file(
            handle.sandbox_id, handle.session_id, "first.txt", b"hello"
        )
        after_first = agents_md.read_text()
        assert section_marker in after_first, (
            "first upload must inject the attachments section into AGENTS.md"
        )

        # Second upload must NOT duplicate the section.
        handle.manager.upload_file(
            handle.sandbox_id, handle.session_id, "second.txt", b"world"
        )
        after_second = agents_md.read_text()
        assert after_second.count(section_marker) == 1, (
            "second upload should not duplicate the attachments section; "
            f"got {after_second.count(section_marker)} occurrences"
        )


class TestGetUploadStats:
    """Tests for SandboxManager.get_upload_stats()."""

    def test_get_upload_stats_empty(
        self,
        running_sandbox: Callable[..., SandboxHandle],
    ) -> None:
        """Test get_upload_stats returns zeros for empty directory."""
        handle = running_sandbox(with_session=True)
        assert handle.session_id is not None

        file_count, total_size = handle.manager.get_upload_stats(
            handle.sandbox_id, handle.session_id
        )

        assert file_count == 0
        assert total_size == 0

    def test_get_upload_stats_with_files(
        self,
        running_sandbox: Callable[..., SandboxHandle],
    ) -> None:
        """Test get_upload_stats returns correct count and size."""
        handle = running_sandbox(with_session=True)
        assert handle.session_id is not None

        # Upload some files
        handle.manager.upload_file(
            handle.sandbox_id, handle.session_id, "file1.txt", b"hello"
        )  # 5 bytes
        handle.manager.upload_file(
            handle.sandbox_id, handle.session_id, "file2.txt", b"world!"
        )  # 6 bytes

        file_count, total_size = handle.manager.get_upload_stats(
            handle.sandbox_id, handle.session_id
        )

        assert file_count == 2
        assert total_size == 11  # 5 + 6
