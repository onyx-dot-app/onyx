import csv
import io
import tempfile
from typing import IO, cast

from pydantic import BaseModel

from onyx.connectors.models import TabularSection, TextSection
from onyx.file_processing.extract_file_text import detect_encoding, stage_xlsx_sheets
from onyx.file_processing.file_types import OnyxFileExtensions
from onyx.file_store.staging import RawFileCallback
from onyx.utils.csv_utils import csv_reader
from onyx.utils.logger import setup_logger

logger = setup_logger()

CONTENT_SKIPPED_PLACEHOLDER = "<content-skipped>"


class TabularExtractionResult(BaseModel):
    sections: list[TabularSection | TextSection]
    staged_file_id: str


def is_tabular_file(file_name: str) -> bool:
    lowered = file_name.lower()
    return any(lowered.endswith(ext) for ext in OnyxFileExtensions.TABULAR_EXTENSIONS)


def _stream_delimited_file(
    file: IO[bytes], stage: RawFileCallback, is_tsv: bool
) -> str | None:
    """Transcodes a CSV or TSV to a staged UTF-8 CSV, a row at a time.

    Never holds the file in memory, as `stage_xlsx_sheets` does not for a
    workbook: a large file would otherwise peak at several times its size as a
    decoded string plus its encoded copy. Returns None when the file holds no
    content.
    """
    encoding = detect_encoding(file)
    text_in = io.TextIOWrapper(file, encoding=encoding, errors="replace", newline="")
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", newline="") as tmp:
        if is_tsv:
            # Re-serialize as CSV so downstream parsers that assume the default
            # Excel dialect read the columns correctly.
            csv.writer(tmp, lineterminator="\n").writerows(
                csv_reader(text_in, dialect="excel-tab")
            )
        else:
            started = False
            for line in text_in:
                if not started:
                    # Matches the leading strip() this did when it read the
                    # whole file at once, so the first header keeps its name.
                    line = line.lstrip()
                    if not line:
                        continue
                    started = True
                tmp.write(line)
        tmp.flush()
        binary = cast(IO[bytes], tmp.buffer)
        if binary.seek(0, io.SEEK_END) == 0:
            return None
        binary.seek(0)
        return stage(binary, "text/csv")


def tabular_file_to_sections(
    file: IO[bytes],
    file_name: str,
    stage: RawFileCallback,
    link: str = "",
    skip_content: bool = False,
) -> list[TabularSection | TextSection]:
    """Convert a tabular file into one or more TabularSections.

    - .xlsx → one staged TabularSection per non-empty sheet.
    - .csv / .tsv → one staged TabularSection for the whole file.
    - empty input → `[]`.
    - skip_content → one placeholder TextSection, so the file indexes as its
      title only. Nothing is parsed or staged.
    """
    lowered = file_name.lower()

    if not lowered.endswith(tuple(OnyxFileExtensions.TABULAR_EXTENSIONS)):
        raise ValueError(f"{file_name!r} is not a tabular file")

    if skip_content:
        return [TextSection(text=CONTENT_SKIPPED_PLACEHOLDER, link=link or file_name)]

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
        csv_file_id = _stream_delimited_file(
            file, stage, is_tsv=lowered.endswith(".tsv")
        )
    except Exception:
        logger.exception("Failure decoding %s", file_name)
        raise

    if csv_file_id is None:
        return []
    return [TabularSection(csv_file_id=csv_file_id, link=link or file_name)]


def extract_and_stage_tabular_file(
    file: IO[bytes],
    file_name: str,
    content_type: str,
    raw_file_callback: RawFileCallback,
    link: str = "",
    skip_content: bool = False,
) -> TabularExtractionResult:
    """Extract tabular sections AND stage the raw bytes via the callback. The
    raw bytes are staged even with skip_content, so the file stays readable."""
    sections = tabular_file_to_sections(
        file=file,
        file_name=file_name,
        stage=raw_file_callback,
        link=link,
        skip_content=skip_content,
    )
    # rewind so the callback can re-read what extraction consumed
    file.seek(0)
    staged_file_id = raw_file_callback(file, content_type)

    return TabularExtractionResult(
        sections=sections,
        staged_file_id=staged_file_id,
    )
