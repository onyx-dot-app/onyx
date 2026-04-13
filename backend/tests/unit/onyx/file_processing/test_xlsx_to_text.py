import io
from typing import cast

import openpyxl
from openpyxl.worksheet.worksheet import Worksheet

from onyx.file_processing.extract_file_text import xlsx_to_text


def _make_xlsx(sheets: dict[str, list[list[str]]]) -> io.BytesIO:
    """Create an in-memory xlsx file from a dict of sheet_name -> matrix of strings."""
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


class TestXlsxToText:
    def test_single_sheet_basic(self) -> None:
        xlsx = _make_xlsx(
            {
                "Sheet1": [
                    ["Name", "Age"],
                    ["Alice", "30"],
                    ["Bob", "25"],
                ]
            }
        )
        result = xlsx_to_text(xlsx)
        lines = [line for line in result.strip().split("\n") if line.strip()]
        assert len(lines) == 3
        assert "Name" in lines[0]
        assert "Age" in lines[0]
        assert "Alice" in lines[1]
        assert "30" in lines[1]
        assert "Bob" in lines[2]

    def test_multiple_sheets_separated(self) -> None:
        xlsx = _make_xlsx(
            {
                "Sheet1": [["a", "b"]],
                "Sheet2": [["c", "d"]],
            }
        )
        result = xlsx_to_text(xlsx)
        # TEXT_SECTION_SEPARATOR is "\n\n"
        assert "\n\n" in result
        parts = result.split("\n\n")
        assert any("a" in p for p in parts)
        assert any("c" in p for p in parts)

    def test_empty_cells(self) -> None:
        xlsx = _make_xlsx(
            {
                "Sheet1": [
                    ["a", "", "b"],
                    ["", "c", ""],
                ]
            }
        )
        result = xlsx_to_text(xlsx)
        lines = [line for line in result.strip().split("\n") if line.strip()]
        assert len(lines) == 2

    def test_commas_in_cells_are_quoted(self) -> None:
        """Cells containing commas should be quoted in CSV output."""
        xlsx = _make_xlsx(
            {
                "Sheet1": [
                    ["hello, world", "normal"],
                ]
            }
        )
        result = xlsx_to_text(xlsx)
        assert '"hello, world"' in result

    def test_empty_workbook(self) -> None:
        xlsx = _make_xlsx({"Sheet1": []})
        result = xlsx_to_text(xlsx)
        assert result.strip() == ""

    def test_long_empty_row_run_capped(self) -> None:
        """Runs of >2 empty rows should be capped to 2."""
        xlsx = _make_xlsx(
            {
                "Sheet1": [
                    ["header"],
                    [""],
                    [""],
                    [""],
                    [""],
                    ["data"],
                ]
            }
        )
        result = xlsx_to_text(xlsx)
        lines = [line for line in result.strip().split("\n") if line.strip()]
        # 4 empty rows capped to 2, so: header + 2 empty + data = 4 lines
        assert len(lines) == 4
        assert "header" in lines[0]
        assert "data" in lines[-1]

    def test_long_empty_col_run_capped(self) -> None:
        """Runs of >2 empty columns should be capped to 2."""
        xlsx = _make_xlsx(
            {
                "Sheet1": [
                    ["a", "", "", "", "b"],
                    ["c", "", "", "", "d"],
                ]
            }
        )
        result = xlsx_to_text(xlsx)
        lines = [line for line in result.strip().split("\n") if line.strip()]
        assert len(lines) == 2
        # Each row should have 4 fields (a + 2 empty + b), not 5
        # csv format: a,,,b (3 commas = 4 fields)
        first_line = lines[0].strip()
        # Count commas to verify column reduction
        assert first_line.count(",") == 3

    def test_short_empty_runs_kept(self) -> None:
        """Runs of <=2 empty rows/cols should be preserved."""
        xlsx = _make_xlsx(
            {
                "Sheet1": [
                    ["a", "b"],
                    ["", ""],
                    ["", ""],
                    ["c", "d"],
                ]
            }
        )
        result = xlsx_to_text(xlsx)
        lines = [line for line in result.strip().split("\n") if line.strip()]
        # All 4 rows preserved (2 empty rows <= threshold)
        assert len(lines) == 4

    def test_bad_zip_file_returns_empty(self) -> None:
        bad_file = io.BytesIO(b"not a zip file")
        result = xlsx_to_text(bad_file, file_name="test.xlsx")
        assert result == ""

    def test_bad_zip_tilde_file_returns_empty(self) -> None:
        bad_file = io.BytesIO(b"not a zip file")
        result = xlsx_to_text(bad_file, file_name="~$temp.xlsx")
        assert result == ""

    def test_large_sparse_sheet(self) -> None:
        """A sheet with data, a big empty gap, and more data — gap is capped to 2."""
        rows: list[list[str]] = [["row1_data"]]
        rows.extend([[""] for _ in range(10)])
        rows.append(["row2_data"])
        xlsx = _make_xlsx({"Sheet1": rows})
        result = xlsx_to_text(xlsx)
        lines = [line for line in result.strip().split("\n") if line.strip()]
        # 10 empty rows capped to 2: row1_data + 2 empty + row2_data = 4
        assert len(lines) == 4
        assert "row1_data" in lines[0]
        assert "row2_data" in lines[-1]

    def test_quotes_in_cells(self) -> None:
        """Cells containing quotes should be properly escaped."""
        xlsx = _make_xlsx(
            {
                "Sheet1": [
                    ['say "hello"', "normal"],
                ]
            }
        )
        result = xlsx_to_text(xlsx)
        # csv.writer escapes quotes by doubling them
        assert '""hello""' in result

    def test_each_row_is_separate_line(self) -> None:
        """Each row should produce its own line (regression for writerow vs writerows)."""
        xlsx = _make_xlsx(
            {
                "Sheet1": [
                    ["r1c1", "r1c2"],
                    ["r2c1", "r2c2"],
                    ["r3c1", "r3c2"],
                ]
            }
        )
        result = xlsx_to_text(xlsx)
        lines = [line for line in result.strip().split("\n") if line.strip()]
        assert len(lines) == 3
        assert "r1c1" in lines[0] and "r1c2" in lines[0]
        assert "r2c1" in lines[1] and "r2c2" in lines[1]
        assert "r3c1" in lines[2] and "r3c2" in lines[2]
