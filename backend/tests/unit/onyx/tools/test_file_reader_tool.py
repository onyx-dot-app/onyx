"""Tests for the FileReaderTool.

Verifies:
- Tool definition schema is well-formed
- File ID validation (allowlist, UUID format)
- Character range extraction and clamping
- Error handling for missing parameters and non-text files
- is_available() reflects DISABLE_VECTOR_DB
"""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from onyx.agents.tools import ToolInvocation
from onyx.file_store.models import ChatFileType, InMemoryChatFile
from onyx.llm.cancellation import CancellationSignal
from onyx.tools.interface import ToolContext
from onyx.tools.models import FileReadResult, ToolCallException
from onyx.tools.tool_implementations.file_reader.file_reader_tool import (
    FILE_ID_FIELD,
    MAX_NUM_CHARS,
    NUM_CHARS_FIELD,
    START_CHAR_FIELD,
    FileReaderTool,
)

TOOL_MODULE = "onyx.tools.tool_implementations.file_reader.file_reader_tool"


def _make_tool(
    user_file_ids: list | None = None,
    chat_file_ids: list | None = None,
) -> FileReaderTool:
    MagicMock()
    return FileReaderTool(
        tool_id=99,
        user_file_ids=user_file_ids or [],
        chat_file_ids=chat_file_ids or [],
    )


def _text_file(content: str, filename: str = "test.txt") -> InMemoryChatFile:
    return InMemoryChatFile(
        file_id="some-file-id",
        content=content.encode("utf-8"),
        file_type=ChatFileType.PLAIN_TEXT,
        filename=filename,
    )


# ------------------------------------------------------------------
# Tool metadata
# ------------------------------------------------------------------


class TestToolMetadata:
    def test_tool_name(self) -> None:
        tool = _make_tool()
        assert tool.name == "read_file"

    def test_tool_definition_schema(self) -> None:
        tool = _make_tool()
        defn = tool.tool_definition()
        assert defn["type"] == "function"
        func = defn["function"]
        assert func["name"] == "read_file"
        props = func["parameters"]["properties"]
        assert isinstance(props, dict)
        assert FILE_ID_FIELD in props
        assert START_CHAR_FIELD in props
        assert NUM_CHARS_FIELD in props
        assert func["parameters"]["required"] == [FILE_ID_FIELD]


# ------------------------------------------------------------------
# File ID validation
# ------------------------------------------------------------------


class TestFileIdValidation:
    def test_rejects_invalid_uuid(self) -> None:
        tool = _make_tool()
        with pytest.raises(ToolCallException, match="Invalid file_id"):
            tool._validate_file_id("not-a-uuid")

    def test_rejects_file_not_in_allowlist(self) -> None:
        tool = _make_tool(user_file_ids=[uuid4()])
        other_id = uuid4()
        with pytest.raises(ToolCallException, match="not in available files"):
            tool._validate_file_id(str(other_id))

    def test_accepts_user_file_id(self) -> None:
        uid = uuid4()
        tool = _make_tool(user_file_ids=[uid])
        assert tool._validate_file_id(str(uid)) == uid

    def test_accepts_chat_file_id(self) -> None:
        cid = uuid4()
        tool = _make_tool(chat_file_ids=[cid])
        assert tool._validate_file_id(str(cid)) == cid


# ------------------------------------------------------------------
# run() — character range extraction
# ------------------------------------------------------------------


