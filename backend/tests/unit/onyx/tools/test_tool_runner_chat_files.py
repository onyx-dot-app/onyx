"""
Unit tests for chat_files handling in tool_runner.py.

These tests verify that chat files are properly passed to PythonTool
through the PythonToolOverrideKwargs mechanism.
"""

import pytest

from onyx.tools.models import ChatFile
from onyx.tools.models import PythonToolOverrideKwargs


class TestChatFilesPassingToPythonTool:
    """Tests for passing chat_files to PythonTool."""

    @pytest.fixture
    def sample_chat_files(self) -> list[ChatFile]:
        """Create sample chat files for testing."""
        return [
            ChatFile(filename="test.xlsx", content=b"excel content"),
            ChatFile(filename="data.csv", content=b"col1,col2\n1,2\n3,4"),
        ]

    def test_chat_files_passed_to_python_tool_override_kwargs(
        self,
        sample_chat_files: list[ChatFile],
    ) -> None:
        """Test that PythonToolOverrideKwargs correctly stores chat_files."""
        # Verify the override_kwargs structure stores chat_files correctly
        override_kwargs = PythonToolOverrideKwargs(chat_files=sample_chat_files)

        assert override_kwargs.chat_files == sample_chat_files
        assert len(override_kwargs.chat_files) == 2
        assert override_kwargs.chat_files[0].filename == "test.xlsx"
        assert override_kwargs.chat_files[0].content == b"excel content"
        assert override_kwargs.chat_files[1].filename == "data.csv"

    def test_empty_chat_files_defaults_to_empty_list(self) -> None:
        """Test that empty chat_files defaults to empty list."""
        override_kwargs = PythonToolOverrideKwargs()
        assert override_kwargs.chat_files == []

    def test_none_chat_files_handled_in_tool_runner(self) -> None:
        """Test that None chat_files are handled gracefully in the tool_runner code path.

        The tool_runner.py uses `chat_files or []` pattern when creating
        PythonToolOverrideKwargs, so we verify this pattern works correctly.
        """
        # Simulate the pattern used in tool_runner.py:
        # override_kwargs = PythonToolOverrideKwargs(chat_files=chat_files or [])
        chat_files_param: list[ChatFile] | None = None

        # This is the exact pattern used in tool_runner.py
        override_kwargs = PythonToolOverrideKwargs(
            chat_files=chat_files_param or [],
        )

        assert override_kwargs.chat_files == []
        assert isinstance(override_kwargs.chat_files, list)


class TestChatFileConversion:
    """Tests for ChatLoadedFile to ChatFile conversion."""

    def test_convert_loaded_files_to_chat_files(self) -> None:
        """Test conversion of ChatLoadedFile to ChatFile."""
        from onyx.chat.models import ChatLoadedFile
        from onyx.chat.process_message import _convert_loaded_files_to_chat_files
        from onyx.file_store.models import ChatFileType

        # Create sample ChatLoadedFile objects
        loaded_files = [
            ChatLoadedFile(
                file_id="file-1",
                content=b"test content 1",
                file_type=ChatFileType.DOC,
                filename="document.pdf",
                content_text="parsed text",
                token_count=10,
            ),
            ChatLoadedFile(
                file_id="file-2",
                content=b"csv,data\n1,2",
                file_type=ChatFileType.CSV,
                filename="data.csv",
                content_text="csv,data\n1,2",
                token_count=5,
            ),
        ]

        # Convert to ChatFile
        chat_files = _convert_loaded_files_to_chat_files(loaded_files)

        assert len(chat_files) == 2
        assert chat_files[0].filename == "document.pdf"
        assert chat_files[0].content == b"test content 1"
        assert chat_files[1].filename == "data.csv"
        assert chat_files[1].content == b"csv,data\n1,2"

    def test_convert_files_with_none_content_skipped(self) -> None:
        """Test that files with None content are skipped."""
        from onyx.chat.models import ChatLoadedFile
        from onyx.chat.process_message import _convert_loaded_files_to_chat_files
        from onyx.file_store.models import ChatFileType

        loaded_files = [
            ChatLoadedFile(
                file_id="file-1",
                content=b"valid content",
                file_type=ChatFileType.DOC,
                filename="valid.pdf",
                content_text="text",
                token_count=10,
            ),
            ChatLoadedFile(
                file_id="file-2",
                content=b"",
                file_type=ChatFileType.DOC,
                filename="invalid.pdf",
                content_text=None,
                token_count=0,
            ),
        ]

        chat_files = _convert_loaded_files_to_chat_files(loaded_files)

        # Only the file with valid content should be included
        assert len(chat_files) == 1
        assert chat_files[0].filename == "valid.pdf"

    def test_convert_files_with_missing_filename_uses_fallback(self) -> None:
        """Test that files without filename use file_id as fallback."""
        from onyx.chat.models import ChatLoadedFile
        from onyx.chat.process_message import _convert_loaded_files_to_chat_files
        from onyx.file_store.models import ChatFileType

        loaded_files = [
            ChatLoadedFile(
                file_id="abc123",
                content=b"content",
                file_type=ChatFileType.DOC,
                filename=None,
                content_text="text",
                token_count=5,
            ),
        ]

        chat_files = _convert_loaded_files_to_chat_files(loaded_files)

        assert len(chat_files) == 1
        assert chat_files[0].filename == "file_abc123"

    def test_convert_empty_list_returns_empty(self) -> None:
        """Test that empty input returns empty output."""
        from onyx.chat.process_message import _convert_loaded_files_to_chat_files

        chat_files = _convert_loaded_files_to_chat_files([])
        assert chat_files == []


class TestChatFileModel:
    """Tests for the ChatFile model itself."""

    def test_chat_file_creation(self) -> None:
        """Test ChatFile model creation."""
        chat_file = ChatFile(
            filename="test.xlsx",
            content=b"binary content",
        )

        assert chat_file.filename == "test.xlsx"
        assert chat_file.content == b"binary content"

    def test_chat_file_with_unicode_filename(self) -> None:
        """Test ChatFile with unicode filename."""
        chat_file = ChatFile(
            filename="报告.xlsx",
            content=b"content",
        )

        assert chat_file.filename == "报告.xlsx"

    def test_chat_file_with_spaces_in_filename(self) -> None:
        """Test ChatFile with spaces in filename."""
        chat_file = ChatFile(
            filename="my file name.xlsx",
            content=b"content",
        )

        assert chat_file.filename == "my file name.xlsx"
