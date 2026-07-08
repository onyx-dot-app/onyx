from typing import Any
from typing import IO

from pydantic import BaseModel

from onyx.file_processing.extract_file_text import xlsx_sheet_extraction
from onyx.file_processing.file_types import OnyxMimeTypes
from onyx.file_processing.file_types import SPREADSHEET_MIME_TYPE
from onyx.file_store.models import ChatFileType

# Per-sheet cap on CSV text returned for in-chat spreadsheet previews. Sheets are
# truncated (at a row boundary) beyond this to keep preview payloads bounded.
MAX_PREVIEW_CHARS_PER_SHEET = 500_000

# MIME types that can be parsed into per-sheet CSV previews by openpyxl.
_SPREADSHEET_PREVIEW_MIME_TYPES = {
    SPREADSHEET_MIME_TYPE,
    "application/vnd.ms-excel.sheet.macroenabled.12",
}


class SpreadsheetSheetPreview(BaseModel):
    name: str
    csv: str
    truncated: bool


class SpreadsheetPreview(BaseModel):
    sheets: list[SpreadsheetSheetPreview]


def _normalize_mime_type(mime_type: str) -> str:
    return mime_type.split(";", 1)[0].strip().lower()


def is_spreadsheet_mime_type(mime_type: str | None) -> bool:
    return (
        mime_type is not None
        and _normalize_mime_type(mime_type) in _SPREADSHEET_PREVIEW_MIME_TYPES
    )


def _truncate_csv_at_row_boundary(csv_text: str, max_chars: int) -> str:
    """Cut CSV text to at most max_chars, ending on a row boundary. A newline is
    only a row boundary when the preceding text has balanced quotes (i.e. we are
    not inside a quoted multi-line field)."""
    cut = csv_text.rfind("\n", 0, max_chars)
    while cut > 0 and csv_text.count('"', 0, cut) % 2 == 1:
        cut = csv_text.rfind("\n", 0, cut)
    return csv_text[:cut] if cut > 0 else csv_text[:max_chars]


def parse_spreadsheet_for_preview(
    file: IO[Any], file_name: str = ""
) -> SpreadsheetPreview:
    """Convert a stored xlsx file into per-sheet CSV text suitable for rendering
    a preview table in the frontend. Sheets larger than
    MAX_PREVIEW_CHARS_PER_SHEET are truncated at a row boundary."""
    sheet_previews: list[SpreadsheetSheetPreview] = []
    for csv_text, title in xlsx_sheet_extraction(file, file_name):
        truncated = False
        if len(csv_text) > MAX_PREVIEW_CHARS_PER_SHEET:
            csv_text = _truncate_csv_at_row_boundary(
                csv_text, MAX_PREVIEW_CHARS_PER_SHEET
            )
            truncated = True
        sheet_previews.append(
            SpreadsheetSheetPreview(name=title, csv=csv_text, truncated=truncated)
        )
    return SpreadsheetPreview(sheets=sheet_previews)


def mime_type_to_chat_file_type(mime_type: str | None) -> ChatFileType:
    if mime_type is None:
        return ChatFileType.PLAIN_TEXT

    normalized_mime_type = _normalize_mime_type(mime_type)
    if normalized_mime_type in OnyxMimeTypes.IMAGE_MIME_TYPES:
        return ChatFileType.IMAGE

    if normalized_mime_type in OnyxMimeTypes.TABULAR_MIME_TYPES:
        return ChatFileType.TABULAR

    if normalized_mime_type in OnyxMimeTypes.DOCUMENT_MIME_TYPES:
        return ChatFileType.DOC

    return ChatFileType.PLAIN_TEXT
