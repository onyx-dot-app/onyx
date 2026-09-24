"""Guards that legacy .xls workbooks are read, and reach the paths connectors use.

Onyx accepted a .xls, extracted nothing, and raised no error, so the file indexed as an
empty document. Three separate gates had to open — the extension map, the connector's
spreadsheet gate, and the staging path — and the first two alone changed nothing, which is
why each has its own test here rather than one end-to-end assertion.

The fixture is synthetic and deliberately exercises every xlrd cell type: text, integer,
float, date (stored as a float and distinguished only by cell type), boolean and empty.
"""

from io import BytesIO
from pathlib import Path

from onyx.file_processing.extract_file_text import (
    extract_file_text_locally,
    stage_spreadsheet_sheets,
    xls_sheet_extraction,
    xls_to_text,
)
from onyx.file_processing.file_types import OnyxFileExtensions

FIXTURES = Path(__file__).parent / "fixtures"
LEGACY = FIXTURES / "legacy_workbook.xls"


def _fixture() -> BytesIO:
    return BytesIO(LEGACY.read_bytes())


def test_a_legacy_workbook_yields_its_text() -> None:
    text = xls_to_text(_fixture(), "legacy_workbook.xls")

    assert "Widget Pro" in text
    assert "Widget Lite" in text
    assert text.strip(), "an .xls previously produced the empty string with no error"


def test_every_sheet_is_read_not_just_the_first() -> None:
    text = xls_to_text(_fixture(), "legacy_workbook.xls")

    assert "SHEET2-TOKEN" in text


def test_sheet_titles_are_returned() -> None:
    titles = [title for _csv, title in xls_sheet_extraction(_fixture(), "legacy.xls")]

    assert titles == ["Entitlements", "Notes"]


def test_an_integer_does_not_gain_a_decimal_point() -> None:
    """xlrd returns every number as a float, so a naive reader indexes 2520 as '2520.0'
    and a search for the figure as written in the sheet misses it."""
    text = xls_to_text(_fixture(), "legacy_workbook.xls")

    assert "2520" in text
    assert "2520.0" not in text


def test_a_float_keeps_its_fraction() -> None:
    text = xls_to_text(_fixture(), "legacy_workbook.xls")

    assert "1250.5" in text


def test_a_date_is_not_indexed_as_a_serial_number() -> None:
    """A date is a float distinguished only by cell type. Read naively it indexes as
    '46295.0', which answers no question anyone would ask."""
    text = xls_to_text(_fixture(), "legacy_workbook.xls")

    assert "2026-09-30" in text
    assert "46295" not in text


def test_a_boolean_is_readable() -> None:
    text = xls_to_text(_fixture(), "legacy_workbook.xls")

    assert "TRUE" in text
    assert "FALSE" in text


def test_a_corrupt_workbook_is_a_log_line_not_an_exception() -> None:
    """Same contract as the .xlsx path: one unreadable file must not fail the document."""
    assert xls_to_text(BytesIO(b"not a workbook"), "broken.xls") == ""


def test_the_extension_map_routes_xls() -> None:
    """Gate one. Without this, extract_file_text_locally raises for a .xls."""
    text = extract_file_text_locally(_fixture(), "legacy_workbook.xls")

    assert "Widget Pro" in text


def test_the_connector_spreadsheet_gate_admits_xls() -> None:
    """Gate two, and the one that made the first fix a no-op: the connectors test this set
    BEFORE any extraction happens, so a .xls was dropped before a document existed."""
    assert ".xls" in OnyxFileExtensions.SPREADSHEET_EXTENSIONS
    assert ".xls" in OnyxFileExtensions.TABULAR_EXTENSIONS
    assert ".xls" in OnyxFileExtensions.TEXT_AND_DOCUMENT_EXTENSIONS


def test_the_staging_path_produces_one_csv_per_sheet() -> None:
    """Gate three. TabularSections are built from staged CSVs, so a .xls that never reaches
    staging is read as prose rather than as rows."""
    staged: list[bytes] = []

    def _stage(payload, _content_type):  # type: ignore[no-untyped-def]
        staged.append(payload.read())
        return f"file-{len(staged)}"

    sheets = stage_spreadsheet_sheets(
        _fixture(), _stage, file_name="legacy_workbook.xls"
    )

    assert [s.title for s in sheets] == ["Entitlements", "Notes"]
    assert [s.csv_file_id for s in sheets] == ["file-1", "file-2"]
    first = staged[0].decode()
    assert "Widget Pro" in first
    assert "2026-09-30" in first, (
        "the staged CSV must carry the same rendering as the text path"
    )


def test_staging_still_works_for_xlsx() -> None:
    """The rename and the dispatch must not disturb the format that already worked."""
    import openpyxl

    buffer = BytesIO()
    workbook = openpyxl.Workbook()
    workbook.active.title = "Costs"
    workbook.active["A1"] = "XLSX-MARKER"
    workbook.save(buffer)
    buffer.seek(0)

    staged: list[bytes] = []

    def _stage(payload, _content_type):  # type: ignore[no-untyped-def]
        staged.append(payload.read())
        return "file-1"

    sheets = stage_spreadsheet_sheets(buffer, _stage, file_name="costs.xlsx")

    assert [s.title for s in sheets] == ["Costs"]
    assert "XLSX-MARKER" in staged[0].decode()


def test_the_two_formats_render_the_same_values_the_same_way() -> None:
    """The point of sharing _sheet_to_csv: a figure must read identically whichever
    workbook format it arrived in, or a golden answer matches one and not the other."""
    import openpyxl

    buffer = BytesIO()
    workbook = openpyxl.Workbook()
    workbook.active["A1"] = "Quantity"
    workbook.active["A2"] = 2520
    workbook.save(buffer)
    buffer.seek(0)

    from onyx.file_processing.extract_file_text import xlsx_to_text

    modern = xlsx_to_text(buffer, "modern.xlsx")

    assert "2520" in modern and "2520.0" not in modern
    assert "2520" in xls_to_text(_fixture(), "legacy_workbook.xls")


def test_a_modern_workbook_misnamed_xls_is_not_a_hard_failure() -> None:
    """The realistic bad input: someone renames an .xlsx to .xls. xlrd refuses it, and that
    must cost the one file, not the document it arrived in."""
    import openpyxl

    buffer = BytesIO()
    workbook = openpyxl.Workbook()
    workbook.active["A1"] = "modern"
    workbook.save(buffer)
    buffer.seek(0)

    assert xls_to_text(buffer, "actually_xlsx.xls") == ""
