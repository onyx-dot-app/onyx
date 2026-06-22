import csv
import io
from typing import IO

from pydantic import BaseModel

from onyx.configs.app_configs import XLSX_STREAM_SHEET_BYTES
from onyx.connectors.models import TabularSection
from onyx.file_processing.extract_file_text import file_io_to_text
from onyx.file_processing.extract_file_text import stage_or_inline_xlsx_sheets
from onyx.file_processing.extract_file_text import xlsx_has_large_sheet
from onyx.file_processing.extract_file_text import xlsx_sheet_extraction
from onyx.file_processing.file_types import OnyxFileExtensions
from onyx.file_store.staging import RawFileCallback
from onyx.utils.logger import setup_logger

logger = setup_logger()


class TabularExtractionResult(BaseModel):
    sections: list[TabularSection]
    staged_file_id: str


def is_tabular_file(file_name: str) -> bool:
    lowered = file_name.lower()
    return any(lowered.endswith(ext) for ext in OnyxFileExtensions.TABULAR_EXTENSIONS)


def _tsv_to_csv(tsv_text: str) -> str:
    """Re-serialize tab-separated text as CSV so downstream parsers that
    assume the default Excel dialect read the columns correctly."""
    out = io.StringIO()
    csv.writer(out, lineterminator="\n").writerows(
        csv.reader(io.StringIO(tsv_text), dialect="excel-tab")
    )
    return out.getvalue().rstrip("\n")


def _xlsx_to_streamed_sections(
    file: IO[bytes],
    file_name: str,
    link: str,
    raw_file_callback: RawFileCallback,
) -> list[TabularSection]:
    """Render each worksheet's CSV with bounded memory: small sheets stay inline
    (keeping their descriptor chunks downstream); sheets larger than
    `XLSX_STREAM_SHEET_BYTES` are file-backed in the file store so a huge sheet
    never lands on the worker heap."""
    return [
        TabularSection(
            link=link or file_name,
            text=sheet.text,
            csv_file_id=sheet.csv_file_id,
            heading=f"{file_name} :: {sheet.title}",
        )
        for sheet in stage_or_inline_xlsx_sheets(
            file, raw_file_callback, XLSX_STREAM_SHEET_BYTES
        )
    ]


def tabular_file_to_sections(
    file: IO[bytes],
    file_name: str,
    link: str = "",
    raw_file_callback: RawFileCallback | None = None,
) -> list[TabularSection]:
    """Convert a tabular file into one or more TabularSections.

    - .xlsx → one TabularSection per non-empty sheet. A workbook with a very
      large sheet (and a `raw_file_callback`) is streamed per sheet — small
      sheets stay inline, oversized sheets are file-backed; otherwise the whole
      workbook is rendered inline.
    - .csv / .tsv → a single TabularSection containing the full decoded file.

    Returns an empty list when the file yields no extractable content.
    """
    lowered = file_name.lower()

    if not lowered.endswith(tuple(OnyxFileExtensions.TABULAR_EXTENSIONS)):
        raise ValueError(f"{file_name!r} is not a tabular file")

    if lowered.endswith(tuple(OnyxFileExtensions.SPREADSHEET_EXTENSIONS)):
        if raw_file_callback is not None and xlsx_has_large_sheet(file):
            return _xlsx_to_streamed_sections(
                file,
                file_name=file_name,
                link=link,
                raw_file_callback=raw_file_callback,
            )
        return [
            TabularSection(
                link=link or file_name,
                text=csv_text,
                heading=f"{file_name} :: {sheet_title}",
            )
            for csv_text, sheet_title in xlsx_sheet_extraction(
                file, file_name=file_name
            )
        ]

    try:
        text = file_io_to_text(file).strip()
    except Exception:
        logger.exception("Failure decoding %s", file_name)
        raise

    if not text:
        return []
    if lowered.endswith(".tsv"):
        text = _tsv_to_csv(text)
    return [TabularSection(link=link or file_name, text=text)]


def extract_and_stage_tabular_file(
    file: IO[bytes],
    file_name: str,
    content_type: str,
    raw_file_callback: RawFileCallback,
    link: str = "",
) -> TabularExtractionResult:
    """Extract tabular sections AND stage the raw bytes via the callback."""
    sections = tabular_file_to_sections(
        file=file,
        file_name=file_name,
        link=link,
        raw_file_callback=raw_file_callback,
    )
    # rewind so the callback can re-read what extraction consumed
    file.seek(0)
    staged_file_id = raw_file_callback(file, content_type)

    return TabularExtractionResult(
        sections=sections,
        staged_file_id=staged_file_id,
    )
