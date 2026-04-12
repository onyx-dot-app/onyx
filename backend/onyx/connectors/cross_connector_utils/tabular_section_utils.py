"""Helpers for converting tabular files (xlsx, csv, tsv) into
TabularSection objects.

This lives in `connectors/cross_connector_utils` because:
- It imports `TabularSection` from `connectors.models` (connector-layer type).
- It calls `file_processing` primitives (`xlsx_sheet_extraction`, `file_io_to_text`)
  but does the connector-layer wrapping here so every connector that ingests
  tabular data can share the same section shape.
"""

from typing import IO

from onyx.connectors.models import TabularSection
from onyx.file_processing.extract_file_text import file_io_to_text
from onyx.file_processing.extract_file_text import xlsx_sheet_extraction
from onyx.utils.logger import setup_logger

logger = setup_logger()


# Extensions routed through this helper instead of the generic
# `extract_text_and_images` path. Keep in sync with
# `OnyxFileExtensions.TABULAR_EXTENSIONS`.
TABULAR_FILE_EXTENSIONS = {".xlsx", ".csv", ".tsv"}


def is_tabular_file(file_name: str) -> bool:
    """Return True if the file extension indicates a tabular file
    (xlsx, csv, tsv)."""
    lowered = file_name.lower()
    return any(lowered.endswith(ext) for ext in TABULAR_FILE_EXTENSIONS)


def tabular_file_to_sections(
    file: IO[bytes],
    file_name: str,
    link: str = "",
) -> list[TabularSection]:
    """Convert a tabular file into one or more TabularSections.

    - `.xlsx` → one TabularSection per non-empty sheet, with
      `link=f"sheet:{title}"`.
    - `.csv` / `.tsv` → a single TabularSection containing the full
      decoded file, with `link=link` (falling back to `file_name` when
      the caller doesn't provide one — `TabularSection.link` is required).

    Returns an empty list when the file yields no extractable content
    (empty workbook, empty csv, decode failure).

    Raises `ValueError` if `file_name` isn't a recognized tabular
    extension — callers should gate on `is_tabular_file` first.
    """
    lowered = file_name.lower()

    if lowered.endswith(".xlsx"):
        return [
            TabularSection(link=f"sheet:{sheet_title}", text=csv_text)
            for csv_text, sheet_title in xlsx_sheet_extraction(
                file, file_name=file_name
            )
        ]

    if lowered.endswith((".csv", ".tsv")):
        try:
            text = file_io_to_text(file).strip()
        except Exception as e:
            logger.warning(f"Failed to decode {file_name}: {e}")
            return []
        if not text:
            return []
        return [TabularSection(link=link or file_name, text=text)]

    raise ValueError(f"{file_name!r} is not a tabular file")
