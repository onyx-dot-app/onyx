import csv
import io
from typing import IO

from pydantic import BaseModel

from onyx.connectors.models import TabularSection
from onyx.file_processing.extract_file_text import file_io_to_text
from onyx.file_processing.extract_file_text import stage_xlsx_sheets
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


def tabular_file_to_sections(
    file: IO[bytes],
    file_name: str,
    stage: RawFileCallback,
    link: str = "",
) -> list[TabularSection]:
    """Convert a tabular file into one or more TabularSections.

    - .xlsx → one staged TabularSection per non-empty sheet.
    - .csv / .tsv → one staged TabularSection for the whole file.
    - empty input → `[]`.
    """
    lowered = file_name.lower()

    if not lowered.endswith(tuple(OnyxFileExtensions.TABULAR_EXTENSIONS)):
        raise ValueError(f"{file_name!r} is not a tabular file")

    if lowered.endswith(tuple(OnyxFileExtensions.SPREADSHEET_EXTENSIONS)):
        return [
            TabularSection(
                csv_file_id=sheet.csv_file_id,
                link=link or file_name,
                heading=f"{file_name} :: {sheet.title}",
            )
            for sheet in stage_xlsx_sheets(
                file,
                stage,
                file_name=file_name,
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
    csv_file_id = stage(io.BytesIO(text.encode("utf-8")), "text/csv")
    return [TabularSection(csv_file_id=csv_file_id, link=link or file_name)]


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
        stage=raw_file_callback,
        link=link,
    )
    # rewind so the callback can re-read what extraction consumed
    file.seek(0)
    staged_file_id = raw_file_callback(file, content_type)

    return TabularExtractionResult(
        sections=sections,
        staged_file_id=staged_file_id,
    )
