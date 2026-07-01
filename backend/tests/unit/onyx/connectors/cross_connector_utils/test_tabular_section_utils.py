import io
from collections.abc import Callable
from typing import cast
from typing import IO

import openpyxl
import pytest
from openpyxl.worksheet.worksheet import Worksheet

from onyx.connectors.cross_connector_utils.tabular_section_utils import is_tabular_file
from onyx.connectors.cross_connector_utils.tabular_section_utils import (
    tabular_file_to_sections,
)


def _make_stage_callback() -> tuple[
    dict[str, tuple[bytes, str]],
    Callable[[IO[bytes], str], str],
]:
    staged: dict[str, tuple[bytes, str]] = {}

    def fake_stage(content: IO[bytes], content_type: str) -> str:
        file_id = f"csv-{len(staged)}"
        staged[file_id] = (content.read(), content_type)
        return file_id

    return staged, fake_stage


def _make_xlsx_bytes(sheets: dict[str, list[list[str]]]) -> io.BytesIO:
    wb = openpyxl.Workbook()
    if wb.active is not None:
        wb.remove(cast(Worksheet, wb.active))
    for sheet_name, rows in sheets.items():
        ws = wb.create_sheet(title=sheet_name)
        for row in rows:
            ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


class TestIsTabularFile:
    def test_recognizes_xlsm(self) -> None:
        assert is_tabular_file("CWG_Cash_Flow_Analysis.(Telcon)_.xlsm")
        assert is_tabular_file("FOO.XLSM")

    def test_recognizes_existing_extensions(self) -> None:
        assert is_tabular_file("data.xlsx")
        assert is_tabular_file("data.csv")
        assert is_tabular_file("data.tsv")

    def test_rejects_non_tabular(self) -> None:
        assert not is_tabular_file("report.pdf")
        assert not is_tabular_file("note.txt")


class TestTabularFileToSections:
    def test_xlsm_file_parsed_like_xlsx(self) -> None:
        """.xlsm uses the same OOXML container as .xlsx — openpyxl reads
        both, so tabular_file_to_sections must not reject .xlsm by name."""
        xlsm_bytes = _make_xlsx_bytes(
            {
                "Sheet1": [
                    ["Name", "Age"],
                    ["Alice", "30"],
                    ["Bob", "25"],
                ]
            }
        )

        staged, fake_stage = _make_stage_callback()
        sections = tabular_file_to_sections(
            xlsm_bytes,
            file_name="budget.xlsm",
            stage=fake_stage,
        )
        assert len(sections) == 1
        assert "Alice" in staged[sections[0].csv_file_id][0].decode("utf-8")
        assert sections[0].heading == "budget.xlsm :: Sheet1"

    def test_unknown_extension_raises(self) -> None:
        with pytest.raises(ValueError):
            tabular_file_to_sections(
                io.BytesIO(b""),
                file_name="notes.pdf",
                stage=lambda _content, _content_type: "unused",
            )

    def test_empty_csv_returns_no_sections(self) -> None:
        _staged, fake_stage = _make_stage_callback()

        sections = tabular_file_to_sections(
            io.BytesIO(b"\n\n"),
            file_name="empty.csv",
            stage=fake_stage,
        )

        assert sections == []


class TestFileBackedXlsx:
    """Every non-empty workbook sheet is staged as CSV and referenced by
    `csv_file_id`."""

    def test_sheet_is_staged_no_truncation(self) -> None:
        rows = [["name", "score"]] + [[f"user{i}", str(i)] for i in range(200)]
        xlsx = _make_xlsx_bytes({"Sheet1": rows})
        staged, fake_stage = _make_stage_callback()

        sections = tabular_file_to_sections(
            xlsx, file_name="big.xlsx", stage=fake_stage
        )

        assert len(sections) == 1
        section = sections[0]
        assert section.csv_file_id is not None
        assert section.heading == "big.xlsx :: Sheet1"

        csv_bytes, content_type = staged[section.csv_file_id]
        assert content_type == "text/csv"
        csv_text = csv_bytes.decode("utf-8")
        assert "name,score" in csv_text
        assert "user0,0" in csv_text
        assert "user199,199" in csv_text  # last row present -> no truncation
        data_rows = [line for line in csv_text.splitlines() if line.strip()]
        assert len(data_rows) == 201  # header + 200 rows

    def test_small_workbook_also_stages_sheet(self) -> None:
        xlsx = _make_xlsx_bytes({"Sheet1": [["a", "b"], ["1", "2"]]})
        staged, fake_stage = _make_stage_callback()

        sections = tabular_file_to_sections(
            xlsx, file_name="small.xlsx", stage=fake_stage
        )
        assert len(sections) == 1
        assert sections[0].csv_file_id is not None
        assert staged[sections[0].csv_file_id][0].decode("utf-8") == "a,b\n1,2\n"
