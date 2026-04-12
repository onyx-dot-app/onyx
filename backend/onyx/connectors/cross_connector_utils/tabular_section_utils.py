from typing import IO

from onyx.connectors.models import TabularSection
from onyx.file_processing.extract_file_text import file_io_to_text
from onyx.file_processing.extract_file_text import xlsx_sheet_extraction
from onyx.file_processing.file_types import OnyxFileExtensions
from onyx.utils.logger import setup_logger

logger = setup_logger()


def is_tabular_file(file_name: str) -> bool:
    lowered = file_name.lower()
    return any(
        lowered.endswith(ext) for ext in OnyxFileExtensions.TABULAR_EXTENSIONS
    )


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
      the caller doesn't provide one).

    Returns an empty list when the file yields no extractable content.
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
