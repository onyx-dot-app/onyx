import io
from typing import cast

import openpyxl
import pytest
from openpyxl.worksheet.worksheet import Worksheet

from onyx.connectors.cross_connector_utils.tabular_section_utils import (
    is_tabular_file,
)
from onyx.connectors.cross_connector_utils.tabular_section_utils import (
    tabular_file_to_sections,
)


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

        sections = tabular_file_to_sections(
            xlsm_bytes,
            file_name="budget.xlsm",
        )
        assert len(sections) == 1
        assert "Alice" in sections[0].text
        assert sections[0].heading == "budget.xlsm :: Sheet1"

    def test_unknown_extension_raises(self) -> None:
        with pytest.raises(ValueError):
            tabular_file_to_sections(io.BytesIO(b""), file_name="notes.pdf")
