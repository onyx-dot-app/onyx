"""extract_file_text_locally parses by extension without touching the
database, so it is what a child process may run."""

from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import openpyxl
import pytest

from onyx.file_processing.extract_file_text import extract_file_text_locally

FIXTURES = Path(__file__).parent / "fixtures"


def test_pdfium_runs_in_process_when_the_caller_is_already_isolated() -> None:
    with (
        FIXTURES.joinpath("multipage.pdf").open("rb") as pdf,
        patch(
            "onyx.file_processing.extract_file_text.run_in_isolated_process"
        ) as isolated,
    ):
        text = extract_file_text_locally(pdf, "multipage.pdf", isolate_pdfium=False)

    assert text.strip()
    isolated.assert_not_called()


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
