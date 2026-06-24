import csv
import io
from collections.abc import Generator
from collections.abc import Iterable
from collections.abc import Iterator
from collections.abc import Mapping

from pydantic import BaseModel

# Python's csv default field size limit is 131072 bytes (128 KiB), which
# real-world data (long descriptions, pasted docs, base64 blobs) routinely
# exceeds — the parser then raises `Error: field larger than field limit
# (131072)` and fails the whole row, aborting indexing of the CSV section
# (ONYX-BACKEND-H6FM). Bump to 128 MiB, matching the order of magnitude the
# salesforce connector already opts into for bulk exports.
_CSV_FIELD_SIZE_LIMIT_BYTES = 128 * 1024 * 1024
csv.field_size_limit(_CSV_FIELD_SIZE_LIMIT_BYTES)

_NEWLINE_CSV_ERROR = "new-line character seen in unquoted field"

# Leading characters that spreadsheet software (Excel, LibreOffice, Google
# Sheets) interprets as the start of a formula. Exporting user-supplied text
# beginning with one of these enables CSV/formula injection (e.g. DDE payloads
# like `=cmd|' /C calc'!A1`) against whoever opens the export.
_FORMULA_PREFIX_CHARS = ("=", "+", "-", "@", "\t", "\r")


def sanitize_csv_cell(value: str) -> str:
    """Neutralize spreadsheet formula injection in a CSV cell.

    Prefixes values that start with a formula-trigger character with a
    single quote, which spreadsheet software treats as "render as text".
    """
    if value.startswith(_FORMULA_PREFIX_CHARS):
        return "'" + value
    return value


def sanitize_csv_cell_or_none(value: str | None) -> str | None:
    """sanitize_csv_cell that passes None through."""
    return sanitize_csv_cell(value) if value is not None else None


def sanitize_csv_row(row: Mapping[str, str | None]) -> dict[str, str | None]:
    """Apply sanitize_csv_cell to every non-None value of a CSV row dict."""
    return {key: sanitize_csv_cell_or_none(value) for key, value in row.items()}


class ParsedRow(BaseModel):
    header: list[str]
    row: list[str]


def normalize_csv_newlines(text: str) -> str:
    """Normalize Windows (\\r\\n) and old-Mac (\\r) line endings to Unix (\\n).

    io.StringIO does not split on bare \\r, so csv.reader raises
    "new-line character seen in unquoted field" for files that use \\r as
    the row separator (e.g. old Mac-format CSVs from Google Drive).
    """
    return text.replace("\r\n", "\n").replace("\r", "\n")


def read_csv_header(csv_text: str) -> list[str]:
    """Return the first non-blank row (the header) of a CSV string, or
    [] if the text has no usable header.

    Falls back to normalized line endings when csv.reader raises the
    specific "new-line character" error.
    """

    def _read(text: str) -> list[str]:
        for row in csv.reader(io.StringIO(text)):
            if any(c.strip() for c in row):
                return row
        return []

    if not csv_text.strip():
        return []
    try:
        return _read(csv_text)
    except csv.Error as e:
        if _NEWLINE_CSV_ERROR not in str(e):
            raise csv.Error(f"read_csv_header failed: {e}") from e
    try:
        return _read(normalize_csv_newlines(csv_text))
    except csv.Error as e:
        raise csv.Error(f"read_csv_header failed: {e}") from e


def parse_csv_stream(lines: Iterable[str]) -> Iterator[ParsedRow]:
    """Stream each data row paired with its header from a CSV line source (a file
    handle or any iterable of lines), header first, without buffering the input.

    Assumes clean line endings; `parse_csv_string` wraps this for in-memory
    strings that may use bare-``\\r`` (old Mac) row separators.
    """
    reader = csv.reader(lines)
    header: list[str] | None = None
    for row in reader:
        if not any(cell.strip() for cell in row):
            continue
        if header is None:
            header = row
            continue
        yield ParsedRow(header=header, row=row)


def parse_csv_string(csv_text: str) -> Generator[ParsedRow, None, None]:
    """Yield each data row paired with its header from a CSV string.

    Falls back to normalized line endings when csv.reader raises the
    specific "new-line character" error (e.g. old Mac-format CSVs).
    """
    if not csv_text.strip():
        return
    try:
        rows = list(parse_csv_stream(io.StringIO(csv_text)))
    except csv.Error as e:
        if _NEWLINE_CSV_ERROR not in str(e):
            raise csv.Error(f"parse_csv_string failed: {e}") from e
        try:
            rows = list(parse_csv_stream(io.StringIO(normalize_csv_newlines(csv_text))))
        except csv.Error as e2:
            raise csv.Error(f"parse_csv_string failed: {e2}") from e2
    yield from rows
