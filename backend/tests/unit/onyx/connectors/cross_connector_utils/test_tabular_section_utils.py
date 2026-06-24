import io
from typing import cast
from typing import IO

import openpyxl
import pytest
from openpyxl.worksheet.worksheet import Worksheet

from onyx.connectors.cross_connector_utils.tabular_section_utils import is_tabular_file
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
        assert "Alice" in (sections[0].text or "")
        assert sections[0].heading == "budget.xlsm :: Sheet1"

    def test_unknown_extension_raises(self) -> None:
        with pytest.raises(ValueError):
            tabular_file_to_sections(io.BytesIO(b""), file_name="notes.pdf")


class TestFileBackedXlsx:
    """Within a workbook routed to streaming, each sheet is handled by size:
    oversized sheets are file-backed (no inline text, not truncated); small
    sheets stay inline so they keep their descriptor chunks downstream."""

    def test_oversized_sheet_is_file_backed_no_truncation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import onyx.connectors.cross_connector_utils.tabular_section_utils as mod

        rows = [["name", "score"]] + [[f"user{i}", str(i)] for i in range(200)]
        xlsx = _make_xlsx_bytes({"Sheet1": rows})
        # Enter the streaming path and force this sheet over the inline threshold
        # without needing a multi-MB fixture.
        monkeypatch.setattr(mod, "xlsx_has_large_sheet", lambda _f: True)
        monkeypatch.setattr(mod, "XLSX_STREAM_SHEET_BYTES", 10)

        staged: dict[str, tuple[bytes, str]] = {}

        def fake_callback(content: IO[bytes], content_type: str) -> str:
            file_id = f"csv-{len(staged)}"
            staged[file_id] = (content.read(), content_type)
            return file_id

        sections = mod.tabular_file_to_sections(
            xlsx, file_name="big.xlsx", raw_file_callback=fake_callback
        )

        assert len(sections) == 1
        section = sections[0]
        assert section.text is None
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

    def test_small_sheet_in_streaming_workbook_stays_inline(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import onyx.connectors.cross_connector_utils.tabular_section_utils as mod

        xlsx = _make_xlsx_bytes({"Sheet1": [["a", "b"], ["1", "2"]]})
        # Streaming path, but this sheet is tiny -> inline (keeps descriptors).
        monkeypatch.setattr(mod, "xlsx_has_large_sheet", lambda _f: True)
        sections = mod.tabular_file_to_sections(
            xlsx, file_name="mixed.xlsx", raw_file_callback=lambda _c, _t: "unused"
        )
        assert len(sections) == 1
        assert sections[0].csv_file_id is None
        assert "a,b" in (sections[0].text or "")

    def test_small_workbook_uses_inline_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import onyx.connectors.cross_connector_utils.tabular_section_utils as mod

        xlsx = _make_xlsx_bytes({"Sheet1": [["a", "b"], ["1", "2"]]})
        monkeypatch.setattr(mod, "xlsx_has_large_sheet", lambda _f: False)
        sections = mod.tabular_file_to_sections(
            xlsx, file_name="small.xlsx", raw_file_callback=lambda _c, _t: "unused"
        )
        assert len(sections) == 1
        assert sections[0].csv_file_id is None
        assert "a,b" in (sections[0].text or "")
