"""extract_file_text_locally parses by extension without touching the
database, so it is what a child process may run."""

from io import BytesIO

import openpyxl
import pytest

from onyx.file_processing.extract_file_text import extract_file_text_locally


def _workbook_bytes() -> bytes:
    workbook = openpyxl.Workbook()
    workbook.create_sheet("Totals")["A1"] = "quarterly total"
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_macro_enabled_workbooks_take_the_workbook_parser() -> None:
    text = extract_file_text_locally(BytesIO(_workbook_bytes()), "budget.xlsm")

    assert "quarterly total" in text
    assert "PK" not in text


def test_unknown_binary_raises() -> None:
    with pytest.raises(ValueError):
        extract_file_text_locally(BytesIO(b"\x00\x01\x02"), "blob.bin")
