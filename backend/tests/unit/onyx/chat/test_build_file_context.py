"""build_file_context must explain empty files to the model.

An image-only PDF (or a file whose worker-side processing hasn't finished)
used to be injected as a bare "File: x\n\nEnd of File" block, which led models
to invent workarounds (web-searching for the document, guessing contents).
"""

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


def test_metadata_only_files_keep_tool_instructions() -> None:
    result = build_file_context(
        tool_file_id="abc",
        filename="sheet.xlsx",
        file_type=ChatFileType.TABULAR,
        content_text=None,
        token_count=0,
    )
    assert "file_reader" in result.message.message
    assert CONTENT_UNAVAILABLE_NOTICE not in result.message.message
