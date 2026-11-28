from typing import IO, Any

from pydantic import BaseModel

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_processing.extract_file_text import (
    XLSX_TRUNCATION_MARKER,
    xlsx_sheet_extraction,
)
from onyx.file_processing.file_types import (
    SPREADSHEET_MIME_TYPES,
    OnyxMimeTypes,
    is_sandbox_only_file,
)
from onyx.file_processing.zip_limits import ZipSizeLimitError
from onyx.file_store.models import ChatFileType

# Per-sheet cap on CSV text returned for in-chat spreadsheet previews. Sheets are
# truncated (at a row boundary) beyond this to keep preview payloads bounded.
MAX_PREVIEW_CHARS_PER_SHEET = 500_000
# Cap on the CSV text of all sheets of one preview, so a workbook of many large
# sheets also gets a bounded payload.
MAX_PREVIEW_CHARS_TOTAL = 2_000_000
# Previews parse inside the request, so they get a tighter decompression budget.
MAX_PREVIEW_DECOMPRESSED_BYTES = 100 * 1024 * 1024


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
        and _normalize_mime_type(mime_type) in SPREADSHEET_MIME_TYPES
    )


def is_code_interpreter_staged_mime_type(mime_type: str | None) -> bool:
    return (
        mime_type is not None
        and _normalize_mime_type(mime_type)
        in OnyxMimeTypes.CODE_INTERPRETER_STAGED_MIME_TYPES
    )


def is_code_interpreter_staged_file(file_name: str, mime_type: str | None) -> bool:
    """Code files are staged by extension: browsers send no reliable mime type."""
    return is_sandbox_only_file(file_name) or is_code_interpreter_staged_mime_type(
        mime_type
    )


def _truncate_csv_at_row_boundary(csv_text: str, max_chars: int) -> str:
    """Cut CSV text to at most max_chars, ending on a row boundary. Single
    forward pass tracking quote parity: a newline only counts as a row boundary
    when it falls outside a quoted field. If no complete row fits within the
    cap, return an empty string rather than emitting malformed CSV."""
    if len(csv_text) <= max_chars:
        return csv_text
    last_boundary = 0
    in_quotes = False
    for i in range(max_chars):
        char = csv_text[i]
        if char == '"':
            in_quotes = not in_quotes
        elif char == "\n" and not in_quotes:
            last_boundary = i
    return csv_text[:last_boundary]


def parse_spreadsheet_for_preview(
    file: IO[Any], file_name: str = ""
) -> SpreadsheetPreview:
    """Convert a stored xlsx file into per-sheet CSV text suitable for rendering
    a preview table in the frontend. Sheets larger than
    MAX_PREVIEW_CHARS_PER_SHEET are truncated at a row boundary. Each sheet
    uses the text it keeps of MAX_PREVIEW_CHARS_TOTAL. Once the sheets reach
    that total, the sheet that crosses it is truncated the same way, later
    sheets are left out, and the last sheet shown is marked truncated."""
    sheet_previews: list[SpreadsheetSheetPreview] = []
    budget = MAX_PREVIEW_CHARS_TOTAL
    try:
        sheets = xlsx_sheet_extraction(
            file, file_name, max_decompressed_bytes=MAX_PREVIEW_DECOMPRESSED_BYTES
        )
    except ZipSizeLimitError as e:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, str(e)) from e
    for csv_text, title in sheets:
        if budget <= 0:
            if sheet_previews:
                sheet_previews[-1].truncated = True
            break
        truncated = csv_text.endswith(XLSX_TRUNCATION_MARKER)
        if truncated:
            csv_text = csv_text.removesuffix(XLSX_TRUNCATION_MARKER).rstrip("\n")
        # The total budget, not the sheet cap, cuts this sheet
        budget_cut = len(csv_text) > budget and budget <= MAX_PREVIEW_CHARS_PER_SHEET
        limit = min(MAX_PREVIEW_CHARS_PER_SHEET, budget)
        if len(csv_text) > limit:
            csv_text = _truncate_csv_at_row_boundary(csv_text, limit)
            truncated = True
        budget -= len(csv_text)
        sheet_previews.append(
            SpreadsheetSheetPreview(name=title, csv=csv_text, truncated=truncated)
        )
        if budget_cut:
            break
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
