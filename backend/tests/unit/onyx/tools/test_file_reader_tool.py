"""Tests for the FileReaderTool.

Verifies:
- Tool definition schema is well-formed
- File ID validation (allowlist, UUID format)
- Character range extraction and clamping
- Error handling for missing parameters and non-text files
- is_available() reflects DISABLE_VECTOR_DB
"""

from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import uuid4

import pytest

from onyx.file_store.models import ChatFileType
from onyx.file_store.models import InMemoryChatFile
from onyx.server.query_and_chat.placement import Placement
from onyx.tools.models import ToolCallException
from onyx.tools.tool_implementations.file_reader.file_reader_tool import FILE_ID_FIELD
from onyx.tools.tool_implementations.file_reader.file_reader_tool import FileReaderTool
from onyx.tools.tool_implementations.file_reader.file_reader_tool import MAX_NUM_CHARS
from onyx.tools.tool_implementations.file_reader.file_reader_tool import NUM_CHARS_FIELD
from onyx.tools.tool_implementations.file_reader.file_reader_tool import (
    START_CHAR_FIELD,
)

TOOL_MODULE = "onyx.tools.tool_implementations.file_reader.file_reader_tool"
_PLACEMENT = Placement(turn_index=0)


def _make_tool(
    user_file_ids: list | None = None,
    chat_file_ids: list | None = None,
) -> FileReaderTool:
    emitter = MagicMock()
    return FileReaderTool(
        tool_id=99,
        emitter=emitter,
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
    @patch(f"{TOOL_MODULE}.get_session_with_current_tenant")
    @patch(f"{TOOL_MODULE}.load_user_file")
    def test_returns_full_content_by_default(
        self,
        mock_load_user_file: MagicMock,
        mock_get_session: MagicMock,
    ) -> None:
        uid = uuid4()
        content = "Hello, world!"
        mock_load_user_file.return_value = _text_file(content)
        mock_get_session.return_value.__enter__.return_value = MagicMock()

        tool = _make_tool(user_file_ids=[uid])
        resp = tool.run(
            placement=_PLACEMENT,
            override_kwargs=MagicMock(),
            **{FILE_ID_FIELD: str(uid)},
        )
        assert content in resp.llm_facing_response

    @patch(f"{TOOL_MODULE}.get_session_with_current_tenant")
    @patch(f"{TOOL_MODULE}.load_user_file")
    def test_respects_start_char_and_num_chars(
        self,
        mock_load_user_file: MagicMock,
        mock_get_session: MagicMock,
    ) -> None:
        uid = uuid4()
        content = "abcdefghijklmnop"
        mock_load_user_file.return_value = _text_file(content)
        mock_get_session.return_value.__enter__.return_value = MagicMock()

        tool = _make_tool(user_file_ids=[uid])
        resp = tool.run(
            placement=_PLACEMENT,
            override_kwargs=MagicMock(),
            **{FILE_ID_FIELD: str(uid), START_CHAR_FIELD: 4, NUM_CHARS_FIELD: 6},
        )
        assert "efghij" in resp.llm_facing_response

    @patch(f"{TOOL_MODULE}.get_session_with_current_tenant")
    @patch(f"{TOOL_MODULE}.load_user_file")
    def test_clamps_num_chars_to_max(
        self,
        mock_load_user_file: MagicMock,
        mock_get_session: MagicMock,
    ) -> None:
        uid = uuid4()
        content = "x" * (MAX_NUM_CHARS + 500)
        mock_load_user_file.return_value = _text_file(content)
        mock_get_session.return_value.__enter__.return_value = MagicMock()

        tool = _make_tool(user_file_ids=[uid])
        resp = tool.run(
            placement=_PLACEMENT,
            override_kwargs=MagicMock(),
            **{FILE_ID_FIELD: str(uid), NUM_CHARS_FIELD: MAX_NUM_CHARS + 9999},
        )
        assert f"Characters 0-{MAX_NUM_CHARS}" in resp.llm_facing_response

    @patch(f"{TOOL_MODULE}.get_session_with_current_tenant")
    @patch(f"{TOOL_MODULE}.load_user_file")
    def test_includes_continuation_hint(
        self,
        mock_load_user_file: MagicMock,
        mock_get_session: MagicMock,
    ) -> None:
        uid = uuid4()
        content = "x" * 100
        mock_load_user_file.return_value = _text_file(content)
        mock_get_session.return_value.__enter__.return_value = MagicMock()

        tool = _make_tool(user_file_ids=[uid])
        resp = tool.run(
            placement=_PLACEMENT,
            override_kwargs=MagicMock(),
            **{FILE_ID_FIELD: str(uid), NUM_CHARS_FIELD: 10},
        )
        assert "use start_char=10 to continue reading" in resp.llm_facing_response

    def test_raises_on_missing_file_id(self) -> None:
        tool = _make_tool()
        with pytest.raises(ToolCallException, match="Missing required"):
            tool.run(
                placement=_PLACEMENT,
                override_kwargs=MagicMock(),
            )

    @patch(f"{TOOL_MODULE}.get_session_with_current_tenant")
    @patch(f"{TOOL_MODULE}.load_user_file")
    def test_raises_on_non_text_file(
        self,
        mock_load_user_file: MagicMock,
        mock_get_session: MagicMock,
    ) -> None:
        uid = uuid4()
        mock_load_user_file.return_value = InMemoryChatFile(
            file_id="img",
            content=b"\x89PNG",
            file_type=ChatFileType.IMAGE,
            filename="photo.png",
        )
        mock_get_session.return_value.__enter__.return_value = MagicMock()

        tool = _make_tool(user_file_ids=[uid])
        with pytest.raises(ToolCallException, match="not a text file"):
            tool.run(
                placement=_PLACEMENT,
                override_kwargs=MagicMock(),
                **{FILE_ID_FIELD: str(uid)},
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
