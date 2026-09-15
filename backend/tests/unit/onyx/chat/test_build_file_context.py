"""build_file_context must explain empty files to the model.

An image-only PDF (or a file whose worker-side processing hasn't finished)
used to be injected as a bare "File: x\n\nEnd of File" block, which led models
to invent workarounds (web-searching for the document, guessing contents).
"""

import pytest

from onyx.chat.chat_utils import (
    CONTENT_PENDING_NOTICE,
    CONTENT_UNAVAILABLE_NOTICE,
    build_file_context,
)
from onyx.file_store.models import ChatFileType


def test_content_is_injected_verbatim() -> None:
    result = build_file_context(
        tool_file_id="abc",
        filename="doc.pdf",
        file_type=ChatFileType.DOC,
        content_text="hello world",
        token_count=3,
    )
    assert "hello world" in result.message.message
    assert CONTENT_UNAVAILABLE_NOTICE not in result.message.message
    assert result.message.token_count == 3


def test_empty_content_gets_unavailable_notice() -> None:
    result = build_file_context(
        tool_file_id="abc",
        filename="scan.pdf",
        file_type=ChatFileType.DOC,
        content_text="",
        token_count=0,
    )
    assert CONTENT_UNAVAILABLE_NOTICE in result.message.message
    assert result.message.token_count > 0


def test_whitespace_only_content_gets_unavailable_notice() -> None:
    result = build_file_context(
        tool_file_id="abc",
        filename="scan.pdf",
        file_type=ChatFileType.DOC,
        content_text="  \n\n  ",
        token_count=0,
    )
    assert CONTENT_UNAVAILABLE_NOTICE in result.message.message


def test_empty_pending_content_gets_pending_notice() -> None:
    result = build_file_context(
        tool_file_id="abc",
        filename="scan.pdf",
        file_type=ChatFileType.DOC,
        content_text=None,
        token_count=0,
        content_pending=True,
    )
    assert CONTENT_PENDING_NOTICE in result.message.message
    assert CONTENT_UNAVAILABLE_NOTICE not in result.message.message


def test_metadata_only_files_keep_tool_instructions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("onyx.chat.chat_utils.DISABLE_VECTOR_DB", True)
    result = build_file_context(
        tool_file_id="abc",
        filename="sheet.xlsx",
        file_type=ChatFileType.TABULAR,
        content_text=None,
        token_count=0,
    )
    assert "file_reader" in result.message.message
    assert CONTENT_UNAVAILABLE_NOTICE not in result.message.message


def test_metadata_only_files_omit_file_reader_when_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FileReaderTool is only attached when the vector DB is off. Naming it
    otherwise sends the model after a tool it was never given.
    """
    monkeypatch.setattr("onyx.chat.chat_utils.DISABLE_VECTOR_DB", False)
    result = build_file_context(
        tool_file_id="abc",
        filename="sheet.xlsx",
        file_type=ChatFileType.TABULAR,
        content_text=None,
        token_count=0,
    )
    assert "file_reader" not in result.message.message
    # Pin the replacement hint: dropping tools_hint entirely would otherwise
    # satisfy the negative assertion above.
    assert "internal search" in result.message.message
    assert "sheet.xlsx" in result.message.message
    # The UUID only means something to read_file, which is not attached here.
    assert "abc" not in result.message.message
    assert CONTENT_UNAVAILABLE_NOTICE not in result.message.message