class TestRun:
    @patch.object(FileReaderTool, "_load_file")
    def test_returns_full_content_by_default(
        self,
        mock_load_user_file: MagicMock,
    ) -> None:
        uid = uuid4()
        content = "Hello, world!"
        mock_load_user_file.return_value = _text_file(content)

        tool = _make_tool(user_file_ids=[uid])
        resp = tool.run(
            invocation=ToolInvocation(
                call_id="test",
                arguments={FILE_ID_FIELD: str(uid)},
                cancellation=CancellationSignal(),
                update=lambda _progress: None,
            ),
            context=ToolContext(),
        )
        assert content in resp.text
        assert isinstance(resp.details, FileReadResult)
        assert resp.details.file_id == str(uid)
        assert resp.details.start_char == 0
        assert resp.details.end_char == len(content)
        assert resp.details.preview_start == content

    @patch.object(FileReaderTool, "_load_file")
    def test_respects_start_char_and_num_chars(
        self,
        mock_load_user_file: MagicMock,
    ) -> None:
        uid = uuid4()
        content = "abcdefghijklmnop"
        mock_load_user_file.return_value = _text_file(content)

        tool = _make_tool(user_file_ids=[uid])
        resp = tool.run(
            invocation=ToolInvocation(
                call_id="test",
                arguments={
                    FILE_ID_FIELD: str(uid),
                    START_CHAR_FIELD: 4,
                    NUM_CHARS_FIELD: 6,
                },
                cancellation=CancellationSignal(),
                update=lambda _progress: None,
            ),
            context=ToolContext(),
        )
        assert "efghij" in resp.text

    @patch.object(FileReaderTool, "_load_file")
    def test_clamps_num_chars_to_max(
        self,
        mock_load_user_file: MagicMock,
    ) -> None:
        uid = uuid4()
        content = "x" * (MAX_NUM_CHARS + 500)
        mock_load_user_file.return_value = _text_file(content)

        tool = _make_tool(user_file_ids=[uid])
        resp = tool.run(
            invocation=ToolInvocation(
                call_id="test",
                arguments={
                    FILE_ID_FIELD: str(uid),
                    NUM_CHARS_FIELD: MAX_NUM_CHARS + 9999,
                },
                cancellation=CancellationSignal(),
                update=lambda _progress: None,
            ),
            context=ToolContext(),
        )
        assert f"Characters 0-{MAX_NUM_CHARS}" in resp.text

    @patch.object(FileReaderTool, "_load_file")
    def test_includes_continuation_hint(
        self,
        mock_load_user_file: MagicMock,
    ) -> None:
        uid = uuid4()
        content = "x" * 100
        mock_load_user_file.return_value = _text_file(content)

        tool = _make_tool(user_file_ids=[uid])
        resp = tool.run(
            invocation=ToolInvocation(
                call_id="test",
                arguments={FILE_ID_FIELD: str(uid), NUM_CHARS_FIELD: 10},
                cancellation=CancellationSignal(),
                update=lambda _progress: None,
            ),
            context=ToolContext(),
        )
        assert "use start_char=10 to continue reading" in resp.text

    def test_raises_on_missing_file_id(self) -> None:
        tool = _make_tool()
        with pytest.raises(ToolCallException, match="Missing required"):
            tool.run(
                invocation=ToolInvocation(
                    call_id="test",
                    arguments={},
                    cancellation=CancellationSignal(),
                    update=lambda _progress: None,
                ),
                context=ToolContext(),
            )

    @patch.object(FileReaderTool, "_load_file")
    def test_raises_on_non_text_file(
        self,
        mock_load_user_file: MagicMock,
    ) -> None:
        uid = uuid4()
        mock_load_user_file.return_value = InMemoryChatFile(
            file_id="img",
            content=b"\x89PNG",
            file_type=ChatFileType.IMAGE,
            filename="photo.png",
        )

        tool = _make_tool(user_file_ids=[uid])
        with pytest.raises(ToolCallException, match="not a text file"):
            tool.run(
                invocation=ToolInvocation(
                    call_id="test",
                    arguments={FILE_ID_FIELD: str(uid)},
                    cancellation=CancellationSignal(),
                    update=lambda _progress: None,
                ),
                context=ToolContext(),
            )


# ------------------------------------------------------------------
# is_available()
# ------------------------------------------------------------------


class TestIsAvailable:
    @patch(f"{TOOL_MODULE}.DISABLE_VECTOR_DB", True)
    def test_available_when_vector_db_disabled(self) -> None:
        assert FileReaderTool.is_available(MagicMock()) is True

    @patch(f"{TOOL_MODULE}.DISABLE_VECTOR_DB", False)
    def test_unavailable_when_vector_db_enabled(self) -> None:
        assert FileReaderTool.is_available(MagicMock()) is False
