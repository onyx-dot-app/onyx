from io import BytesIO

import pytest

from onyx.file_store.models import ChatFileType
from onyx.server.query_and_chat import chat_utils
from onyx.server.query_and_chat.chat_utils import mime_type_to_chat_file_type


def test_mime_type_to_chat_file_type_strips_parameters() -> None:
    assert (
        mime_type_to_chat_file_type("text/csv; charset=utf-8") == ChatFileType.TABULAR
    )
    assert (
        mime_type_to_chat_file_type("application/pdf; charset=binary")
        == ChatFileType.DOC
    )
    assert (
        mime_type_to_chat_file_type("image/png; name=image.png") == ChatFileType.IMAGE
    )


def test_mime_type_to_chat_file_type_normalizes_case_and_whitespace() -> None:
    assert (
        mime_type_to_chat_file_type(" Text/CSV ; charset=utf-8") == ChatFileType.TABULAR
    )


def test_spreadsheet_preview_caps_the_text_of_all_sheets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(chat_utils, "MAX_PREVIEW_CHARS_PER_SHEET", 50)
    monkeypatch.setattr(chat_utils, "MAX_PREVIEW_CHARS_TOTAL", 120)
    # Ten sheets of 59 characters each; the sheet cap cuts each to 49, and the
    # 22 characters left cut the third to 19.
    sheet = "a,bc\n" * 11 + "z,zz"
    monkeypatch.setattr(
        chat_utils,
        "xlsx_sheet_extraction",
        lambda *_args, **_kwargs: [(sheet, f"Sheet{index}") for index in range(10)],
    )
    preview = chat_utils.parse_spreadsheet_for_preview(BytesIO(), "many.xlsx")
    assert [len(sheet.csv) for sheet in preview.sheets] == [49, 49, 19]
    assert [sheet.name for sheet in preview.sheets] == ["Sheet0", "Sheet1", "Sheet2"]
    assert all(sheet.truncated for sheet in preview.sheets)
    # Each sheet ends on a row boundary.
    assert all(sheet.csv.endswith("a,bc") for sheet in preview.sheets)


def test_spreadsheet_preview_marks_left_out_sheets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(chat_utils, "MAX_PREVIEW_CHARS_TOTAL", 8)
    monkeypatch.setattr(
        chat_utils,
        "xlsx_sheet_extraction",
        lambda *_args, **_kwargs: [("a,b\nc,d", "First"), ("e,f", "Second")],
    )
    preview = chat_utils.parse_spreadsheet_for_preview(BytesIO(), "two.xlsx")
    assert [(sheet.name, sheet.csv, sheet.truncated) for sheet in preview.sheets] == [
        ("First", "a,b\nc,d", False),
        ("Second", "", True),
    ]


def test_a_sheet_that_the_sheet_cap_cuts_uses_only_the_text_it_keeps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A first sheet over the whole budget keeps the sheet cap's 500,000
    # characters, which leaves budget for the next sheet.
    big = "a,b\n" * 750_000
    monkeypatch.setattr(
        chat_utils,
        "xlsx_sheet_extraction",
        lambda *_args, **_kwargs: [(big, "Big"), ("c,d", "Small")],
    )
    preview = chat_utils.parse_spreadsheet_for_preview(BytesIO(), "big.xlsx")
    assert len(big) > chat_utils.MAX_PREVIEW_CHARS_TOTAL
    assert [(sheet.name, sheet.truncated) for sheet in preview.sheets] == [
        ("Big", True),
        ("Small", False),
    ]
    assert len(preview.sheets[0].csv) <= chat_utils.MAX_PREVIEW_CHARS_PER_SHEET
    assert preview.sheets[1].csv == "c,d"
